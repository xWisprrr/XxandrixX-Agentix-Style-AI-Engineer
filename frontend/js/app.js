/**
 * app.js — Main application controller
 * Manages WebSocket, session, and coordinates modules.
 */

const app = (() => {
  let sessionId = null;
  let socket = null;
  let reconnectDelay = 1000;
  let reconnectTimer = null;
  let isWorking = false;

  // ── Session ID ─────────────────────────────────────────
  function generateSessionId() {
    if (typeof crypto !== 'undefined' && crypto.randomUUID) {
      return 'sess_' + crypto.randomUUID().replace(/-/g, '');
    }
    // Fallback: use crypto.getRandomValues for cryptographic randomness
    const arr = new Uint8Array(16);
    crypto.getRandomValues(arr);
    return 'sess_' + Array.from(arr, b => b.toString(16).padStart(2, '0')).join('');
  }

  function getOrCreateSessionId() {
    let id = localStorage.getItem('agentix_session_id');
    if (!id) {
      id = generateSessionId();
      localStorage.setItem('agentix_session_id', id);
    }
    return id;
  }

  // ── WebSocket ──────────────────────────────────────────
  function connect() {
    sessionId = getOrCreateSessionId();
    const wsProto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProto}//${location.host}/ws/${sessionId}`;

    setConnectionStatus('connecting');

    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
      reconnectDelay = 1000;
      clearTimeout(reconnectTimer);
      setConnectionStatus('connected');
      terminal.log('system', 'Connected to Agentix server');

      // Reload history on reconnect
      loadHistory();
    };

    socket.onmessage = (event) => {
      let data;
      try {
        data = JSON.parse(event.data);
      } catch (e) {
        console.warn('Bad JSON from server:', event.data);
        return;
      }
      dispatch(data);
    };

    socket.onerror = (err) => {
      console.error('WebSocket error:', err);
    };

    socket.onclose = () => {
      setConnectionStatus('disconnected');
      terminal.log('warn', 'Connection lost. Reconnecting in ' + (reconnectDelay / 1000).toFixed(1) + 's…');
      scheduleReconnect();
    };
  }

  function scheduleReconnect() {
    clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(() => {
      connect();
    }, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 2, 30000);
  }

  // ── Event dispatcher ───────────────────────────────────
  function dispatch(event) {
    const { type, data, timestamp } = event;

    switch (type) {
      case 'agent_status':
        updateAgentStatus(data.agent, data.state);
        terminal.log('system', `[${data.agent}] → ${data.state}`);
        break;

      case 'plan':
        if (data.steps) {
          chat.showPlan(data.steps);
          terminal.log('info', `Plan: ${data.steps.length} steps`);
        }
        break;

      case 'step_start':
        terminal.log('info', `▶ Step: ${data.name}`);
        chat.showSystemMessage(`Running: **${data.name}**`);
        break;

      case 'step_complete':
        terminal.log('success', `✓ Step complete: ${data.name}`);
        if (data.output) {
          terminal.log('info', data.output.slice(0, 500));
        }
        break;

      case 'step_error':
        terminal.log('error', `✗ Step failed: ${data.name} — ${data.error}`);
        break;

      case 'file_created':
        terminal.log('success', `📄 File created: ${data.path}`);
        filetree.refresh();
        break;

      case 'file_modified':
        terminal.log('info', `✏ File modified: ${data.path}`);
        filetree.refresh();
        break;

      case 'log':
        terminal.log(data.level || 'info', data.message);
        break;

      case 'chat_response':
        chat.hideLoading();
        setWorking(false);
        if (data.message) {
          chat.addMessage('assistant', data.message);
        }
        break;

      case 'task_complete':
        setWorking(false);
        chat.hideLoading();
        terminal.log('success', '✔ Task complete');
        filetree.refresh();
        break;

      case 'task_error':
        setWorking(false);
        chat.hideLoading();
        terminal.log('error', `Task error: ${data.error}`);
        chat.addMessage('system', `⚠️ Error: ${data.error}`);
        break;

      default:
        terminal.log('debug', `[${type}] ${JSON.stringify(data).slice(0, 120)}`);
    }
  }

  // ── Agent status badges ────────────────────────────────
  function updateAgentStatus(agent, state) {
    const badge = document.getElementById(`agent-${agent}`);
    if (!badge) return;
    badge.classList.remove('active', 'error', 'idle');
    if (state === 'active') badge.classList.add('active');
    else if (state === 'error') badge.classList.add('error');
  }

  function resetAgentBadges() {
    ['planner', 'coder', 'tester', 'debugger'].forEach(a => updateAgentStatus(a, 'idle'));
  }

  // ── Connection status ──────────────────────────────────
  function setConnectionStatus(state) {
    const el = document.getElementById('connection-status');
    const label = document.getElementById('connection-label');
    if (!el) return;
    el.className = 'connection-status ' + state;
    label.textContent = state === 'connected' ? 'Connected'
      : state === 'connecting' ? 'Connecting…'
      : 'Disconnected';
  }

  // ── Send message ───────────────────────────────────────
  async function sendMessage() {
    const input = document.getElementById('chat-input');
    const message = input.value.trim();
    if (!message || isWorking) return;

    input.value = '';
    input.style.height = '';
    setWorking(true);
    resetAgentBadges();

    chat.addMessage('user', message);
    chat.showLoading();
    terminal.log('system', '⟶ Sending task…');

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, message }),
      });

      if (!res.ok) {
        throw new Error(`Server error: ${res.status}`);
      }
    } catch (err) {
      setWorking(false);
      chat.hideLoading();
      terminal.log('error', `Failed to send: ${err.message}`);
      chat.addMessage('system', `⚠️ Failed to send message: ${err.message}`);
    }
  }

  function setWorking(working) {
    isWorking = working;
    const btn = document.getElementById('btn-send');
    const input = document.getElementById('chat-input');
    if (btn) btn.disabled = working;
    if (input) input.disabled = working;
  }

  // ── Load history ───────────────────────────────────────
  async function loadHistory() {
    try {
      const res = await fetch(`/api/sessions/${sessionId}/history`);
      if (!res.ok) return;
      const data = await res.json();
      if (data.history && data.history.length > 0) {
        data.history.forEach(msg => chat.addMessage(msg.role, msg.content));
      }
    } catch (_) {
      // Not critical
    }
  }

  // ── Public API ─────────────────────────────────────────
  function fillPrompt(text) {
    const input = document.getElementById('chat-input');
    if (input) {
      input.value = text;
      input.focus();
    }
  }

  function getSessionId() {
    return sessionId;
  }

  // ── Init ───────────────────────────────────────────────
  function init() {
    connect();

    const btn = document.getElementById('btn-send');
    const input = document.getElementById('chat-input');
    const clearChat = document.getElementById('btn-clear-chat');
    const clearTerm = document.getElementById('btn-clear-terminal');
    const refreshFiles = document.getElementById('btn-refresh-files');
    const closeModal = document.getElementById('btn-close-modal');

    if (btn) btn.addEventListener('click', sendMessage);

    if (input) {
      input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
          e.preventDefault();
          sendMessage();
        }
      });

      input.addEventListener('input', () => {
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 160) + 'px';
      });
    }

    if (clearChat) clearChat.addEventListener('click', () => chat.clear());
    if (clearTerm) clearTerm.addEventListener('click', () => terminal.clear());
    if (refreshFiles) refreshFiles.addEventListener('click', () => filetree.refresh());

    if (closeModal) {
      closeModal.addEventListener('click', () => {
        document.getElementById('file-modal').style.display = 'none';
      });
    }

    document.getElementById('file-modal')?.addEventListener('click', (e) => {
      if (e.target.id === 'file-modal') {
        e.target.style.display = 'none';
      }
    });
  }

  document.addEventListener('DOMContentLoaded', init);

  return { fillPrompt, getSessionId, sendMessage };
})();
