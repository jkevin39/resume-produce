'use strict';
(() => {
  const input = document.getElementById('history-filter');
  const filter = () => {
    const keyword = input?.value.trim().toLowerCase() || '';
    let visible = 0;
    document.querySelectorAll('#history-list .history-item').forEach(row => {
      row.hidden = !row.dataset.filterText.includes(keyword);
      if (!row.hidden) visible++;
    });
    const empty = document.getElementById('history-empty');
    if (empty) empty.hidden = visible > 0;
  };
  input?.addEventListener('input', filter);
  let pending = false;
  document.addEventListener('submit', async event => {
    const form = event.target.closest('[data-snapshot-trash]');
    if (!form) return;
    event.preventDefault();
    if (pending || (form.dataset.confirm && !confirm(form.dataset.confirm))) return;
    pending = true;
    const buttons = [...document.querySelectorAll('[data-snapshot-trash] button')];
    buttons.forEach(button => button.disabled = true);
    const status = document.getElementById('snapshot-action-status');
    status.textContent = '正在处理…';
    try {
      const response = await fetch(form.action, {method:'POST',headers:{'X-Requested-With':'fetch'}});
      const result = await response.json();
      const body = document.getElementById('history-body');
      if (body && result.html) {
        const open = document.getElementById('snapshot-trash')?.open;
        body.innerHTML = result.html;
        document.getElementById('snapshot-trash').open = open || form.action.endsWith('/move') || !result.ok;
        window.initializeGenerationNames?.(body);
        filter();
      }
      if (!response.ok || !result.ok) throw new Error(result.error || '操作失败，请重试');
      if (!body) {window.location.assign(result.url);return;}
      status.textContent = result.message;
      window.toast?.(result.message, 'success');
    } catch (error) {
      status.textContent = error.message || '操作失败，请重试';
      window.toast?.(status.textContent, 'error');
    } finally {pending = false;buttons.forEach(button => button.disabled = false);}
  });
  filter();
})();
