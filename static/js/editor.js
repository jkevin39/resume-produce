(() => {
  const config=JSON.parse(document.getElementById('draft-config').textContent), M=ResumeEditorModel;
  const $=id=>document.getElementById(id), frame=$('resume-frame');
  let spec=config.spec, revision=config.revision || 0, selectedId=null, mode='object', clipboard=null;
  let dirty=true, busy=false, composing=false, session=false, staleDOM=false, deferred=false, installing=false;
  let ready=Promise.resolve(), sequence=0, queuedHistory=null, dragId=null, bookmark=null;
  let sidebarFocus=false, sidebarChanged=false, pendingRender=false, focusAfterRender=null;
  const styles={'font-size':'font_size','line-height':'line_height','page-padding':'page_padding','section-gap':'section_gap','bullet-gap':'bullet_gap','title-color':'title_color'};
  const labels={section:'板块',education:'教育',experience:'经历',projects:'项目',bullet:'Bullet',skills:'技能'};
  const state=()=>({spec,custom_css:$('custom-css').value,selection:bookmark || {id:selectedId,mode}});
  const history=new M.History(state());
  function error(message='') { $('errors').hidden=!message; $('errors').textContent=message; }
  function changed() { dirty=true;revision++;$('save-status').textContent='有未保存修改';$('save-status').classList.add('dirty');historyControls(); }
  function historyControls() {
    const pending=JSON.stringify([spec,$('custom-css').value])!==JSON.stringify([history.present.spec,history.present.custom_css]);
    $('undo').disabled=busy || (!pending && !history.past.length);
    $('redo').disabled=busy || pending || !history.future.length;
  }
  function label(o) { return `${labels[o.kind]}：${o.kind==='section'?o.section.title:(o.item.organization || o.item.school || o.item.name || o.item.text || '未填写').slice(0,32)}`; }
  function options(select, rows, empty) {
    if(document.activeElement===select && select.id!=='restore-section')return;
    const previous=select.value;select.replaceChildren();
    if(empty!==undefined) select.add(new Option(empty,''));
    for(const [value,text] of rows) select.add(new Option(text,value));
    select.value=previous;
    if(select.selectedIndex<0 && select.options.length)select.selectedIndex=0;
  }
  function selectionControls() {
    const all=M.objects(spec),obj=all.find(o=>o.id===selectedId);
    if(!obj) selectedId=null;
    options($('object-picker'),all.map(o=>[o.id,label(o)]),'未选择');$('object-picker').value=selectedId || '';
    options($('move-target'),all.filter(o=>o.id!==selectedId).map(o=>[o.id,label(o)]),'选择目标');
    options($('restore-section'),spec.layout.sections.filter(s=>s.hidden).map(s=>[s.canvas_id,s.title]));
    $('object-status').textContent=obj?`${mode==='text'?'文字编辑':'对象选择'} · ${label(obj)}`:'点击 ⠿ 选择或拖动对象；点击文字直接编辑。';
    historyControls();
    for(const id of ['copy-object','remove-object','move-up','move-down','move-to']) $(id).disabled=busy || !obj;
    $('paste-object').disabled=busy || !clipboard;
    $('duplicate-experience').disabled=busy || obj?.kind!=='experience';
    for(const select of document.querySelectorAll('#object-controls select'))select.disabled=busy || composing || mode==='text';
    $('restore-section-button').disabled=busy || !spec.layout.sections.some(s=>s.hidden && s.canvas_id===$('restore-section').value);
    $('remove-object').textContent=obj?.kind==='section'?'隐藏板块':'删除条目';
    frame.contentDocument?.querySelectorAll('[data-canvas-id]').forEach(n=>n.classList.toggle('canvas-selected',mode==='object' && n.dataset.canvasId===selectedId));
  }
  function displayControls() {
    $('cjk-font').value=spec.style.cjk_font || 'songti';
    $('theme').value=spec.theme;$('density').value=spec.density;$('show-photo').checked=spec.show_photo;
    for(const key of ['width','height','position']) $('photo-'+key).value=spec.photo[key];
    const color=$('title-color'), value=spec.style.title_color || '';
    color.querySelectorAll('[data-custom-color]').forEach(n=>n.remove());
    if(![...color.options].some(n=>n.value===value)){const option=new Option(`当前自定义色（${value}）`,value);option.dataset.customColor='true';color.add(option);}
    for(const [id,key] of Object.entries(styles)) $(id).value=spec.style[key];
    selectionControls();
  }
  function freeze(value) {
    busy=value;
    document.querySelectorAll('.editor-panel button,.editor-panel input,.editor-panel select,.editor-panel textarea').forEach(n=>{n.disabled=value || (n.closest('#draft-name')?.dataset.pending === 'true');});
    frame.style.pointerEvents=value || staleDOM?'none':'';
    frame.contentDocument?.querySelectorAll('[data-path]').forEach(n=>{n.contentEditable=String(!value && !staleDOM);});
    selectionControls();
  }
  function capture() {
    const doc=frame.contentDocument, node=doc?.activeElement;
    if(node?.matches('[data-path]')) {
      const selection=doc.getSelection(), id=node.closest('[data-canvas-id]')?.dataset.canvasId;
      if(selection && (!node.contains(selection.anchorNode) || !node.contains(selection.focusNode))){bookmark=null;return null;}
      const offset=(n,o)=>{try {const r=doc.createRange();r.selectNodeContents(node);r.setEnd(n,o);return Array.from(r.toString()).length;} catch {return 0;}};
      bookmark={id:id || null,path:node.dataset.path,field:node.dataset.path.split('.').at(-1),mode:'text',anchor:selection?offset(selection.anchorNode,selection.anchorOffset):0,focus:selection?offset(selection.focusNode,selection.focusOffset):0};
    } else if(document.activeElement?.matches('.editor-panel input[type=text],.editor-panel textarea')) {
      const n=document.activeElement;bookmark={control:n.id,anchor:n.selectionStart,focus:n.selectionEnd,mode:'text'};
    } else if(mode==='object') bookmark={id:selectedId,mode};
    return bookmark;
  }
  function restore(saved) {
    if(!saved)return;
    saved=structuredClone(saved);
    bookmark=saved;selectedId=saved.id || null;mode=saved.mode || 'object';
    if(saved.control) {
      const n=$(saved.control);if(n && !n.disabled){n.focus();n.setSelectionRange(saved.anchor,saved.focus);}return;
    }
    const doc=frame.contentDocument;
    if(mode==='text' && !busy) {
      const parent=saved.id?[...doc.querySelectorAll('[data-canvas-id]')].find(n=>n.dataset.canvasId===saved.id):doc;
      const node=[...(parent?.querySelectorAll('[data-path]') || [])].find(n=>saved.id?n.dataset.path.split('.').at(-1)===saved.field:n.dataset.path===saved.path);
      if(node) {
        node.focus();
        const at=offset=>{const walker=doc.createTreeWalker(node,4);let n,last;while((n=walker.nextNode())){last=n;const chars=Array.from(n.textContent);if(offset<=chars.length)return [n,chars.slice(0,offset).join('').length];offset-=chars.length;}return last?[last,last.length]:[node,0];};
        const a=at(saved.anchor || 0),f=at(saved.focus || 0);doc.getSelection().setBaseAndExtent(a[0],a[1],f[0],f[1]);
      } else mode='object';
    }
    bookmark=saved;
    selectionControls();
  }
  function readField(node) {
    const keys=node.dataset.path.split('.');let cursor=spec;
    for(const key of keys.slice(0,-1))cursor=cursor[key];
    const field=keys.at(-1),text=(node.closest('[hidden]')?node.textContent:node.innerText).replace(/\r/g,'');
    ResumeInlineStyles.edit(spec,node.closest('[data-canvas-id]')?.dataset.canvasId || 'profile',field,cursor[field],text);
    cursor[field]=text;
  }
  function commit() {
    if(composing)return;
    capture();history.commit(state());session=false;selectionControls();
  }
  function begin() {
    if(!session) { capture();history.rememberSelection(bookmark);session=true; }
  }
  function transaction(fn) {
    if(busy || composing)return;
    commit();
    try {
      fn();M.project(spec);
      const requestedFocus=focusAfterRender;focusAfterRender=null;
      if(requestedFocus){
        mode='text';
        bookmark={id:requestedFocus.id,field:requestedFocus.field,mode:'text',anchor:0,focus:0};
      } else {
        mode='object';bookmark={id:selectedId,mode};
      }
      if(history.commit(state())) {changed();staleDOM=true;displayControls();scheduleRender();}
      selectionControls();error();
    } catch(exc){error(exc.message);}
  }
  async function api(action,extra={}) {
    const response=await fetch(`/api/drafts/${config.draft_id}/${action}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...state(),revision,...extra})});
    if(!response.ok) {const data=await response.json();throw new Error((data.errors || ['请求失败']).join('；'));}
    return response;
  }
  function textActive() {return composing || session;}
  async function render() {
    if(textActive()){deferred=true;return;}
    const version=revision,requestSequence=++sequence;
    try {
      const data=await (await api('preview')).json();
      if(version!==revision || requestSequence!==sequence || data.revision!==revision)return;
      if(textActive()){deferred=true;return;}
      if(sidebarFocus){pendingRender=true;return;}
      await install(data.html,bookmark);
    } catch(exc) {if(version===revision)error(exc.message);}
  }
  function flushPendingRender() {
    if(sidebarFocus || !pendingRender)return;
    pendingRender=false;deferred=false;freeze(busy);ready=render();
  }
  function scheduleRender() {
    // A native select may still be open while its change/focus events are
    // delivered.  Keep the iframe alive until that control is settled.
    if(sidebarFocus){pendingRender=true;return ready;}
    deferred=false;freeze(busy);ready=render();return ready;
  }
  function historyStep(redo) {
    if(busy)return;
    if(composing){queuedHistory=redo?'redo':'undo';return;}
    commit();const value=redo?history.redo():history.undo();if(!value)return;
    spec=value.spec;$('custom-css').value=value.custom_css;bookmark=value.selection;selectedId=bookmark?.id || null;mode=bookmark?.mode || 'object';
    changed();staleDOM=true;displayControls();scheduleRender();
  }
  function keydown(event) {
    if(event.target.closest?.('#draft-name'))return;
    if(event.key==='Escape'){
      if(composing)return;
      if(event.target.closest?.('dialog'))return;
      sidebarFocus=false;
      event.preventDefault();
      commit();
      frame.contentDocument?.activeElement?.blur();
      selectedId=null;mode='object';bookmark=null;
      selectionControls();
      return;
    }
    if(event.key==='Backspace' && !event.metaKey && !event.ctrlKey && !event.altKey && !event.shiftKey){
      const textTarget=event.target.closest?.('[contenteditable=true],input,textarea,select');
      const dialogOpen=document.querySelector('dialog[open]');
      if(mode==='object' && selectedId && !textTarget && !dialogOpen && !composing && !busy && !sidebarFocus){
        event.preventDefault();
        transaction(()=>M.removeObject(spec,selectedId));
      }
      return;
    }
    if(!(event.metaKey || event.ctrlKey) || event.altKey)return;
    const key=event.key.toLowerCase();
    if(key==='z' || key==='y'){event.preventDefault();historyStep(key==='y' || event.shiftKey);return;}
    const textTarget=event.target.closest('[contenteditable=true],input,textarea');
    if(mode!=='object' || textTarget || busy || composing)return;
    if(key==='c' && selectedId) {event.preventDefault();copy();}
    if(key==='v' && clipboard) {event.preventDefault();paste();}
  }
  function copy() {commit();try{clipboard=M.copyObject(spec,selectedId);selectionControls();error();}catch(exc){error(exc.message);}}
  function paste() {transaction(()=>{selectedId=M.pasteObject(spec,clipboard,mode==='object'?selectedId:null);});}
  function select(id) {commit();selectedId=id;mode='object';bookmark={id,mode};frame.contentDocument?.activeElement?.blur();selectionControls();}
  function install(html,saved) {
    installing=true;
    return new Promise(resolve=>{
      frame.onload=async()=>{
        const doc=frame.contentDocument;staleDOM=false;
        doc.addEventListener('keydown',keydown);
        doc.addEventListener('focusin',e=>{if(e.target.matches('[data-path]') && !installing){mode='text';selectedId=e.target.closest('[data-canvas-id]')?.dataset.canvasId || null;capture();selectionControls();}});
        doc.addEventListener('selectionchange',()=>{if(!installing && doc.activeElement?.matches?.('[data-path]'))capture();});
        doc.addEventListener('beforeinput',e=>{if(e.target.matches('[data-path]') && !busy && !staleDOM){begin();}});
        doc.addEventListener('focusout',e=>{if(e.target.matches('[data-path]') && !composing && !staleDOM && !busy && !installing){
          commit(); // Blur alone must not replace the iframe (including clicks on disabled controls).
        }});
        doc.addEventListener('compositionstart',()=>{begin();composing=true;selectionControls();});
        doc.addEventListener('compositionend',e=>{
          // Keep the session composing until Chrome dispatches its final input.
          setTimeout(()=>{
            composing=false;if(e.target.matches('[data-path]'))readField(e.target);changed();capture();
            if(queuedHistory){const action=queuedHistory;queuedHistory=null;historyStep(action==='redo');}
          },0);
        });
        doc.addEventListener('input',e=>{
          if(!e.target.matches('[data-path]') || busy || staleDOM)return;
          begin();if(!composing && !e.isComposing){readField(e.target);changed();capture();ResumePreview.show(frame,$('layout-status'));}
        });
        doc.addEventListener('paste',e=>{if(e.target.closest('[data-path]')){e.preventDefault();doc.execCommand('insertText',false,e.clipboardData.getData('text/plain'));}});
        doc.addEventListener('click',e=>{
          if(composing || busy || staleDOM)return;
          const handle=e.target.closest('[data-select-id]');if(handle){e.preventDefault();e.stopPropagation();select(handle.dataset.selectId);return;}
          if(e.target.closest('[data-resize-id]')){e.stopPropagation();return;}
          if(e.target.closest('button,input,select,textarea'))return;
          const field=e.target.closest('[data-path]');
          if(field){e.stopPropagation();field.focus();mode='text';selectedId=field.closest('[data-canvas-id]')?.dataset.canvasId || null;capture();selectionControls();return;}
          const obj=e.target.closest('[data-canvas-id]');if(obj){e.preventDefault();e.stopPropagation();select(obj.dataset.canvasId);}
        });
        doc.addEventListener('dragstart',e=>{
          const handle=e.target.closest('[data-select-id]');
          if(!handle || busy || composing){e.preventDefault();return;}
          select(handle.dataset.selectId);dragId=selectedId;e.dataTransfer.setData('text/plain',dragId);e.dataTransfer.effectAllowed='move';
        });
        doc.addEventListener('dragover',e=>{if(dragId){e.preventDefault();e.dataTransfer.dropEffect='move';}});
        doc.addEventListener('drop',e=>{if(!dragId)return;e.preventDefault();const target=e.target.closest('[data-canvas-id]');const id=dragId;dragId=null;if(target)transaction(()=>M.moveObject(spec,id,target.dataset.canvasId,false));});
        doc.addEventListener('dragend',()=>{dragId=null;});
        doc.querySelectorAll('[data-resize-id]').forEach(handle=>handle.addEventListener('pointerdown',e=>{
          if(busy || composing)return;e.preventDefault();select(handle.dataset.resizeId);
          const obj=handle.closest('[data-canvas-id]'),parent=obj.parentElement,box=parent.getBoundingClientRect();
          let span=M.locate(spec,selectedId).node.span || 12;
          handle.setPointerCapture(e.pointerId);
          const move=event=>{span=Math.max(6,Math.min(12,Math.round((event.clientX-obj.getBoundingClientRect().left)/box.width*12)));obj.style.gridColumn=`span ${span}`;};
          const end=event=>{handle.removeEventListener('pointermove',move);handle.removeEventListener('pointerup',end);handle.removeEventListener('pointercancel',cancel);if(event.type==='pointerup')transaction(()=>M.resizeObject(spec,selectedId,span));};
          const cancel=event=>{obj.style.gridColumn=`span ${M.locate(spec,selectedId).node.span || 12}`;end(event);};
          handle.addEventListener('pointermove',move);handle.addEventListener('pointerup',end);handle.addEventListener('pointercancel',cancel);
        }));
        doc.querySelectorAll('img').forEach(img=>{for(const type of ['load','error'])img.addEventListener(type,()=>ResumePreview.show(frame,$('layout-status')));});
        freeze(busy);restore(saved);installing=false;await ResumePreview.show(frame,$('layout-status'));resolve();
      };
      frame.srcdoc=html;
    });
  }
  const sidebarControl=target=>target?.closest?.('.editor-panel select,.editor-panel input,.editor-panel textarea,.editor-panel button');
  document.addEventListener('pointerdown',event=>{
    if(!sidebarControl(event.target) || event.target.disabled || busy)return;
    sidebarFocus=true;sidebarChanged=false;
    // Commit the text session and its stable bookmark before the native
    // control takes focus.  No iframe replacement is requested here.
    if(!composing)capture();
    if(textActive() && !composing)commit();
  },true);
  document.addEventListener('change',event=>{
    if(!sidebarControl(event.target))return;
    sidebarChanged=true;
    setTimeout(()=>{sidebarFocus=false;sidebarChanged=false;flushPendingRender();},0);
  },true);
  document.addEventListener('focusout',event=>{
    if(!sidebarControl(event.target))return;
    setTimeout(()=>{if(!sidebarChanged && !sidebarControl(document.activeElement)){sidebarFocus=false;flushPendingRender();}},0);
  },true);
  document.addEventListener('click',event=>{
    if(!event.target.closest?.('.editor-panel button'))return;
    setTimeout(()=>{sidebarFocus=false;sidebarChanged=false;flushPendingRender();},0);
  },true);
  document.addEventListener('keydown',keydown);
  for(const [button,control,property] of [['apply-inline-size','inline-size','font_size'],['apply-inline-font','inline-font','cjk_font']]) $(button).onclick=()=>{
    const saved=bookmark && structuredClone(bookmark);
    if(!saved || saved.control || saved.mode!=='text' || saved.anchor===saved.focus){error('请先在同一字段内选中文字');return;}
    const value=$(control).value;
    if(busy || composing)return;
    commit();history.rememberSelection(saved);
    ResumeInlineStyles.apply(spec,saved.id || 'profile',saved.field,Math.min(saved.anchor,saved.focus),Math.max(saved.anchor,saved.focus),value===''?null:property==='font_size'?Number(value):value,property);
    bookmark=saved;mode='text';selectedId=saved.id;
    if(history.commit(state())){changed();staleDOM=true;scheduleRender();}
  };
  $('undo').onclick=()=>historyStep(false);$('redo').onclick=()=>historyStep(true);
  $('object-picker').onchange=()=>select($('object-picker').value);
  $('copy-object').onclick=copy;$('paste-object').onclick=paste;
  $('duplicate-experience').onclick=()=>transaction(()=>{selectedId=M.pasteObject(spec,M.copyObject(spec,selectedId),selectedId);});
  $('add-experience').onclick=()=>transaction(()=>{selectedId=M.addObject(spec,'experience');focusAfterRender={id:selectedId,field:'organization'};});
  $('add-object').onclick=()=>transaction(()=>{
    const kind=$('add-kind').value, obj=M.locate(spec,selectedId);
    selectedId=M.addObject(spec,kind,kind==='bullet'?(obj?.kind==='bullet'?obj.parentId:selectedId):(obj?.kind==='section' && obj.section.kind===kind?selectedId:null));
    focusAfterRender={id:selectedId,field:kind==='section'?'title':kind==='education'?'school':kind==='skills'?'name':kind==='bullet'?'text':'organization'};
  });
  $('remove-object').onclick=()=>transaction(()=>M.removeObject(spec,selectedId));
  $('move-up').onclick=()=>transaction(()=>M.stepObject(spec,selectedId,-1));
  $('move-down').onclick=()=>transaction(()=>M.stepObject(spec,selectedId,1));
  $('move-to').onclick=()=>{const target=$('move-target').value;transaction(()=>M.moveObject(spec,selectedId,target,false));};
  $('reset-layout').onclick=()=>transaction(()=>M.resetLayout(spec));
  $('restore-section-button').onclick=()=>{const id=$('restore-section').value;const obj=M.locate(spec,id);if(!obj || obj.kind!=='section' || !obj.section.hidden){selectionControls();error('请选择有效的隐藏板块。');return;}transaction(()=>{obj.section.hidden=false;selectedId=id;});};
  const updateStyle=()=>{
    spec.style.cjk_font=$('cjk-font').value;
    spec.theme=$('theme').value;spec.density=$('density').value;spec.show_photo=$('show-photo').checked;
    for(const key of ['width','height','position'])spec.photo[key]=$('photo-'+key).value;
    for(const [id,key] of Object.entries(styles))spec.style[key]=$(id).value;
  };
  for(const id of ['cjk-font','theme','density','show-photo','photo-width','photo-height','photo-position']) $(id).addEventListener('change',()=>{
    // Commit pending text before applying one style transaction.
    transaction(()=>{
      if(id==='density') {
        const compact=$('density').value==='compact';
        for(const [key,value] of Object.entries(compact?{font_size:'9.5pt',line_height:'1.3',page_padding:'10mm 14mm',section_gap:'2.8mm',bullet_gap:'.45mm'}:{font_size:'10.5pt',line_height:'1.42',page_padding:'14mm 16mm',section_gap:'4.2mm',bullet_gap:'.7mm'})) {
          const control=Object.keys(styles).find(id=>styles[id]===key);$(control).value=value;
        }
      }
      updateStyle();
    });
  });
  for(const id of [...Object.keys(styles),'custom-css']) {
    const node=$(id);
    node.addEventListener('focus',begin);
    node.addEventListener('input',()=>{begin();if(id==='custom-css'){const css=frame.contentDocument?.getElementById('custom-css');if(css)css.textContent=node.value;}else updateStyle();changed();ResumePreview.show(frame,$('layout-status'));});
    node.addEventListener('blur',()=>{commit();scheduleRender();});
  }
  const defaultsStatus=$('layout-defaults-status');
  fetch('/api/layout-defaults').then(r=>r.json()).then(data=>{defaultsStatus.textContent=data.message;}).catch(()=>{defaultsStatus.textContent='默认排版状态读取失败，可重试保存。';});
  async function saveDefaults(clear=false) {
    if(busy || composing)return;
    if(!clear){updateStyle();commit();}
    freeze(true);
    try {
      await ready;
      const response=await fetch('/api/layout-defaults', {method:clear?'DELETE':'PUT',headers:{'Content-Type':'application/json'},
        ...(clear?{}:{body:JSON.stringify({theme:spec.theme,density:spec.density,style:spec.style})})});
      const data=await response.json();
      if(!response.ok)throw new Error(data.error || '操作失败，请重试。');
      defaultsStatus.textContent=data.message + (!clear && $('custom-css').value.trim()?' 当前自定义 CSS 的覆盖效果未纳入默认排版。':'');
    }catch(e){defaultsStatus.textContent=e.message;}finally{freeze(false);}
  }
  $('save-layout-defaults').onclick=()=>saveDefaults();
  $('clear-layout-defaults').onclick=()=>saveDefaults(true);
  $('reset-css').onclick=()=>transaction(()=>{$('custom-css').value='';});
  $('restore-css').onclick=()=>transaction(()=>{$('custom-css').value=config.custom_css;});
  document.querySelectorAll('[data-refresh]').forEach(button=>button.onclick=async()=>{
    if(busy || composing)return;
    const part=button.dataset.refresh;
    if(!confirm(part==='profile'?'读取当前履历文字（保留当前简介）？此操作可撤销。':'替换服务端资源后不能撤销，并会清空撤销/重做记录。继续？'))return;
    commit();freeze(true);
    try {
      await ready;revision++;
      const data=await (await api('refresh',{part})).json();spec=data.spec;changed();bookmark={id:selectedId,mode:'object'};
      if(part==='profile')history.commit(state());else history.reset(state());
      displayControls();await install(data.html,bookmark);
    } catch(exc){error(exc.message);}finally{freeze(false);}
  });
  $('draft-photo').onchange=async()=>{
    const file=$('draft-photo').files[0];if(!file || busy || composing)return;
    if(!confirm('替换照片后不能撤销，并会清空撤销/重做记录。继续？')){$('draft-photo').value='';return;}
    commit();freeze(true);
    try {
      await ready;revision++;
      const form=new FormData();form.append('photo',file);form.append('revision',revision);
      const response=await fetch(`/api/drafts/${config.draft_id}/photo`,{method:'POST',body:form});
      if(!response.ok)throw new Error((await response.json()).errors.join('；'));
      spec.show_photo=true;changed();history.reset(state());displayControls();await render();
    }catch(exc){error(exc.message);}finally{freeze(false);}
  };
  $('save').onclick=async()=>{
    if(busy || composing)return;commit();freeze(true);
    try{await ready;error();const result=await (await api('save')).json();dirty=false;window.location.assign(result.url);}
    catch(exc){error(exc.message);}finally{freeze(false);}
  };
  $('export').onclick=async()=>{
    if(busy || composing)return;commit();freeze(true);
    try{await ready;const response=await api('export'),url=URL.createObjectURL(await response.blob());const link=document.createElement('a');link.href=url;link.download=`${config.draft_id}-draft.html`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
    catch(exc){error(exc.message);}finally{freeze(false);}
  };
  $('print').onclick=async()=>{if(busy || composing)return;commit();
    try{await ready;const html=await (await api('export')).text();await install(html,null);await ResumePreview.print(frame,$('layout-status'));await scheduleRender();}catch(exc){error(exc.message);}
  };
  let leaveUrl='';
  document.addEventListener('click',e=>{const link=e.target.closest('a[href]');if(!dirty || !link || link.target==='_blank' || e.ctrlKey || e.metaKey)return;e.preventDefault();leaveUrl=link.href;$('leave-dialog').showModal();});
  $('keep-editing').onclick=()=>$('leave-dialog').close();$('leave-draft').onclick=()=>{dirty=false;window.location.assign(leaveUrl);};
  window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
  displayControls();scheduleRender();
})();
