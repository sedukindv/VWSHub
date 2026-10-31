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
      ![1, 2, 3].includes(value.version) ||
      !Array.isArray(value.cells) ||
      value.cells.length > (value.version === 1 ? 256 : 4096)
    )
      throw new Error("Некорректный файл вида VWSHub");
    const shape =
      value.version === 1 && [1, 2, 3, 4].includes(value.columns)
        ? layout(value.columns ** 2)
        : value.version >= 2 && typeof value.layout === "string"
          ? layout(value.layout)
          : null;
    if (!shape) throw new Error("Некорректный файл вида VWSHub");
    const known = new Map(
      cameras.filter((c) => !c.is_hidden).map((c) => [c.id, c]),
    );
    const identities=new Map(cameras.filter(c=>!c.is_hidden&&c.origin_id).map(c=>[c.origin_id+":"+(c.import_id||c.id),c]));
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
      if (
        cell.visibility_revision !== undefined &&
        (!Number.isSafeInteger(cell.visibility_revision) ||
          cell.visibility_revision < 0)
      )
        throw new Error("Некорректная ревизия видимости камеры");
      const portable=value.version===3&&cell.origin_id!==undefined;
      if(portable&&(!/^[A-Za-z0-9_-]{1,100}$/.test(cell.origin_id)||typeof cell.origin_id!=="string"||typeof cell.source_id!=="string"||!/^[A-Za-z0-9_-]{1,100}$/.test(cell.source_id)))throw new Error("Некорректная ссылка источника");
      const source=portable?identities.get(cell.origin_id+":"+cell.source_id):known.get(cell.camera_id);
      if (
        !source ||
        Number(cell.visibility_revision || 0) !==
          Number(source.visibility_revision || 0)
      ) {
        unavailable++;
        return null;
      }
      return {
        camera_id: source.id,
        stream: cell.stream,
        ...(portable?{origin_id:cell.origin_id,source_id:cell.source_id}:{}),
        ...(cell.visibility_revision
          ? { visibility_revision: cell.visibility_revision }
          : {}),
      };
    });
    return {
      format: "vwshub.view",
      version: 3,
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
      version: 3,
      layout: selected.id,
      columns: selected.columns,
      cells: cells.map((c) =>
        c && c.camera_id
          ? {
              camera_id: c.camera_id,
              stream: c.stream === "main" ? "main" : "sub",
              ...(c.visibility_revision
                ? { visibility_revision: c.visibility_revision }
                : {}),
              ...(c.origin_id?{origin_id:c.origin_id,source_id:c.source_id||c.camera_id}:{}),
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
  function reconcile(cells, cameras) {
    const known = new Map(
      cameras.filter((c) => !c.is_hidden).map((c) => [c.id, c]),
    );
    return cells.map((cell) =>
      cell &&
      known.has(cell.camera_id) &&
        (!cell.origin_id||(cell.origin_id===known.get(cell.camera_id).origin_id&&cell.source_id===(known.get(cell.camera_id).import_id||cell.camera_id)))&&
      Number(cell.visibility_revision || 0) ===
        Number(known.get(cell.camera_id).visibility_revision || 0)
        ? cell
        : null,
    );
  }
  function collection(cameras, spaces, selection = { kind: "all" }) {
    const available = cameras.filter((c) => !c.is_hidden),
      byId = new Map(available.map((c) => [c.id, c]));
    if (selection.kind === "all") return available;
    if (selection.kind === "device")
      return available.filter((c) => c.recorder_id === selection.id);
    if (selection.kind === "unassigned") {
      const assigned = new Set(
        spaces.flatMap((space) => space.camera_ids || []),
      );
      return available.filter((c) => !assigned.has(c.id));
    }
    const space = spaces.find(
      (s) => s.id === (selection.space_id || selection.id),
    );
    if (!space || !["space", "zone"].includes(selection.kind)) return [];
    const ordered=space.members?[...space.members.filter(m=>!m.zone_id),...(space.zones||[]).flatMap(z=>space.members.filter(m=>m.zone_id===z.id))]:null;
    const ids = ordered
      ? ordered
          .filter((member) =>
            selection.kind === "zone"
              ? member.zone_id === selection.id
              : !selection.root_only || !member.zone_id,
          )
          .map((m) => m.channel_id)
      : space.camera_ids || [];
    return [...new Set(ids)].map((id) => byId.get(id)).filter(Boolean);
  }
  return {
    layouts,
    layout,
    fit,
    normalize,
    serialize,
    pan,
    consumerId,
    reconcile,
    collection,
  };
});
