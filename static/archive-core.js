/* Pure archive calculations; shared by the browser and node:test. Times are camera-local. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.VMSArchiveCore = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const clamp = (n, min, max) => Math.max(min, Math.min(max, n));
  function time(value) {
    if (typeof value === 'number') return Number.isFinite(value) ? value : null;
    if (typeof value !== 'string') return null;
    // Reject impossible dates instead of letting Date roll February 31 into March.
    const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?$/.exec(value);
    if (!m) return null;
    const [y, mo, d, h, mi, sec] = [m[1],m[2],m[3],m[4],m[5],m[6]||0].map(Number);
    const date = new Date(y, mo - 1, d, h, mi, Number(sec));
    if (date.getFullYear() !== y || date.getMonth() !== mo - 1 || date.getDate() !== d || date.getHours() !== h || date.getMinutes() !== mi || date.getSeconds() !== Number(sec)) return null;
    return date.getTime();
  }
  function local(ms, separator = 'T') {
    const d = new Date(ms), pad = n => String(n).padStart(2, '0');
    if (!Number.isFinite(d.getTime())) return '';
    return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}${separator}${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  }
  function dayRange(day) {
    const start = time(day + 'T00:00:00');
    if (start === null) return null;
    const end = new Date(start); end.setDate(end.getDate()+1);
    return {start, end:end.getTime()};
  }
  function normalize(records, start, end) {
    if (!Array.isArray(records) || !Number.isFinite(start) || !Number.isFinite(end) || end <= start) return [];
    const intervals = records.flatMap(r => r && typeof r === 'object' ? (Array.isArray(r.Intervals) ? r.Intervals : [r]) : [])
      .filter(r=>r&&typeof r==='object')
      .map(r => ({start:time(r.BeginTime), end:time(r.EndTime)}))
      .filter(r => r.start !== null && r.end !== null && r.end > r.start && r.end > start && r.start < end)
      .map(r => ({start:Math.max(start,r.start), end:Math.min(end,r.end)}))
      .sort((a,b) => a.start-b.start || a.end-b.end);
    const merged = [];
    for (const interval of intervals) {
      const last=merged.at(-1);
      if (last && interval.start <= last.end) last.end=Math.max(last.end,interval.end);
      else merged.push({...interval});
    }
    return merged;
  }
  function intervalAt(intervals, ms) { return intervals.find(r => r.start <= ms && ms < r.end) || null; }
  function adjacent(intervals, ms, direction) {
    if (direction < 0) return [...intervals].reverse().find(r => r.start < ms - 500) || null;
    const current=intervalAt(intervals,ms);
    return intervals.find(r => r.start >= (current ? current.end : ms)) || null;
  }
  function selection(a,b,start,end) {
    if (![a,b,start,end].every(Number.isFinite) || end-start < 1000) return null;
    let left=clamp(Math.min(a,b),start,end),right=clamp(Math.max(a,b),start,end);
    if (right-left < 1000) { right=Math.min(end,left+1000); left=Math.max(start,right-1000); }
    return {start:Math.max(start,Math.floor(left/1000)*1000),end:Math.min(end,Math.ceil(right/1000)*1000)};
  }
  function coverage(intervals, selection) {
    if (!selection || selection.end <= selection.start) return 0;
    // normalize also protects callers from overlapping/duplicate records.
    const clean=normalize(intervals.map(r=>({BeginTime:r.start,EndTime:r.end})),selection.start,selection.end);
    return clean.reduce((sum,r)=>sum+r.end-r.start,0);
  }
  function viewWindow(start,end,span,anchor=(start+end)/2,ratio=.5) {
    const width=clamp(span,Math.min(1000,end-start),end-start);
    const left=clamp(anchor-width*clamp(ratio,0,1),start,end-width);
    return {start:left,end:left+width};
  }
  function zoomPoint(old,next,x,y,px,py,width,height) {
    const scale=clamp(next,1,8),mult=scale/old;
    return {scale,x:clamp(px-(px-x)*mult,-width*(scale-1)/2,width*(scale-1)/2),y:clamp(py-(py-y)*mult,-height*(scale-1)/2,height*(scale-1)/2)};
  }
  return {clamp,time,local,dayRange,normalize,intervalAt,adjacent,selection,coverage,viewWindow,zoomPoint};
});
