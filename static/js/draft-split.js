'use strict';
(() => {
  const area = document.querySelector('.preview-area');
  const analysis = document.getElementById('jd-analysis-panel');
  const handle = document.getElementById('draft-splitter');
  const split = createPaneSplit({top:analysis, handle,
    available:() => area.clientHeight - 20 - handle.offsetHeight,
    enabled:() => analysis.open,
    apply:height => {
      handle.hidden = height === null;
      analysis.style.height = height === null ? '' : `${height}px`;
      const style = getComputedStyle(analysis);
      analysis.querySelector('.collapsible-body').style.height = height === null ? '' : `${analysis.clientHeight - analysis.querySelector('summary').offsetHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom)}px`;
    }
  });
  analysis.addEventListener('toggle', () => {handle.hidden = !analysis.open; split.finish(); split.render();});
  new ResizeObserver(split.render).observe(area);
  split.render();
})();
