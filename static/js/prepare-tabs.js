// prepare 左栏分页辅助：display 显隐会把 scrollTop 归零，这里记忆各页滚动位置并在切回时恢复。
// 切换本身由纯 CSS radio 完成（:checked ~ 兄弟选择器），本文件只补滚动记忆，不承担显隐。
'use strict';
(() => {
  const root = document.getElementById('prepare-analysis');
  if (!root) return;
  const cards = Array.from(root.querySelectorAll('.grid > .card'));
  if (cards.length < 2) return;
  const saved = new Map();
  cards.forEach(card => card.addEventListener('scroll', () => saved.set(card, card.scrollTop), {passive: true}));
  root.addEventListener('change', event => {
    if (event.target.name !== 'analysis-tab') return;
    // change 触发时 CSS 已应用：刚显示的页有布局盒，被隐藏的页 offsetParent 为 null。
    const visible = cards.find(card => card.offsetParent !== null);
    if (!visible || !saved.has(visible)) return;
    const top = saved.get(visible);
    requestAnimationFrame(() => { visible.scrollTop = top; });
  });
})();
