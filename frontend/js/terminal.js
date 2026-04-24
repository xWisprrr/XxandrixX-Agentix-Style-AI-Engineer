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
    // Trim only leading/trailing blank lines while preserving interior structure
    let start = 0;
    let end = lines.length - 1;
    while (start <= end && lines[start].trim() === '') start++;
    while (end >= start && lines[end].trim() === '') end--;
    const trimmed = lines.slice(start, end + 1);
    trimmed.forEach(line => {

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
