window.ResumePreview = {
  async show(frame, status) {
    const doc = frame.contentDocument;
    const page = doc && doc.querySelector('.resume-page');
    if (!page) return {overflow: false};
    if (doc.fonts) await doc.fonts.ready;
    const vertical = Math.max(0, page.scrollHeight - page.clientHeight);
    const horizontal = Math.max(0, page.scrollWidth - page.clientWidth);
    const messages = [];
    if (vertical > 1) messages.push(`纵向超出 ${Math.ceil(vertical)} px`);
    if (horizontal > 1) messages.push(`横向超出 ${Math.ceil(horizontal)} px`);
    let overlap=false, textOverflow=false;
    page.querySelectorAll('[data-canvas-container]').forEach(container => {
      const items=[...container.children].filter(n=>n.matches('[data-canvas-id]') && n.getClientRects().length && !n.closest('[hidden]'));
      for(let i=0;i<items.length;i++) for(let j=i+1;j<items.length;j++) {
        for(const a of items[i].getClientRects()) for(const b of items[j].getClientRects()) {
          if(Math.min(a.right,b.right)-Math.max(a.left,b.left)>1 && Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>1) overlap=true;
        }
      }
    });
    page.querySelectorAll('.resume-text').forEach(n=>{
      const parent=n.closest('[data-canvas-id], .header-content');
      if(!parent || n.closest('[hidden]') || !n.textContent.trim())return;
      const bounds=parent.getBoundingClientRect();
      for(const r of n.getClientRects()) {
        if(r.left<bounds.left-1 || r.right>bounds.right+1 || r.top<bounds.top-1 || r.bottom>bounds.bottom+1)textOverflow=true;
      }
    });
    if(overlap) messages.push('画布兄弟对象重叠（请检查自定义 CSS）');
    if(textOverflow) messages.push('文字溢出（请检查宽度或自定义 CSS）');
    const photo = page.querySelector('.profile-photo');
    if (photo && photo.complete && !photo.naturalWidth) messages.push('照片加载失败');
    if (!page.querySelector('.resume-header').classList.contains('no-photo') && !photo) messages.push('缺少草稿照片');
    if (doc.fonts && [...doc.fonts].some(font => font.status === 'error')) messages.push('字体加载失败');
    if (/\{\{|\}\}|TODO|PLACEHOLDER/.test(page.innerText)) messages.push('存在明显占位符');
    const contacts = [...page.querySelectorAll('.contact-info > span')].slice(0, 2);
    if (!page.querySelector('h1')?.innerText.trim() || !contacts.some(node => node.innerText.trim())) messages.push('姓名或联系方式为空');
    status.textContent = messages.length ? messages.join('；') + '。可调整内容/样式，或确认后继续打印。' : '一页布局与资源检查通过';
    status.className = messages.length ? 'statusbar status-warn' : 'statusbar status-ok';
    frame.style.height = `${Math.max(page.scrollHeight + 40, 1165)}px`;
    return {overflow: vertical > 1 || horizontal > 1, vertical, horizontal};
  },
  async print(frame, status) {
    frame.contentDocument.activeElement?.blur();
    const result = await this.show(frame, status);
    if (result.overflow && !window.confirm('内容超过一页或存在横向溢出，是否仍继续打印？')) return;
    frame.contentWindow.focus();
    frame.contentWindow.print();
  }
};
