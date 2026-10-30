/* Archive behavior tests: no camera, DOM or network access. */
'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const core=require('../static/archive-core.js');
const at=value=>core.time(`2026-10-29T${value}`);
const record=(start,end)=>({BeginTime:`2026-10-29 ${start}`,EndTime:`2026-10-29 ${end}`});

test('minute input and second input identify the same camera-local instant',()=>{
  const minute=core.time('2026-10-29T12:34');
  assert.equal(minute,core.time('2026-10-29 12:34:00'));
  assert.equal(core.local(minute),'2026-10-29T12:34:00');
});

test('impossible calendar dates and clock values are rejected instead of rolled over',()=>{
  for(const value of ['2026-02-29T12:00','2026-02-31T12:00','2026-04-31T12:00','2026-13-01T12:00','2026-00-01T12:00','2026-10-00T12:00','2026-10-29T24:00','2026-10-29T12:60','2026-10-29T12:00:60','not-a-date',undefined,Infinity]) assert.equal(core.time(value),null,String(value));
  assert.notEqual(core.time('2024-02-29T12:00:00'),null);
});

test('local formatting preserves date and seconds when used for recorder requests',()=>{
  const ms=at('23:59:58');
  assert.equal(core.local(ms,' '),'2026-10-29 23:59:58');
  assert.equal(core.time(core.local(ms)),ms);
  assert.equal(core.local(NaN),'');
  assert.equal(core.time(0),0);
});

test('day range ends at next local midnight across month and leap-year boundaries',()=>{
  const endOfMonth=core.dayRange('2026-10-31');
  assert.equal(core.local(endOfMonth.start),'2026-10-31T00:00:00');
  assert.equal(core.local(endOfMonth.end),'2026-11-01T00:00:00');
  assert.equal(core.local(core.dayRange('2024-02-29').end),'2024-03-01T00:00:00');
  assert.equal(core.dayRange('2026-02-29'),null);
});

test('recording normalization preserves holes inside a grouped DVR result',()=>{
  const intervals=core.normalize([{...record('12:00:00','12:10:00'),Intervals:[record('12:00:00','12:02:00'),record('12:07:00','12:10:00')]}],at('11:00:00'),at('13:00:00'));
  assert.deepEqual(intervals,[{start:at('12:00:00'),end:at('12:02:00')},{start:at('12:07:00'),end:at('12:10:00')}]);
  assert.equal(core.intervalAt(intervals,at('12:04:00')),null);
});

test('malformed nested intervals cannot break the archive page',()=>{
  const data=[null,{},false,{Intervals:[null,undefined,'bad',{},record('12:00:00','12:01:00')]}];
  assert.deepEqual(core.normalize(data,at('11:00:00'),at('13:00:00')),[{start:at('12:00:00'),end:at('12:01:00')}]);
});

test('overlapping and duplicate records become a sorted union without changing real gaps',()=>{
  const original=[record('12:08:00','12:10:00'),record('12:00:00','12:04:00'),record('12:02:00','12:05:00'),record('12:00:00','12:04:00'),record('12:05:00','12:06:00')];
  const snapshot=JSON.stringify(original);
  assert.deepEqual(core.normalize(original,at('11:00:00'),at('13:00:00')),[{start:at('12:00:00'),end:at('12:06:00')},{start:at('12:08:00'),end:at('12:10:00')}]);
  assert.equal(JSON.stringify(original),snapshot,'DVR response is not mutated');
});

test('normalization clips to the loaded period and ignores empty/outside records',()=>{
  const result=core.normalize([record('11:59:00','12:02:00'),record('12:08:00','12:12:00'),record('12:03:00','12:03:00'),record('12:04:00','12:01:00'),record('13:00:00','13:05:00')],at('12:00:00'),at('12:10:00'));
  assert.deepEqual(result,[{start:at('12:00:00'),end:at('12:02:00')},{start:at('12:08:00'),end:at('12:10:00')}]);
  assert.deepEqual(core.normalize(null,0,10),[]);
  assert.deepEqual(core.normalize([],10,0),[]);
});

test('recording lookup uses exclusive ends so a gap is not treated as recorded',()=>{
  const intervals=[{start:1000,end:3000},{start:5000,end:7000}];
  assert.equal(core.intervalAt(intervals,1000),intervals[0]);
  assert.equal(core.intervalAt(intervals,2999),intervals[0]);
  assert.equal(core.intervalAt(intervals,3000),null);
  assert.equal(core.intervalAt(intervals,5000),intervals[1]);
  assert.equal(core.intervalAt(intervals,7000),null);
});

