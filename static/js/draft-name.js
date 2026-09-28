'use strict';
(() => {
  const root = document.getElementById('draft-name');
  const button = root.querySelector('[data-name-display]');
  const input = root.querySelector('[data-name-input]');
  const status = root.querySelector('[data-name-status]');
  let composing = false, pending = false;
  const close = () => {input.hidden = true; button.hidden = false; button.focus();};
  button.addEventListener('click', () => {
    input.value = button.textContent;
    status.textContent = 'Enter 保存，Esc 取消';
    button.hidden = true; input.hidden = false; input.focus(); input.select();
  });
  input.addEventListener('compositionstart', () => {composing = true;});
  input.addEventListener('compositionend', () => {composing = false;});
  input.addEventListener('keydown', async event => {
    event.stopPropagation();
    if (composing || event.isComposing || event.keyCode === 229 || pending) return;
    if (event.key === 'Escape') {event.preventDefault(); status.textContent = ''; close(); return;}
    if (event.key !== 'Enter') return;
    event.preventDefault(); pending = true; root.dataset.pending = 'true'; input.disabled = true;
    status.textContent = '正在保存名称…';
    try {
      const response = await fetch(root.dataset.url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({display_name:input.value})});
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error((result.errors || ['改名失败']).join('；'));
      button.textContent = button.title = result.display_name;
      document.title = `中文草稿 / ${result.display_name} · 简历生成 Agent`;
      status.textContent = '名称已保存'; close(); window.toast?.('名称已保存', 'success');
    } catch (error) {
      status.textContent = error.message || '改名失败，请重试'; window.toast?.(status.textContent, 'error');
    } finally {
      pending = false; delete root.dataset.pending; input.disabled = false;
      if (!input.hidden) input.focus();
    }
  });
})();
