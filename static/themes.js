/* Shared WVW theme tokens. No network dependencies. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.WVWThemes = api;
})(typeof window !== "undefined" ? window : this, function () {
  "use strict";
  const defaults = {
    light: { background: "#f4f6fa", surface: "#ffffff", surface_alt: "#f8f9fc", text: "#1b2440", text_soft: "#44516e", muted: "#586680", line: "#d2d9e8", accent: "#526cf5", icon_color: "#64738c", success: "#167f61", warning: "#95601c", danger: "#be344b", info: "#2877bb" },
    dark: { background: "#10151f", surface: "#171e2b", surface_alt: "#141b27", text: "#e8edf7", text_soft: "#b7c3d8", muted: "#9cabc3", line: "#36455f", accent: "#8295ff", icon_color: "#9cabc3", success: "#48c7a0", warning: "#e7b465", danger: "#f1788a", info: "#78b8f2" },
  };
  const variables = { background: "bg", surface: "surface", surface_alt: "surface-alt", text: "text", text_soft: "text-soft", muted: "muted", line: "line", accent: "accent", icon_color: "icon-color", success: "success", warning: "warning", danger: "danger", info: "info" };
  const isColor = value => typeof value === "string" && /^#[a-f0-9]{6}$/i.test(value);
  function colors(branding, theme) {
    const mode = theme === "dark" ? "dark" : "light", chosen = { ...defaults[mode] };
    for (const key of ["accent", "icon_color"]) if (isColor(branding?.[key])) chosen[key] = branding[key];
    for (const [key, value] of Object.entries(branding?.theme_colors?.[mode] || {})) if (Object.hasOwn(variables, key) && isColor(value)) chosen[key] = value;
    const buttonText=branding?.theme_colors?.[mode]?.button_text;
    if(isColor(buttonText)) chosen.button_text=buttonText;
    return chosen;
  }
  function contrast(a, b) {
    function luminance(color) {
      const rgb = [1, 3, 5].map(index => parseInt(color.slice(index, index + 2), 16) / 255).map(v => v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
      return rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722;
    }
    const first = luminance(a), second = luminance(b);
    return (Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05);
  }
  function readable(color, values, surfaces = [values.background, values.surface, values.surface_alt]) {
    const fits = candidate => surfaces.every(surface => contrast(candidate,surface) >= 4.5);
    if (fits(color)) return color;
    const rgb = value => [1,3,5].map(index=>parseInt(value.slice(index,index+2),16));
    const source=rgb(color);
    for(let step=1;step<=100;step++) for(const target of ["#000000","#ffffff",values.text]) {
      const channels=rgb(target),weight=step/100;
      const candidate="#"+source.map((value,index)=>Math.round(value+(channels[index]-value)*weight).toString(16).padStart(2,"0")).join("");
      if(fits(candidate)) return candidate;
    }
    return values.text;
  }
  function mixColor(color, surface, amount) {
    return "#"+[1,3,5].map(index=>Math.round(parseInt(color.slice(index,index+2),16)*amount+parseInt(surface.slice(index,index+2),16)*(1-amount)).toString(16).padStart(2,"0")).join("");
  }
  function semanticColor(values, key) {
    const surfaces=[values.background,values.surface,values.surface_alt];
    // A common foreground must also remain readable on the tinted badge/notice.
    // Unusual palettes may need less tint to preserve the same AA foreground.
    for(let percent=12;percent>=0;percent--) {
      const background=mixColor(values[key],values.surface,percent/100);
      const foreground=readable(values[key],values,[...surfaces,background]);
      if([...surfaces,background].every(surface=>contrast(foreground,surface)>=4.5)) return {foreground,background};
    }
    return {foreground:values.text,background:values.surface};
  }
  function selectedColor(values) {
    const surfaces=[values.background,values.surface,values.surface_alt];
    for(let percent=13;percent>=0;percent--) {
      const background=mixColor(values.accent,values.surface,percent/100);
      if(![values.text,values.text_soft,values.muted].every(text=>contrast(text,background)>=4.5)) continue;
      const foreground=readable(values.accent,values,[...surfaces,background]);
      if([...surfaces,background].every(surface=>contrast(foreground,surface)>=4.5)) return {foreground,background};
    }
    return {foreground:values.text,background:values.surface};
  }
  function buttonColors(values) {
    const automatic = background => contrast(background,"#ffffff") >= contrast(background,"#000000") ? "#ffffff" : "#000000";
    const foreground = isColor(values.button_text) ? values.button_text : automatic(values.accent);
    let hover="#"+[1,3,5].map(index=>Math.round(parseInt(values.accent.slice(index,index+2),16)*0.86).toString(16).padStart(2,"0")).join("");
    if(isColor(values.button_text)) hover=readable(hover,{background:foreground,surface:foreground,surface_alt:foreground,text:values.accent});
    return {foreground,hover,hoverForeground:isColor(values.button_text)?foreground:automatic(hover),checkInk:automatic(values.accent)};
  }
  function validate(palette) {
    const errors = [];
    for (const theme of ["light", "dark"]) {
      const values = palette[theme] || {};
      for (const key of Object.keys(variables)) if (!isColor(values[key])) errors.push({ theme, key, reason: "color" });
      if (Object.hasOwn(values,"button_text") && !isColor(values.button_text)) errors.push({theme,key:"button_text",reason:"color"});
      if (errors.some(e => e.theme === theme)) continue;
      if(isColor(values.button_text)) {
        const ratio=contrast(values.button_text,values.accent);
        if(ratio<4.5) errors.push({theme,key:"button_text",background:"accent",ratio,reason:"contrast"});
      }
      for (const key of ["text", "text_soft", "muted"]) for (const background of ["background", "surface", "surface_alt"]) {
        const ratio = contrast(values[key], values[background]);
        if (ratio < 4.5) errors.push({ theme, key, background, ratio, reason: "contrast" });
      }
    }
    return errors;
  }
  function apply(node, branding, theme) {
    const selected = theme === "dark" ? "dark" : theme === "light" ? "light" : typeof matchMedia === "function" && matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    const values = colors(branding, selected);
    for (const [key, variable] of Object.entries(variables)) node.style.setProperty("--" + variable, values[key]);
    const buttons=buttonColors(values);
    node.style.setProperty("--accent-contrast",buttons.foreground);
    node.style.setProperty("--accent-hover",buttons.hover);
    node.style.setProperty("--accent-hover-contrast",buttons.hoverForeground);
    const selectedColors=selectedColor(values);
    node.style.setProperty("--accent-text",selectedColors.foreground);
    node.style.setProperty("--accent-dim",selectedColors.background);
    node.style.setProperty("--focus-color",readable(values.accent,values));
    for(const key of ["success","warning","danger","info"]) {
      const status=semanticColor(values,key);
      node.style.setProperty("--"+key+"-text",status.foreground);
      node.style.setProperty("--"+key+"-bg",status.background);
    }
    const arrowColor=readable(values.icon_color,values);
    const arrow=`<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="none" stroke="${arrowColor}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="m4 6 4 4 4-4"/></svg>`;
    node.style.setProperty("--select-arrow",`url("data:image/svg+xml,${encodeURIComponent(arrow)}")`);
    for(const [variable,shape] of Object.entries({checkmark:"m3 8 3 3 7-7",checkline:"M4 8h8"})) {
      const svg=`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="none" stroke="${buttons.checkInk}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="${shape}"/></svg>`;
      node.style.setProperty("--"+variable,`url("data:image/svg+xml,${encodeURIComponent(svg)}")`);
    }
    for (const [key, value] of Object.entries({ input: values.surface, "surface-raised": values.surface_alt, hover: values.surface_alt, "muted-2": values.muted, "line-strong": values.line, video: values.background, "video-empty": values.surface_alt })) node.style.setProperty("--" + key, value);
    return values;
  }
  return { defaults, variables, colors, contrast, readable, semanticColor, selectedColor, buttonColors, validate, apply };
});
