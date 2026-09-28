'use strict';
(() => {
  const KEY = 'v091k-collapsible';
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (_) {}
  const initialize = root => root.querySelectorAll('details[data-collapsible]').forEach(detail => {
    if (Object.prototype.hasOwnProperty.call(saved, detail.dataset.collapsible)) detail.open = saved[detail.dataset.collapsible];
  });
  initialize(document);
  document.addEventListener('toggle', event => {
    if (!event.target.matches('details[data-collapsible]')) return;
    saved[event.target.dataset.collapsible] = event.target.open;
    try { localStorage.setItem(KEY, JSON.stringify(saved)); } catch (_) {}
  }, true);
  document.addEventListener('input', event => {
    const form = event.target.closest('[data-library-form]');
    if (form) form.dataset.dirty = 'true';
  });
  const identity = form => form.action + ':' + (form.elements.identifier?.value || '');
  window.ResumeLibrary = {
    update(result, submittedForm) {
      const body = document.getElementById('library-body');
      const open = new Map([...document.querySelectorAll('details[data-collapsible]')].map(x => [x.dataset.collapsible, x.open]));
      const edits = [...body.querySelectorAll('form[data-dirty]')].filter(f => f !== submittedForm).map(f => ({key: identity(f), values: [...f.elements].map(x => ({name: x.name, value: x.value, checked: x.checked, type: x.type}))}));
      body.innerHTML = result.library_html;
      document.getElementById('library-trash').innerHTML = result.trash_html;
      initialize(document);
      document.querySelectorAll('details[data-collapsible]').forEach(x => {if(open.has(x.dataset.collapsible)) x.open = open.get(x.dataset.collapsible);});
      for (const edit of edits) {
        const form = [...body.querySelectorAll('form')].find(f => identity(f) === edit.key);
        if (!form) continue;
        for (const value of edit.values) {
          const inputs = [...form.elements].filter(x => x.name === value.name);
          for (const input of inputs) {
            if (value.type === 'checkbox') { if(input.value === value.value) input.checked = value.checked; }
            else if (input.name) input.value = value.value;
          }
        }
        form.dataset.dirty = 'true';
        const detail = form.closest('details'); if(detail) detail.open = true;
      }
      document.getElementById('library-summary').innerHTML = result.summary_html;
      const picker = document.getElementById('target-object'), previous = picker.value;
      picker.innerHTML = result.options_html;
      if ([...picker.options].some(x => x.value === previous)) picker.value = previous;
      const focus = [...document.querySelectorAll('[data-collapsible]')].find(x => x.dataset.collapsible === result.focus);
      if (focus) focus.open = true;
      return focus;
    }
  };
  let pending = false;
  document.addEventListener('submit', async event => {
    const form = event.target.closest('[data-library-form]');
    if (!form) return;
    event.preventDefault();
    if (pending || (form.dataset.confirm && !confirm(form.dataset.confirm))) return;
    const status = form.querySelector('[data-library-status]');
    const body = new FormData(form);
    const purge = new URL(form.action, window.location.href).pathname.endsWith('/purge');
    pending = true;
    const buttons = [...document.querySelectorAll('[data-library-form] button')];
    buttons.forEach(x => x.disabled = true);
    try {
      const response = await fetch(form.action, {method:'POST', headers:{'X-Requested-With':'fetch'}, body});
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error((result.errors || ['保存失败']).join('；'));
      const focus = window.ResumeLibrary.update(result, form);
      if (!purge) {
        const message = document.createElement('p'); message.setAttribute('role','status'); message.textContent = result.message;
        (focus?.querySelector('.collapsible-body') || document.getElementById('library-body')).prepend(message);
      }
      window.toast?.(result.message, 'success');
    } catch (error) {
      status.textContent = error.message || '保存失败，输入已保留。';
      window.toast?.(status.textContent, 'error');
    } finally { pending = false; buttons.forEach(x => x.disabled = false); }
  });
})();
