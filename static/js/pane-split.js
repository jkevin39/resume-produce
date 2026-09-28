'use strict';
// axis: 'y'（默认，纵向分栏，draft 用）| 'x'（横向分栏，prepare 用）。
// minPrimary/minSecondary：主轴两端的最小尺寸约束，y 向为高度（120/300），x 向为宽度（prepare 传 280/360）。
window.createPaneSplit = ({top, handle, available, enabled = () => true, apply, axis = 'y', minPrimary = 120, minSecondary = 300}) => {
  const horiz = axis === 'x';
  let ratio = 0.4, drag = null;
  const clamp = size => Math.max(minPrimary, Math.min(available() - minSecondary, size));
  const render = () => {
    if (!enabled()) {finish(); apply(null); return;}
    const size = clamp(available() * ratio);
    apply(size);
    const percent = Math.round(size / available() * 100);
    handle.setAttribute('aria-valuemin', Math.round(minPrimary / available() * 100));
    handle.setAttribute('aria-valuemax', Math.round((available() - minSecondary) / available() * 100));
    handle.setAttribute('aria-valuenow', percent);
    handle.setAttribute('aria-valuetext', `${horiz ? '左侧' : '上方'}区域占 ${percent}%`);
  };
  const finish = () => {
    if (!drag) return;
    const {overlay, id} = drag;
    drag = null;
    overlay.remove();
    document.body.classList.remove(horiz ? 'draft-resizing-x' : 'draft-resizing');
    if (handle.hasPointerCapture(id)) handle.releasePointerCapture(id);
  };
  handle.addEventListener('pointerdown', event => {
    if (event.button !== 0 || drag || !enabled()) return;
    event.preventDefault();
    const overlay = document.createElement('div');
    overlay.className = 'draft-drag-overlay';
    document.body.append(overlay);
    const rect = top.getBoundingClientRect();
    drag = {id:event.pointerId, pos: horiz ? event.clientX : event.clientY, size: horiz ? rect.width : rect.height, overlay};
    document.body.classList.add(horiz ? 'draft-resizing-x' : 'draft-resizing');
    window.getSelection()?.removeAllRanges();
    handle.setPointerCapture(event.pointerId);
  });
  handle.addEventListener('pointermove', event => {
    if (!drag || event.pointerId !== drag.id) return;
    event.preventDefault();
    ratio = clamp(drag.size + (horiz ? event.clientX : event.clientY) - drag.pos) / available();
    render();
  });
  handle.addEventListener('pointerup', finish);
  handle.addEventListener('pointercancel', finish);
  handle.addEventListener('lostpointercapture', finish);
  window.addEventListener('blur', finish);
  handle.addEventListener('keydown', event => {
    const back = horiz ? 'ArrowLeft' : 'ArrowUp', forward = horiz ? 'ArrowRight' : 'ArrowDown';
    if (![back, forward, 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const current = horiz ? top.offsetWidth : top.offsetHeight;
    const size = event.key === 'Home' ? minPrimary : event.key === 'End' ? available() - minSecondary : current + (event.key === back ? -20 : 20);
    ratio = clamp(size) / available();
    render();
  });
  return {render, finish};
};
