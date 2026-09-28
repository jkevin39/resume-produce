'use strict';
// prepare 左右分栏：左栏分页区宽度由 createPaneSplit(axis:'x') 管理；整区高度仍显式撑满视口。
(() => {
  const area = document.getElementById('prepare-workspace');
  const top = document.getElementById('prepare-analysis');
  const header = document.querySelector('.prepare-header');
  const handle = document.getElementById('prepare-splitter');
  const desktop = matchMedia('(min-width: 901px)');
  const split = createPaneSplit({top, handle, axis: 'x', minPrimary: 280, minSecondary: 360,
    available:() => area.clientWidth - handle.offsetWidth,
    enabled:() => desktop.matches,
    apply:width => {top.style.width = width === null ? '' : `${width}px`;}
  });
  const layout = () => {
    split.finish();
    area.style.height = desktop.matches ? `${Math.max(432, innerHeight - area.getBoundingClientRect().top - scrollY - 16)}px` : '';
    split.render();
  };
  new ResizeObserver(layout).observe(header);
  window.addEventListener('resize', layout);
  desktop.addEventListener('change', layout);
  layout();
})();
