'use strict';
// prepare 页：经历折叠块摘要上的“已选 N”标识。
// 初始计数由服务端渲染（与默认勾选规则一致），这里负责勾选变化时即时更新；
// 全部取消勾选时标识隐藏，并去掉摘要高亮。
(() => {
  const experiences = document.querySelectorAll('details.evidence-experience');
  if (!experiences.length) return;
  const update = details => {
    const badge = details.querySelector('[data-selection-badge]');
    if (!badge) return;
    const count = details.querySelectorAll('input[name="evidence_ids"]:checked:not(:disabled)').length;
    badge.textContent = `已选 ${count}`;
    badge.hidden = count === 0;
    details.classList.toggle('has-selection', count > 0);
  };
  experiences.forEach(details => {
    details.querySelectorAll('input[name="evidence_ids"]').forEach(input => {
      input.addEventListener('change', () => update(details));
    });
    update(details);
  });
})();
