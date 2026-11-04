/* WVW sign-in/setup: shared branding, local dictionaries and safe text rendering. */
(async () => {
  "use strict";
  document.querySelectorAll("[data-icon]").forEach(node=>node.innerHTML=window.VWSIcons.html(node.dataset.icon));
  const branding=JSON.parse(document.querySelector("#branding-data")?.textContent || "{}");
  document.body.style.removeProperty("--accent");
  document.body.style.removeProperty("--icon-color");
  let theme="auto";
  try { const saved=localStorage.getItem("vwshub.auth.theme"); if(["auto","light","dark"].includes(saved))theme=saved; } catch(_) {}
  const themeControls=document.createElement("div");
  themeControls.className="theme-switch";themeControls.setAttribute("role","group");themeControls.setAttribute("aria-label","Тема");
  themeControls.innerHTML=[["auto","monitor","Автоматическая"],["light","sun","Светлая"],["dark","moon","Тёмная"]].map(([value,icon,label])=>`<button type="button" data-auth-theme="${value}" aria-label="${label}">${window.VWSIcons.html(icon)}</button>`).join("");
  document.querySelector(".auth-language")?.prepend(themeControls);
  const applyTheme=()=>{
    document.documentElement.dataset.theme=theme;
    window.WVWThemes.apply(document.documentElement,branding,theme);
    themeControls.querySelectorAll("button").forEach(button=>{button.classList.toggle("active",button.dataset.authTheme===theme);button.setAttribute("aria-pressed",String(button.dataset.authTheme===theme));});
  };
  themeControls.querySelectorAll("button").forEach(button=>button.onclick=()=>{theme=button.dataset.authTheme;try{localStorage.setItem("vwshub.auth.theme",theme);}catch(_){}applyTheme();});
  applyTheme();
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change",applyTheme);
  if (!branding.favicon && branding.favicon_icon) {
    const link=document.querySelector("#site-favicon");
    if(link)link.href=window.VWSIcons.dataURL(branding.favicon_icon,branding.accent);
  }
  const language=document.querySelector("#auth-language");
  let selected=document.documentElement.lang || "ru";
  try { selected=localStorage.getItem("vwshub.language") || selected; } catch(_) {}
  selected=window.WVWI18n.canonical(selected);
  if(language)language.innerHTML=window.WVWI18n.options(selected);
  const password=document.querySelector("#password"), confirm=document.querySelector("#password-confirm");
  const sync=()=>{ if(confirm)confirm.setCustomValidity(password.value===confirm.value ? "" : window.WVWI18n.t("Пароли не совпадают")); };
  let languageGeneration=0;
  async function apply(value) {
    const generation=++languageGeneration;
    await window.WVWI18n.load(value).catch(()=>{});
    if(generation!==languageGeneration)return;
    window.WVWI18n.setLanguage(value);
    if(language)language.value=value;
    try{localStorage.setItem("vwshub.language",value);}catch(_){}
    sync();
  }
  if(language)language.onchange=()=>apply(language.value);
  if(confirm){password.addEventListener("input",sync);confirm.addEventListener("input",sync);}
  await apply(selected);
  if(language)language.disabled=false;
})();
