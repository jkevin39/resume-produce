'use strict';
// v0.9.3k：履历材料导入无刷新。
// 拦截材料表单 submit，用 FormData fetch 提交；成功后局部插入新经历块、
// 更新履历库摘要、清除空态；失败时保留输入并就近提示。
// 该表单不走 model-forms.js（已从 data-model-form 移出），本文件自带
// pending 防重复守卫与同款遮罩加载动画。
(() => {
  const form = document.getElementById('material-import-form');
  if (!form) return;
  const submitButton = form.querySelector('button[type="submit"]');
  let pending = false;

  const status = document.createElement('p');
  status.setAttribute('role', 'status');
  status.hidden = true;
  form.append(status);

  const showStatus = (message, isError) => {
    status.textContent = message;
    status.className = isError ? 'error-box' : 'muted';
    status.hidden = !message;
  };
  const showOverlay = () => {
    const overlay = document.createElement('div');
    overlay.className = 'model-loading';
    overlay.setAttribute('role', 'status');
    overlay.dataset.importOverlay = 'true';
    const spinner = document.createElement('span');
    spinner.className = 'spinner';
    const text = document.createElement('p');
    text.textContent = form.dataset.loadingText || '处理中，请稍候。';
    overlay.append(spinner, text);
    form.append(overlay);
  };
  const hideOverlay = () => form.querySelector('[data-import-overlay]')?.remove();

  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (pending) return;
    const ocr = form.querySelector('[data-ocr-target]')?.ocrController;
    if (ocr?.isBusy()) { showStatus('图片仍在识别，请完成后再提交材料。', true); return; }
    const body = new FormData(form);
    ocr?.setImporting(true);
    pending = true;
    submitButton.disabled = true;
    showStatus('', false);
    showOverlay();
    try {
      const response = await fetch(form.action, {
        method: 'POST',
        headers: {'X-Requested-With': 'fetch'},
        body,
      });
      let result;
      try {
        result = await response.json();
      } catch (parseError) {
        // 非 JSON 响应（如 413 拦截之外的框架错误页）兜底为可读文案
        throw new Error('请求失败（可能是文件过大或服务器异常），请检查后重试。');
      }
      if (!response.ok || !result.ok) {
        throw new Error((result.errors || ['拆解失败，请重试。']).join('；'));
      }
      const block = window.ResumeLibrary.update(result);
      form.reset();
      if (block) {
        block.open = true;
        block.scrollIntoView({behavior: 'smooth', block: 'nearest'});
      }
      window.toast?.('材料已拆解并写入履历库', 'success');
    } catch (error) {
      const message = error instanceof TypeError ? '连接失败，输入已保留。请检查服务后重试。' : error.message;
      showStatus(message, true);
      window.toast?.(message, 'error');
    } finally {
      pending = false;
      ocr?.setImporting(false);
      submitButton.disabled = false;
      hideOverlay();
    }
  });
})();
