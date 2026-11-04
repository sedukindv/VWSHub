'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');

test('late initial dictionary cannot overwrite a newer language chosen on sign-in',async()=>{
  const waiting={},selected=[];
  const language={value:'ar',disabled:true};
  const stored={'vwshub.language':'ar'};
  const document={
    documentElement:{lang:'ru',dataset:{}},body:{style:{removeProperty(){}}},
    querySelectorAll:()=>[],
    createElement:()=>({setAttribute(){},querySelectorAll:()=>[]}),
    querySelector:selector=>selector==='#branding-data'?{textContent:'{}'}:selector==='#auth-language'?language:selector==='.auth-language'?{prepend(){}}:null,
  };
  const context={document,localStorage:{getItem:key=>stored[key],setItem:(key,value)=>stored[key]=value},matchMedia:()=>({addEventListener(){}})};
  context.window={VWSIcons:{html:()=>''},WVWThemes:{apply(){}},WVWI18n:{canonical:x=>x,options:()=>'',load:code=>new Promise(resolve=>waiting[code]=resolve),setLanguage:code=>selected.push(code),t:x=>x}};
  vm.createContext(context);
  const initial=vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/auth.js'),'utf8'),context);
  language.value='fr';const newer=language.onchange();
  waiting.fr();await newer;waiting.ar();await initial;
  assert.deepEqual(selected,['fr']);
  assert.equal(stored['vwshub.language'],'fr');assert.equal(language.value,'fr');
  assert.equal(language.disabled,false);
});
