/* WVW local dictionaries; all translation requests stay on this server. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.WVWI18n = api;
})(typeof window !== "undefined" ? window : this, function () {
  "use strict";
  const names = {ru:"Русский",en:"English",ar:"العربية",be:"Беларуская",bn:"বাংলা",cs:"Čeština",da:"Dansk",nl:"Nederlands",fa:"فارسی",fi:"Suomi",fr:"Français",de:"Deutsch",hi:"हिन्दी",hu:"Magyar",id:"Bahasa Indonesia",it:"Italiano",ja:"日本語",ko:"한국어","zh-CN":"简体中文","nb-NO":"Norsk bokmål",pl:"Polski","pt-BR":"Português (Brasil)",es:"Español",sv:"Svenska","zh-TW":"繁體中文",tr:"Türkçe",uk:"Українська",vi:"Tiếng Việt"};
  const dictionaries = {}, pending = {}, protectedText = new Set(), originals = new WeakMap(), attributeOriginals = new WeakMap();
  let language = "ru", observer, patterns = [], englishKeys = new Map(), plurals = {};
  const canonical = value => Object.hasOwn(names, value) ? value : "en";
  const escapeRegex = value => [...value].map(char => ".*+?^${}()|[]\\".includes(char) ? "\\"+char : char).join("");
  function setDictionary(code, values) {
    values=Object.fromEntries(Object.entries(values).filter(([key,value])=>typeof value==="string" && value.trim() && !/[<>]/.test(value)));
    dictionaries[canonical(code)] = values;
    if (code === "en") englishKeys = new Map(Object.entries(values).map(([key,value])=>[value,key]));
    if (code === "ru") patterns = Object.keys(values).filter(key => /__WVW_ARG_\d+__|\{[^{}]+\}/.test(key)).map(key => {
      const tokens = [...key.matchAll(/__WVW_ARG_\d+__|\{[^{}]+\}/g)].map(m=>m[0]);
      let source = escapeRegex(key);
      for (const token of tokens) source = source.replace(escapeRegex(token), "(.+?)");
      return { key, tokens, regex: new RegExp("^"+source+"$") };
    });
  }
  function translate(value, code = language, fallback) {
    if (value === null || value === undefined) return "";
    const text = String(value), trimmed = text.trim();
    if (!trimmed) return text;
    code = canonical(code);
    const key = Object.hasOwn(dictionaries.ru || {}, trimmed) ? trimmed : englishKeys.get(trimmed) || trimmed;
    let result = dictionaries[code]?.[key] || (code === "ru" ? dictionaries.ru?.[key] : dictionaries.en?.[key]);
    if (!result && /[А-Яа-яЁё]/.test(trimmed)) for (const pattern of patterns) {
      const match = trimmed.match(pattern.regex);
      if (!match) continue;
      result = dictionaries[code]?.[pattern.key] || dictionaries.en?.[pattern.key] || pattern.key;
      pattern.tokens.forEach((token,index)=>{ result=result.replaceAll(token,match[index+1]); });
      break;
    }
    result = result || (code === "ru" && /[А-Яа-яЁё]/.test(trimmed) ? trimmed : fallback) || trimmed;
    return text.slice(0,text.length-text.trimStart().length)+result+text.slice(text.trimEnd().length);
  }
  async function load(code) {
    code = canonical(code);
    async function one(locale) {
      if (dictionaries[locale]) return;
      if (!pending[locale]) pending[locale] = fetch("/static/locales/"+locale+".json?v=0.9.0", {credentials:"same-origin"}).then(response=>{
        if (!response.ok) throw new Error("Dictionary unavailable: "+locale);
        return response.json();
      }).then(values=>setDictionary(locale,values)).catch(error=>{ delete pending[locale]; throw error; });
      await pending[locale];
    }
    await Promise.all([one("ru"),one("en"),Object.keys(plurals).length ? Promise.resolve() : fetch("/static/locales/plurals.json?v=0.9.0",{credentials:"same-origin"}).then(response=>{if(!response.ok)throw new Error("Plural dictionary unavailable");return response.json();}).then(values=>{plurals=values;})]);
    if (code !== "ru" && code !== "en") await one(code).catch(()=>{});
    return code;
  }
  function options(selected) {
    return Object.entries(names).map(([code,name])=>`<option value="${code}" ${code===selected?"selected":""} lang="${code}" dir="auto" data-no-i18n>${name}</option>`).join("");
  }
  function protect(value) { if (typeof value === "string" && /[А-Яа-яЁё]/.test(value) ) protectedText.add(value); return value; }
  function applyDOM(container) {
    if (typeof document === "undefined" || !container) return;
    const protectedSelectors = "[data-no-i18n],[data-i18n-ignore],script,style,textarea,pre,code,[contenteditable=true],.brand-copy,.user-copy strong,#arc-camera-title,#arc-camera option:not([value='']),#arc-group option:not([value='']),#arc-track-label,#wall-group option:not([value='']),.wall-tree-camera > span,.wall-tile header strong,.wall-tile footer,.wall-inspector-body h2,#wall-selected,.inventory-device .infra-name strong,.inventory-channel .infra-name strong,.infra-reference-row .infra-name strong,.infra-name-link,.cell-name strong,.group-card-head h2,.log-detail";
    const excluded = node => node.parentElement?.closest(protectedSelectors);
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      if (excluded(node) || !node.textContent.trim() || protectedText.has(node.textContent.trim())) continue;
      const prior = originals.get(node);
      // A renderer can reuse a text node for a different status/count.
      const original = prior && node.textContent === prior.translated ? prior.source : node.textContent;
      const translated = translate(original);
      originals.set(node,{source:original,translated});
      if (translated !== node.textContent) node.textContent = translated;
    }
    const elements = [...(container.matches?.("[title],[placeholder],[aria-label]") ? [container] : []),...(container.querySelectorAll?.("[title],[placeholder],[aria-label]") || [])];
    for (const element of elements) {
      if (element.closest("[data-no-i18n],[data-i18n-ignore]") || element.matches(".wall-tile,.wall-tree-camera,.infra-name-link")) continue;
      for (const name of ["title","placeholder","aria-label"]) {
        if (!element.hasAttribute(name)) continue;
        const saved = attributeOriginals.get(element) || {};
        const current = element.getAttribute(name), prior = saved[name];
        const original = prior && current === prior.translated ? prior.source : current;
        const result = translate(original);
        saved[name] = {source:original,translated:result};
        attributeOriginals.set(element,saved);
        if (element.getAttribute(name)!==result) element.setAttribute(name,result);
      }
    }
  }
  function setLanguage(code) {
    language = canonical(code);
    if (typeof document !== "undefined") {
      document.documentElement.lang = language;
      document.documentElement.dir = ["ar","fa"].includes(language) ? "rtl" : "ltr";
      applyDOM(document.body);
      if (!observer && typeof MutationObserver === "function") {
        let queued = false;
        const roots = new Set();
        const observe = () => observer.observe(document.body,{childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:["title","placeholder","aria-label"]});
        observer = new MutationObserver(records=>{
          for (const record of records) {
            const element = record.target.nodeType === 3 ? record.target.parentElement : record.target;
            if (element) roots.add(element);
          }
          if (queued || !roots.size) return;
          queued = true;
          queueMicrotask(()=>{
            queued=false;
            const changed=[...roots].filter(element=>element.isConnected);
            roots.clear();
            // Ignore our own text/attribute writes and translate only changed subtrees.
            observer.disconnect();
            try { for(const element of changed) if(!changed.some(parent=>parent!==element && parent.contains(element))) applyDOM(element); }
            finally { observe(); }
          });
        });
        observe();
      }
    }
  }
  const locale = code => canonical(code);
  const t = value => translate(value);
  function number(value, code = language, options = {}) { return new Intl.NumberFormat(locale(code), options).format(value); }
  function dateTime(value, code = language, timeZone, options = {}) {
    const date = new Date(value); if (!Number.isFinite(date.getTime())) return String(value || "");
    return new Intl.DateTimeFormat(locale(code), {dateStyle:"medium",timeStyle:"medium",...(timeZone?{timeZone}:{}),...options}).format(date);
  }
  function count(value, noun = "camera", code = language) {
    code=canonical(code);
    const category = new Intl.PluralRules(locale(code)).select(Number(value));
    const forms=plurals[code]?.[noun] || plurals.en?.[noun];
    if(forms) return (forms[category] || forms.other || Object.values(forms)[0]).replaceAll("{count}",number(value,code));
    const fallback={camera:["камер","cameras"],channel:["каналов","channels"],fragment:["отрезков","fragments"],window:["окон","windows"],space:["пространств","spaces"],zone:["зон","zones"],device:["устройств","devices"]}[noun] || ["объектов","items"];
    return number(value,code)+" "+translate(fallback[0],code,code === "ru" ? fallback[0] : fallback[1]);
  }
  const setPlurals = values => { plurals=values; };

  return { names, canonical, locale, options, translate, t, load, setLanguage, applyDOM, setDictionary, protect, number, dateTime, count, setPlurals, get language(){return language;} };
});
