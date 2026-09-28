const {test} = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const {removeAtPath} = require(path.join(__dirname, '../static/js/editor-model.js'));

test('removes a bullet without changing its siblings', () => {
  const spec = {experiences:[{bullets:[{text:'一'}, {text:'二'}]}]};
  removeAtPath(spec, 'experiences.0.bullets.0');
  assert.deepEqual(spec.experiences[0].bullets, [{text:'二'}]);
});

test('removes whole experience and skill items', () => {
  const spec = {experiences:[{id:1}, {id:2}], skills:[{name:'Python'}, {name:'SQL'}]};
  removeAtPath(spec, 'experiences.1');
  removeAtPath(spec, 'skills.0');
  assert.deepEqual(spec, {experiences:[{id:1}], skills:[{name:'SQL'}]});
});

test('rejects paths that do not point to an array item', () => {
  assert.throws(() => removeAtPath({profile:{name:'x'}}, 'profile.name'));
});

const {addExperience, setSections} = require('../static/js/editor-model.js');
function canvasSpec() {
  return {experiences: [], section_order: [], layout: {version: 1, sections: ['education','experience','projects','skills'].map(section => ({section, canvas_id: section, hidden: true, items: []}))}};
}
test('new experience restores section; deep copy has independent IDs and content', () => {
  const spec = canvasSpec();
  const first = addExperience(spec);
  assert.deepEqual(spec.experiences[0], {
    organization:'', title:'', date:'', location:'',
    bullets:[{text:'', evidence_ids:[], canvas_id:spec.experiences[0].bullets[0].canvas_id}],
    canvas_id:first,
  });
  spec.experiences[0].bullets[0].evidence_ids = ['provenance'];
  const copy = addExperience(spec, first);
  assert.notEqual(first, copy);
  assert.notEqual(spec.experiences[0].bullets[0].canvas_id, spec.experiences[1].bullets[0].canvas_id);
  spec.experiences[1].bullets[0].text = '人工副本';
  assert.notEqual(spec.experiences[0].bullets[0].text, '人工副本');
  assert.deepEqual(spec.experiences[1].bullets[0].evidence_ids, ['provenance']);
  assert.deepEqual(spec.section_order, ['experience']);
  assert.deepEqual(spec.layout.sections[1].items.map(n => n.canvas_id), [first, copy]);
  removeAtPath(spec, 'experiences.0.bullets.0');
  assert.deepEqual(spec.layout.sections[1].items[0].bullets, []);
  removeAtPath(spec, 'experiences.0');
  assert.deepEqual(spec.layout.sections[1].items.map(n => n.canvas_id), [copy]);
});
test('new skills carry an optional description through copy and keep provenance',()=>{
 const spec=completeSpec(),id=M.addObject(spec,'skills');
 assert.equal(M.locate(spec,id).item.description,'');
 M.locate(spec,id).item.name='SQL';M.locate(spec,id).item.description='用于周度指标整理';
 const copy=M.pasteObject(spec,M.copyObject(spec,id),id),copied=M.locate(spec,copy).item;
 assert.equal(copied.name,'SQL');assert.equal(copied.description,'用于周度指标整理');
 assert.notEqual(copy,id);assert.deepEqual(copied.evidence_ids,[]);
});
test('section controls mutate layout; invalid selection is a no-op', () => {
  const spec = canvasSpec();
  setSections(spec, ['skills','education']);
  assert.deepEqual(spec.layout.sections.filter(s => !s.hidden).map(s => s.section), ['skills','education']);
  const before = JSON.stringify(spec);
  assert.throws(() => addExperience(spec, 'missing'));
  assert.throws(() => setSections(spec, ['skills','skills']));
  assert.equal(JSON.stringify(spec), before);
});

