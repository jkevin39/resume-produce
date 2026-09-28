(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.ResumeEditorModel = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  function removeAtPath(value, path) {
    const keys = String(path).split('.');
    let cursor = value;
    for (const key of keys.slice(0, -1)) {
      cursor = Array.isArray(cursor) ? cursor[Number(key)] : cursor[key];
      if (cursor == null) throw new Error(`无法删除不存在的路径：${path}`);
    }
    const index = Number(keys[keys.length - 1]);
    if (!Array.isArray(cursor) || !Number.isInteger(index) || index < 0 || index >= cursor.length) {
      throw new Error(`删除路径必须指向数组项：${path}`);
    }
    const removed = cursor.splice(index, 1)[0];
    if (value.layout) {
      for (const section of value.layout.sections) {
        section.items = section.items.filter(n => n.canvas_id !== removed.canvas_id);
        for (const node of section.items) {
          if (node.bullets) node.bullets = node.bullets.filter(id => id !== removed.canvas_id);
        }
      }
    }
    return value;
  }
  const newId = () => 'canvas_' + globalThis.crypto.randomUUID().replaceAll('-', '');
  function setSections(spec, order) {
    const sections = spec.layout.sections;
    if (new Set(order).size !== order.length || order.some(name => !sections.some(s => s.section === name))) {
      throw new Error('板块顺序包含重复或未知板块');
    }
    // Hidden sections retain their slots; visible slots follow the requested order.
    const visible = order.map(name => sections.find(s => s.section === name));
    let index = 0;
    spec.layout.sections = sections.map(s => order.includes(s.section) ? visible[index++] : s);
    spec.layout.sections.forEach(s => { s.hidden = !order.includes(s.section); });
    spec.section_order = [...order];
  }
  function addExperience(spec, sourceId = null) {
    const section = spec.layout.sections.find(s => s.section === 'experience');
    const index = sourceId === null ? spec.experiences.length - 1 : spec.experiences.findIndex(e => e.canvas_id === sourceId);
    if (sourceId !== null && index < 0) throw new Error('请先选择一段经历');
    const item = sourceId === null ? {
      organization: '', title: '', date: '', location: '',
      bullets: [{text: '', evidence_ids: []}]
    } : JSON.parse(JSON.stringify(spec.experiences[index]));
    item.canvas_id = newId();
    item.bullets.forEach(bullet => { bullet.canvas_id = newId(); });
    spec.experiences.splice(index + 1, 0, item);
    section.items.splice(index + 1, 0, {canvas_id: item.canvas_id, bullets: item.bullets.map(b => b.canvas_id)});
    section.hidden = false;
    spec.section_order = spec.layout.sections.filter(s => !s.hidden).map(s => s.section);
    return item.canvas_id;
  }
  const clone = value => JSON.parse(JSON.stringify(value));
  const sectionKeys = {education:'education', experience:'experiences', projects:'projects', skills:'skills',custom:'custom_bullets'};
  const kindOf=s=>s.kind || s.section;
  function objects(spec) {
    const result=[];
    for (const section of spec.layout.sections) {
      const kind=kindOf(section),array=spec[sectionKeys[kind]] || [];
      result.push({id:section.canvas_id,kind:'section',item:section,node:section,section,parentId:null,array:spec.layout.sections,nodes:spec.layout.sections});
      for (const node of section.items) {
        const item=array.find(x=>x.canvas_id===node.canvas_id);
        result.push({id:item.canvas_id,kind,item,node,section,parentId:section.canvas_id,array,nodes:section.items});
        for(const bullet of item.bullets || []) result.push({id:bullet.canvas_id,kind:'bullet',item:bullet,node:null,section,parentId:item.canvas_id,array:item.bullets,nodes:node.bullets});
      }
    }
    return result;
  }
  const locate=(spec,id)=>objects(spec).find(o=>o.id===id);
  const refId=n=>typeof n==='string'?n:n.canvas_id;
  function project(spec) {
    for(const [kind,key] of Object.entries(sectionKeys)) {
      if(!spec[key])continue;
      const index=new Map(spec[key].map(x=>[x.canvas_id,x]));
      spec[key]=spec.layout.sections.filter(s=>kindOf(s)===kind).flatMap(s=>s.items.map(n=>{
        const item=index.get(n.canvas_id);
        if(n.bullets){const bullets=new Map(item.bullets.map(b=>[b.canvas_id,b]));item.bullets=n.bullets.map(id=>bullets.get(id));}
        return item;
      }));
    }
    spec.section_order=[...new Set(spec.layout.sections.filter(s=>!s.hidden && kindOf(s)!=='custom').map(kindOf))];
    if(spec.inline_styles){const ids=new Set(['profile',...objects(spec).map(o=>o.id)]);spec.inline_styles=spec.inline_styles.filter(s=>ids.has(s.object_id));}
    return spec;
  }
  function copyObject(spec,id) {
    const obj=locate(spec,id);if(!obj)throw new Error('请选择画布对象');
    const content=obj.kind==='section'?obj.section.items.map(n=>clone(locate(spec,n.canvas_id).item)):null;
    const ids=new Set([id]);
    const collect=item=>{ids.add(item.canvas_id);for(const b of item.bullets || [])ids.add(b.canvas_id);};
    if(content)content.forEach(collect);else collect(obj.item);
    return clone({kind:obj.kind,item:obj.item,node:obj.node,content,sourceId:id,parentId:obj.parentId,index:obj.nodes.findIndex(n=>refId(n)===id),styles:(spec.inline_styles || []).filter(s=>ids.has(s.object_id))});
  }
  function destination(spec,kind,targetId,after=true) {
    const target=locate(spec,targetId);if(!target)throw new Error('请选择兼容的目标对象');
    if(kind==='section')return {array:spec.layout.sections,nodes:spec.layout.sections,index:spec.layout.sections.indexOf(target.section)+(after?1:0),section:target.section};
    if(target.kind===kind)return {array:target.array,nodes:target.nodes,index:target.nodes.findIndex(n=>refId(n)===target.id)+(after?1:0),section:target.section};
    if(kind==='bullet' && ['experience','projects'].includes(target.kind))return {array:target.item.bullets,nodes:target.node.bullets,index:target.node.bullets.length,section:target.section};
    if(target.kind==='section' && kindOf(target.section)===kind)return {array:spec[sectionKeys[kind]],nodes:target.section.items,index:target.section.items.length,section:target.section};
    throw new Error('此对象不能放入所选容器');
  }
  function pasteObject(spec,clipboard,targetId=null) {
    if(!clipboard)throw new Error('请先复制一个画布对象');
    let dest;
    if(clipboard.kind==='section') {
      const target=locate(spec,targetId) || locate(spec,clipboard.sourceId);
      dest={array:spec.layout.sections,nodes:spec.layout.sections,index:target?spec.layout.sections.indexOf(target.section)+1:spec.layout.sections.length};
    } else if(targetId)dest=destination(spec,clipboard.kind,targetId);
    else if(locate(spec,clipboard.sourceId))dest=destination(spec,clipboard.kind,clipboard.sourceId);
    else {dest=destination(spec,clipboard.kind,clipboard.parentId);dest.index=Math.min(clipboard.index || 0,dest.nodes.length);}
    const item=clone(clipboard.item),node=clone(clipboard.node),mapping=new Map();
    const assign=item=>{const old=item.canvas_id;item.canvas_id=newId();if(old)mapping.set(old,item.canvas_id);for(const b of item.bullets || [])assign(b);};
    assign(item);
    if(clipboard.kind==='section') {
      const content=clone(clipboard.content || []);content.forEach(assign);
      item.items=item.items.map(n=>({...n,canvas_id:mapping.get(n.canvas_id),...(n.bullets?{bullets:n.bullets.map(id=>mapping.get(id))}:{})}));
      spec[sectionKeys[kindOf(item)]].push(...content);item.hidden=false;
      dest.array.splice(dest.index,0,item);
    } else {
      if(node){node.canvas_id=item.canvas_id;if(item.bullets)node.bullets=item.bullets.map(b=>b.canvas_id);}
      dest.array.push(item);dest.nodes.splice(dest.index,0,node || item.canvas_id);dest.section.hidden=false;
    }
    if(clipboard.styles?.length)spec.inline_styles=[...(spec.inline_styles || []),...clipboard.styles.map(s=>({...s,object_id:mapping.get(s.object_id)}))];
    project(spec);return item.canvas_id;
  }
  function addObject(spec,kind,parentId=null) {
    if(kind==='section') {
      const section={canvas_id:newId(),kind:'custom',section:'custom',title:'',hidden:false,span:12,items:[]};
      spec.custom_bullets ||= [];spec.layout.sections.push(section);addObject(spec,'custom',section.canvas_id);return section.canvas_id;
    }
    const empty={education:{school:'',degree:'',major:'',date:'',details:''},experience:{organization:'',title:'',date:'',location:'',bullets:[{text:'',evidence_ids:[]}]},projects:{organization:'',title:'',date:'',location:'',bullets:[{text:'',evidence_ids:[]}]},bullet:{text:'',evidence_ids:[]},custom:{text:'',evidence_ids:[]},skills:{name:'',description:'',evidence_ids:[]}};
    if(kind==='bullet' && kindOf(locate(spec,parentId)?.section || {})==='custom')kind='custom';
    if(!empty[kind])throw new Error('不支持此对象类型');
    const section=spec.layout.sections.find(s=>kindOf(s)===kind);
    if(!parentId && section)parentId=section.canvas_id;
    const item=empty[kind],node=kind==='bullet'?null:{canvas_id:'new',...(item.bullets?{bullets:[]}:{})};
    return pasteObject(spec,{kind,item,node},parentId);
  }
  function removeObject(spec,id) {
    const obj=locate(spec,id);if(!obj)return;
    if(obj.kind==='section')obj.section.hidden=true;
    else {obj.array.splice(obj.array.indexOf(obj.item),1);obj.nodes.splice(obj.nodes.findIndex(n=>refId(n)===id),1);}
    project(spec);
  }
  function moveObject(spec,id,targetId,after=true) {
    if(id===targetId)return;
    const obj=locate(spec,id);if(!obj)throw new Error('移动对象不存在');
    const dest=destination(spec,obj.kind,targetId,after),index=obj.nodes.findIndex(n=>refId(n)===id);
    if(obj.nodes===dest.nodes && index<dest.index)dest.index--;
    const ref=obj.nodes.splice(index,1)[0];dest.nodes.splice(dest.index,0,ref);
    if(obj.array!==dest.array){obj.array.splice(obj.array.indexOf(obj.item),1);dest.array.push(obj.item);}
    if(obj.kind!=='section')dest.section.hidden=false;
    project(spec);
  }
  function stepObject(spec,id,direction) {
    const obj=locate(spec,id);if(!obj)return;
    const index=obj.nodes.findIndex(n=>refId(n)===id),target=obj.nodes[index+direction];
    if(target)moveObject(spec,id,refId(target),direction>0);
  }
  function resizeObject(spec,id,span) {
    const obj=locate(spec,id);
    if(!obj || !['section','education','experience','projects'].includes(obj.kind)) throw new Error('此对象宽度随父容器');
    if(!Number.isInteger(span) || span<6 || span>12) throw new Error('宽度须为 6–12 格（50%–100%）');
    obj.node.span=span;
  }
  function resetLayout(spec) {
    for(const s of spec.layout.sections) { delete s.span; for(const n of s.items) delete n.span; }
  }
  class History {
    constructor(state) { this.reset(state); }
    reset(state) { this.present=clone(state);this.past=[];this.future=[]; }
    rememberSelection(selection) { this.present.selection=clone(selection); }
    commit(state) {
      if(JSON.stringify([state.spec,state.custom_css])===JSON.stringify([this.present.spec,this.present.custom_css])) return false;
      this.past.push(this.present);this.present=clone(state);this.future=[];return true;
    }
    undo() { if(!this.past.length)return null;this.future.push(this.present);this.present=this.past.pop();return clone(this.present); }
    redo() { if(!this.future.length)return null;this.past.push(this.present);this.present=this.future.pop();return clone(this.present); }
  }

  return {removeAtPath, setSections, addExperience, objects, locate, project, copyObject, pasteObject, addObject, removeObject, moveObject, stepObject, resizeObject, resetLayout, History};
});
