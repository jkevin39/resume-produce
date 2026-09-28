const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const vm = require('node:vm');
const source = readFileSync(require('node:path').join(__dirname, '../static/js/preview-checker.js'), 'utf8');

function setup({vertical=0, horizontal=0, photo=null, showPhoto=false, name='测试', phone='13800000000', email='', confirm=true}={}) {
  const calls = [];
  const page = {
    scrollHeight:1123+vertical, clientHeight:1123, scrollWidth:794+horizontal, clientWidth:794,
    innerText:'测试简历',
    querySelector(selector) {
      if (selector === '.profile-photo') return photo;
      if (selector === '.resume-header') return {classList:{contains:()=>!showPhoto}};
      if (selector === 'h1') return {innerText:name};
    },
    querySelectorAll(selector) { return selector === '.contact-info > span' ? [{innerText:phone}, {innerText:email}, {innerText:'上海'}] : []; },
  };
  const frame = {
    style:{},
    contentDocument:{querySelector:()=>page, activeElement:{blur:()=>calls.push('blur')}},
    contentWindow:{focus:()=>calls.push('focus-frame'), print:()=>calls.push('print-frame')},
  };
  const context = {window:{confirm:()=>{ calls.push('confirm'); return confirm; }}};
  vm.runInNewContext(source, context);
  return {checker:context.window.ResumePreview, frame, status:{}, calls};
}

test('normal page prints only the supplied resume iframe', async () => {
  const {checker,frame,status,calls} = setup();
  await checker.print(frame,status);
  assert.deepEqual(calls,['blur','focus-frame','print-frame']);
  assert.match(status.textContent,/检查通过/);
});
test('overflow cancel leaves content untouched and does not print', async () => {
  const {checker,frame,status,calls} = setup({vertical:100,confirm:false});
  await checker.print(frame,status);
  assert.deepEqual(calls,['blur','confirm']);
  assert.match(status.textContent,/纵向超出 100/);
});
test('overflow confirmation still prints the iframe', async () => {
  const {checker,frame,status,calls} = setup({horizontal:20});
  await checker.print(frame,status);
  assert.deepEqual(calls,['blur','confirm','focus-frame','print-frame']);
  assert.match(status.textContent,/横向超出 20/);
});
test('broken or missing enabled photos are reported', async () => {
  for (const photo of [null,{complete:true,naturalWidth:0}]) {
    const {checker,frame,status} = setup({showPhoto:true,photo});
    await checker.show(frame,status);
    assert.match(status.textContent,/照片/);
  }
});
test('location alone does not satisfy contact information', async () => {
  const {checker,frame,status} = setup({phone:'',email:''});
  await checker.show(frame,status);
  assert.match(status.textContent,/姓名或联系方式为空/);
});
