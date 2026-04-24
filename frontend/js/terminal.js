/**
 * terminal.js — Execution log terminal panel
 */

const terminal = (() => {
  function getOutput() {
    return document.getElementById('terminal-output');
  }

  function formatTime() {
    const now = new Date();
    return now.toTimeString().slice(0, 8);
  }

  function log(level, message) {
    const output = getOutput();
    if (!output) return;

    const lines = String(message).split('\n');
    lines.forEach(line => {
      if (!line && lines.length > 1) return; // skip empty lines in multi-line output

      const el = document.createElement('div');
      el.className = `log-line ${level}`;

      const time = document.createElement('span');
      time.className = 'log-time';
      time.textContent = formatTime();

      const msg = document.createElement('span');
      msg.className = 'log-msg';
      msg.textContent = line;

      el.appendChild(time);
      el.appendChild(msg);
      output.appendChild(el);
    });

    // Auto-scroll
    output.scrollTop = output.scrollHeight;

    // Prune old lines (keep last 500)
    const maxLines = 500;
    const children = output.children;
    while (children.length > maxLines) {
      output.removeChild(children[0]);
    }
  }

  function clear() {
    const output = getOutput();
    if (output) output.innerHTML = '';
  }

  return { log, clear };
})();
