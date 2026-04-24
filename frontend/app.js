/**
 * Agentix — Frontend WebSocket Client
 * Handles real-time communication with the backend and renders the UI.
 */

// ── Session setup ──────────────────────────────────────────────────────────

const SESSION_KEY = 'agentix_session_id';
let sessionId = sessionStorage.getItem(SESSION_KEY);
if (!sessionId) {
  sessionId = crypto.randomUUID();
  sessionStorage.setItem(SESSION_KEY, sessionId);
}

// ── DOM references ─────────────────────────────────────────────────────────

const chatContainer   = document.getElementById('chatContainer');
const chatInput       = document.getElementById('chatInput');
const sendBtn         = document.getElementById('sendBtn');
const statusDot       = document.getElementById('statusDot');
const statusLabel     = document.getElementById('statusLabel');
const projectIdEl     = document.getElementById('projectId');
const fileTree        = document.getElementById('fileTree');
const terminal        = document.getElementById('terminal');
const planPane        = document.getElementById('planPane');
const agentStatusBar  = document.getElementById('agentStatusBar');
const agentStatusText = document.getElementById('agentStatusText');
const inputHints      = document.getElementById('inputHints');
const fileViewerOverlay = document.getElementById('fileViewerOverlay');
const fileViewerPath    = document.getElementById('fileViewerPath');
const fileViewerContent = document.getElementById('fileViewerContent');
const fileViewerClose   = document.getElementById('fileViewerClose');

// ── State ──────────────────────────────────────────────────────────────────

const state = {
  files: {},       // path -> content
  plan:  [],       // PlanStep[]
  projectId: null,
  wsStatus: 'disconnected',
  activeAgent: null,
};

// ── WebSocket ──────────────────────────────────────────────────────────────

let ws = null;
let reconnectTimer = null;
let reconnectDelay = 1000;

function connect() {
  const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
  const wsUrl = `${protocol}://${location.host}/ws/${sessionId}`;
  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    console.log('[WS] connected');
    reconnectDelay = 1000;
    setStatus('connected', 'Ready');
    addTerminalLine('WebSocket connected. Ready to build.', 'success');
  };

  ws.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      handleServerMessage(msg);
    } catch (e) {
      console.error('[WS] parse error', e, ev.data);
    }
  };

  ws.onclose = () => {
    console.log('[WS] closed');
    setStatus('disconnected', 'Reconnecting…');
    scheduleReconnect();
  };

  ws.onerror = (e) => {
    console.error('[WS] error', e);
  };
}

function scheduleReconnect() {
  clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(() => {
    reconnectDelay = Math.min(reconnectDelay * 1.5, 10000);
    connect();
  }, reconnectDelay);
}

function sendMessage(text) {
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    addSystemMessage('⚠️ Not connected. Please wait…');
    return;
  }
  ws.send(JSON.stringify({ message: text }));
}

// ── Message handler ────────────────────────────────────────────────────────

