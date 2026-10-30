const test=require('node:test');
const assert=require('node:assert/strict');
const V=require('../static/view-model.js');
const cameras=[{id:'front'},{id:'yard'}];
const view=(cells=[],columns=2)=>({format:'vwshub.view',version:1,columns,cells});

test('valid imported view preserves camera order, stream and explicit blank cells',()=>{
  const input=view([{camera_id:'yard',stream:'main'},null,{camera_id:'front',stream:'sub'}],3);
  const output=V.normalize(input,cameras);
  assert.deepEqual(output,{...input,version:2,layout:"9",unavailable:0});
  assert.notStrictEqual(output.cells[0],input.cells[0]);
});

test('a camera hidden by current user scope becomes a blank cell instead of being attached',()=>{
  const output=V.normalize(view([{camera_id:'front',stream:'main'},{camera_id:'private-recorder',stream:'sub'},null]),[{id:'front'}]);
  assert.deepEqual(output.cells,[{camera_id:'front',stream:'main'},null,null]);
  assert.equal(output.unavailable,1);
  assert.ok(!JSON.stringify(output).includes('private-recorder'));
});

test('all unavailable cameras remain empty without shifting the layout positions',()=>{
  const output=V.normalize(view([{camera_id:'front',stream:'main'},null,{camera_id:'yard',stream:'sub'}]),[]);
  assert.deepEqual(output.cells,[null,null,null]);assert.equal(output.unavailable,2);
});

test('empty imported view is a valid intentionally blank monitor',()=>{
  assert.deepEqual(V.normalize(view([],4),cameras).cells,[]);
});

test('the exact 256-cell limit is accepted but a larger file is rejected',()=>{
  assert.equal(V.normalize(view(Array(256).fill(null)),cameras).cells.length,256);
  assert.throws(()=>V.normalize(view(Array(257).fill(null)),cameras),/Некорректный/);
});

for(const bad of [null,undefined,'not an object',42,[],{}, {format:'other',version:1,columns:2,cells:[]},{format:'vwshub.view',version:2,columns:2,cells:[]},view([],5),view([],0),view([],'2'),{...view(),cells:{} }]){
  test('invalid schema cannot replace a monitor: '+JSON.stringify(bad),()=>assert.throws(()=>V.normalize(bad,cameras),/Некорректный/));
}

for(const cell of [{},{camera_id:7,stream:'main'},{camera_id:'x'.repeat(151),stream:'main'},{camera_id:'front',stream:'third'},false,[]]){
  test('invalid cell is rejected before loading a stream: '+JSON.stringify(cell),()=>assert.throws(()=>V.normalize(view([cell]),cameras),/Некорректная/));
}

test('serialized view contains only portable IDs/streams, never URLs, passwords or internal UIDs',()=>{
  const output=V.serialize(2,[{uid:91,camera_id:'front',stream:'main',password:'sensitive',ip:'192.0.2.1',url:'rtsp://credentials'},null,{camera_id:'yard',stream:'invalid'}]);
  assert.deepEqual(output,{...view([{camera_id:'front',stream:'main'},null,{camera_id:'yard',stream:'sub'}]),version:2,layout:"4"});
  assert.ok(!/sensitive|192\.0\.2|rtsp|uid|password/.test(JSON.stringify(output)));
});

test('normalization ignores untrusted extra keys and JSON prototype payloads',()=>{
  const input=JSON.parse('{"format":"vwshub.view","version":1,"columns":2,"cells":[{"camera_id":"front","stream":"main","__proto__":{"administrator":true},"password":"secret"}],"__proto__":{"administrator":true},"constructor":{"prototype":{"administrator":true}},"credentials":"secret"}');
  const result=V.normalize(input,cameras);
  assert.deepEqual(result,{...view([{camera_id:'front',stream:'main'}]),version:2,layout:'4',unavailable:0});
  assert.equal(Object.prototype.administrator,undefined);
  assert.equal(result.administrator,undefined);
  assert.equal(Object.hasOwn(result,'__proto__'),false);
  assert.equal(Object.hasOwn(result.cells[0],'password'),false);
});

test('export/import round trip retains duplicate camera tiles and blank positions',()=>{
  const cells=[{camera_id:'front',stream:'main'},null,{camera_id:'front',stream:'sub'},null];
  const output=V.normalize(JSON.parse(JSON.stringify(V.serialize(4,cells))),cameras);
  assert.equal(output.columns,4);assert.deepEqual(output.cells,cells);assert.equal(output.unavailable,0);
});

for(const [count,expected] of [[1,'1'],[4,'4'],[5,'6'],[6,'6'],[7,'8'],[8,'8'],[9,'9'],[10,'16'],[17,'25'],[26,'36'],[37,'64'],[64,'64'],[65,'64'],[256,'64']])
  test('automatic wall capacity fits '+count+' cameras',()=>assert.equal(V.fit(count),expected));
for(const layout of V.layouts)test('every VMS layout survives export/import: '+layout.id,()=>{
  const result=V.normalize(V.serialize(layout.id,[{camera_id:'front',stream:'main'}]),cameras);
  assert.equal(result.layout,layout.id);assert.equal(result.columns,layout.columns);
});
test('digital pan clamps to actual image bounds including letterboxing',()=>{
  const p=V.pan(2,1000,1000,400,400,1600,900);
  assert.equal(p.zoom,2);assert.equal(p.x,200);assert.equal(p.y,25);
  const reset=V.pan(1,p.x,p.y,400,400,1600,900);
  assert.ok(reset.x===0&&reset.y===0);
});

test('large version 2 views retain all 4096 positions while legacy views keep their original bound',()=>{
 const cells=Array(4096).fill(null);cells[4095]={camera_id:'yard',stream:'sub'};
 const result=V.normalize(V.serialize('64',cells),cameras);
 assert.equal(result.cells.length,4096);assert.equal(result.cells[4095].camera_id,'yard');
 assert.throws(()=>V.serialize('64',Array(4097).fill(null)));
 assert.equal(V.fit(4096),'64');
});

test('independent live consumers work without randomUUID on LAN HTTP',()=>{
 const crypto=require('node:crypto').webcrypto;
 const source={getRandomValues:crypto.getRandomValues.bind(crypto)};
 assert.equal(source.randomUUID,undefined);
 const first=V.consumerId(source),second=V.consumerId(source);
 assert.match(first,/^[0-9a-f]{32}$/);assert.match(second,/^[0-9a-f]{32}$/);
 assert.notEqual(first,second);
});
