/* Keyboard contract tests with isolated DOM adapters; no browser or device starts. */
'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {createDialogFocus}=require('../static/devices.js');

function fixture(){
  const listeners=[];
  const document={activeElement:null,addEventListener(type,callback,capture){listeners.push({type,callback,capture});},removeEventListener(type,callback,capture){const i=listeners.findIndex(x=>x.type===type&&x.callback===callback&&x.capture===capture);if(i>=0)listeners.splice(i,1);}};
  const node=(name,options={})=>({name,isConnected:true,disabled:false,hidden:false,...options,closest(){return this.hidden?{}:null;},getClientRects(){return this.hidden?[]:[{}];},focus(){if(this.isConnected&&!this.disabled)document.activeElement=this;}});
  const scope=(name,nodes)=>({name,isConnected:true,querySelectorAll:()=>nodes,contains:target=>target===document.activeElement&&nodes.includes(target)||nodes.includes(target),focus(){document.activeElement=this;}});
  function key(name,shiftKey=false){const event={key:name,shiftKey,defaultPrevented:false,stopped:false,preventDefault(){this.defaultPrevented=true;},stopPropagation(){this.stopped=true;}};for(const listener of [...listeners])if(listener.type==='keydown')listener.callback(event);return event;}
  return {document,node,scope,key,listeners};
}

test('hardware dialog traps both tab boundaries and re-enters from the obscured background',()=>{
  const f=fixture(),first=f.node('first'),middle=f.node('middle'),last=f.node('last'),outside=f.node('background');
  const controller=createDialogFocus(f.document);controller.push(f.scope('hardware',[first,middle,last]),()=>{});
  last.focus();assert.equal(f.key('Tab').defaultPrevented,true);assert.equal(f.document.activeElement,first);
  first.focus();assert.equal(f.key('Tab',true).defaultPrevented,true);assert.equal(f.document.activeElement,last);
  outside.focus();assert.equal(f.key('Tab').defaultPrevented,true);assert.equal(f.document.activeElement,first);
  middle.focus();assert.equal(f.key('Tab').defaultPrevented,false,'ordinary interior Tab remains native');
  controller.dispose();
});

test('disabled and hidden controls are excluded from the modal tab loop',()=>{
  const f=fixture(),disabled=f.node('disabled',{disabled:true}),hidden=f.node('hidden',{hidden:true}),enabled=f.node('enabled');
  const controller=createDialogFocus(f.document);controller.push(f.scope('hardware',[disabled,hidden,enabled]),()=>{});
  enabled.focus();f.key('Tab');assert.equal(f.document.activeElement,enabled);
  controller.dispose();
});

test('Escape cancels only the top confirmation, then returns focus to its trigger',async()=>{
  const f=fixture(),origin=f.node('device card'),trigger=f.node('reboot'),confirm=f.node('confirmation checkbox');
  const hardware=f.scope('hardware',[trigger]),confirmation=f.scope('confirmation',[confirm]);
  const controller=createDialogFocus(f.document);let mainClosed=0,confirmClosed=0;
  const main=controller.push(hardware,()=>{mainClosed++;hardware.isConnected=false;main.close();},origin);
  const child=controller.push(confirmation,()=>{confirmClosed++;confirmation.isConnected=false;child.close();},trigger);
  confirm.focus();const event=f.key('Escape');await Promise.resolve();
  assert.equal(event.defaultPrevented,true);assert.equal(event.stopped,true);
  assert.equal(confirmClosed,1);assert.equal(mainClosed,0);assert.equal(f.document.activeElement,trigger);
  f.key('Escape');await Promise.resolve();
  assert.equal(mainClosed,1);assert.equal(f.document.activeElement,origin);
  controller.dispose();
});

test('refresh/replacement does not focus removed controls and explicit close retains the original device card',async()=>{
  const f=fixture(),origin=f.node('device card'),oldClose=f.node('old close'),newClose=f.node('new close');
  const controller=createDialogFocus(f.document);
  const old=controller.push(f.scope('old hardware',[oldClose]),()=>{},origin);
  oldClose.focus();old.close(false);oldClose.isConnected=false;
  const current=controller.push(f.scope('new hardware',[newClose]),()=>{},origin);newClose.focus();
  await Promise.resolve();assert.equal(f.document.activeElement,newClose);
  current.close();await Promise.resolve();assert.equal(f.document.activeElement,origin);
  controller.dispose();
});

test('a detached confirmation trigger falls back to the remaining hardware dialog',async()=>{
  const f=fixture(),first=f.node('close'),trigger=f.node('removed action'),confirm=f.node('confirmation');
  const controller=createDialogFocus(f.document);controller.push(f.scope('hardware',[first,trigger]),()=>{});
  const child=controller.push(f.scope('confirmation',[confirm]),()=>{},trigger);confirm.focus();trigger.isConnected=false;
  child.close();await Promise.resolve();assert.equal(f.document.activeElement,first);
  controller.dispose();assert.equal(f.listeners.length,0);
  assert.equal(f.key('Escape').defaultPrevented,false,'disposed device views leave no keyboard interceptor');
});
