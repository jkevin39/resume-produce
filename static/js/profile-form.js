(() => {
  const form = document.getElementById('profile-form');
  if (!form) return;
  const rows = document.getElementById('education-rows');
  const status = document.getElementById('profile-status');
  const save = document.getElementById('save-profile');
  const fields = document.getElementById('profile-fields');
  const profileKeys = ['name', 'phone', 'email', 'location', 'summary'];
  let dirty = false;
  let pending = false;
  const changed = () => {
    dirty = true;
    status.className = 'muted';
    status.textContent = '有未保存的修改。请先保存，再生成简历。';
  };
  function appendEducation(value = {}, index = '') {
    const row = document.getElementById('education-template').content.firstElementChild.cloneNode(true);
    row.dataset.originalIndex = String(index);
    row.querySelectorAll('[data-field]').forEach(input => { input.value = value[input.dataset.field] || ''; });
    rows.append(row);
    return row;
  }
  form.addEventListener('input', changed);
  document.getElementById('add-education').addEventListener('click', () => {
    appendEducation().querySelector('input').focus();
    changed();
  });
  rows.addEventListener('click', event => {
    const button = event.target.closest('[data-remove-education]');
    if (button) { button.closest('.education-row').remove(); changed(); }
  });
  window.addEventListener('beforeunload', event => {
    if (dirty) { event.preventDefault(); event.returnValue = ''; }
  });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (pending) return;
    const profile = Object.fromEntries(profileKeys.map(key => [key, form.elements.namedItem(key).value]));
    const education = Array.from(rows.children).map(row => ({
      original_index: row.dataset.originalIndex === '' ? null : Number(row.dataset.originalIndex),
      ...Object.fromEntries(Array.from(row.querySelectorAll('[data-field]')).map(input => [input.dataset.field, input.value])),
    }));
    pending = true;
    fields.disabled = true;
    save.disabled = true;
    status.className = 'muted';
    status.textContent = '正在保存…';
    try {
      const response = await fetch(form.action, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({profile, education}),
      });
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error((result.errors || ['保存未完成，请重试。']).join('；'));
      rows.replaceChildren();
      result.profile.education.forEach((item, index) => appendEducation(item, index));
      profileKeys.forEach(key => { form.elements.namedItem(key).value = result.profile.profile[key] || ''; });
      document.querySelectorAll('[data-profile-name]').forEach(node => { node.textContent = result.profile.profile.name || '姓名待填写'; });
      dirty = false;
      status.className = 'status-ok';
      status.textContent = '已保存。新生成的简历会使用这些信息；已有草稿可主动读取最新履历资料。';
      window.toast?.('基本信息已保存', 'success');
    } catch (error) {
      status.className = 'error-box';
      status.textContent = error.message === 'Failed to fetch' ? '连接失败，输入已保留。请检查服务后重试。' : error.message;
      window.toast?.('基本信息保存失败', 'error');
    } finally {
      pending = false;
      fields.disabled = false;
      save.disabled = false;
    }
  });
})();
