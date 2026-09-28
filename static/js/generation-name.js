'use strict';
window.initializeGenerationNames = (scope=document) => scope.querySelectorAll('[data-generation-name]').forEach(root => {
  if(root.dataset.initialized)return;root.dataset.initialized='true';
  const trigger = root.querySelector('.name-trigger');
  const actions = root.querySelector('[data-name-actions]');
  const editor = root.querySelector('[data-name-editor]');
  const input = editor.querySelector('input');
  const save = root.querySelector('[data-name-save]');
  const cancel = root.querySelector('[data-name-cancel]');
  const status = root.querySelector('[data-name-status]');
  function close() {
    actions.hidden = editor.hidden = true;
    trigger.setAttribute('aria-expanded', 'false');
    trigger.focus({preventScroll: true});
  }
  trigger.addEventListener('click', () => {
    if (save.disabled) return;
    actions.hidden = !actions.hidden;
    editor.hidden = true;
    trigger.setAttribute('aria-expanded', String(!actions.hidden));
  });
  root.querySelector('[data-rename]').addEventListener('click', () => {
    actions.hidden = true;
    editor.hidden = false;
    input.value = trigger.textContent;
    status.textContent = '';
    input.focus({preventScroll: true});
    input.select();
  });
  cancel.addEventListener('click', () => { status.textContent = ''; close(); });
  input.addEventListener('keydown', event => {
    if (event.isComposing) return;
    if (event.key === 'Enter') { event.preventDefault(); save.click(); }
    if (event.key === 'Escape' && !save.disabled) { event.preventDefault(); cancel.click(); }
  });
  save.addEventListener('click', async () => {
    if (save.disabled) return;
    input.disabled = save.disabled = cancel.disabled = true;
    status.textContent = '正在保存…';
    try {
      const response = await fetch(root.dataset.url, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({display_name: input.value})
      });
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error(result.error || '改名失败，请重试。');
      trigger.textContent = result.display_name;
      const row=root.closest('[data-filter-text]');
      if(row){row.dataset.filterText=(result.display_name+' '+row.querySelector('.history-meta').textContent).toLowerCase();document.getElementById('history-filter')?.dispatchEvent(new Event('input'));}
      root.querySelector('[data-name-id]').hidden = result.display_name === root.dataset.generationId;
      status.textContent = '名称已保存';
      window.toast?.('快照名称已保存', 'success');
      close();
    } catch (error) {
      status.textContent = error instanceof TypeError ? '改名失败，原名称已保留，请检查连接。' : error.message;
      window.toast?.(status.textContent, 'error');
    } finally {
      input.disabled = save.disabled = cancel.disabled = false;
    }
  });
});

window.initializeGenerationNames();
