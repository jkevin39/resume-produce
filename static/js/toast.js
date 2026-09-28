// 轻量 toast 通知：与既有行内状态元素并行双写，不替代它们（行内元素是现有回归断言对象）。
'use strict';
(() => {
  function container() {
    let node = document.getElementById('toast-container');
    if (!node) {
      node = document.createElement('div');
      node.id = 'toast-container';
      node.setAttribute('aria-live', 'polite');
      document.body.append(node);
    }
    return node;
  }
  // type: 'success' | 'error' | 默认中性；失败 toast 停留更久。
  window.toast = (message, type = '') => {
    const node = document.createElement('div');
    node.className = 'toast' + (type ? ' ' + type : '');
    node.textContent = message;
    container().append(node);
    const stay = type === 'error' ? 6000 : 3200;
    setTimeout(() => {
      node.classList.add('leaving');
      setTimeout(() => node.remove(), 300);
    }, stay);
  };
})();