test('next recording jumps across a gap and does not restart the active interval',()=>{
  const intervals=[{start:1000,end:3000},{start:5000,end:7000},{start:9000,end:11000}];
  assert.equal(core.adjacent(intervals,1500,1),intervals[1]);
  assert.equal(core.adjacent(intervals,3000,1),intervals[1]);
  assert.equal(core.adjacent(intervals,8500,1),intervals[2]);
  assert.equal(core.adjacent(intervals,10000,1),null);
});

test('previous first returns the active recording start, then the preceding interval',()=>{
  const intervals=[{start:1000,end:3000},{start:5000,end:7000}];
  assert.equal(core.adjacent(intervals,6500,-1),intervals[1]);
  assert.equal(core.adjacent(intervals,5000,-1),intervals[0]);
  assert.equal(core.adjacent(intervals,4000,-1),intervals[0]);
  assert.equal(core.adjacent(intervals,1000,-1),null);
});

test('dragging backwards exports the same ordered interval as dragging forwards',()=>{
  assert.deepEqual(core.selection(7000,2000,0,10000),core.selection(2000,7000,0,10000));
  assert.deepEqual(core.selection(7000,2000,0,10000),{start:2000,end:7000});
});

test('a tiny drag becomes at least one second at either edge of the loaded period',()=>{
  assert.deepEqual(core.selection(0,100,0,10000),{start:0,end:1000});
  assert.deepEqual(core.selection(9900,10000,0,10000),{start:9000,end:10000});
  assert.equal(core.selection(100,200,0,999),null);
  assert.equal(core.selection(NaN,2000,0,10000),null);
});

test('export selection is bounded by loaded timestamps even when they are fractional seconds',()=>{
  for(const [first,last] of [[-5000,20000],[710,715],[1740,1745]]){
    const picked=core.selection(first,last,700,1750);
    assert.ok(picked.start>=700);
    assert.ok(picked.end<=1750);
    assert.ok(picked.end-picked.start>=1000);
  }
});

test('coverage reports real recorded milliseconds without counting duplicate footage twice',()=>{
  const intervals=[{start:0,end:4000},{start:2000,end:6000},{start:8000,end:10000},{start:8000,end:10000}];
  assert.equal(core.coverage(intervals,{start:1000,end:9000}),6000);
  assert.equal(core.coverage(intervals,{start:6000,end:8000}),0);
  assert.equal(core.coverage(intervals,{start:9500,end:11000}),500);
  assert.equal(core.coverage(intervals,null),0);
});

test('timeline zoom keeps the requested timestamp under the same cursor ratio',()=>{
  const window=core.viewWindow(0,10000,4000,3500,.25);
  assert.equal(window.end-window.start,4000);
  assert.equal(window.start+(window.end-window.start)*.25,3500);
});

test('timeline cannot pan outside loaded records, zoom below one second, or exceed the search period',()=>{
  assert.deepEqual(core.viewWindow(0,10000,4000,0,.5),{start:0,end:4000});
  assert.deepEqual(core.viewWindow(0,10000,4000,10000,.5),{start:6000,end:10000});
  assert.deepEqual(core.viewWindow(0,10000,100,5000),{start:4500,end:5500});
  assert.deepEqual(core.viewWindow(0,10000,20000),{start:0,end:10000});
  assert.deepEqual(core.viewWindow(0,500,100),{start:0,end:500});
});

test('digital zoom anchors the image point under the mouse instead of drifting to center',()=>{
  const zoomed=core.zoomPoint(1,2,0,0,50,25,400,200);
  assert.equal((50-zoomed.x)/zoomed.scale,50);
  assert.equal((25-zoomed.y)/zoomed.scale,25);
});

test('digital pan remains bounded and resetting zoom restores the entire frame',()=>{
  const zoomed=core.zoomPoint(1,20,0,0,1000,-1000,400,200);
  assert.equal(zoomed.scale,8);
  assert.ok(Math.abs(zoomed.x)<=400*(zoomed.scale-1)/2);
  assert.ok(Math.abs(zoomed.y)<=200*(zoomed.scale-1)/2);
  const reset=core.zoomPoint(8,.2,zoomed.x,zoomed.y,30,20,400,200);
  assert.equal(reset.scale,1);
  assert.ok(reset.x===0 && reset.y===0);
});

test('slider snaps gaps to nearest playable second and never the exclusive file end',()=>{
 const intervals=[{start:10000,end:20000},{start:40000,end:50000}];
 assert.equal(core.nearest(intervals,21000),19000);
 assert.equal(core.nearest(intervals,39000),40000);
 assert.equal(core.nearest(intervals,0),10000);
 assert.equal(core.nearest(intervals,99999),49000);
 assert.equal(core.nearest(intervals,15000),15000);
 assert.equal(core.nearest([],15000),null);
 assert.equal(core.nearest(intervals,NaN),null);
});
