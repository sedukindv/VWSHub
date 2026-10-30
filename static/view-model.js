(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.VWSViewModel = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  const layouts = Object.freeze(
    [
      { id: "1", count: 1, columns: 1, rows: 1 },
      { id: "4", count: 4, columns: 2, rows: 2 },
      { id: "6", count: 6, columns: 3, rows: 3, large: 2 },
      { id: "8", count: 8, columns: 4, rows: 4, large: 3 },
      { id: "9", count: 9, columns: 3, rows: 3 },
      { id: "16", count: 16, columns: 4, rows: 4 },
      { id: "25", count: 25, columns: 5, rows: 5 },
      { id: "36", count: 36, columns: 6, rows: 6 },
      { id: "64", count: 64, columns: 8, rows: 8 },
    ].map(Object.freeze),
  );
  function layout(id) {
    const value = layouts.find((item) => item.id === String(id));
    if (!value) throw new Error("Неизвестная раскладка видеостены");
    return value;
  }
  function fit(count) {
    if (!Number.isInteger(count) || count < 0 || count > 4096)
      throw new Error("В виде может быть до 4096 камер");
    return (layouts.find((item) => item.count >= count) || layouts.at(-1)).id;
  }
  function normalize(value, cameras) {
    if (
      !value ||
      typeof value !== "object" ||
      value.format !== "vwshub.view" ||
      ![1, 2].includes(value.version) ||
      !Array.isArray(value.cells) ||
      value.cells.length > (value.version === 1 ? 256 : 4096)
    )
      throw new Error("Некорректный файл вида VWSHub");
    const shape =
      value.version === 1 && [1, 2, 3, 4].includes(value.columns)
        ? layout(value.columns ** 2)
        : value.version === 2 && typeof value.layout === "string"
          ? layout(value.layout)
          : null;
    if (!shape) throw new Error("Некорректный файл вида VWSHub");
    const known = new Set(cameras.map((c) => c.id));
    let unavailable = 0;
    const cells = value.cells.map((cell) => {
      if (cell === null) return null;
      if (
        !cell ||
        typeof cell !== "object" ||
        typeof cell.camera_id !== "string" ||
        cell.camera_id.length > 150 ||
        !["main", "sub"].includes(cell.stream)
      )
        throw new Error("Некорректная ячейка вида");
      if (!known.has(cell.camera_id)) {
        unavailable++;
        return null;
      }
      return { camera_id: cell.camera_id, stream: cell.stream };
    });
    return {
      format: "vwshub.view",
      version: 2,
      layout: shape.id,
      columns: shape.columns,
      cells,
      unavailable,
    };
  }
  function serialize(shape, cells) {
    // Numeric column arguments keep the original helper usable by 0.7 callers.
    const selected = layout(typeof shape === "number" ? shape ** 2 : shape);
    if (!Array.isArray(cells) || cells.length > 4096)
      throw new Error("В виде может быть до 4096 камер");
    return {
      format: "vwshub.view",
      version: 2,
      layout: selected.id,
      columns: selected.columns,
      cells: cells.map((c) =>
        c && c.camera_id
          ? {
              camera_id: c.camera_id,
              stream: c.stream === "main" ? "main" : "sub",
            }
          : null,
      ),
    };
  }
  function pan(
    zoom,
    x,
    y,
    width,
    height,
    videoWidth = width,
    videoHeight = height,
  ) {
    const scale = Math.max(1, Math.min(8, Number(zoom) || 1));
    const factor = Math.min(width / videoWidth, height / videoHeight);
    const maxX = Math.max(0, (videoWidth * factor * scale - width) / 2);
    const maxY = Math.max(0, (videoHeight * factor * scale - height) / 2);
    return {
      zoom: scale,
      x: Math.max(-maxX, Math.min(maxX, Number(x) || 0)),
      y: Math.max(-maxY, Math.min(maxY, Number(y) || 0)),
    };
  }
  function consumerId(source) {
    // getRandomValues also works on ordinary HTTP origins in a local network.
    return Array.from(source.getRandomValues(new Uint8Array(16)), (byte) =>
      byte.toString(16).padStart(2, "0"),
    ).join("");
  }
  return { layouts, layout, fit, normalize, serialize, pan, consumerId };
});
