import os
import sys
import json
import time
import uuid
import shutil
import threading
import subprocess
import shlex
import base64
from urllib.parse import urlparse
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, request, jsonify, send_from_directory, abort
from werkzeug.exceptions import HTTPException

try:
    from flask_cors import CORS
except Exception:
    CORS = None

try:
    import requests
except Exception:
    requests = None

# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------
APP_ROOT = Path(__file__).resolve().parent
DIFF_ROOT = (APP_ROOT / "..").resolve()  # assumes gui is inside DiffRhythm root
INFER_SCRIPT = DIFF_ROOT / "infer" / "infer.py"
DEFAULT_BASE = APP_ROOT / "projects"  # base folder for Claude-like projects
UPLOADS_DIR = APP_ROOT / "uploads"
TMP_DIR = APP_ROOT / "tmp"
CONFIG_PATH = APP_ROOT / "config.json"
FAVORITES_FILE = APP_ROOT / "favorites.json"

DEFAULT_CONFIG = {
    "repo_id": "ASLP-lab/DiffRhythm-1_2",
    "audio_length": 95,
    "batch_infer_num": 1,
    "use_chunked": False,
    "steps": 56,
    "cfg_strength": 3.8,
    "cuda_visible_devices": "0",
    "base_dir": str(DEFAULT_BASE),
    "active_project": "Default",
    # optional: force a specific python binary
    # "python_bin": "/full/path/to/python"
}

# Quality presets for simple mode
QUALITY_PRESETS = {
    'fast': {'steps': 32, 'cfg_strength': 3.5},
    'balanced': {'steps': 56, 'cfg_strength': 3.8},
    'high': {'steps': 72, 'cfg_strength': 4.0}
}


def resolve_diff_root(cfg: dict = None) -> Path:
    """Try to resolve the DiffRhythm root directory.
    Order:
      1) cfg.get('diff_root')
      2) env DIFFRHYTHM_ROOT
      3) APP_ROOT/.. (default heuristic)
      4) Walk up to 4 ancestors from APP_ROOT to find 'infer/infer.py'
    """
    candidates = []
    if cfg and cfg.get('diff_root'):
        candidates.append(Path(cfg['diff_root']).expanduser().resolve())
    env_root = os.environ.get('DIFFRHYTHM_ROOT')
    if env_root:
        candidates.append(Path(env_root).expanduser().resolve())
    candidates.append((APP_ROOT / '..').resolve())
    # walk parents
    p = APP_ROOT
    for _ in range(4):
        p = p.parent
        candidates.append(p.resolve())

    for root in candidates:
        if (root / 'infer' / 'infer.py').exists():
            return root
    return candidates[0] if candidates else (APP_ROOT / '..').resolve()


def discover_models(diff_root: Path) -> list:
    """Heuristically discover available model repo-ids.
    Sources:
      - Env DIFFRHYTHM_MODELS (comma or newline separated)
      - A 'models' or 'checkpoints' directory with names like 'DiffRhythm-*'
      - Grep common files (infer/infer.py, README.md) for 'ASLP-lab/DiffRhythm-*'
      - Fallback to known defaults
    """
    env_models = os.environ.get('DIFFRHYTHM_MODELS')
    if env_models:
        vals = [s.strip() for s in env_models.replace('\n', ',').split(',') if s.strip()]
        return sorted(set(vals))

    found = set()

    # Directory-based discovery
    for dname in ['models', 'checkpoints', 'pretrained', 'pretrained_models']:
        d = diff_root / dname
        if d.exists() and d.is_dir():
            for x in d.iterdir():
                name = x.name
                if x.is_dir() and name.lower().startswith('diffrhythm-'):
                    found.add(f'ASLP-lab/{name}')
                elif x.is_file():
                    import re as _re
                    m = _re.match(r'(DiffRhythm[-_][0-9][._][0-9])', name, flags=_re.I)
                    if m:
                        token = m.group(1).replace('.', '_')
                        found.add(f'ASLP-lab/{token}')

    # Grep key files
    for rel in ['infer/infer.py', 'README.md']:
        f = diff_root / rel
        if f.exists():
            try:
                txt = f.read_text(encoding='utf-8', errors='ignore')
                import re as _re
                for m in _re.finditer(r'ASLP-lab/(DiffRhythm[-_][0-9][._][0-9])', txt):
                    token = m.group(1).replace('.', '_')
                    found.add(f'ASLP-lab/{token}')
            except Exception:
                pass

    if not found:
        return ['ASLP-lab/DiffRhythm-1_2', 'ASLP-lab/DiffRhythm-1_1']
    return sorted(found)


    root = resolve_diff_root(cfg)
    models = discover_models(root)
    resp = [{'repo_id': repo, 'label': repo.split('/')[-1].replace('_', '.') } for repo in models]
    return jsonify({'ok': True, 'models': resp, 'diff_root': str(root)})
