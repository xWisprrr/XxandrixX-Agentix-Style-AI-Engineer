/**
 * chat.js — Chat message rendering
 */

const chat = (() => {
  let loadingEl = null;

  function getContainer() {
    return document.getElementById('chat-messages');
  }

  function scrollToBottom() {
    const container = getContainer();
    if (container) {
      container.scrollTop = container.scrollHeight;
    }
  }

  function addMessage(role, content) {
    const container = getContainer();
    if (!container) return;

    // Remove welcome message if present
    const welcome = container.querySelector('.welcome-message');
    if (welcome) welcome.remove();

    const el = document.createElement('div');
    el.className = `chat-message ${role}`;

    const roleLabel = role === 'user' ? '🧑 You'
      : role === 'assistant' ? '🤖 Agentix'
      : '⚙ System';

    const now = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    el.innerHTML = `
      <div class="msg-header">
        <span class="msg-role">${roleLabel}</span>
        <span class="msg-time">${now}</span>
      </div>
      <div class="msg-body">${renderContent(content)}</div>
    `;

    container.appendChild(el);
    scrollToBottom();
  }

  function showSystemMessage(text) {
    addMessage('system', text);
  }

  function showPlan(steps) {
    const container = getContainer();
    if (!container) return;

    const el = document.createElement('div');
    el.className = 'chat-message system';

    const stepsHtml = steps.map((s, i) => `
      <div class="plan-step">
        <span class="step-num">${i + 1}.</span>
        <span class="step-name">${escapeHtml(s.name)}</span>
      </div>
    `).join('');

    el.innerHTML = `
      <div class="msg-header">
        <span class="msg-role">📋 Plan</span>
      </div>
      <div class="msg-body">
        <div class="plan-container">
          <div class="plan-title">Execution Plan — ${steps.length} steps</div>
          ${stepsHtml}
        </div>
      </div>
    `;

    container.appendChild(el);
    scrollToBottom();
  }

  function showLoading() {
    if (loadingEl) return;
    const container = getContainer();
    if (!container) return;

    loadingEl = document.createElement('div');
    loadingEl.className = 'loading-indicator';
    loadingEl.innerHTML = `
      <span>Agentix is working</span>
      <div class="loading-dots">
        <span></span><span></span><span></span>
      </div>
    `;
    container.appendChild(loadingEl);
    scrollToBottom();
  }

  function hideLoading() {
    if (loadingEl) {
      loadingEl.remove();
      loadingEl = null;
    }
  }

  function clear() {
    const container = getContainer();
    if (container) {
      container.innerHTML = '';
    }
  }

  // ── Content renderer ───────────────────────────────────
  function renderContent(text) {
    let html = escapeHtml(text);

    // Code blocks ```lang ... ```
    html = html.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
      return `<pre><code>${code}</code></pre>`;
    });

    // Inline code `...`
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

    // Bold **...**
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

    // Italic *...*
    html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');

    // Headers ## ... and # ...
    html = html.replace(/^## (.+)$/gm, '<h3 style="color:var(--accent-green);margin:6px 0 4px">$1</h3>');
    html = html.replace(/^# (.+)$/gm, '<h2 style="color:var(--text-bright);margin:8px 0 4px">$1</h2>');

    // List items - ...
    html = html.replace(/^  - (.+)$/gm, '<li style="margin-left:16px">$1</li>');
    html = html.replace(/^- (.+)$/gm, '<li>$1</li>');

    // Checkmarks
    html = html.replace(/✅/g, '<span style="color:var(--accent-green)">✅</span>');
    html = html.replace(/⚠️/g, '<span style="color:var(--dot-working)">⚠️</span>');

    // Newlines to <br> (but not inside pre tags)
    html = html.replace(/\n/g, '<br>');

    return html;
  }

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  return { addMessage, showPlan, showSystemMessage, showLoading, hideLoading, clear };
})();
