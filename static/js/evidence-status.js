'use strict';
// v0.9.3k：改为 document 级 submit 事件委托（submit 事件冒泡）。
// 页面加载后动态插入的证据表单（材料导入无刷新新增的经历块）同样生效。
document.addEventListener('submit', async event => {
  const form = event.target instanceof Element ? event.target.closest('[data-evidence-form]') : null;
  if (!form) return;
  event.preventDefault();
  const select = form.querySelector('select');
  const button = form.querySelector('button');
  const message = form.querySelector('[data-update-status]');
  if (button.disabled) return;
  const status = select.value;
  select.disabled = button.disabled = true;
  message.textContent = '正在更新…';
  try {
    const response = await fetch(form.action, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({status})
    });
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || '更新失败，请重试。');
    form.dataset.savedStatus = result.status;
    select.value = result.status;
    message.textContent = '已更新';
    window.toast?.('证据状态已更新', 'success');
  } catch (error) {
    select.value = form.dataset.savedStatus;
    message.textContent = error instanceof TypeError ? '更新失败，请检查连接后重试。' : error.message;
    window.toast?.(message.textContent, 'error');
  } finally {
    select.disabled = button.disabled = false;
  }
});
