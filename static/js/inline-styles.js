(function(root,factory){const api=factory();if(typeof module==='object' && module.exports)module.exports=api;else root.ResumeInlineStyles=api;})(globalThis,function(){
  const same=(s,id,field)=>s.object_id===id && s.field===field;
  function canonical(styles){
    const sorted=styles.filter(s=>s.start<s.end).sort((a,b)=>a.object_id.localeCompare(b.object_id)||a.field.localeCompare(b.field)||a.start-b.start),result=[];
    for(const s of sorted){const last=result.at(-1);if(last && same(last,s.object_id,s.field) && last.end===s.start && last.font_size===s.font_size && last.cjk_font===s.cjk_font)last.end=s.end;else result.push({...s});}
    return result;
  }
  function apply(spec,id,field,start,end,value,property='font_size'){
    if(start===end)return;
    if(!Number.isInteger(start)||!Number.isInteger(end)||start<0||start>end)throw new Error('选区无效');
    if(!['font_size','cjk_font'].includes(property))throw new Error('不支持的行内样式');
    if(value!==null && (property==='font_size'?(!Number.isFinite(value)||value<8||value>24||value*2%1):!['songti','heiti','kaiti'].includes(value)))throw new Error('无效字号或中文字体');
    const current=(spec.inline_styles || []).filter(s=>same(s,id,field));
    const points=[...new Set([start,end,...current.flatMap(s=>[s.start,s.end])])].sort((a,b)=>a-b);
    const out=(spec.inline_styles || []).filter(s=>!same(s,id,field));
    for(let i=0;i<points.length-1;i++){
      const a=points[i],b=points[i+1],prior=current.find(s=>s.start<=a && s.end>=b);
      const run={...(prior || {object_id:id,field}),start:a,end:b};
      if(a>=start && b<=end){if(value===null)delete run[property];else run[property]=value;}
      if('font_size' in run || 'cjk_font' in run)out.push(run);
    }
    spec.inline_styles=canonical(out);
  }
  function edit(spec,id,field,oldText,newText){
    const a=Array.from(oldText),b=Array.from(newText);let start=0,suffix=0;
    while(start<a.length && start<b.length && a[start]===b[start])start++;
    while(suffix<a.length-start && suffix<b.length-start && a[a.length-1-suffix]===b[b.length-1-suffix])suffix++;
    const end=a.length-suffix,delta=b.length-a.length,out=[];
    for(const s of spec.inline_styles || []){
      if(!same(s,id,field)){out.push(s);continue;}
      if(s.end<=start)out.push(s);
      else if(s.start>=end)out.push({...s,start:s.start+delta,end:s.end+delta});
      else {if(s.start<start)out.push({...s,end:start});if(s.end>end)out.push({...s,start:end+delta,end:s.end+delta});}
    }
    spec.inline_styles=canonical(out);
  }
  return {apply,edit,canonical};
});