RUN_LOCK = threading.Lock()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 300  # 300 MB

# Enable CORS for /api/* to ease n8n integrations
if CORS is not None:
    CORS(app, resources={r"/api/*": {"origins": "*"}})



# Global JSON error handler so the client never receives HTML when it expects JSON
@app.errorhandler(Exception)
def _json_errors(e):
    code = 500
    msg = str(e)
    if isinstance(e, HTTPException):
        code = e.code or 500
        msg = e.description or msg
    return jsonify({"ok": False, "error": msg}), code

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
DEFAULT_PROJECT_NAME = "Default"

def is_reserved_project(name: str) -> bool:
    return (name or "").strip().lower() == DEFAULT_PROJECT_NAME.lower()

def ensure_default_project(cfg=None):
    base = ensure_project_base(cfg)
    d = (base / DEFAULT_PROJECT_NAME)
    d.mkdir(parents=True, exist_ok=True)
    return d

def load_config():
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()

def save_config(cfg: dict):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

def timestamp_str():
    return datetime.now().strftime("%Y%m%d-%H%M%S")

def ensure_project_base(cfg=None) -> Path:
    cfg = cfg or load_config()
    base = Path(cfg.get("base_dir", str(DEFAULT_BASE))).resolve()
    base.mkdir(parents=True, exist_ok=True)
    # ensure Default project exists
    (base / "Default").mkdir(exist_ok=True)
    return base

def project_path(project: str, cfg=None) -> Path:
    base = ensure_project_base(cfg)
    safe = (project or "Default").strip().replace("..", "").replace("\\", "/").strip("/")
    if not safe:
        safe = "Default"
    p = (base / safe).resolve()
    if base not in p.parents and base != p:
        raise ValueError("Invalid project path")
    p.mkdir(exist_ok=True)
    return p

def project_path_no_create(project: str, cfg=None) -> Path:
    base = ensure_project_base(cfg)
    safe = (project or "Default").strip().replace("..", "").replace("\\", "/").strip("/")
    if not safe:
        safe = "Default"
    p = (base / safe).resolve()
    if base not in p.parents and base != p:
        raise ValueError("Invalid project path")
    return p

def list_audio_files(folder: Path):
    items = []
    for p in sorted(folder.glob("*.wav")):
        items.append({
            "name": p.name,
            "size": p.stat().st_size,
            "mtime": int(p.stat().st_mtime),
        })
    return items

def history_file(p: Path) -> Path:
    return p / "history.json"

