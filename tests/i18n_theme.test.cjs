'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const i18n=require('../static/i18n.js');
const themes=require('../static/themes.js');
const folder=path.join(__dirname,'../static/locales');
const codes=Object.keys(i18n.names);
const source=JSON.parse(fs.readFileSync(path.join(folder,'ru.json'),'utf8'));
const tokens=value=>[...value.matchAll(/__WVW_ARG_\d+__|\{[^{}]+\}/g)].map(m=>m[0]).sort();
for(const code of codes){
  test(`dictionary ${code}: coverage, placeholders and all plural categories`,()=>{
    const dictionary=JSON.parse(fs.readFileSync(path.join(folder,code+'.json'),'utf8'));
    assert.deepEqual(Object.keys(dictionary).sort(),Object.keys(source).sort());
    for(const [key,value] of Object.entries(dictionary)){
      assert.equal(typeof value,'string');assert.ok(value.trim(),`${code}: ${key}`);
      assert.deepEqual(tokens(value),tokens(key),`${code}: ${key}`);
    }
    const plural=JSON.parse(fs.readFileSync(path.join(folder,'plurals.json'),'utf8'));
    for(const noun of ['camera','channel','fragment','window']){
      const forms=plural[code][noun];
      for(const category of new Intl.PluralRules(code).resolvedOptions().pluralCategories){
        assert.ok(forms[category]||forms.other,`${code}/${noun}/${category}`);
      }
    }
    i18n.setDictionary(code,dictionary);i18n.setPlurals(plural);
    for(const noun of ['camera','channel','fragment','window'])for(const value of [0,1,2,5,21,101,1.5]){
      const text=i18n.count(value,noun,code);
      assert.ok(text&&!/undefined|\{count\}|__WVW_ARG/.test(text));
      assert.ok(text.includes(i18n.number(value,code)));
    }
  });
}
test('English fallback and dynamic substitutions keep values intact',t=>{
  t.after(()=>{for(const code of ['ru','en','fr'])i18n.setDictionary(code,JSON.parse(fs.readFileSync(path.join(folder,code+'.json'),'utf8')));});
  i18n.setDictionary('ru',{'Ок':'Ок','Камер: __WVW_ARG_0__':'Камер: __WVW_ARG_0__'});
  i18n.setDictionary('en',{'Ок':'OK','Камер: __WVW_ARG_0__':'Cameras: __WVW_ARG_0__'});
  i18n.setDictionary('fr',{});
  assert.equal(i18n.translate('Ок','fr'),'OK');
  assert.equal(i18n.translate('Камер: 37','fr'),'Cameras: 37');
  assert.equal(i18n.translate(undefined,'fr'),'');
  assert.equal(i18n.translate('Новая подпись','ru','New label'),'Новая подпись');
  assert.equal(i18n.translate('Новая подпись','fr','New label'),'New label');
});
test('theme defaults meet AA for primary, secondary and muted text',()=>{
  assert.deepEqual(themes.validate(themes.defaults),[]);
  assert.equal(themes.contrast('#000000','#ffffff'),21);
  const invalid=structuredClone(themes.defaults);invalid.light.text='#ffffff';
  assert.ok(themes.validate(invalid).some(e=>e.reason==='contrast'));
});
test('theme colors remain separate and malformed CSS falls back safely',()=>{
  const brand={theme_colors:{light:{text:'#112233'},dark:{text:'#ddeeff',surface:'url(bad)'}}};
  assert.equal(themes.colors(brand,'light').text,'#112233');
  assert.equal(themes.colors(brand,'dark').text,'#ddeeff');
  assert.equal(themes.colors(brand,'dark').surface,themes.defaults.dark.surface);
});