function handleServerMessage(msg) {
  const { event, data, agent } = msg;

  switch (event) {
    case 'user_message':
      // Already shown optimistically
      break;

    case 'agent_message':
      addChatMessage('agent', data.content, data.agent || agent);
      break;

    case 'agent_status':
      showAgentStatus(data.status || data.message || '');
      if (data.agent) state.activeAgent = data.agent;
      break;

    case 'plan_created':
      state.plan = data.steps || [];
      renderPlan();
      switchTab('plan');
      break;

    case 'plan_step_start':
      updateStepStatus(data.step.index, 'active');
      switchTab('plan');
      break;

    case 'plan_step_done':
      updateStepStatus(data.step.index, 'done');
      if (data.files && data.files.length > 0) {
        addTerminalLine(`  ✓ Created: ${data.files.join(', ')}`, 'success');
      }
      break;

    case 'file_created':
    case 'file_updated': {
      const isNew = event === 'file_created';
      const filePath = String(data.path || '');
      // Guard against prototype pollution via crafted path keys
      if (filePath && filePath !== '__proto__' && filePath !== 'constructor' && filePath !== 'prototype') {
        state.files[filePath] = data.content;
        renderFileTree();
        const verb = isNew ? 'Created' : 'Updated';
        addTerminalLine(`  ${isNew ? '+' : '~'} ${verb}: ${filePath} (${data.size} bytes)`, isNew ? 'success' : 'info');
      }
      break;
    }

    case 'file_tree':
      // File tree is managed by individual file events; this is just a sync
      break;

    case 'execution_start':
      addTerminalLine('', 'info');
      addTerminalLine(`▶ Running project (attempt ${data.attempt})…`, 'prompt');
      addTerminalLine('─'.repeat(50), 'info');
      setStatus('executing', 'Executing');
      switchTab('terminal');
      break;

    case 'execution_output': {
      const phase = data.phase || 'run';
      if (data.stdout) {
        data.stdout.split('\n').forEach(line => {
          if (line.trim()) addTerminalLine(line, 'stdout');
        });
      }
      if (data.stderr) {
        data.stderr.split('\n').forEach(line => {
          if (line.trim()) addTerminalLine(line, 'stderr');
        });
      }
      if ('exit_code' in data) {
        const ok = data.exit_code === 0 || data.timed_out;
        const exitMsg = data.timed_out
          ? '⏱ Process timed out (normal for servers)'
          : `Exit code: ${data.exit_code}`;
        addTerminalLine(exitMsg, ok ? 'success' : 'stderr');
        if (data.duration) addTerminalLine(`Duration: ${data.duration.toFixed(2)}s`, 'info');
      }
      break;
    }

    case 'execution_done':
      addTerminalLine('─'.repeat(50), 'info');
      break;

    case 'error':
      addChatMessage('agent', `❌ Error: ${data.message}`, 'orchestrator');
      addTerminalLine(`ERROR: ${data.message}`, 'stderr');
      setStatus('error', 'Error');
      hideAgentStatus();
      break;

    case 'done':
      state.projectId = data.project_id;
      if (data.project_id) projectIdEl.textContent = `#${data.project_id}`;
      const finalState = data.state || 'complete';
      setStatus(finalState, finalState.charAt(0).toUpperCase() + finalState.slice(1));
      hideAgentStatus();
      addTerminalLine('', 'info');
      addTerminalLine('══ Build complete ══', 'success');
      break;

    case 'heartbeat':
      break;

    default:
      console.debug('[WS] unknown event:', event, data);
  }
}

// ── UI: Chat ───────────────────────────────────────────────────────────────

function addChatMessage(role, content, agentRole) {
  const div = document.createElement('div');
  div.className = `chat-message ${role}`;

  const meta = document.createElement('div');
  meta.className = 'message-meta';

  if (role === 'agent' && agentRole) {
    const badge = document.createElement('span');
    badge.className = `agent-badge badge-${agentRole}`;
    badge.textContent = agentRole.charAt(0).toUpperCase() + agentRole.slice(1);
    meta.appendChild(badge);
  } else if (role === 'user') {
    meta.textContent = 'You';
  }

  const bubble = document.createElement('div');
  bubble.className = 'message-bubble';
  bubble.textContent = content;

  div.appendChild(meta);
  div.appendChild(bubble);
  chatContainer.appendChild(div);
  chatContainer.scrollTop = chatContainer.scrollHeight;
}

function addSystemMessage(content) {
  addChatMessage('system', content, null);
}

// ── UI: Agent Status Bar ───────────────────────────────────────────────────

function showAgentStatus(text) {
  agentStatusBar.classList.remove('hidden');
  agentStatusText.textContent = text;
}

function hideAgentStatus() {
  agentStatusBar.classList.add('hidden');
}

// ── UI: Terminal ───────────────────────────────────────────────────────────

function addTerminalLine(text, type = 'info') {
  // Remove the blinking cursor temporarily
  const cursor = terminal.querySelector('.terminal-cursor');
  if (cursor) terminal.removeChild(cursor);

  const span = document.createElement('span');
  span.className = `terminal-line ${type}`;
  span.textContent = text;
  terminal.appendChild(span);
  terminal.appendChild(document.createTextNode('\n'));

  // Re-add cursor
  const newCursor = document.createElement('span');
  newCursor.className = 'terminal-cursor';
  terminal.appendChild(newCursor);

  terminal.scrollTop = terminal.scrollHeight;
}

// ── UI: Plan ───────────────────────────────────────────────────────────────

function renderPlan() {
  planPane.innerHTML = '';
  if (!state.plan.length) {
    planPane.innerHTML = '<div class="plan-empty">No plan yet.</div>';
    return;
  }
  state.plan.forEach(step => {
    const el = buildStepEl(step);
    planPane.appendChild(el);
  });
}

