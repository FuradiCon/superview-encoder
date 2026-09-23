// Superview Encoder UI. Python owns all state; this file only renders
// snapshots (window.render) and forwards clicks to window.pywebview.api.
(function () {
  const $ = (id) => document.getElementById(id);
  const api = () => window.pywebview && window.pywebview.api;
  const openErrors = new Set();
  let last = null;

  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  function fmtSize(b) {
    if (b >= 1e9) return (b / 1e9).toFixed(1) + ' GB';
    if (b >= 1e6) return Math.round(b / 1e6) + ' MB';
    return Math.max(1, Math.round(b / 1e3)) + ' KB';
  }
  function fmtEta(s) {
    if (s == null) return 'estimating…';
    s = Math.round(s);
    return '~' + (s >= 60 ? Math.floor(s / 60) + 'm ' + String(s % 60).padStart(2, '0') + 's' : s + 's') + ' left';
  }

  function chipText(it) {
    if (it.status === 'converting') return Math.floor(it.pct) + '%';
    return it.status;
  }

  window.render = function (s) {
    last = s;
    // encoder chip
    const enc = $('enc');
    if (s.encoder) {
      enc.classList.toggle('cpu', !s.encoder.gpu);
      enc.querySelector('b').textContent = s.encoder.gpu ? 'GPU' : 'CPU';
      $('enc-label').textContent = s.encoder.gpu ? '· ' + s.encoder.label : '· SLOW · no GPU encoder found';
    } else {
      enc.classList.add('cpu');
      enc.querySelector('b').textContent = 'ERROR';
      $('enc-label').textContent = '· no encoder';
    }

    // now converting
    const cur = s.items.find((i) => i.status === 'converting');
    $('now').hidden = !cur;
    if (cur) {
      $('now-label').textContent = 'Converting · ' + s.current.index + ' of ' + s.current.total;
      $('now-name').textContent = cur.name;
      $('now-meta').textContent = cur.meta;
      $('now-pct').textContent = Math.floor(cur.pct) + '%';
      $('now-bar').style.width = cur.pct + '%';
      $('now-eta').textContent = fmtEta(cur.eta) + (cur.speed ? ' · ' + cur.speed.toFixed(1) + '× realtime' : '');
    }

    // queue
    $('q-label').textContent = 'Queue · ' + s.items.length;
    $('list').innerHTML = s.items.length ? s.items.map((it) => {
      const failed = it.status === 'failed';
      const err = failed && openErrors.has(it.id) ? '<div class="err">' + esc(it.error || '') + '</div>' : '';
      const x = it.status === 'waiting' ? '<button class="x" data-remove="' + it.id + '" title="Remove">✕</button>' : '<span></span>';
      return '<div class="row' + (failed ? ' failed' : '') + '" data-id="' + it.id + '">' +
        '<span class="chip c-' + it.status + '">' + esc(chipText(it)) + '</span>' +
        '<span class="name" title="' + esc(it.path) + '">' + esc(it.name) + '<small>' + fmtSize(it.size) + '</small></span>' +
        '<span class="meta">' + esc(it.detail) + '</span>' + x + err + '</div>';
    }).join('') : '<div class="q-empty">Nothing queued yet.</div>';

    // footer
    $('path').textContent = s.error || s.output_dir;
    $('path').classList.toggle('bad', !!s.error);
    $('path').title = s.output_dir;
  };

  // clicks
  $('browse').onclick = () => api() && api().browse_files();
  $('cancel').onclick = () => api() && api().cancel_current();
  $('clear').onclick = () => api() && api().clear_finished();
  $('change').onclick = () => api() && api().choose_output_dir();
  $('open').onclick = () => api() && api().open_output_dir();
  $('list').addEventListener('click', (e) => {
    const rm = e.target.closest('[data-remove]');
    if (rm) { api() && api().remove(Number(rm.dataset.remove)); return; }
    const row = e.target.closest('.row.failed');
    if (row && !e.target.closest('.err')) {
      const id = Number(row.dataset.id);
      openErrors.has(id) ? openErrors.delete(id) : openErrors.add(id);
      if (last) window.render(last);
    }
  });

  // drag-over look (the actual drop is handled in Python, which gets full paths)
  let depth = 0;
  document.addEventListener('dragenter', (e) => { e.preventDefault(); depth++; document.body.classList.add('dragging'); });
  document.addEventListener('dragleave', () => { if (--depth <= 0) { depth = 0; document.body.classList.remove('dragging'); } });
  document.addEventListener('dragover', (e) => e.preventDefault());
  document.addEventListener('drop', (e) => { e.preventDefault(); depth = 0; document.body.classList.remove('dragging'); });

  window.addEventListener('pywebviewready', async () => window.render(await api().get_state()));
})();
