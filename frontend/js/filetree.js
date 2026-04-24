/**
 * filetree.js — Workspace file tree
 */

const filetree = (() => {
  let knownFiles = new Set();

  function getTree() {
    return document.getElementById('file-tree');
  }

  async function refresh() {
    const sessionId = app.getSessionId();
    if (!sessionId) return;

    try {
      const res = await fetch(`/api/sessions/${sessionId}/files`);
      if (!res.ok) return;
      const data = await res.json();
      render(data.files || []);
    } catch (err) {
      console.warn('Failed to refresh file tree:', err);
    }
  }

  function render(files) {
    const tree = getTree();
    if (!tree) return;

    if (!files || files.length === 0) {
      tree.innerHTML = '<div class="empty-state">No files yet</div>';
      knownFiles.clear();
      return;
    }

    tree.innerHTML = '';

    const newFiles = files.filter(f => !knownFiles.has(f));
    newFiles.forEach(f => knownFiles.add(f));

    files.forEach(filePath => {
      const item = document.createElement('div');
      item.className = 'file-tree-item';
      if (newFiles.includes(filePath)) {
        item.classList.add('new-file');
      }

      const icon = document.createElement('span');
      icon.className = 'file-icon';
      icon.textContent = getFileIcon(filePath);

      const name = document.createElement('span');
      name.className = 'file-name';
      name.textContent = filePath;
      name.title = filePath;

      item.appendChild(icon);
      item.appendChild(name);

      item.addEventListener('click', () => openFile(filePath));
      tree.appendChild(item);
    });
  }

  function getFileIcon(path) {
    const ext = path.split('.').pop().toLowerCase();
    const icons = {
      py: '🐍', js: '📜', ts: '📘', html: '🌐', css: '🎨',
      json: '📋', md: '📝', txt: '📄', sh: '⚙', yaml: '📐',
      yml: '📐', toml: '🔧', env: '🔑', rs: '🦀', go: '🐹',
    };
    return icons[ext] || '📄';
  }

  async function openFile(filePath) {
    const sessionId = app.getSessionId();
    if (!sessionId) return;

    try {
      const res = await fetch(`/api/sessions/${sessionId}/files/${encodeURIComponent(filePath)}`);
      if (!res.ok) {
        terminal.log('error', `Could not open ${filePath}: ${res.status}`);
        return;
      }
      const data = await res.json();
      showModal(filePath, data.content);
    } catch (err) {
      terminal.log('error', `Failed to open file: ${err.message}`);
    }
  }

  function showModal(filePath, content) {
    const modal = document.getElementById('file-modal');
    const pathEl = document.getElementById('modal-file-path');
    const contentEl = document.getElementById('modal-file-content');

    if (!modal || !pathEl || !contentEl) return;

    pathEl.textContent = filePath;
    contentEl.textContent = content;
    modal.style.display = 'flex';
  }

  return { refresh, render };
})();
