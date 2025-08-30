/* DiffRhythm GUI - Frontend
 * Favorites overhaul: same "…" menu as folders + modal for create/edit (Title + Prompt only)
 * No backend change required (expects /api/favorites GET/POST and DELETE).
 */

(() => {
  // ---------------------------
  // State / Utils
  // ---------------------------
  const STATE = {
    mode: 'simple',
    config: null,
    activeProject: 'Default',
    projects: [],
    files: [],
    history: [],
    favorites: [],
    menusOpen: new Set(), // track open dropdowns
  };

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const ce = (tag, cls, html) => {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    if (html !== undefined) el.innerHTML = html;
    return el;
  };

  const uuid = () => 'xxxxxxxx'.replace(/x/g, () => (Math.random()*16|0).toString(16));

  const getJSON = async (url) => {
    const r = await fetch(url);
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  };

  const postJSON = async (url, body) => {
    const r = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body ?? {}),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  };

  const del = async (url) => {
    const r = await fetch(url, { method: 'DELETE' });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  };

  // ---------------------------
  // Toasts
  // ---------------------------
  function toast(msg, type = 'info', ms = 2200) {
    const t = ce('div', `toast ${type}`);
    t.textContent = msg;
    document.body.appendChild(t);
    requestAnimationFrame(() => t.style.transform = 'translateY(0)');
    setTimeout(() => {
      t.style.opacity = '0';
      setTimeout(() => t.remove(), 300);
    }, ms);
  }

  // ---------------------------
  // Modal system
  // ---------------------------
  function modalBase({ iconClass = 'input', title = '', body = null, actions = [] }) {
    let overlay = ce('div', 'modal-overlay');
    let modal = ce('div', 'modal');

    const header = ce('div', 'modal-header');
    const icon = ce('div', `modal-icon ${iconClass}`);
    icon.textContent = iconClass === 'danger' ? '⛔' : iconClass === 'confirm' ? '⚠️' : '✨';
    const t = ce('div', 'modal-title', title);
    header.appendChild(icon);
    header.appendChild(t);

    const mb = ce('div', 'modal-body');
    if (body) mb.appendChild(body);

    const act = ce('div', 'modal-actions');
    actions.forEach(a => act.appendChild(a));

    modal.appendChild(header);
    modal.appendChild(mb);
    modal.appendChild(act);
    overlay.appendChild(modal);

    function close() {
      overlay.classList.remove('show');
      setTimeout(() => overlay.remove(), 200);
      document.removeEventListener('keydown', onEsc, true);
    }
    function onEsc(e) { if (e.key === 'Escape') close(); }
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    document.addEventListener('keydown', onEsc, true);

    document.body.appendChild(overlay);
    requestAnimationFrame(() => overlay.classList.add('show'));

    return { overlay, close };
  }

  function modalFormFavorite({ initialTitle = '', initialPrompt = '', submitLabel = 'Save', onSubmit }) {
    const wrap = ce('div');
    const msg = ce('div', 'modal-message', "Fill in Title and Prompt. Icon isn't editable.");
    const inpTitle = ce('input', 'modal-input');
    inpTitle.placeholder = 'Favorite title';
    inpTitle.value = initialTitle || '';

    const inpPrompt = ce('textarea', 'modal-input');
    inpPrompt.placeholder = 'Prompt';
    inpPrompt.style.marginTop = '10px';
    inpPrompt.value = initialPrompt || '';
    inpPrompt.rows = 6;

    wrap.appendChild(msg);
    wrap.appendChild(inpTitle);
    wrap.appendChild(inpPrompt);

    const btnCancel = ce('button', 'modal-btn cancel', 'Cancel');
    const btnSubmit = ce('button', 'modal-btn confirm', submitLabel);

    const { overlay, close } = modalBase({
      iconClass: 'input',
      title: '✏️ Prompt Favorite',
      body: wrap,
      actions: [btnCancel, btnSubmit],
    });

    btnCancel.onclick = () => close();
    btnSubmit.onclick = async () => {
      const title = (inpTitle.value || '').trim();
      const prompt = (inpPrompt.value || '').trim();
      if (!title) return toast('Title is required.', 'error');
      if (!prompt) return toast('Prompt is required.', 'error');
      try {
        await onSubmit({ title, prompt });
        close();
      } catch (e) {
        toast('Error: ' + (e?.message || e), 'error');
      }
    };

    inpTitle.focus();
  }

  function modalConfirm({ title, message, danger = false, confirmLabel = 'Confirm' }) {
    return new Promise((resolve) => {
      const msg = ce('div', 'modal-message', message);
      const btnCancel = ce('button', 'modal-btn cancel', 'Cancel');
      const btnConfirm = ce('button', `modal-btn ${danger ? 'danger' : 'confirm'}`, confirmLabel);

      const { close } = modalBase({
        iconClass: danger ? 'danger' : 'confirm',
        title,
        body: msg,
        actions: [btnCancel, btnConfirm],
      });

      btnCancel.onclick = () => { close(); resolve(false); };
      btnConfirm.onclick = () => { close(); resolve(true); };
    });
  }

  // ---------------------------
  // Config
  // ---------------------------
  async function loadConfig() {
    const cfg = await getJSON('/api/config');
    STATE.config = cfg;
    STATE.activeProject = cfg.active_project || 'Default';
    $('#base_dir').value = cfg.base_dir || '';
  }

  async function saveDefaults() {
    const body = {
      base_dir: $('#base_dir').value,
      repo_id: $('#form-advanced select[name=repo_id]').value,
      audio_length: parseInt($('#form-advanced select[name=audio_length]').value, 10),
      batch_infer_num: parseInt($('#form-advanced input[name=batch_infer_num]').value, 10),
      use_chunked: $('#form-advanced input[name=use_chunked]').checked,
      steps: parseInt($('#form-advanced input[name=steps]').value, 10),
      cfg_strength: parseFloat($('#form-advanced input[name=cfg_strength]').value),
      cuda_visible_devices: $('#form-advanced input[name=cuda_visible_devices]').value,
      active_project: STATE.activeProject,
    };
    await postJSON('/api/config', body);
    toast('Settings saved', 'success');
    await loadProjects(); // base_dir may change project list
    await loadFiles();
  }
  window.saveDefaults = saveDefaults;

  // ---------------------------
  // Projects (folders)
  // ---------------------------
  async function loadProjects() {
    const data = await getJSON('/api/projects/list');
    STATE.projects = data.projects || [];
    STATE.activeProject = data.active || STATE.activeProject || 'Default';
    renderProjects();
  }

  function renderProjects() {
    const box = $('#proj-list');
    box.innerHTML = '';
    STATE.projects.forEach(p => {
      const row = ce('div', 'proj');
      if (p.name === STATE.activeProject) row.classList.add('active');

      const main = ce('div', 'proj-main');
      const icon = ce('div', 'proj-icon', '📁');
      const name = ce('div', null, p.name);
      main.appendChild(icon);
      main.appendChild(name);

      const right = ce('div', 'row');
      const count = ce('div', 'count', String(p.count ?? 0));

      // same menu UI as folders
      const menu = ce('div', 'proj-menu');
      const btn = ce('div', 'proj-menu-btn', '•••');
      const drop = ce('div', 'proj-menu-dropdown');

      const itRename = ce('div', 'proj-menu-item', '✏️ Rename');
      const itDelete = ce('div', 'proj-menu-item danger', '🗑️ Delete');
      drop.appendChild(itRename);
      drop.appendChild(itDelete);

      menu.appendChild(btn);
      menu.appendChild(drop);

      row.onclick = async (e) => {
        if (menu.contains(e.target)) return; // do not switch project if clicking menu
        if (p.name !== STATE.activeProject) {
          STATE.activeProject = p.name;
          await postJSON('/api/config', { active_project: STATE.activeProject });
          renderProjects();
          await loadFiles();
        }
      };

      btn.onclick = (e) => {
        e.stopPropagation();
        toggleMenu(menu);
      };

      itRename.onclick = async (e) => {
        e.stopPropagation();
        if (p.name === 'Default') {
          toast("Project 'Default' cannot be renamed.", 'error');
          closeAllMenus();
          return;
        }
        promptRenameProject(p.name);
      };

      itDelete.onclick = async (e) => {
        e.stopPropagation();
        if (p.name === 'Default') {
          toast("Project 'Default' cannot be deleted.", 'error');
          closeAllMenus();
          return;
        }
        const ok = await modalConfirm({
          title: 'Delete project',
          message: `Delete project “${p.name}”?`,
          danger: true,
          confirmLabel: 'Delete'
        });
        closeAllMenus();
        if (!ok) return;
        try {
          await postJSON('/api/projects/delete', { name: p.name, force: true });
          await loadProjects();
          await loadFiles();
          toast('Project deleted', 'success');
        } catch (err) {
          toast('Error: ' + (err?.message || err), 'error');
        }
      };

      right.appendChild(count);
      right.appendChild(menu);

      row.appendChild(main);
      row.appendChild(right);
      box.appendChild(row);
    });
  }

  function promptRenameProject(oldName) {
    const wrap = ce('div');
    const inp = ce('input', 'modal-input');
    inp.placeholder = 'New name';
    inp.value = oldName;
    wrap.appendChild(ce('div', 'modal-message', 'Rename project'));
    wrap.appendChild(inp);

    const btnCancel = ce('button', 'modal-btn cancel', 'Cancel');
    const btnOk = ce('button', 'modal-btn confirm', 'Rename');

    const { close } = modalBase({
      iconClass: 'input',
      title: '✏️ Rename Project',
      body: wrap,
      actions: [btnCancel, btnOk],
    });

    btnCancel.onclick = () => close();
    btnOk.onclick = async () => {
      const newName = (inp.value || '').trim();
      if (!newName) return toast('Name is required', 'error');
      if (newName === oldName) return close();
      try {
        await postJSON('/api/projects/rename', { old: oldName, new: newName });
        close();
        await loadProjects();
        await loadFiles();
        toast('Project renamed', 'success');
      } catch (e) {
        toast('Error: ' + (e?.message || e), 'error');
      }
    };

    inp.focus();
  }

  async function addProject() {
    const wrap = ce('div');
    const inp = ce('input', 'modal-input');
    inp.placeholder = 'Project name';
    wrap.appendChild(ce('div', 'modal-message', 'Create a new project'));
    wrap.appendChild(inp);

    const btnCancel = ce('button', 'modal-btn cancel', 'Cancel');
    const btnOk = ce('button', 'modal-btn confirm', 'Create');

    const { close } = modalBase({
      iconClass: 'input',
      title: '➕ New Project',
      body: wrap,
      actions: [btnCancel, btnOk],
    });

    btnCancel.onclick = () => close();
    btnOk.onclick = async () => {
      const name = (inp.value || '').trim();
      if (!name) return toast('Name is required', 'error');
      try {
        await postJSON('/api/projects/create', { name });
        close();
        await loadProjects();
        toast('Project created', 'success');
      } catch (e) {
        toast('Error: ' + (e?.message || e), 'error');
      }
    };
    inp.focus();
  }
  window.addProject = addProject;

  // ---------------------------
  // Files pane (right column)
  // ---------------------------
  async function loadFiles() {
    const data = await getJSON(`/api/files/list?project=${encodeURIComponent(STATE.activeProject)}`);
    STATE.files = data.files ?? [];
    STATE.history = data.history ?? [];
    renderFiles();
  }

  function renderFiles() {
  const box = $('#files-box');
  box.innerHTML = '';
  if (!STATE.files.length) {
    box.innerHTML = '<div class="small" style="color:var(--text-tertiary)">No files for this project.</div>';
    return;
  }

  // index latest history by file
  const histByFile = new Map();
  (STATE.history || []).forEach(h => {
    if (!h || !h.file) return;
    const prev = histByFile.get(h.file);
    if (!prev || (h.ts || 0) > (prev.ts || 0)) histByFile.set(h.file, h);
  });

  const bname = (s) => (s || '').split(/[\\/]/).pop();

  STATE.files
    .slice()
    .sort((a, b) => b.mtime - a.mtime)
    .forEach(file => {
      const card = ce('div', 'track');

      // Header
      const head = ce('div', 'track-header');
      head.appendChild(ce('div', 'track-name', file.name));
      head.appendChild(ce('div', 'track-date', new Date(file.mtime * 1000).toLocaleString()));
      card.appendChild(head);

      const h = histByFile.get(file.name);

      // Audio ref chip when history says audio mode
      if (h && h.ref_mode === 'audio' && h.ref_audio) {
        const chip = ce('div', 'ref-chip', `Audio ref: ${bname(h.ref_audio)}`);
        chip.title = h.ref_audio;
        chip.onclick = () => {
          if (STATE.mode === 'advanced') {
            $('input[name=ref_mode][value=audio]').checked = true;
            toggleRefModeAdvanced();
            $('#ref_audio_existing').value = bname(h.ref_audio);
          } else {
            $('input[name=ref_mode_simple][value=audio]').checked = true;
            toggleRefModeSimple();
            $('#ref_audio_existing_simple').value = bname(h.ref_audio);
          }
          toast('Audio reference selected', 'success');
        };
        card.appendChild(chip);
      }

      // Config (collapsed by default)
      if (h) {
        const cfgBox = ce('div', 'config-box');
        const cfgTop = ce('div', 'config-top');
        cfgTop.appendChild(ce('div', 'config-label', 'Config'));
        const btnT = ce('button', 'config-toggle', 'Show config');
        cfgTop.appendChild(btnT);
        const cfgContent = ce('div', 'config-content');
        const tbl = ce('table', 'config-table');

        const addRow = (k, v) => {
          if (v === undefined || v === null || v === '') return;
          const tr = ce('tr');
          tr.appendChild(ce('td', 'cfg-k', k));
          tr.appendChild(ce('td', 'cfg-v', String(v)));
          tbl.appendChild(tr);
        };

        addRow('Model', h.repo_id);
        addRow('Dur', h.audio_length ? `${h.audio_length}s` : '');
        addRow('Steps', h.steps);
        addRow('CFG', h.cfg_strength);
        addRow('Batch', h.batch_infer_num);
        addRow('Chunked', h.chunked ? 'Yes' : 'No');
        if (h.ref_mode === 'prompt' && h.prompt) addRow('Prompt used', h.prompt);

        if (tbl.childElementCount) {
          cfgContent.appendChild(tbl);
          cfgBox.appendChild(cfgTop);
          cfgBox.appendChild(cfgContent);
          card.appendChild(cfgBox);
          btnT.onclick = () => {
            cfgBox.classList.toggle('expanded');
            btnT.textContent = cfgBox.classList.contains('expanded') ? 'Hide config' : 'Show config';
          };
        }
      }

      // Player
      const audio = ce('audio', 'audio');
      audio.controls = true;
      audio.src = `/play/${encodeURIComponent(STATE.activeProject)}/${encodeURIComponent(file.name)}`;
      card.appendChild(audio);

      // Actions (two rows)
      const actions = ce('div', 'track-actions');
      const row1 = ce('div', 'actions-row');
      const row2 = ce('div', 'actions-row');

      // Row 1: Use as audio reference + Reuse prompt (if prompt history exists)
      const bUse = ce('button', 'btn primary', '🎯 Use as audio reference');
      bUse.onclick = () => {
        if (STATE.mode === 'advanced') {
          $('input[name=ref_mode][value=audio]').checked = true;
          toggleRefModeAdvanced();
          $('#ref_audio_existing').value = file.name;
        } else {
          $('input[name=ref_mode_simple][value=audio]').checked = true;
          toggleRefModeSimple();
          $('#ref_audio_existing_simple').value = file.name;
        }
        toast('Selected as audio reference', 'success');
      };
      row1.appendChild(bUse);

      if (h && h.ref_mode === 'prompt' && h.prompt) {
        const bReuse = ce('button', 'btn', '↩️ Reuse prompt');
        bReuse.onclick = () => {
          $$('input[name=\"ref_prompt\"]').forEach(inp => inp.value = h.prompt);
          const r1 = $('input[name=ref_mode][value=prompt]');
          const r2 = $('input[name=ref_mode_simple][value=prompt]');
          if (r1) { r1.checked = true; toggleRefModeAdvanced(); }
          if (r2) { r2.checked = true; toggleRefModeSimple(); }
          toast('Prompt loaded', 'success');
        };
        row1.appendChild(bReuse);
      }

      // Row 2: Download, Rename, Delete
      const aDn = ce('a');
      aDn.href = `/download/${encodeURIComponent(STATE.activeProject)}/${encodeURIComponent(file.name)}`;
      aDn.innerHTML = '<button class="btn">⬇️ Download</button>';
      row2.appendChild(aDn);

      const bRename = ce('button', 'btn', '✏️ Rename');
      bRename.onclick = () => {
        const wrap = ce('div');
        const inp = ce('input', 'modal-input'); inp.value = file.name;
        wrap.appendChild(ce('div', 'modal-message', 'Rename file'));
        wrap.appendChild(inp);
        const btnCancel = ce('button', 'modal-btn cancel', 'Cancel');
        const btnOk = ce('button', 'modal-btn confirm', 'Rename');
        const { close } = modalBase({ iconClass: 'input', title: '✏️ Rename File', body: wrap, actions: [btnCancel, btnOk] });
        btnCancel.onclick = () => close();
        btnOk.onclick = async () => {
          const newName = (inp.value || '').trim();
          if (!newName || newName === file.name) return close();
          try {
            await postJSON('/api/files/rename', { project: STATE.activeProject, src: file.name, dst: newName });
            close();
            await loadFiles();
            toast('File renamed', 'success');
          } catch (e) {
            toast('Error: ' + (e?.message || e), 'error');
          }
        };
        inp.focus();
      };
      row2.appendChild(bRename);

      const bDel = ce('button', 'btn danger', '🗑️ Delete');
      bDel.onclick = () => {
        const btnCancel = ce('button', 'modal-btn cancel', 'Cancel');
        const btnOk = ce('button', 'modal-btn danger', 'Delete');
        const { close } = modalBase({
          iconClass: 'danger',
          title: 'Delete file',
          body: ce('div', 'modal-message', `Delete <b>${file.name}</b>? This cannot be undone.`),
          actions: [btnCancel, btnOk],
        });
        btnCancel.onclick = close;
        btnOk.onclick = async () => {
          try {
            await postJSON('/api/files/delete', { project: STATE.activeProject, name: file.name });
            close();
            await loadFiles();
            toast('Deleted', 'success');
          } catch (e) {
            toast('Error: ' + (e?.message || e), 'error');
          }
        };
      };
      row2.appendChild(bDel);

      actions.appendChild(row1);
      actions.appendChild(row2);
      card.appendChild(actions);
      box.appendChild(card);
    });
}

  // ---------------------------
  // Mode (simple / advanced)
  // ---------------------------
  function setMode(m) {
    STATE.mode = m;
    if (m === 'advanced') {
      $('#advanced').style.display = '';
      $('#simple').style.display = 'none';
      $('#btn-advanced').classList.add('active');
      $('#btn-simple').classList.remove('active');
    } else {
      $('#advanced').style.display = 'none';
      $('#simple').style.display = '';
      $('#btn-simple').classList.add('active');
      $('#btn-advanced').classList.remove('active');
    }
  }
  window.setMode = setMode;

  function toggleRefModeSimple() {
    const val = $('input[name=ref_mode_simple]:checked').value;
    $('#prompt-section-simple').style.display = (val === 'prompt') ? '' : 'none';
    $('#audio-section-simple').style.display = (val === 'audio') ? '' : 'none';
  }

  function toggleRefModeAdvanced() {
    const val = $('input[name=ref_mode]:checked').value;
    $('#prompt-section').style.display = (val === 'prompt') ? '' : 'none';
    $('#audio-section').style.display = (val === 'audio') ? '' : 'none';
  }

  // ---------------------------
  // Generate
  // ---------------------------
  async function generate(mode) {
    const form = new FormData(mode === 'advanced' ? $('#form-advanced') : $('#form-simple'));
    form.set('project', STATE.activeProject);
    form.set('mode', mode);

    if (mode === 'simple') {
      form.set('ref_mode', $('input[name=ref_mode_simple]:checked').value);
    }

    const btn = (mode === 'advanced') ? $('#btn-generate-advanced') : $('#btn-generate-simple');
    btn.disabled = true;
    btn.innerHTML = '⏳ Generating...';

    try {
      const r = await fetch('/api/generate', { method: 'POST', body: form });
      const data = await r.json();
      $('#logs').value = (data.logs || data.error || '') + '\n';
      if (!data.ok) {
        toast(data.error || 'Generation error', 'error', 3500);
      } else {
        toast('Generation completed', 'success');
        await loadFiles();
      }
    } catch (e) {
      toast('Error: ' + (e?.message || e), 'error');
    } finally {
      btn.disabled = false;
      btn.innerHTML = '🎵 Generate Music';
    }
  }
  window.generate = generate;

  // ---------------------------
  // Favorites
  // ---------------------------
  async function loadFavorites() {
    try {
      const data = await getJSON('/api/favorites');
      STATE.favorites = Array.isArray(data.favorites) ? data.favorites : [];
      renderFavorites();
    } catch (e) {
      STATE.favorites = [];
      renderFavorites();
    }
  }

  async function saveFavorites(all) {
    await postJSON('/api/favorites', { favorites: all });
  }

  function renderFavorites() {
    const box = $('#favorites-list');
    box.innerHTML = '';
    if (!STATE.favorites.length) {
      box.innerHTML = '<div class="small" style="color:var(--text-tertiary)">No favorites yet. Click “Save Current Prompt” to create one.</div>';
      return;
    }

    STATE.favorites.forEach(fav => {
      const row = ce('div', 'favorite-item');

      // header line: title + menu
      const head = ce('div', 'favorite-name');
      const titleSpan = ce('span', null, fav.title || 'Untitled');

      const menu = ce('div', 'proj-menu');     // reuse same menu UI/classes as folders
      const btn = ce('div', 'proj-menu-btn', '•••');
      const drop = ce('div', 'proj-menu-dropdown');

      const itApply = ce('div', 'proj-menu-item', '📥 Apply to prompt');
      const itEdit  = ce('div', 'proj-menu-item', '✏️ Edit');
      const itDel   = ce('div', 'proj-menu-item danger', '🗑️ Delete');

      drop.appendChild(itApply);
      drop.appendChild(itEdit);
      drop.appendChild(itDel);
      menu.appendChild(btn);
      menu.appendChild(drop);

      head.appendChild(titleSpan);
      head.appendChild(menu);

      // one-line preview
      const prev = ce('div', 'favorite-prompt', (fav.prompt || '').trim());

      // interactions
      row.onclick = (e) => {
        if (menu.contains(e.target)) return; // clicking menu shouldn't apply
        applyFavorite(fav);
      };

      btn.onclick = (e) => {
        e.stopPropagation();
        toggleMenu(menu);
      };

      itApply.onclick = (e) => {
        e.stopPropagation();
        applyFavorite(fav);
        closeAllMenus();
      };

      itEdit.onclick = async (e) => {
        e.stopPropagation();
        editFavorite(fav);
        // menu closes in edit callback
      };

      itDel.onclick = async (e) => {
        e.stopPropagation();
        const ok = await modalConfirm({
          title: 'Delete favorite',
          message: `Delete “${fav.title || 'Untitled'}”?`,
          danger: true,
          confirmLabel: 'Delete'
        });
        if (!ok) { closeAllMenus(); return; }
        try {
          if (fav.id) {
            await del(`/api/favorites/${encodeURIComponent(fav.id)}`);
            await loadFavorites();
          } else {
            STATE.favorites = STATE.favorites.filter(x => x !== fav);
            await saveFavorites(STATE.favorites);
            renderFavorites();
          }
          toast('Favorite deleted', 'success');
        } catch (err) {
          toast('Error: ' + (err?.message || err), 'error');
        } finally {
          closeAllMenus();
        }
      };

      row.appendChild(head);
      row.appendChild(prev);
      box.appendChild(row);
    });
  }

  function applyFavorite(fav) {
    if (STATE.mode === 'advanced') {
      $('input[name=ref_mode][value=prompt]').checked = true;
      toggleRefModeAdvanced();
      $('#form-advanced input[name=ref_prompt]').value = fav.prompt || '';
    } else {
      $('input[name=ref_mode_simple][value=prompt]').checked = true;
      toggleRefModeSimple();
      $('#form-simple input[name=ref_prompt]').value = fav.prompt || '';
    }
    toast('Prompt applied', 'success');
  }

  function addCurrentPromptToFavorites() {
    const current = getCurrentPromptText();
    const suggested = suggestTitleFromPrompt(current);

    modalFormFavorite({
      initialTitle: suggested,
      initialPrompt: current,
      submitLabel: 'Save',
      onSubmit: async ({ title, prompt }) => {
        const fav = { id: uuid(), title, prompt };
        STATE.favorites.push(fav);
        await saveFavorites(STATE.favorites);
        renderFavorites();
        toast('Favorite added', 'success');
      }
    });
  }
  window.addCurrentPromptToFavorites = addCurrentPromptToFavorites;

  function editFavorite(fav) {
    modalFormFavorite({
      initialTitle: fav.title || '',
      initialPrompt: fav.prompt || '',
      submitLabel: 'Update',
      onSubmit: async ({ title, prompt }) => {
        const updated = STATE.favorites.map(x => {
          if (x === fav || (fav.id && x.id === fav.id)) {
            return { ...x, title, prompt }; // do NOT touch icon
          }
          return x;
        });
        STATE.favorites = updated;
        await saveFavorites(STATE.favorites);
        renderFavorites();
        toast('Favorite updated', 'success');
        closeAllMenus();
      }
    });
  }

  function getCurrentPromptText() {
    if (STATE.mode === 'advanced') {
      const valRadio = $('input[name=ref_mode]:checked').value;
      if (valRadio === 'prompt') {
        return ($('#form-advanced input[name=ref_prompt]').value || '').trim();
      } else {
        return '';
      }
    } else {
      const valRadio = $('input[name=ref_mode_simple]:checked').value;
      if (valRadio === 'prompt') {
        return ($('#form-simple input[name=ref_prompt]').value || '').trim();
      } else {
        return '';
      }
    }
  }

  function suggestTitleFromPrompt(p) {
    const t = (p || '').trim();
    if (!t) return 'My favorite';
    const s = t.split(/[.,;:!?]/)[0].trim();
    if (s.length <= 40) return s || 'My favorite';
    return s.slice(0, 40).trim() + '…';
  }

  // ---------------------------
  // Menus helpers
  // ---------------------------
  function toggleMenu(menuEl) {
    const drop = $('.proj-menu-dropdown', menuEl);
    const isOpen = drop.classList.contains('show');
    closeAllMenus();
    if (!isOpen) {
      drop.classList.add('show');
      menuEl.classList.add('open');
      STATE.menusOpen.add(menuEl);
    }
  }
  function closeAllMenus() {
    document.querySelectorAll('.proj-menu-dropdown.show').forEach(d => d.classList.remove('show'));
    document.querySelectorAll('.proj-menu.open').forEach(m => m.classList.remove('open'));
    STATE.menusOpen.clear();
  }
  document.addEventListener('click', (e) => {
    if (![...STATE.menusOpen].some(m => m.contains(e.target))) {
      closeAllMenus();
    }
  });

  // ---------------------------
  // Bind UI
  // ---------------------------
  function bindUI() {
    setMode('simple');

    $$('input[name=ref_mode_simple]').forEach(r => r.addEventListener('change', toggleRefModeSimple));
    toggleRefModeSimple();

    $$( 'input[name=ref_mode]' ).forEach(r => r.addEventListener('change', toggleRefModeAdvanced));
    toggleRefModeAdvanced();
  }

  
  async function reloadModels() {
    const btns = $$('.btn-reload-models');
    btns.forEach(b => b.disabled = true);
    const n = await loadModels();
    if (n > 0) {
      toast('Models reloaded (' + n + ')', 'success');
    } else {
      toast('Failed to reload models', 'error');
    }
    btns.forEach(b => b.disabled = false);
  }
  window.reloadModels = reloadModels;

  // Reset all fields to start a new generation
  function resetGeneration(mode) {
    const form = mode === 'advanced' ? $('#form-advanced') : $('#form-simple');
    if (!form) return;

    // Reset native form fields
    form.reset();

    // Ensure prompt mode is selected
    if (mode === 'advanced') {
      const pr = form.querySelector('input[name=ref_mode][value=prompt]');
      if (pr) pr.checked = true;
      if (typeof toggleRefModeAdvanced === 'function') toggleRefModeAdvanced();
      const ex = $('#ref_audio_existing'); if (ex) ex.value = '';
    } else {
      const pr = form.querySelector('input[name=ref_mode_simple][value=prompt]');
      if (pr) pr.checked = true;
      if (typeof toggleRefModeSimple === 'function') toggleRefModeSimple();
      const ex = $('#ref_audio_existing_simple'); if (ex) ex.value = '';
    }

    // Clear file inputs
    const fileInp = form.querySelector('input[name=ref_audio]');
    if (fileInp) fileInp.value = '';

    // Clear prompt fields (input or textarea)
    form.querySelectorAll("[name='ref_prompt']").forEach(el => el.value = '');

    // Restore advanced defaults from server config, if available
    if (mode === 'advanced' && STATE && STATE.config) {
      const cfg = STATE.config;
      const setVal = (sel, v) => { const el = form.querySelector(sel); if (el && v !== undefined && v !== null) el.value = String(v); };
      setVal("select[name=repo_id]", cfg.repo_id);
      setVal("select[name=audio_length]", cfg.audio_length);
      setVal("input[name=steps]", cfg.steps);
      setVal("input[name=cfg_strength]", cfg.cfg_strength);
      setVal("input[name=batch_infer_num]", cfg.batch_infer_num);
      const chk = form.querySelector("input[name=use_chunked]"); if (chk) chk.checked = !!cfg.use_chunked;
      const cuda = form.querySelector("input[name=cuda_visible_devices]"); if (cuda && cfg.cuda_visible_devices !== undefined) cuda.value = String(cfg.cuda_visible_devices);
    }

    // Clear logs
    const logs = $('#logs'); if (logs) logs.value = '';

    toast('Form reset', 'success');
  }
  window.resetGeneration = resetGeneration;
// ---------------------------
  // Boot
  // ---------------------------
  
  async function loadModels() {
    try {
      const data = await getJSON('/api/models');
      if (!data?.ok) throw new Error(data?.error || 'Failed to load models');
      const models = data.models || [];
      const fill = (sel) => {
        const el = $(sel);
        if (!el) return;
        const current = el.value;
        el.innerHTML = '';
        models.forEach(m => {
          const opt = document.createElement('option');
          opt.value = m.repo_id;
          opt.textContent = m.label;
          el.appendChild(opt);
        });
        // try keep previous or default from config
        if (current && models.some(m => m.repo_id === current)) {
          el.value = current;
        } else if (STATE?.config?.repo_id && models.some(m => m.repo_id === STATE.config.repo_id)) {
          el.value = STATE.config.repo_id;
        }
      };
      fill('#form-simple select[name=repo_id]');
      fill('#form-advanced select[name=repo_id]');
      return models.length;
    } catch (e) {
      return 0;
    }
  }
async function init() {
    bindUI();
    await loadConfig();
    await loadModels();
    await loadProjects();
    await loadFiles();
    await loadFavorites(); // show favorites on initial load
  }

  window.setTimeout(init, 0);
})();
