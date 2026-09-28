const {test}=require('node:test'),assert=require('node:assert/strict');
const M=require('../static/js/editor-model.js'),I=require('../static/js/inline-styles.js');
const fresh=()=>({education:[],experiences:[],projects:[],skills:[],custom_bullets:[],layout:{version:2,sections:['education','experience','projects','skills'].map(kind=>({canvas_id:kind,kind,section:kind,title:kind,span:12,hidden:false,items:[]}))}});
test('deep section copies remap every descendant and style; duplicate kind moves preserve owners',()=>{
 const s=fresh(),a=M.addObject(s,'experience');const bullet=M.locate(s,a).item.bullets[0];bullet.text='甲😀乙';bullet.evidence_ids=['evidence'];
 I.apply(s,bullet.canvas_id,'text',1,2,14);
 const clip=M.copyObject(s,'experience'),copy=M.pasteObject(s,clip,'experience');
 const copied=M.locate(s,copy),entry=M.locate(s,copied.node.items[0].canvas_id);
 assert.notEqual(entry.id,a);assert.notEqual(entry.item.bullets[0].canvas_id,bullet.canvas_id);
 assert.equal(s.inline_styles[1].object_id,entry.item.bullets[0].canvas_id);assert.deepEqual(entry.item.bullets[0].evidence_ids,['evidence']);
 M.moveObject(s,a,copy);assert.equal(M.locate(s,'experience').node.items.length,0);assert.equal(copied.node.items.length,2);
 M.stepObject(s,a,-1);assert.equal(copied.node.items[0].canvas_id,a);
 M.removeObject(s,copy);assert.equal(copied.section.hidden,true);M.resizeObject(s,copy,6);
 // Clipboard is independent of its source tree, including after actual source removal.
 s.layout.sections=s.layout.sections.filter(x=>x.canvas_id!=='experience');M.project(s);
 assert.ok(M.pasteObject(s,clip));
 const ids=M.objects(s).map(o=>o.id);assert.equal(new Set(ids).size,ids.length);
});
test('custom title and bullets copy, hide and undo with complete independent content',()=>{
 const s=fresh(),section=M.addObject(s,'section'),bullet=s.custom_bullets[0].canvas_id;M.locate(s,bullet).item.text='自定义';
 M.locate(s,section).item.title='自定义';I.apply(s,section,'title',0,2,16);const h=new M.History({spec:s,custom_css:'',selection:{id:section}});
 const copy=M.pasteObject(s,M.copyObject(s,section),section);h.commit({spec:s,custom_css:'',selection:{id:copy}});
 assert.equal(s.custom_bullets.length,2);assert.equal(h.undo().spec.custom_bullets.length,1);assert.equal(h.redo().spec.custom_bullets.length,2);
 M.removeObject(s,bullet);assert.equal(M.locate(s,section).node.items.length,0);
});
test('Unicode edits split ranges; inserted plain text inherits no formatting; default clears only selection',()=>{
 const s={};I.apply(s,'p','text',0,3,12.5);I.edit(s,'p','text','甲😀乙','甲X😀乙');
 assert.deepEqual(s.inline_styles.map(x=>[x.start,x.end]),[[0,1],[2,4]]);
 I.apply(s,'p','text',2,3,null);assert.deepEqual(s.inline_styles.map(x=>[x.start,x.end]),[[0,1],[3,4]]);
 I.edit(s,'p','text','甲X😀乙','');assert.deepEqual(s.inline_styles,[]);
 assert.throws(()=>I.apply(s,'p','text',0,1,12.1));
});
test('font and size overlap independently; reset one property preserves the other',()=>{
 const s={};I.apply(s,'p','text',0,5,12);I.apply(s,'p','text',2,7,'heiti','cjk_font');
 assert.deepEqual(s.inline_styles.map(x=>[x.start,x.end,x.font_size,x.cjk_font]),[[0,2,12,undefined],[2,5,12,'heiti'],[5,7,undefined,'heiti']]);
 I.apply(s,'p','text',3,6,null,'cjk_font');assert.equal(s.inline_styles.find(x=>x.start===3).font_size,12);
 I.apply(s,'p','text',0,7,null);assert.ok(s.inline_styles.every(x=>!('font_size' in x)));
 assert.throws(()=>I.apply(s,'p','text',0,2,'Arial','cjk_font'));
 I.edit(s,'p','text','甲乙中文ABC','X甲乙中文ABC');assert.equal(s.inline_styles[0].start,3);
});
