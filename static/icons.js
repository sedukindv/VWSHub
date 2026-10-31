/* Lucide 1.65.0 is bundled locally; no icon requests leave this server. */
(() => {
  "use strict";
  const aliases = {
    grid: "layout-grid",
    archive: "archive",
    photo: "camera",
    users: "users-round",
    settings: "settings",
    list: "logs",
    palette: "paintbrush",
    panel: "panel-left-close",
    logout: "log-out",
    refresh: "refresh-cw",
    edit: "pencil",
    clone: "copy",
    trash: "trash-2",
    close: "x",
    expand: "maximize",
    left: "chevron-left",
    right: "chevron-right",
    alert: "triangle-alert",
    brand: "shield-check",
    route: "route",
  };
  const escape = (value) =>
    String(value).replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
  const nodes = new Map(),
    names = new Set();
  for (const [key, value] of Object.entries(window.lucide.icons)) {
    const name = key
      .replace(/([a-z0-9])([A-Z])/g, "$1-$2")
      .replace(/([A-Z])([A-Z][a-z])/g, "$1-$2")
      .toLowerCase();
    const canonical = name.replace(/([a-z])([0-9])/g, "$1-$2");
    if (!nodes.has(canonical)) nodes.set(canonical, value);
    if (!nodes.has(name)) nodes.set(name, value);
    names.add(canonical);
  }
  const html = (name, fallback = "circle-help") => {
    const actual = aliases[name] || name;
    const items =
      nodes.get(actual) ||
      nodes.get(actual.replace(/([0-9])-([0-9])/g, "$1$2")) ||
      nodes.get(fallback) ||
      nodes.get("folder");
    return `<svg class="lucide" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${items
      .map(
        ([tag, attributes]) =>
          `<${tag} ${Object.entries(attributes)
            .map(([key, value]) => `${key}="${escape(value)}"`)
            .join(" ")}/>`,
      )
      .join("")}</svg>`;
  };
  window.VWSIcons = {
    html,
    names: [...names].sort(),
    has: (name) => nodes.has(name),
    dataURL: (name, color = "#526cf5") =>
      "data:image/svg+xml," +
      encodeURIComponent(
        html(name, "shield-check").replace(
          "<svg ",
          '<svg xmlns="http://www.w3.org/2000/svg" style="color:' +
            (/^#[0-9a-f]{6}$/i.test(color) ? color : "#526cf5") +
            '" ',
        ),
      ),
  };
})();