function buildStepEl(step) {
  const div = document.createElement('div');
  div.className = `plan-step ${step.status || 'pending'}`;
  div.id = `step-${step.index}`;

  const icon = document.createElement('div');
  icon.className = 'step-icon';
  icon.textContent = step.status === 'done' ? '✓' : step.status === 'failed' ? '✕' : step.index + 1;

  const body = document.createElement('div');
  body.className = 'step-body';

  const title = document.createElement('div');
  title.className = 'step-title';
  title.textContent = step.title;

  const desc = document.createElement('div');
  desc.className = 'step-desc';
  desc.textContent = step.description;

  body.appendChild(title);
  body.appendChild(desc);
  div.appendChild(icon);
  div.appendChild(body);
  return div;
}

function updateStepStatus(index, status) {
  const existing = document.getElementById(`step-${index}`);
  if (!existing || !state.plan[index]) return;
  state.plan[index].status = status;
  const updated = buildStepEl(state.plan[index]);
  existing.replaceWith(updated);
}

// ── UI: File Tree ──────────────────────────────────────────────────────────

const FILE_ICONS = {
  py: '🐍', js: '🟨', ts: '🔷', html: '🌐', css: '🎨',
  json: '📋', md: '📝', sh: '⚙️', txt: '📄', yml: '⚙️',
  yaml: '⚙️', sql: '🗄️', go: '🔵', rs: '🦀', default: '📄',
};

function getFileIcon(path) {
  const ext = path.split('.').pop().toLowerCase();
  return FILE_ICONS[ext] || FILE_ICONS.default;
}

function renderFileTree() {
  const paths = Object.keys(state.files);
  if (!paths.length) {
    fileTree.innerHTML = '<div class="file-tree-empty">Files will appear here as they\'re generated.</div>';
    return;
  }
  fileTree.innerHTML = '';
  paths.sort().forEach(path => {
    const item = document.createElement('div');
    item.className = 'file-item new';
    item.innerHTML = `<span class="file-icon">${getFileIcon(path)}</span><span title="${path}">${path}</span>`;
    item.addEventListener('click', () => openFileViewer(path));
    fileTree.appendChild(item);
    // Remove the new animation class after it plays
    setTimeout(() => item.classList.remove('new'), 500);
  });
}

// ── UI: File Viewer ────────────────────────────────────────────────────────

function openFileViewer(path) {
  const content = state.files[path] || '';
  fileViewerPath.textContent = path;
  fileViewerContent.textContent = content;
  fileViewerOverlay.classList.add('open');
}

fileViewerClose.addEventListener('click', () => {
  fileViewerOverlay.classList.remove('open');
});

fileViewerOverlay.addEventListener('click', (e) => {
  if (e.target === fileViewerOverlay) fileViewerOverlay.classList.remove('open');
});

// ── UI: Status ─────────────────────────────────────────────────────────────

function setStatus(state, label) {
  statusDot.className = `status-dot ${state}`;
  statusLabel.textContent = label;
}

// ── UI: Tabs ───────────────────────────────────────────────────────────────

document.querySelectorAll('.panel-tab').forEach(tab => {
  tab.addEventListener('click', () => switchTab(tab.dataset.tab));
});

function switchTab(name) {
  document.querySelectorAll('.panel-tab').forEach(t => t.classList.toggle('active', t.dataset.tab === name));
  document.querySelectorAll('.panel-pane').forEach(p => p.classList.toggle('active', p.id === `pane-${name}`));
}

// ── UI: Input ──────────────────────────────────────────────────────────────

chatInput.addEventListener('input', () => {
  chatInput.style.height = 'auto';
  chatInput.style.height = Math.min(chatInput.scrollHeight, 140) + 'px';
});

chatInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    doSend();
  }
});

sendBtn.addEventListener('click', doSend);

function doSend() {
  const text = chatInput.value.trim();
  if (!text) return;
  chatInput.value = '';
  chatInput.style.height = 'auto';
  inputHints.style.display = 'none';
  addChatMessage('user', text, null);
  sendMessage(text);
  showAgentStatus('Processing request…');
  setStatus('planning', 'Planning');
}

// ── Hint chips ─────────────────────────────────────────────────────────────

document.querySelectorAll('.hint-chip').forEach(chip => {
  chip.addEventListener('click', () => {
    chatInput.value = chip.textContent;
    chatInput.focus();
  });
});

// ── Boot ───────────────────────────────────────────────────────────────────

connect();
