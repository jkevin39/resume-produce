(() => {
  document.querySelectorAll('[data-ocr-target]').forEach(panel => {
    const zone = panel.querySelector('[data-image-paste]');
    if (!zone) return;
    const target = document.getElementById(panel.dataset.ocrTarget);
    const label = panel.dataset.ocrLabel;
    const picker = panel.querySelector('input[type=file]');
    const preview = panel.querySelector('img');
    const result = panel.querySelector('textarea');
    const status = panel.querySelector('[role=status]');
    const recognize = panel.querySelector('[data-recognize]');
    const apply = [...panel.querySelectorAll('[data-apply]')];
    let file, imageUrl, busy = false, importing = false, hasResult = false, applied = false;
    let requestVersion = 0, controller;
    function sync() {
      picker.disabled = busy || importing;
      recognize.disabled = busy || importing || !file;
      result.disabled = busy || importing;
      zone.setAttribute('aria-disabled', String(busy || importing));
      apply.forEach(b => b.disabled = busy || importing || !hasResult || applied || !result.value.trim());
    }
    function clear() {
      requestVersion++; controller?.abort(); controller = null;
      if (imageUrl) URL.revokeObjectURL(imageUrl);
      file = imageUrl = null; busy = hasResult = applied = false;
      picker.value = ''; preview.removeAttribute('src'); preview.hidden = true;
      result.value = ''; status.textContent = ''; sync();
    }
    panel.ocrController = {
      isBusy: () => busy,
      setImporting: value => { importing = value; sync(); },
      clear,
    };
    function choose(files) {
      if (busy || importing) return;
      if (files.length !== 1) { status.textContent = '一次请选择一张图片。'; return; }
      const candidate = files[0];
      if (!['image/png', 'image/jpeg'].includes(candidate.type) || candidate.size > 4 * 1024 * 1024) {
        status.textContent = '请选择不超过 4MB 的 PNG/JPEG 图片。'; return;
      }
      file = candidate;
      if (imageUrl) URL.revokeObjectURL(imageUrl);
      imageUrl = URL.createObjectURL(file); preview.src = imageUrl; preview.hidden = false;
      result.value = ''; hasResult = applied = false;
      status.textContent = '图片已就绪，点击识别文字。'; sync();
    }
    zone.addEventListener('paste', e => {
      if (!e.clipboardData.files.length) return;
      e.preventDefault(); choose([...e.clipboardData.files]);
    });
    picker.addEventListener('change', () => choose([...picker.files]));
    result.addEventListener('input', () => { applied = false; sync(); });
    recognize.addEventListener('click', async () => {
      if (busy || importing || !file) return;
      const version = ++requestVersion;
      controller = new AbortController(); busy = true; sync();
      status.textContent = '正在本机识别…';
      try {
        const body = new FormData(); body.append('image', file);
        const response = await fetch('/api/ocr', {method: 'POST', body, signal: controller.signal});
        const data = await response.json();
        if (version !== requestVersion) return;
        if (!response.ok || !data.ok) throw new Error(data.error || '识别失败，请重试。');
        result.value = data.text; hasResult = true; applied = false;
        status.textContent = '识别完成，可修改文字后追加或替换' + label + '。';
      } catch (e) {
        if (version === requestVersion) status.textContent = e.name === 'AbortError' ? '识别已取消。' : '识别失败：' + (e.message || '请重试。');
      } finally {
        if (version === requestVersion) { busy = false; controller = null; sync(); }
      }
    });
    apply.forEach(button => button.addEventListener('click', () => {
      if (busy || importing || applied || !hasResult) return;
      const text = result.value.trim(); if (!text) { status.textContent = '识别结果为空。'; return; }
      if (button.dataset.apply === 'replace') {
        if (target.value.trim() && !confirm('替换当前' + label + '全文？')) return;
        target.value = text;
      } else { target.value = [target.value.trimEnd(), text].filter(Boolean).join('\n'); }
      const sourceFile = document.getElementById(panel.dataset.ocrFile);
      const clearedFile = Boolean(sourceFile?.files.length);
      if (sourceFile) sourceFile.value = '';
      target.dispatchEvent(new Event('input', {bubbles: true}));
      status.textContent = '已写入' + label + '。' + (clearedFile ? '已清除原文件选择，本次提交使用材料正文。' : '');
      applied = true; sync();
    }));
    panel.closest('form')?.addEventListener('reset', clear);
    window.addEventListener('pagehide', clear);
    sync();
  });
})();
