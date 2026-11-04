'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

// Minimal DOM adapter exercises source tracking without a browser dependency.
function fixture() {
  const nodes=[], elements=[];
  const body={querySelectorAll:()=>elements};
  const document={body,documentElement:{},createTreeWalker:()=>{let index=0;return{nextNode:()=>nodes[index++]||null};}};
  const context={document,NodeFilter:{SHOW_TEXT:4},Intl,queueMicrotask};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/i18n.js'),'utf8'),context);
  const api=context.WVWI18n;
  api.setDictionary('ru',{'Камера':'Камера','Пользователь':'Пользователь','Соединение':'Соединение','Нет связи':'Нет связи'});
  api.setDictionary('en',{'Камера':'Camera','Пользователь':'User','Соединение':'Connecting','Нет связи':'Offline'});
  api.setDictionary('fr',{'Камера':'Caméra','Пользователь':'Utilisateur','Соединение':'Connexion','Нет связи':'Hors ligne'});
  const text=(value,protectedValue=false)=>{
    const parent={closest:()=>protectedValue?{}:null};
    const node={textContent:value,parentElement:parent};nodes.push(node);return node;
  };
  const element=value=>{
    const attrs={title:value};
    const el={closest:()=>null,matches:()=>false,hasAttribute:key=>Object.hasOwn(attrs,key),getAttribute:key=>attrs[key],setAttribute:(key,value)=>attrs[key]=value};
    elements.push(el);return el;
  };
  return {api,text,element};
}
test('DOM localization preserves explicitly protected camera/user names that match UI keys',()=>{
  const {api,text}=fixture();const camera=text('Камера',true),user=text('Пользователь',true),label=text('Камера');
  api.setLanguage('en');assert.equal(camera.textContent,'Камера');assert.equal(user.textContent,'Пользователь');assert.equal(label.textContent,'Camera');
  api.setLanguage('fr');assert.equal(camera.textContent,'Камера');assert.equal(label.textContent,'Caméra');
});
test('reused text nodes retain new status instead of restoring an obsolete source',()=>{
  const {api,text}=fixture();const status=text('Соединение');
  api.setLanguage('en');assert.equal(status.textContent,'Connecting');
  status.textContent='Нет связи';api.applyDOM({querySelectorAll:()=>[]});assert.equal(status.textContent,'Offline');
  api.setLanguage('fr');assert.equal(status.textContent,'Hors ligne');
});
test('dynamic titles use the new source and language switches preserve that source',()=>{
  const {api,element}=fixture();const button=element('Соединение');
  api.setLanguage('en');assert.equal(button.getAttribute('title'),'Connecting');
  button.setAttribute('title','Нет связи');api.applyDOM({querySelectorAll:()=>[button]});assert.equal(button.getAttribute('title'),'Offline');
  api.setLanguage('fr');assert.equal(button.getAttribute('title'),'Hors ligne');
});
