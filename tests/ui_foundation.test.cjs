'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const i18n=require('../static/i18n.js');
const themes=require('../static/themes.js');
const folder=path.join(__dirname,'../static/locales');
const dictionaries=Object.fromEntries(Object.keys(i18n.names).map(code=>[code,JSON.parse(fs.readFileSync(path.join(folder,code+'.json'),'utf8'))]));
for(const[code,values]of Object.entries(dictionaries))i18n.setDictionary(code,values);
i18n.setPlurals(JSON.parse(fs.readFileSync(path.join(folder,'plurals.json'),'utf8')));

test('all 28 locale dictionaries cover every shipped source key with plain nonempty text',()=>{
  assert.equal(Object.keys(dictionaries).length,28);
  const keys=Object.keys(dictionaries.ru).sort();assert.ok(keys.length>1300);
  for(const[code,values]of Object.entries(dictionaries)){
    assert.deepEqual(Object.keys(values).sort(),keys,code+' coverage');
    for(const[key,value]of Object.entries(values)){
      assert.equal(typeof value,'string');assert.ok(value.trim(),code+':'+key);
      assert.ok(!/[<>]/.test(value),code+' HTML in translation');
      for(const token of key.match(/__WVW_ARG_\d+__/g)||[])assert.ok(value.includes(token),code+' lost placeholder '+token);
    }
  }
});
test('translation resolves Russian and existing English labels, retaining whitespace and fallback',()=>{
  assert.equal(i18n.translate('Сохранить','en'),'Save');
  assert.equal(i18n.translate('Save','de'),'Speichern');
  assert.equal(i18n.translate('  Сохранить  ','en'),'  Save  ');
  assert.equal(i18n.translate('An unmapped camera name','fr'),'An unmapped camera name');
  assert.equal(i18n.translate(null,'en'),'');
});
test('plural counts include real one/few/many cases and localized numerals',()=>{
  assert.equal(i18n.count(1,'fragment','ru'),'1 отрезок');
  assert.equal(i18n.count(2,'fragment','ru'),'2 отрезка');
  assert.equal(i18n.count(11,'fragment','ru'),'11 отрезков');
  assert.match(i18n.count(1,'camera','en'),/^1 camera$/);
  assert.match(i18n.count(2,'camera','en'),/^2 cameras$/);
  for(const code of Object.keys(i18n.names))for(const noun of ['camera','channel','fragment','window','space','zone','device'])for(const n of [0,1,2,3,5,11,22,101,1.5]){
    const value=i18n.count(n,noun,code);assert.ok(value && !value.includes('undefined') && !value.includes('{count}'),code+':'+noun);
  }
  assert.notEqual(i18n.count(2,'camera','cs'),i18n.count(5,'camera','cs'));
  assert.equal(i18n.number(1234,'ar'),new Intl.NumberFormat('ar').format(1234));
});
test('user timezone affects true timestamps without changing source timestamps',()=>{
  const value='2026-11-03T00:00:00Z';
  assert.notEqual(i18n.dateTime(value,'en','UTC'),i18n.dateTime(value,'en','Asia/Omsk'));
  assert.equal(i18n.dateTime('device-local-time','en','UTC'),'device-local-time');
});
test('both default themes meet normal-text contrast and invalid colors are rejected',()=>{
  assert.deepEqual(themes.validate(themes.defaults),[]);
  assert.ok(themes.contrast('#000000','#ffffff')>20.9);
  const broken=JSON.parse(JSON.stringify(themes.defaults));broken.light.text='#ffffff';
  assert.ok(themes.validate(broken).some(item=>item.theme==='light'&&item.key==='text'&&item.reason==='contrast'));
  broken.light.text='url(javascript:x)';
  assert.ok(themes.validate(broken).some(item=>item.reason==='color'));
});
test('theme application uses independent palettes, retains legacy fallback and sets contrast text',()=>{
  const properties={};const node={style:{setProperty:(key,value)=>properties[key]=value}};
  themes.apply(node,{accent:'#ffffff',theme_colors:{dark:{text:'#eeeeee',surface:'#101010'}}},'dark');
  assert.equal(properties['--text'],'#eeeeee');assert.equal(properties['--surface'],'#101010');
  assert.equal(properties['--accent-contrast'],'#000000');
  assert.ok(properties['--checkmark'].includes('%23000000'));
  assert.ok(themes.contrast(properties['--accent-text'],properties['--surface'])>=4.5);
  assert.equal(themes.colors({theme_colors:{light:{accent:'not-a-color'}}},'light').accent,themes.defaults.light.accent);
});
test('dynamic placeholders survive substitution and unsafe dictionary entries fall back',t=>{
  t.after(()=>{for(const code of ['ru','en','fi'])i18n.setDictionary(code,dictionaries[code]);});
  i18n.setDictionary('ru',{'Записей: __WVW_ARG_0__':'Записей: __WVW_ARG_0__','Сохранить':'Сохранить'});
  i18n.setDictionary('en',{'Записей: __WVW_ARG_0__':'Recordings: __WVW_ARG_0__','Сохранить':'Save'});
  i18n.setDictionary('fi',{'Записей: __WVW_ARG_0__':'Tallenteet: __WVW_ARG_0__','Сохранить':'<img src=x onerror=alert(1)>'});
  assert.equal(i18n.translate('Записей: 17','fi'),'Tallenteet: 17');
  assert.equal(i18n.translate('Сохранить','fi'),'Save');
});