const M=require('../static/js/editor-model.js');
function completeSpec() {return {...canvasSpec(), education:[],projects:[],skills:[]};}
test('all repeated object kinds copy independently; clipboard survives source deletion',()=>{
 const spec=completeSpec();
 for(const kind of ['education','experience','projects','skills']) {
  const id=M.addObject(spec,kind), original=M.locate(spec,id), clipboard=M.copyObject(spec,id);
  const copied=M.pasteObject(spec,clipboard,id);
  assert.notEqual(copied,id);
  assert.notEqual(M.locate(spec,copied).item,original.item);
  if(original.item.bullets) assert.notEqual(M.locate(spec,copied).item.bullets[0].canvas_id,original.item.bullets[0].canvas_id);
  M.removeObject(spec,id);assert.ok(M.pasteObject(spec,clipboard));
 }
 const all=M.objects(spec).map(o=>o.id);assert.equal(new Set(all).size,all.length);
 const entry=spec.experiences[0],bullet=entry.bullets[0].canvas_id,clip=M.copyObject(spec,bullet);
 M.removeObject(spec,entry.canvas_id);
 assert.throws(()=>M.pasteObject(spec,clip));
 assert.ok(M.pasteObject(spec,clip,spec.projects[0].canvas_id));
});
test('moving bullets across entries updates both parents; invalid moves preserve state',()=>{
 const spec=completeSpec(),a=M.addObject(spec,'experience'),b=M.addObject(spec,'projects');
 const bullet=M.locate(spec,a).item.bullets[0].canvas_id;
 M.moveObject(spec,bullet,b);
 assert.equal(M.locate(spec,a).item.bullets.length,0);
 assert.equal(M.locate(spec,bullet).parentId,b);
 assert.ok(M.locate(spec,b).node.bullets.includes(bullet));
 const before=JSON.stringify(spec);
 assert.throws(()=>M.moveObject(spec,a,b));assert.equal(JSON.stringify(spec),before);
 M.stepObject(spec,bullet,-1);assert.equal(M.locate(spec,b).item.bullets[0].canvas_id,bullet);
});
test('entry/section width constraints and movement use layout order',()=>{
 const spec=completeSpec(),a=M.addObject(spec,'education'),b=M.addObject(spec,'education');
 M.resizeObject(spec,a,6);M.moveObject(spec,b,a,false);
 assert.deepEqual(spec.education.map(e=>e.canvas_id),[b,a]);
 assert.equal(M.locate(spec,a).node.span,6);
 for(const width of [5,13,6.5,'6'])assert.throws(()=>M.resizeObject(spec,a,width));
 M.resizeObject(spec,spec.layout.sections[0].canvas_id,7);
 M.resetLayout(spec);assert.equal(M.locate(spec,a).node.span,undefined);
});
test('one history transaction restores content, IDs, width, CSS; edit after undo clears redo',()=>{
 const spec=completeSpec();const h=new M.History({spec,custom_css:'',selection:null});
 const id=M.addObject(spec,'experience');h.commit({spec,custom_css:'',selection:{id}});
 M.resizeObject(spec,id,6);h.commit({spec,custom_css:'body {color: red}',selection:{id}});
 const previous=h.undo();assert.equal(previous.spec.experiences[0].canvas_id,id);assert.equal(previous.custom_css,'');
 assert.equal(M.locate(h.redo().spec,id).node.span,6);
 const branch=h.undo();branch.spec.experiences[0].title='中文一次输入';h.commit(branch);assert.equal(h.future.length,0);
 assert.equal(h.commit(branch),false);
 h.reset(branch);assert.equal(h.past.length,0);
});
test('history retains stable field bookmark and selection direction across undo redo',()=>{
 const spec=completeSpec();const h=new M.History({spec,custom_css:'',selection:{id:'entry',field:'title',anchor:2,focus:2,mode:'text'}});
 spec.profile={name:'改写'};h.commit({spec,custom_css:'',selection:{id:'entry',field:'title',anchor:2,focus:8,mode:'text'}});
 const undo=h.undo();assert.deepEqual(undo.selection,{id:'entry',field:'title',anchor:2,focus:2,mode:'text'});
 const redo=h.redo();assert.deepEqual(redo.selection,{id:'entry',field:'title',anchor:2,focus:8,mode:'text'});
});
