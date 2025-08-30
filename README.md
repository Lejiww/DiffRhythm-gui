
# DiffRhythm – Minimal Web GUI

A modern, intuitive web interface for **[DiffRhythm](https://github.com/ASLP-lab/DiffRhythm)**
It offers a **Simple** mode (guided presets) and an **Advanced** mode (all key parameters), plus **projects**, **prompt favorites**, **audio references**, live **model discovery + rescan**, and a rich **right-hand results panel**.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Flask](https://img.shields.io/badge/Flask-3.x-lightgrey)
![OS](https://img.shields.io/badge/OS-Linux%20%7C%20Windows%20%7C%20macOS-informational)
![License](https://img.shields.io/badge/License-MIT-green)
---

## ✨ Features

- **Two modes**
  - **Simple** — text prompt + quality preset (32 / 56 / 72 steps).
  - **Advanced** — full access to generation knobs.
- **Two reference types** — **Text prompt** or **Audio reference** (uploaded file, URL, base64, or an **existing track** from your project).
- **Projects** — organize generations in folders; create/select projects; per‑project file count.
- **Favorites** — save and reload your best prompts.
- **Model select** — list is **discovered from your local DiffRhythm install**; **↻ Rescan** without page reload.
- **Reset** — one click to reset all fields (Simple & Advanced) for a fresh generation.
- **Right‑hand results column**
  - Audio player + a collapsible **Config** table (Model, Duration, Steps, CFG, Batch, Chunked, **Prompt used**).
  - Action buttons in **two rows**: **Use as audio reference**, **Reuse prompt**, **Download**, **Rename**, **Delete**.
  - If the generation used an audio reference, a chip **“Audio ref: …”** appears and can be clicked to reuse it.

---

## 🧩 Requirements

- Python **3.10+**
- Works best in a virtual environment

---

## 🚀 Install

```bash
git clone https://github.com/ASLP-lab/DiffRhythm.git
cd DiffRhythm/gui

# virtual env
python3 -m venv venv
source venv/bin/activate

# GUI deps
pip install -r requirements.txt
```

> If your GUI lives **outside** `DiffRhythm/gui`, set `DIFFRHYTHM_ROOT` (see below).

---

## ▶️ Run

```bash
python app.py --host 0.0.0.0 --port 7860
# or
./run_gui.sh
```

Open **http://localhost:7860**.

---

## ⚙️ Configuration & Env Vars

Defaults live in `DEFAULT_CONFIG` inside `app.py`. Key values you can set in `config.json`:

```jsonc
{
  "repo_id": "ASLP-lab/DiffRhythm-1_2",
  "audio_length": 95,
  "batch_infer_num": 1,
  "use_chunked": false,
  "steps": 56,
  "cfg_strength": 3.8,
  "cuda_visible_devices": "0",
  "base_dir": "./runs",
  "active_project": "Default",
  // optional: force a Python binary for the underlying call
  // "python_bin": "/full/path/to/python",
  // optional: pin the DiffRhythm root (useful if the GUI is not under the repo)
  // "diff_root": "/path/to/DiffRhythm"
}
```

Environment variables supported:

- **`DIFFRHYTHM_ROOT`** — path to your DiffRhythm repo root (if the GUI is not inside it).
- **`DIFFRHYTHM_MODELS`** — comma- or newline-separated list of model repo-ids to force (e.g. `ASLP-lab/DiffRhythm-1_2,ASLP-lab/DiffRhythm-1_1`).

---

## 🔁 Model discovery & Rescan

The GUI discovers models directly from your **local** DiffRhythm install:

- Resolves the repo root in this order: `config.json:diff_root` → env `DIFFRHYTHM_ROOT` → heuristic (`GUI/..`) → walk up until `infer/infer.py` is found.
- Scans typical folders (`models/`, `checkpoints/`, `pretrained/`, …) and key files for IDs like `ASLP-lab/DiffRhythm-*`.
- Returns `{ ok, models: [{ repo_id, label }], diff_root }` to the UI.

Use the **↻ Rescan models** button (next to the select) to refresh the list without restarting the server.

---

## 🧠 Simple vs Advanced

**Simple mode** exposes: Prompt (multiline), Model, Duration, Quality preset.  
**Advanced mode** exposes all parameters and reference types.

Advanced → CLI flags mapping:

| UI field          | CLI flag            |
|-------------------|---------------------|
| `repo_id`         | `--repo-id`         |
| `audio_length`    | `--audio-length`    |
| `steps`           | `--steps`           |
| `cfg_strength`    | `--cfg-strength`    |
| `batch_infer_num` | `--batch-infer-num` |
| `use_chunked`     | `--chunked`         |
| `ref_prompt`      | `--ref-prompt`      |
| `ref_audio_path`  | `--ref-audio-path`  |
| `lrc_path`        | `--lrc-path`        |

All of the above are passed to DiffRhythm when you click **Generate**.

---

## 🧭 API Overview (server)

- `GET /api/config` — load defaults and presets
- `GET /api/models` — discover local models
- `POST /api/generate` — form submit (Simple/Advanced)
- `POST /api/generate/json` — JSON API for programmatic use
- Project & files:
  - `GET /api/projects/list`
  - `GET /api/files/list?project=...`
  - `POST /api/files/rename`
  - `POST /api/files/delete`
- Favorites:
  - `GET /api/favorites`
  - `POST /api/favorites` (save)
  - `POST /api/favorites/delete/<id>`
- Playback & download:
  - `GET /play/<project>/<filename>`
  - `GET /download/<project>/<filename>`

> The right column is populated from server history so you always see the exact config & prompt used for each track.

---

## 🧹 Reset behavior

The **Reset** button (both tabs) will:

- reset the form,
- switch back to **Prompt** mode,
- clear prompt & audio reference (including “existing track”),
- in Advanced: restore defaults from `config.json`,
- clear the logs area,
- show a toast confirmation.

---

## 🛠️ Patching DiffRhythm (if your `infer/infer.py` misses CLI flags)

Some snapshots of DiffRhythm don’t expose every CLI option this GUI sends.  
If you see errors like `unrecognized arguments: --repo-id ...`, run the patch script below — it’s **idempotent** (safe to run multiple times).

### 1) Create the patch script

```bash
mkdir -p scripts
cat > scripts/patch_diffrhythm.sh << 'EOF'
#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./scripts/patch_diffrhythm.sh /path/to/DiffRhythm
# or set DIFFRHYTHM_ROOT and run without args

ROOT="${1:-${DIFFRHYTHM_ROOT:-}}"
if [[ -z "${ROOT}" ]]; then
  echo "Error: provide DiffRhythm root as argument or set DIFFRHYTHM_ROOT" >&2
  exit 1
fi

INFER="${ROOT%/}/infer/infer.py"
if [[ ! -f "$INFER" ]]; then
  echo "Error: not found: $INFER" >&2
  exit 1
fi

# Backup once
if [[ ! -f "${INFER}.bak" ]]; then
  cp "$INFER" "${INFER}.bak"
fi

python3 - "$INFER" <<'PYEOF'
import io, re, sys, pathlib
path = pathlib.Path(sys.argv[1])
src = path.read_text(encoding="utf-8")

# Ensure argparse is imported
if "import argparse" not in src:
    src = "import argparse\n" + src

# Find parser variable name
m = re.search(r"(\w+)\s*=\s*argparse\.ArgumentParser", src)
if not m:
    print("Could not find argparse.ArgumentParser in infer.py; aborting", file=sys.stderr)
    sys.exit(2)
parser_var = m.group(1)

def has_flag(s, flag):
    return re.search(rf"--{re.escape(flag)}\\b", s) is not None

def add_arg_line(flag, code):
    global src
    if has_flag(src, flag):
        return
    # Insert after the last existing add_argument
    addrs = list(re.finditer(rf"{parser_var}\\s*\\.\\s*add_argument\\(", src))
    if not addrs:
        # fallback: append near parser creation
        insert_at = m.end()
    else:
        insert_at = addrs[-1].end()
        # move to end of that line
        insert_at = src.find("\\n", insert_at)
        if insert_at == -1:
            insert_at = addrs[-1].end()
    src = src[:insert_at] + f"\\n{parser_var}.add_argument({code})" + src[insert_at:]

# Arguments to ensure (idempotent)
add_arg_line("repo-id",       '"--repo-id", type=str, required=False')
add_arg_line("audio-length",  '"--audio-length", type=int, required=False')
add_arg_line("steps",         '"--steps", type=int, required=False')
add_arg_line("cfg-strength",  '"--cfg-strength", type=float, required=False')
add_arg_line("batch-infer-num", '"--batch-infer-num", type=int, required=False')
add_arg_line("chunked",       '"--chunked", action="store_true"')
add_arg_line("ref-prompt",    '"--ref-prompt", type=str, required=False')
add_arg_line("ref-audio-path",'\"--ref-audio-path\", type=str, required=False')
add_arg_line("lrc-path",      '"--lrc-path", type=str, required=False')

path.write_text(src, encoding="utf-8")
print("infer.py patched OK")
PYEOF

echo "✔ DiffRhythm infer.py patched"
EOF
chmod +x scripts/patch_diffrhythm.sh
```

### 2) Run the patch

```bash
# Provide the root explicitly OR export DIFFRHYTHM_ROOT
./scripts/patch_diffrhythm.sh /path/to/DiffRhythm
# or
DIFFRHYTHM_ROOT=/path/to/DiffRhythm ./scripts/patch_diffrhythm.sh
```

The script only **adds argparse flags if they’re missing**.  
It does **not** change your inference logic; it simply ensures the CLI accepts the options this GUI passes.

---

## 📦 API usage (JSON example)

```bash
curl -X POST http://localhost:7860/api/generate/json \
  -H "Content-Type: application/json" \
  -d '{
        "mode": "advanced",
        "repo_id": "ASLP-lab/DiffRhythm-1_2",
        "audio_length": 95,
        "steps": 56,
        "cfg_strength": 3.8,
        "batch_infer_num": 1,
        "use_chunked": false,
        "ref_mode": "prompt",
        "ref_prompt": "solo grand piano, studio quality, no vocals"
      }'
```

---

## 🤝 Contributing

We’d love your help! Here’s how to contribute:

### 1) Issues
- **Search first** to avoid duplicates.
- Open a **Bug report** with clear steps to reproduce, logs, and your environment (OS, Python, GPU).
- Open a **Feature request** with a concise use‑case and expected behavior.

### 2) Pull requests
- **Fork** the repo and create a topic branch: `feat/<topic>` or `fix/<topic>`.
- Keep PRs **small and focused**. Reference related issues in the description (e.g., `Closes #123`).  
- Update docs if behavior or config changes.
- Ensure the GUI **runs locally** without errors (`python app.py`) before submitting.

### 3) Code style
- Keep code **readable and minimal**. Prefer small helper functions over long blocks.
- Use **clear commit messages** (imperative mood). Squash if necessary before merge.

### 4) Review & merge
- Maintainers review for functionality, clarity, and UX consistency.
- I may request changes; once approved, I’ll squash‑merge.

Thank you for contributing!

---

## 📄 License

- **GUI Code**: MIT License - full freedom to use, modify, distribute
- **DiffRhythm Model**: Apache-2.0 - see [upstream repository](https://github.com/ASLP-lab/DiffRhythm)

---

## 🙌 Credits

- **ASLP-LAB** for the incredible DiffRhythm model and research
- GUI crafted with ❤️ by **Le_jiww**

---

**⭐ If this GUI helps you create amazing music, please star the repository!**

**🎵 Happy music generating! 🎵**