test('manual button text persists independently while auto and hover meet AA',()=>{
  const palette=JSON.parse(JSON.stringify(themes.defaults));
  palette.light.accent='#2340ad';palette.light.button_text='#ffffff';
  assert.deepEqual(themes.validate(palette),[]);
  const manual=themes.colors({theme_colors:palette},'light');
  assert.equal(manual.button_text,'#ffffff');
  const buttons=themes.buttonColors(manual);
  assert.equal(buttons.foreground,'#ffffff');assert.equal(buttons.hoverForeground,'#ffffff');
  assert.ok(themes.contrast(buttons.foreground,manual.accent)>=4.5);
  assert.ok(themes.contrast(buttons.hoverForeground,buttons.hover)>=4.5);
  palette.light.button_text='#2340ad';
  assert.ok(themes.validate(palette).some(error=>error.key==='button_text'&&error.reason==='contrast'));
  delete palette.light.button_text;
  assert.equal(Object.hasOwn(themes.colors({theme_colors:palette},'light'),'button_text'),false);
  for(const accent of ['#ffffff','#000000','#526cf5','#8295ff','#ffff00']) {
    const auto=themes.buttonColors({...themes.defaults.light,accent});
    assert.ok(themes.contrast(auto.foreground,accent)>=4.5);
    assert.ok(themes.contrast(auto.hoverForeground,auto.hover)>=4.5);
  }
});

test('white accents and semantic colors retain readable focus, select arrows and status text',()=>{
  const properties={};const node={style:{setProperty:(key,value)=>properties[key]=value}};
  const selected={...themes.defaults.light,accent:'#ffffff',icon_color:'#ffffff',success:'#ffffff',warning:'#ffffff',danger:'#ffffff',info:'#ffffff'};
  const before=JSON.stringify(selected);
  themes.apply(node,{theme_colors:{light:selected}},'light');
  assert.equal(JSON.stringify(selected),before,'derived UI colors must not alter saved choices');
  assert.equal(properties['--accent'],'#ffffff');
  assert.equal(properties['--warning'],'#ffffff');
  for(const key of ['--focus-color','--accent-text'])for(const surface of ['--bg','--surface','--surface-alt'])assert.ok(themes.contrast(properties[key],properties[surface])>=4.5,key+' on '+surface);
  const arrow=decodeURIComponent(properties['--select-arrow']);
  const ink=arrow.match(/stroke="(#[a-f0-9]{6})"/)[1];
  assert.ok(themes.contrast(ink,properties['--surface'])>=4.5,'functional select caret must not disappear');
  for(const key of ['success','warning','danger','info']){
    const text=properties['--'+key+'-text'];
    for(const background of [properties['--bg'],properties['--surface'],properties['--surface-alt'],properties['--'+key+'-bg']])assert.ok(themes.contrast(text,background)>=4.5,key+' status text');
  }
});

test('default and mixed-surface themes keep status foregrounds at AA, reducing tint when needed',()=>{
  const unusual={...themes.defaults.dark,background:'#000000',surface:'#757575',surface_alt:'#151515',text:'#ffffff',text_soft:'#ffffff',muted:'#ffffff',success:'#ffffff',warning:'#ffffff',danger:'#ffffff',info:'#ffffff'};
  for(const palette of [...Object.values(themes.defaults),unusual])for(const key of ['success','warning','danger','info']){
    const status=themes.semanticColor(palette,key);
    for(const background of [palette.background,palette.surface,palette.surface_alt,status.background])assert.ok(themes.contrast(status.foreground,background)>=4.5,key+' on '+background);
  }
  const reduced=themes.semanticColor(unusual,'warning');
  assert.ok(themes.contrast('#ffffff',reduced.background)>=4.5,'a lighter tinted panel must not invalidate the shared white foreground');
});

test('selected accent surfaces retain AA for their accent labels and ordinary secondary text',()=>{
  const custom={...themes.defaults.light,accent:'#000000',text_soft:'#6f6f6f',muted:'#6f6f6f'};
  assert.deepEqual(themes.validate({light:custom,dark:themes.defaults.dark}),[]);
  for(const palette of [...Object.values(themes.defaults),custom]){
    const selected=themes.selectedColor(palette);
    for(const text of [palette.text,palette.text_soft,palette.muted,selected.foreground])assert.ok(themes.contrast(text,selected.background)>=4.5,text+' on selected '+selected.background);
    const properties={};themes.apply({style:{setProperty:(key,value)=>properties[key]=value}},{theme_colors:{light:palette}},'light');
    assert.equal(properties['--accent-dim'],selected.background);
    assert.equal(properties['--accent-text'],selected.foreground);
    assert.equal(properties['--accent'],palette.accent,'raw saved accent stays intact');
  }
});
