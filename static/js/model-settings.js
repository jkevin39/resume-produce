(() => {
 const form = document.querySelector('#model-settings-form'); if (!form) return;
 const catalog = JSON.parse(document.querySelector('#model-catalog').textContent);
 const current = JSON.parse(document.querySelector('#model-current').textContent);
 const provider = form.elements.provider, model = form.elements.model;
 const remembered = {[current.provider]: current.model};
 const refresh = () => {
   model.replaceChildren(...Object.entries(catalog[provider.value].models).map(([id, name]) => new Option(name, id)));
   if (remembered[provider.value]) model.value = remembered[provider.value];
 };
 refresh(); provider.addEventListener('change', refresh);
 model.addEventListener('change', () => remembered[provider.value] = model.value);
 form.addEventListener('submit', async e => {
  e.preventDefault(); const button = form.querySelector('button'); button.disabled = true;
  const status = form.querySelector('[role=status]');
  try {
   const response = await fetch('/api/model-settings', {method: 'POST', headers: {'Content-Type': 'application/json'},
     body: JSON.stringify({provider: provider.value, model: model.value, thinking: form.elements.thinking.value === 'true'})});
   const data = await response.json();
   if (!response.ok) throw new Error(data.error || '保存失败');
   status.textContent = '已保存，新一轮操作生效。';
   document.querySelector('.runtime-line strong').textContent = data.runtime_label;
   document.querySelector('#model-settings summary').textContent = '模型设置 · ' + model.selectedOptions[0].text + ' · 思考' + (data.settings.thinking ? '开启' : '关闭');
   const warning = document.querySelector('#model-key-warning');
   warning.hidden = !data.key_missing;
  } catch(e) { status.textContent = e.message; }
  finally { button.disabled = false; }
 });
})();