def read_history(p: Path):
    hf = history_file(p)
    if hf.exists():
        try:
            return json.loads(hf.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []

def write_history(p: Path, items):
    history_file(p).write_text(json.dumps(items, indent=2), encoding="utf-8")

def sys_executable():
    # allow override from config
    try:
        cfg = load_config()
        pbin = (cfg.get("python_bin") or "").strip()
        if pbin:
            return pbin
    except Exception:
        pass

    # prefer local venvs under DiffRhythm
    if os.name == "nt":
        cand = [
            DIFF_ROOT / "venv" / "Scripts" / "python.exe",
            DIFF_ROOT / ".venv" / "Scripts" / "python.exe",
        ]
    else:
        cand = [
            DIFF_ROOT / "venv" / "bin" / "python",
            DIFF_ROOT / ".venv" / "bin" / "python",
        ]
    for c in cand:
        if c.exists():
            return str(c)

    # fallback to current interpreter
    return sys.executable or "python3"

def secure_name(name: str) -> str:
    name = (name or "").strip()
    base = Path(name).name
    safe = "".join(ch for ch in base if ch.isalnum() or ch in "._-").strip(".")
    return safe or f"file-{uuid.uuid4().hex[:6]}"

def save_b64(data_b64: str, filename: str, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    fn = secure_name(filename or f"upload-{uuid.uuid4().hex[:6]}")
    p = dest / fn
    with open(p, "wb") as f:
        f.write(base64.b64decode(data_b64))
    return p

def save_from_url(url: str, filename: str | None, dest: Path) -> Path:
    if requests is None:
        raise RuntimeError("requests not installed; cannot download URLs. Install flask-cors requests.")
    dest.mkdir(parents=True, exist_ok=True)
    r = requests.get(url, timeout=30, stream=True)
    r.raise_for_status()
    guess = os.path.basename(urlparse(url).path) or "download.bin"
    fn = secure_name(filename or guess)
    p = dest / fn
    with open(p, "wb") as f:
        for chunk in r.iter_content(8192):
            if chunk:
                f.write(chunk)
    return p

def build_infer_cmd(args_map: dict, tmp_outdir: Path):
    cmd = [sys_executable(), str(INFER_SCRIPT)]
    cmd += ["--output-dir", str(tmp_outdir)]
    cmd += ["--audio-length", str(int(args_map.get("audio_length", 95)))]
    cmd += ["--repo-id", args_map.get("repo_id", DEFAULT_CONFIG["repo_id"])]

    ref_prompt = args_map.get("ref_prompt")
    ref_audio_path = args_map.get("ref_audio_path")
    if ref_audio_path:
        cmd += ["--ref-audio-path", str(ref_audio_path)]
    elif ref_prompt:
        cmd += ["--ref-prompt", ref_prompt]

    if args_map.get("lrc_path"):
        cmd += ["--lrc-path", str(args_map["lrc_path"])]

    if bool(args_map.get("use_chunked")):
        cmd += ["--chunked"]

    cmd += ["--batch-infer-num", str(int(args_map.get("batch_infer_num", 1)))]

    # quality flags
    if "steps" in args_map:
        cmd += ["--steps", str(int(args_map["steps"]))]
    if "cfg_strength" in args_map:
        cmd += ["--cfg-strength", str(float(args_map["cfg_strength"]))]

    return cmd

def run_infer(args_map: dict, env_extra: dict):
    run_token = f"run-{uuid.uuid4().hex[:8]}"
    tmp_outdir = (TMP_DIR / run_token)
    tmp_outdir.mkdir(parents=True, exist_ok=True)

    cmd = build_infer_cmd(args_map, tmp_outdir)

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{DIFF_ROOT}{os.pathsep}" + env.get("PYTHONPATH", "")
    cuda_val = env_extra.get("CUDA_VISIBLE_DEVICES")
    if cuda_val is not None and cuda_val != "":
        env["CUDA_VISIBLE_DEVICES"] = str(cuda_val)
    if sys.platform == "darwin" and "PHONEMIZER_ESPEAK_LIBRARY" not in env:
        env["PHONEMIZER_ESPEAK_LIBRARY"] = \
            "/opt/homebrew/Cellar/espeak-ng/1.52.0/lib/libespeak-ng.dylib"

    # Pre-log: command and params
    sh_join = getattr(shlex, "join", None)
    joined_cmd = sh_join(cmd) if sh_join else " ".join(map(shlex.quote, cmd))
    prelog = []
    prelog.append("DR-GUI CMD: " + joined_cmd + "\n")
    prelog.append("DR-GUI ENV: CUDA_VISIBLE_DEVICES=" + env.get("CUDA_VISIBLE_DEVICES", "") + "\n")
    prelog.append(
        "DR-GUI PARAMS: "
        f"project={args_map.get('project')} "
        f"mode={args_map.get('mode', 'unknown')} "
        f"repo_id={args_map.get('repo_id')} "
        f"audio_length={args_map.get('audio_length')} "
        f"batch_infer_num={args_map.get('batch_infer_num')} "
        f"steps={args_map.get('steps')} "
        f"cfg_strength={args_map.get('cfg_strength')} "
        f"chunked={bool(args_map.get('use_chunked'))} "
        f"ref={'audio' if 'ref_audio_path' in args_map else 'prompt'}\n"
    )
    prelog_txt = "".join(prelog) + "\n"

    proc = subprocess.run(
        cmd,
        cwd=str(DIFF_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    logs = prelog_txt + (proc.stdout or "")

    # Move result to project folder
    project_dir = project_path(args_map.get("project"))
    final_name = f"output-{timestamp_str()}.wav"
    src = tmp_outdir / "output.wav"
    if not src.exists():
        wavs = list(tmp_outdir.glob("*.wav"))
        if wavs:
            src = wavs[0]
    final_path = project_dir / final_name

    ok = False
    if src.exists():
        shutil.move(str(src), str(final_path))
        ok = True

    try:
        shutil.rmtree(tmp_outdir, ignore_errors=True)
    except Exception:
        pass

    return {
        "ok": ok and proc.returncode == 0,
        "returncode": proc.returncode,
        "logs": logs,
        "outfile": str(final_path if ok else ""),
        "outfile_name": final_name if ok else "",
    }

# ---------------------------------------------------------------------------
# Routes: UI pages
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    cfg = load_config()
    base = ensure_project_base(cfg)
    return render_template("index.html", cfg=cfg, diff_root=str(DIFF_ROOT), base_dir=str(base))
    
@app.route("/favicon.ico")
def favicon():
    return send_from_directory(str(APP_ROOT / "static"), "favicon.ico", mimetype="image/x-icon")
# ---------------------------------------------------------------------------
# Routes: Config & Projects
# ---------------------------------------------------------------------------
@app.route("/api/config", methods=["GET", "POST"]) 
def api_config():
    if request.method == "GET":
        return jsonify(load_config())
    data = request.get_json(force=True)
    cfg = load_config()
    cfg.update({
        "repo_id": data.get("repo_id", cfg["repo_id"]),
        "audio_length": int(data.get("audio_length", cfg["audio_length"])),
        "batch_infer_num": int(data.get("batch_infer_num", cfg["batch_infer_num"])) ,
        "use_chunked": bool(data.get("use_chunked", cfg["use_chunked"])),
        "steps": int(data.get("steps", cfg["steps"])),
        "cfg_strength": float(data.get("cfg_strength", cfg["cfg_strength"])),
        "cuda_visible_devices": str(data.get("cuda_visible_devices", cfg["cuda_visible_devices"])),
        "base_dir": data.get("base_dir", cfg["base_dir"]),
        "active_project": data.get("active_project", cfg["active_project"]),
        "python_bin": data.get("python_bin", cfg.get("python_bin", "")),
    })
    ensure_project_base(cfg)
    save_config(cfg)
    return jsonify({"ok": True, "config": cfg})

@app.route("/api/projects/list", methods=["GET"]) 
def api_projects_list():
    cfg = load_config()
    base = ensure_project_base(cfg)
    projects = []
    for p in sorted([d for d in base.iterdir() if d.is_dir()]):
        files = list_audio_files(p)
        projects.append({
            "name": p.name,
            "count": len(files),
        })
    return jsonify({"projects": projects, "active": cfg.get("active_project", "Default")})

@app.route("/api/projects/create", methods=["POST"])
def api_projects_create():
    cfg = load_config()
    ensure_default_project(cfg)

    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    if is_reserved_project(name):
        return jsonify({"ok": False, "error": "The name 'Default' is reserved."}), 400
    
    p = project_path_no_create(name, cfg)
    if p.exists():
        return jsonify({"ok": False, "error": "Project already exists"}), 400
    p.mkdir(parents=True, exist_ok=True)
    return jsonify({"ok": True, "name": p.name})

@app.route("/api/projects/rename", methods=["POST"])
def api_projects_rename():
    cfg = load_config()
    ensure_default_project(cfg)

    data = request.get_json(force=True)
    old = (data.get("old") or "").strip()
    new = (data.get("new") or "").strip()

    if is_reserved_project(old):
        return jsonify({"ok": False, "error": "The 'Default' project cannot be renamed."}), 400
    if is_reserved_project(new):
        return jsonify({"ok": False, "error": "You cannot rename a project to the reserved name 'Default'."}), 400

    # chemins sans création implicite
    src = project_path_no_create(old, cfg)
    dst = project_path_no_create(new, cfg)

    # validations
    if not src.exists():
        return jsonify({"ok": False, "error": "Source project does not exist"}), 400
    if dst.exists():
        return jsonify({"ok": False, "error": "Target project already exists"}), 400
    if src == dst:
        return jsonify({"ok": True})  # rien à faire

    try:
        src.rename(dst)  # move atomique
        # maj projet actif
        if cfg.get("active_project") == old:
            cfg["active_project"] = new
            save_config(cfg)

        # sécurité anti-réapparition si un GET concurrent l'a recréé vide
        try:
            if src.exists():
                items = list(src.iterdir())
                if not any(x.suffix.lower() == ".wav" for x in items):
                    shutil.rmtree(src)
        except Exception:
            pass

        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400

@app.route("/api/projects/delete", methods=["POST"]) 
def api_projects_delete():
    cfg = load_config()
    ensure_default_project(cfg)

    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()

    if is_reserved_project(name):
        return jsonify({"ok": False, "error": "The 'Default' project cannot be deleted."}), 400
    
    force = bool(data.get("force"))
    p = project_path(name, cfg)
    try:
        if force:
            shutil.rmtree(p)
        else:
            # only if empty or only history.json
            items = [x for x in p.iterdir()]
            if any(x.suffix.lower() == ".wav" for x in items):
                return jsonify({"ok": False, "error": "Project not empty"}), 400
            shutil.rmtree(p)
        if cfg.get("active_project") == name:
            cfg["active_project"] = "Default"
            save_config(cfg)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400

# ---------------------------------------------------------------------------
# Routes: Files
# ---------------------------------------------------------------------------
@app.route("/api/files/list", methods=["GET"])
def api_files_list():
    cfg = load_config()
    ensure_default_project(cfg)

    proj = request.args.get("project", cfg.get("active_project", DEFAULT_PROJECT_NAME)) or DEFAULT_PROJECT_NAME
    p = project_path_no_create(proj, cfg)  # helper "no-create" si tu l'as ajouté

    if not p.exists():
        return jsonify({"project": proj, "files": [], "history": []})

    return jsonify({"project": p.name, "files": list_audio_files(p), "history": read_history(p)})

@app.route("/api/files/delete", methods=["POST"]) 
def api_files_delete():
    cfg = load_config()
    data = request.get_json(force=True)
    proj = data.get("project", cfg.get("active_project", "Default"))
    p = project_path(proj, cfg)
    target = (p / data.get("name", "")).resolve()
    if p not in target.parents and p != target:
        return jsonify({"ok": False, "error": "Invalid path"}), 400
    try:
        target.unlink(missing_ok=False)
        # remove from history entries matching this file
        h = read_history(p)
        h = [e for e in h if e.get("file") != target.name]
        write_history(p, h)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400

@app.route("/api/files/rename", methods=["POST"]) 
def api_files_rename():
    cfg = load_config()
    data = request.get_json(force=True)
    proj = data.get("project", cfg.get("active_project", "Default"))
    p = project_path(proj, cfg)
    src = (p / data.get("src", "")).resolve()
    dst = (p / data.get("dst", "")).resolve()
    if p not in src.parents or p not in dst.parents:
        return jsonify({"ok": False, "error": "Invalid path"}), 400
    try:
        src.rename(dst)
        # update history
        h = read_history(p)
        for e in h:
            if e.get("file") == src.name:
                e["file"] = dst.name
        write_history(p, h)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400

@app.route("/play/<project>/<path:filename>") 
def play_file(project, filename):
    cfg = load_config()
    p = project_path(project, cfg)
    file_path = (p / filename).resolve()
    if not file_path.exists():
        abort(404)
    return send_from_directory(p, filename, mimetype="audio/wav", as_attachment=False)

@app.route("/download/<project>/<path:filename>") 
def download_file(project, filename):
    cfg = load_config()
    p = project_path(project, cfg)
    file_path = (p / filename).resolve()
    if not file_path.exists():
        abort(404)
    return send_from_directory(p, filename, as_attachment=True)

# ---------------------------------------------------------------------------
# Routes: Generation
# ---------------------------------------------------------------------------
@app.route("/api/generate", methods=["POST"]) 
def api_generate():
    if not RUN_LOCK.acquire(blocking=False):
        return jsonify({"ok": False, "error": "Another job is running"}), 429

    try:
        cfg = load_config()
        project = request.form.get("project", cfg.get("active_project", "Default"))
        mode = request.form.get("mode", "simple")  # New: track generation mode
        project_dir = project_path(project, cfg)

        # Get reference mode (prompt or audio)
        ref_mode = request.form.get("ref_mode", "prompt")
        
        # Initialize variables
        ref_prompt = ""
        ref_audio_path = None
        lrc_path = None
        ref_audio_existing = ""
        
        # Handle reference input based on selected mode
        if ref_mode == "prompt":
            ref_prompt = request.form.get("ref_prompt", "").strip()
            if not ref_prompt:
                return jsonify({"ok": False, "error": "Text prompt is required when prompt mode is selected"}), 400
        else:  # audio mode
            # Check for existing project file first
            ref_audio_existing = request.form.get("ref_audio_existing", "").strip()
            if ref_audio_existing:
                cand = (project_dir / ref_audio_existing).resolve()
                if (project_dir in cand.parents or project_dir == cand) and cand.exists():
                    ref_audio_path = cand
            
            # Check for uploaded file if no existing file
            if not ref_audio_path:
                file = request.files.get("ref_audio")
                if file and file.filename:
                    fname = f"ref-{uuid.uuid4().hex[:8]}-{Path(file.filename).name}"
                    ref_p = UPLOADS_DIR / fname
                    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
                    file.save(str(ref_p))
                    ref_audio_path = ref_p
            
            if not ref_audio_path:
                return jsonify({"ok": False, "error": "Audio reference is required when audio mode is selected"}), 400

        # Handle LRC file (optional, advanced mode only)
        if mode == "advanced":
            lrc_file = request.files.get("lrc_file")
            if lrc_file and lrc_file.filename:
                lrc_name = f"lrc-{uuid.uuid4().hex[:8]}-{Path(lrc_file.filename).name}"
                lrc_p = UPLOADS_DIR / lrc_name
                UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
                lrc_file.save(str(lrc_p))
                lrc_path = lrc_p

        # Get parameters based on mode
        if mode == "simple":
            # Simple mode: get basic parameters and quality preset defaults
            repo_id = request.form.get("repo_id", cfg["repo_id"]) 
            audio_length = int(request.form.get("audio_length", cfg["audio_length"]))
            
            # Use preset values from form or defaults
            steps = int(request.form.get("steps", cfg["steps"]))
            cfg_strength = float(request.form.get("cfg_strength", cfg["cfg_strength"]))
            
            # Fixed values for simple mode
            batch_infer_num = 1
            use_chunked = False
            cuda_visible_devices = "0"
            
        else:  # advanced mode
            repo_id = request.form.get("repo_id", cfg["repo_id"]) 
            audio_length = int(request.form.get("audio_length", cfg["audio_length"]))
            batch_infer_num = int(request.form.get("batch_infer_num", cfg["batch_infer_num"]))
            steps = int(request.form.get("steps", cfg["steps"]))
            cfg_strength = float(request.form.get("cfg_strength", cfg["cfg_strength"]))
            use_chunked = request.form.get("use_chunked") == "on"
            cuda_visible_devices = request.form.get("cuda_visible_devices", cfg["cuda_visible_devices"]) or "0"

        # Build args map for inference
        args_map = {
            "project": project,
            "mode": mode,
            "repo_id": repo_id,
            "audio_length": audio_length,
            "batch_infer_num": batch_infer_num,
            "use_chunked": use_chunked,
            "steps": steps,
            "cfg_strength": cfg_strength,
        }
        
        if ref_audio_path:
            args_map["ref_audio_path"] = ref_audio_path
        else:
            args_map["ref_prompt"] = ref_prompt
            
        if lrc_path:
            args_map["lrc_path"] = lrc_path

        result = run_infer(args_map, {"CUDA_VISIBLE_DEVICES": cuda_visible_devices})

        # write history entry on success
        if result.get("ok"):
            h = read_history(project_dir)
            history_entry = {
                "ts": int(time.time()),
                "file": result.get("outfile_name"),
                "mode": mode,
                "ref_mode": ref_mode,
                "prompt": ref_prompt if ref_mode == "prompt" else None,
                "ref_audio": ref_audio_existing if ref_audio_existing else (str(ref_audio_path) if ref_audio_path else None),
                "audio_length": audio_length,
                "repo_id": repo_id,
                "steps": steps,
                "cfg_strength": cfg_strength,
                "chunked": use_chunked,
                "batch_infer_num": batch_infer_num,
            }
            h.append(history_entry)
            write_history(project_dir, h)

        return jsonify(result)

    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": f"Generation failed: {str(e)}"}), 500
    finally:
        RUN_LOCK.release()

# ---------------------------------------------------------------------------
# Routes: Generation (JSON for n8n and programmatic clients)
# ---------------------------------------------------------------------------
@app.route("/api/generate/json", methods=["POST"]) 
def api_generate_json():
    if not RUN_LOCK.acquire(blocking=False):
        return jsonify({"ok": False, "error": "Another job is running"}), 429

    try:
        cfg = load_config()
        data = request.get_json(force=True)

        project = data.get("project", cfg.get("active_project", "Default"))
        mode = data.get("mode", "advanced")  # JSON API defaults to advanced
        project_dir = project_path(project, cfg)

        repo_id = data.get("repo_id", cfg["repo_id"]) 
        audio_length = int(data.get("audio_length", cfg["audio_length"]))
        use_chunked = bool(data.get("use_chunked", cfg["use_chunked"]))
        batch_infer_num = int(data.get("batch_infer_num", cfg["batch_infer_num"]))
        steps = int(data.get("steps", cfg["steps"]))
        cfg_strength = float(data.get("cfg_strength", cfg["cfg_strength"]))
        cuda_visible_devices = str(data.get("cuda_visible_devices", cfg["cuda_visible_devices"]) or "")

        ref_audio_path = None
        ref_prompt = data.get("ref_prompt", "")
        ref_mode = data.get("ref_mode") or ("audio" if (data.get("ref_audio_b64") or data.get("ref_audio_url") or data.get("ref_audio_existing")) else "prompt")

        # Handle reference based on mode
        if ref_mode == "audio":
            # existing project file as ref
            if data.get("ref_audio_existing"):
                cand = (project_dir / secure_name(data.get("ref_audio_existing"))).resolve()
                if project_dir in cand.parents or project_dir == cand:
                    if cand.exists():
                        ref_audio_path = cand

            # b64 audio
            if not ref_audio_path and data.get("ref_audio_b64"):
                ref_audio_path = save_b64(data["ref_audio_b64"], data.get("ref_audio_filename") or "ref.wav", UPLOADS_DIR)

            # url audio
            if not ref_audio_path and data.get("ref_audio_url"):
                if requests is None:
                    return jsonify({"ok": False, "error": "requests not installed; cannot fetch URLs"}), 400
                ref_audio_path = save_from_url(data["ref_audio_url"], data.get("ref_audio_filename"), UPLOADS_DIR)
                
            if not ref_audio_path:
                return jsonify({"ok": False, "error": "Audio reference is required when audio mode is selected"}), 400
        else:
            if not ref_prompt.strip():
                return jsonify({"ok": False, "error": "Text prompt is required when prompt mode is selected"}), 400

        # LRC (optional) via b64 or URL
        lrc_path = None
        if data.get("lrc_b64"):
            lrc_path = save_b64(data["lrc_b64"], data.get("lrc_filename") or "lyrics.lrc", UPLOADS_DIR)
        elif data.get("lrc_url"):
            if requests is None:
                return jsonify({"ok": False, "error": "requests not installed; cannot fetch URLs"}), 400
            lrc_path = save_from_url(data["lrc_url"], data.get("lrc_filename"), UPLOADS_DIR)

        args_map = {
            "project": project,
            "mode": mode,
            "repo_id": repo_id,
            "audio_length": audio_length,
            "batch_infer_num": batch_infer_num,
            "use_chunked": use_chunked,
            "steps": steps,
            "cfg_strength": cfg_strength,
        }
        if ref_audio_path:
            args_map["ref_audio_path"] = ref_audio_path
        else:
            args_map["ref_prompt"] = ref_prompt
        if lrc_path:
            args_map["lrc_path"] = lrc_path

        result = run_infer(args_map, {"CUDA_VISIBLE_DEVICES": cuda_visible_devices})

        if result.get("ok"):
            h = read_history(project_dir)
            history_entry = {
                "ts": int(time.time()),
                "file": result.get("outfile_name"),
                "mode": mode,
                "ref_mode": ref_mode,
                "prompt": ref_prompt if ref_mode == "prompt" else None,
                "ref_audio": data.get("ref_audio_existing") or (str(ref_audio_path) if ref_audio_path else None),
                "audio_length": audio_length,
                "repo_id": repo_id,
                "steps": steps,
                "cfg_strength": cfg_strength,
                "chunked": use_chunked,
                "batch_infer_num": batch_infer_num,
            }
            h.append(history_entry)
            write_history(project_dir, h)

        return jsonify(result)

    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": f"Generation failed: {str(e)}"}), 500
    finally:
        RUN_LOCK.release()

@app.route("/api/favorites", methods=["GET", "POST"])
def api_favorites():
    if request.method == "GET":
        # Charger les favoris
        if FAVORITES_FILE.exists():
            try:
                favorites = json.loads(FAVORITES_FILE.read_text(encoding="utf-8"))
                return jsonify({"favorites": favorites})
            except Exception:
                pass
        return jsonify({"favorites": []})
    
    elif request.method == "POST":
        # Sauvegarder les favoris
        data = request.get_json(force=True)
        favorites = data.get("favorites", [])
        
        try:
            FAVORITES_FILE.write_text(json.dumps(favorites, indent=2), encoding="utf-8")
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/favorites/<favorite_id>", methods=["DELETE"])
def api_delete_favorite(favorite_id):
    if FAVORITES_FILE.exists():
        try:
            favorites = json.loads(FAVORITES_FILE.read_text(encoding="utf-8"))
            favorites = [f for f in favorites if f.get("id") != favorite_id]
            FAVORITES_FILE.write_text(json.dumps(favorites, indent=2), encoding="utf-8")
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500
    
    return jsonify({"ok": False, "error": "Favorites file not found"}), 404

# ---- Index and run ----

@app.route("/api/models", methods=["GET"])
def api_models():
    try:
        cfg = load_config()
        root = resolve_diff_root(cfg)
        models = discover_models(root)
        resp = [{'repo_id': repo, 'label': repo.split('/')[-1].replace('_', '.') } for repo in models]
        return jsonify({'ok': True, 'models': resp, 'diff_root': str(root)})
    except Exception as e:
        # Return explicit error so frontend can fallback gracefully
        return jsonify({'ok': False, 'error': str(e)}), 500

if __name__ == "__main__":
    print("DiffRhythm GUI starting...")
    print(f"App root: {APP_ROOT}")
    print(f"DiffRhythm root: {DIFF_ROOT}")
    if not INFER_SCRIPT.exists():
        print("ERROR: infer.py not found. Check that gui/ is next to the project root.")
    app.run(host="0.0.0.0", port=7860, debug=False)
