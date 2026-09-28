// Native form navigation preserves normal browser history and validation.
// v0.9.1k：提交期间用遮罩层 + 加载动画拦截操作，只禁用提交按钮；
// 不得对输入控件设 disabled（submit 阶段禁用会使字段被排除在 POST body 之外）。
(() => {
  const reset = form => {
    delete form.dataset.pending;
    form.removeAttribute('aria-busy');
    form.querySelectorAll('[data-pending-disabled]').forEach(button => {
      button.disabled = false;
      delete button.dataset.pendingDisabled;
    });
    form.querySelector('[data-model-status]')?.remove();
  };
  document.querySelectorAll('form[data-model-form]').forEach(form => {
    form.addEventListener('submit', event => {
      if (form.dataset.pending) { event.preventDefault(); return; }
      form.dataset.pending = 'true';
      form.setAttribute('aria-busy', 'true');
      form.querySelectorAll('button[type="submit"], input[type="submit"]').forEach(button => {
        if (!button.disabled) { button.dataset.pendingDisabled = 'true'; button.disabled = true; }
      });
      const overlay = document.createElement('div');
      overlay.dataset.modelStatus = 'true';
      overlay.className = 'model-loading';
      overlay.setAttribute('role', 'status');
      const spinner = document.createElement('span');
      spinner.className = 'spinner';
      const text = document.createElement('p');
      text.textContent = form.dataset.loadingText || '处理中，请稍候。模型调用可能需要较长时间，请勿重复提交。';
      overlay.append(spinner, text);
      form.append(overlay);
    });
  });
  // A failed request can be retried after Back, including bfcache restores.
  window.addEventListener('pageshow', () => document.querySelectorAll('form[data-model-form]').forEach(reset));
})();
