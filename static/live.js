/* VWSHub operator monitor. View files contain camera IDs, never device credentials. */
(() => {
  "use strict";
  let saved = null;
  window.VWSLive = {
    mount(options) {
      const {
          root,
          cameras,
          groups,
          user,
          settings = {},
          hub: H,
          onArchive,
        } = options,
        { h, t, icon, toast } = H;
      const model = window.VWSViewModel,
        life = new AbortController(),
        signal = life.signal,
        key = "vwshub.view." + user.username;
      const consumer = model.consumerId(crypto);
      let disposed = false,
        uid = 0,
        players = new Map(),
        timers = new Set(),
        ptzCleanup = null,
        sequence = null;
      const make = (id, stream = "sub") => {
        const source = cameras.find((c) => c.id === id);
        return {
          uid: ++uid,
          camera_id: id,
          stream,
          visibility_revision: Number(source?.visibility_revision || 0),
          ...(source?.origin_id
            ? { origin_id: source.origin_id, source_id: source.import_id || id }
            : {}),
        };
      };
      if (!saved || saved.owner !== user.username) {
        saved = {
          owner: user.username,
          layout: model.fit(Math.min(cameras.length, 4)),
          columns: model.layout(model.fit(Math.min(cameras.length, 4))).columns,
          cells: cameras.map((c) => ({
            camera_id: c.id,
            stream: cameras.length === 1 ? "main" : "sub",
            visibility_revision: c.visibility_revision || 0,
            ...(c.origin_id
              ? { origin_id: c.origin_id, source_id: c.import_id || c.id }
              : {}),
          })),
          page: 0,
          tree: true,
          inspector: false,
        };
        try {
          const data = JSON.parse(localStorage.getItem(key) || "null");
          if (data) {
            const v = model.normalize(data, cameras);
            saved.columns = v.columns;
            saved.layout = v.layout;
            saved.cells = v.cells;
          }
        } catch (_) {}
      }
      const m = saved;
      m.treeMode ||= "spaces";
      m.layout ||= String(m.columns ** 2);
      const capacity = () => model.layout(m.layout).count;
      const useLayout = (id) => {
        m.layout = String(id);
        m.columns = model.layout(id).columns;
      };
      const treeOpen = new Map();
      let treeScroll = 0;
      const boundEvents = new WeakMap();
      m.cells = model
        .reconcile(m.cells, cameras)
        .map((c) => (c ? make(c.camera_id, c.stream) : null));
      if (options.cameraId && cameras.some((c) => c.id === options.cameraId)) {
        m.cells = [make(options.cameraId, "main")];
        useLayout("1");
        m.page = 0;
        m.group = "";
        m.title = cameras.find((c) => c.id === options.cameraId).name;
      } else if (options.groupId) {
        m.group = options.groupId;
        const selection = options.zoneId
          ? { kind: "zone", id: options.zoneId, space_id: options.groupId }
          : {
              kind: "space",
              id: options.groupId,
              root_only: !!options.rootOnly,
            };
        m.cells = model
          .collection(cameras, groups, selection)
          .map((c) => make(c.id));
        useLayout(model.fit(m.cells.length));
        m.page = 0;
        const group = groups.find((g) => g.id === options.groupId);
        m.title = options.zoneId
          ? group?.zones?.find((z) => z.id === options.zoneId)?.name
          : group?.name;
      }
      let selected = null,
        focusRestore = null,
        treeQuery = "",
        context = null;
      const $ = (s) => root.querySelector(s),
        $$ = (s) => [...root.querySelectorAll(s)],
        camera = (id) => cameras.find((c) => c.id === id);
      const later = (fn, ms) => {
        const timer = setTimeout(() => {
          timers.delete(timer);
          if (!disposed) fn();
        }, ms);
        timers.add(timer);
        return timer;
      };
      const on = (el, event, fn, opts = {}) => {
        if (!el) return;
        const seen = boundEvents.get(el) || new Set();
        if (seen.has(event)) return;
        seen.add(event);
        boundEvents.set(el, seen);
        el.addEventListener(event, fn, { ...opts, signal });
      };
      const visible = () => {
        m.page = Math.max(
          0,
          Math.min(m.page || 0, Math.ceil(m.cells.length / capacity()) - 1),
        );
        return m.cells.slice(m.page * capacity(), (m.page + 1) * capacity());
      };
      function release(cells) {
        const keys = new Map(
          cells.map((c) => [c.camera_id + "|" + c.stream, c]),
        );
        for (const c of keys.values())
          H.api("/api/live/stop", {
            method: "POST",
            body: { cam_id: c.camera_id, stream: c.stream, consumer },
            keepalive: true,
          }).catch(() => {});
      }
      function stopPlayers() {
        release([...players.values()]);
        for (const timer of timers) clearTimeout(timer);
        timers.clear();
        ptzCleanup?.();
        ptzCleanup = null;
        for (const item of players.values()) {
          item.hls?.destroy();
          item.video.pause();
          item.video.removeAttribute("src");
          item.video.load();
        }
        players.clear();
      }
      function layoutIcon(shape) {
        if (shape.count > 16)
          return `<span class="wall-layout-numeric">${icon("layout-grid")}<span>${shape.count}</span></span>`;
        const step = 24 / shape.columns,
          gap = 1.4,
          cells = [];
        for (let y = 0; y < shape.rows; y++)
          for (let x = 0; x < shape.columns; x++) {
            if (shape.large && x < shape.large && y < shape.large && (x || y))
              continue;
            const size = shape.large && x === 0 && y === 0 ? shape.large : 1;
            cells.push(
              `<rect x="${x * step + gap / 2}" y="${y * step + gap / 2}" width="${step * size - gap}" height="${step * size - gap}" rx="0.7"/>`,
            );
          }
        return `<svg class="wall-layout-diagram" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" aria-hidden="true">${cells.join("")}</svg>`;
      }
      function tile(cell, index) {
        if (!cell)
          return `<button type="button" class="wall-empty" data-empty="${index}"><span>${String(index + m.page * capacity() + 1).padStart(2, "0")}</span>${icon("plus")}<small>${stateText("Выберите камеру", "Choose camera")}</small></button>`;
        const c = camera(cell.camera_id);
        return `<article class="wall-tile ${selected === cell.uid ? "selected" : ""}" tabindex="0" data-tile="${cell.uid}" draggable="true" aria-label="${h(c.name)}"><header><span class="wall-channel">${String(m.page * capacity() + index + 1).padStart(2, "0")}</span><strong title="${h(c.name)}">${h(c.name)}</strong><span class="wall-stream-status" id="live-status-${cell.uid}">${stateText("Соединение", "Connecting")}</span><div class="wall-tile-actions">${c.protocol === "dvrip" ? `<select data-quality="${cell.uid}" aria-label="Stream"><option value="sub" ${cell.stream === "sub" ? "selected" : ""}>SD</option><option value="main" ${cell.stream === "main" ? "selected" : ""}>HD</option></select>` : ""}<button type="button" class="icon-btn" data-focus="${cell.uid}" title="${stateText("Развернуть", "Expand")}">${icon("expand")}</button><button type="button" class="icon-btn" data-remove="${cell.uid}" title="${t("Удалить")}">${icon("close")}</button></div></header><div class="wall-video"><video id="live-video-${cell.uid}" autoplay muted playsinline></video><div class="wall-overlay" id="live-overlay-${cell.uid}"><span class="spin"></span><strong>${stateText("Подключение к камере", "Connecting to camera")}</strong></div></div><footer><span>${h(deviceLabel(c))}${c.protocol === "dvrip" ? ` / CH ${Number(c.channel || 0) + 1}` : ""}</span><span>${c.protocol === "dvrip" ? "DVRIP" : "RTSP"}</span></footer></article>`;
      }
      function stateText(ru, en) {
        return H.state.language === "en" ? en : ru;
      }
      function deviceKey(c) {
        return c.recorder_id || `${c.protocol}|${c.ip}|${c.port}`;
      }
      function deviceLabel(c) {
        return H.state.branding.recorder_labels === "name"
          ? c.recorder_name || c.ip
          : c.ip;
      }
      function captureTree() {
        const list = $("#wall-tree-list");
        if (!list) return;
        treeScroll = list.scrollTop;
        list
          .querySelectorAll("details[data-node]")
          .forEach((el) => treeOpen.set(el.dataset.node, el.open));
      }
      function treeHTML() {
        const query = treeQuery.toLocaleLowerCase().trim();
        const match = (c) =>
          `${c.name} ${c.ip} ${c.recorder_name || ""}`
            .toLocaleLowerCase()
            .includes(query);
        const leaf = (c) =>
          `<button type="button" class="wall-tree-camera" draggable="true" data-camera="${h(c.id)}" title="${h(c.name)}">${icon(c.device_kind === "recorder" ? "webcam" : "camera")}<span>${h(c.name)}</span><small>${c.device_kind === "recorder" ? Number(c.channel || 0) + 1 : "IP"}</small></button>`;
        const node = (selection, label, symbol, members, children) => {
          const key = selection.kind + ":" + selection.id;
          return `<details data-node="${h(key)}" ${treeOpen.get(key) === false && !query ? "" : "open"}><summary>${window.VWSIcons.html(symbol, "folder")}<button type="button" class="wall-tree-collection" draggable="${!!members.length}" data-collection="${h(JSON.stringify(selection))}" data-label="${h(label)}" ${members.length ? "" : "disabled"} title="${stateText("Открыть все камеры", "Open all cameras")}"><span>${h(label)}</span><small>${members.length}</small>${icon("plus")}</button></summary><div>${children}</div></details>`;
        };
        let html = `<div class="wall-tree-global"><button type="button" class="wall-tree-collection" draggable="true" data-collection="${h(JSON.stringify({ kind: "all" }))}" data-label="${stateText("Все источники", "All sources")}">${icon("monitor")}<span>${stateText("Все источники", "All sources")}</span><small>${cameras.length}</small>${icon("plus")}</button></div>`;
        if (m.treeMode === "devices") {
          const available = cameras;
          const hosts = new Map();
          for (const camera of available) {
            const id = deviceKey(camera);
            if (!hosts.has(id)) hosts.set(id, []);
            hosts.get(id).push(camera);
          }
          for (const [id, members] of hosts) {
            const label = deviceLabel(members[0]),
              filtered = label.toLocaleLowerCase().includes(query)
                ? members
                : members.filter(match);
            if (!filtered.length && query) continue;
            html += node(
              { kind: "device", id },
              label,
              members[0].device_kind === "recorder" ? "server" : "camera",
              members,
              filtered.map(leaf).join(""),
            );
          }
        } else {
          for (const space of groups.filter(
            (g) => !m.group || g.id === m.group,
          )) {
            const all = model.collection(cameras, groups, {
                kind: "space",
                id: space.id,
              }),
              spaceMatch = space.name.toLocaleLowerCase().includes(query);
            let children = model
              .collection(cameras, groups, {
                kind: "space",
                id: space.id,
                root_only: true,
              })
              .filter((c) => spaceMatch || match(c))
              .map(leaf)
              .join("");
            for (const zone of space.zones || []) {
              const members = model.collection(cameras, groups, {
                kind: "zone",
                space_id: space.id,
                id: zone.id,
              });
              const filtered =
                spaceMatch || zone.name.toLocaleLowerCase().includes(query)
                  ? members
                  : members.filter(match);
              if (!query || filtered.length)
                children += node(
                  { kind: "zone", id: zone.id, space_id: space.id },
                  zone.name,
                  zone.icon || "map-pin",
                  members,
                  filtered.map(leaf).join(""),
                );
            }
            if (!query || spaceMatch || children)
              html += node(
                { kind: "space", id: space.id },
                space.name,
                space.icon || "layers-3",
                all,
                children,
              );
          }
          if (!m.group) {
            const members = model.collection(cameras, groups, {
                kind: "unassigned",
              }),
              filtered = members.filter(match);
            if (filtered.length)
              html += node(
                { kind: "unassigned", id: "unassigned" },
                stateText("Без пространства", "Unassigned"),
                "folder-open",
                members,
                filtered.map(leaf).join(""),
              );
          }
        }
        return (
          html ||
          `<p class="muted" style="padding:15px">${t("Ничего не найдено")}</p>`
        );
      }
      function setCollection(selection, label = "") {
        m.cells = model
          .collection(cameras, groups, selection)
          .map((c) => make(c.id));
        m.group =
          selection.kind === "space"
            ? selection.id
            : selection.kind === "zone"
              ? selection.space_id
              : "";
        m.title = label;
        m.page = 0;
        focusRestore = null;
        useLayout(model.fit(m.cells.length));
        render();
      }
      function bindTree() {
        $$("[data-collection]").forEach((button) => {
          on(button, "click", (event) => {
            event.preventDefault();
            event.stopPropagation();
            setCollection(
              JSON.parse(button.dataset.collection),
              button.dataset.label,
            );
          });
          on(button, "dragstart", (event) => {
            captureTree();
            event.stopPropagation();
            event.dataTransfer.setData(
              "application/x-vwshub-collection",
              JSON.stringify({
                selection: JSON.parse(button.dataset.collection),
                label: button.dataset.label,
              }),
            );
            event.dataTransfer.effectAllowed = "copy";
          });
        });
        $$(".wall-tree-camera").forEach((button) => {
          on(button, "dragstart", (event) => {
            captureTree();
            event.dataTransfer.setData("text/plain", button.dataset.camera);
            event.dataTransfer.effectAllowed = "copy";
          });
          on(button, "dblclick", () => place(button.dataset.camera, selected));
          on(button, "keydown", (event) => {
            if (event.key === "Enter") place(button.dataset.camera, selected);
          });
        });
        on($("#wall-tree-list"), "scroll", () => {
          treeScroll = $("#wall-tree-list").scrollTop;
        });
      }
      function render() {
        captureTree();
        const retained = new Map();
        const visibleCells = visible();
        const desired = visibleCells
          .filter(Boolean)
          .slice(0, Math.max(1, Number(settings.max_live_streams) || 16));
        const removed = [];
        for (const [id, item] of players) {
          const cell = desired.find((c) => c?.uid === id);
          if (cell && cell.stream === item.stream) {
            const tile = item.video.closest(".wall-tile");
            if (tile) retained.set(id, tile);
          } else {
            item.hls?.destroy();
            item.video.pause();
            item.video.removeAttribute("src");
            item.video.load();
            players.delete(id);
            if (
              !desired.some(
                (c) =>
                  c?.camera_id === item.camera_id && c.stream === item.stream,
              )
            )
              removed.push(item);
          }
        }
        release(removed);
        ptzCleanup?.();
        ptzCleanup = null;
        context?.remove();
        const cells = visible(),
          cap = capacity(),
          pages = Math.max(1, Math.ceil(m.cells.length / cap));
        if (!cells.some((c) => c?.uid === selected))
          selected = cells.find(Boolean)?.uid || null;
        root.innerHTML = `<section class="wall-console"><header class="wall-toolbar"><div class="wall-heading">${icon("monitor")}<h1>${t("Просмотр")}</h1><span>LIVE MONITOR</span></div><div class="row-actions"><button type="button" id="wall-tree-toggle" class="icon-btn" aria-pressed="${m.tree}" aria-label="${stateText("Панель источников", "Source panel")}" title="${stateText("Панель источников", "Source panel")}">${icon(m.tree ? "panel-left-close" : "panel-left-open")}</button><div class="wall-layouts">${model.layouts.map((shape) => `<button type="button" data-layout="${shape.id}" aria-label="${shape.count} ${stateText(shape.count === 1 ? "окно" : shape.count === 4 ? "окна" : "окон", shape.count === 1 ? "window" : "windows")}" title="${shape.count} ${stateText(shape.count === 1 ? "окно" : shape.count === 4 ? "окна" : "окон", shape.count === 1 ? "window" : "windows")}" aria-pressed="${m.layout === shape.id}">${layoutIcon(shape)}</button>`).join("")}</div><button type="button" class="btn btn-sm" id="view-save" title="${stateText("Сохранить в браузере", "Save in browser")}">${icon("check")}<span>${t("Сохранить")}</span></button><button type="button" class="icon-btn" id="view-export" title="${stateText("Экспорт вида", "Export view")}">${icon("download")}</button><button type="button" class="icon-btn" id="view-import" title="${stateText("Импорт вида", "Import view")}">${icon("upload")}</button><button type="button" class="icon-btn" id="wall-fullscreen" title="${stateText("На весь экран", "Fullscreen")}">${icon("expand")}</button><button type="button" class="icon-btn" id="wall-inspector-toggle" title="${t("Параметры подключения")}">${icon("settings")}</button></div></header><div class="wall-body ${m.tree ? "" : "no-tree"} ${m.inspector ? "with-inspector" : ""}"><aside class="wall-tree"><div class="wall-tree-head"><strong>${stateText("Источники", "Sources")}</strong><span>${cameras.length}</span></div><div class="wall-tree-modes" role="tablist" aria-label="${stateText("Дерево источников", "Source tree")}"><button type="button" data-tree-mode="spaces" role="tab" aria-selected="${m.treeMode === "spaces"}">${icon("layers-3")}${stateText("Пространства", "Spaces")}</button><button type="button" data-tree-mode="devices" role="tab" aria-selected="${m.treeMode === "devices"}">${icon("video")}${stateText("Устройства", "Devices")}</button></div><div class="wall-tree-filters"><input id="wall-search" class="field" placeholder="${t("Поиск камер")}" value="${h(treeQuery)}"><select class="select" id="wall-group" ${m.treeMode === "devices" ? "hidden" : ""}><option value="">${stateText("Все пространства", "All spaces")}</option>${groups.map((g) => `<option value="${h(g.id)}" ${m.group === g.id ? "selected" : ""}>${h(g.name)}</option>`).join("")}</select></div><div class="wall-tree-list" id="wall-tree-list">${treeHTML()}</div><div class="wall-tree-bottom"><p>${stateText("Перетащите камеру в ячейку.<br>Двойной щелчок — развернуть.", "Drag a camera into a cell.<br>Double-click to expand.")}</p></div></aside><div class="wall-monitor"><div class="wall-monitor-head"><span>${icon("grid")}${h(m.title || groups.find((g) => g.id === m.group)?.name || stateText("Основной монитор", "Main monitor"))}</span><div>${buttonIcon("wall-prev", "left", m.page === 0)}<span>${m.page + 1} / ${pages}</span>${buttonIcon("wall-next", "right", m.page === pages - 1)}<button type="button" class="icon-btn ${sequence ? "active" : ""}" id="wall-sequence" aria-pressed="${!!sequence}" title="${stateText("Автосмена каждые 15 секунд", "Cycle pages every 15 seconds")}">${icon("route")}</button></div></div><div class="wall-grid" id="wall-grid" data-layout="${m.layout}" style="--columns:${m.columns};--rows:${model.layout(m.layout).rows};--large:${model.layout(m.layout).large || 1};--wall-gap:${Number(H.state.branding.wall_gap ?? 3)}px">${Array.from({ length: cap }, (_, i) => tile(cells[i] || null, i)).join("")}</div><div class="wall-transport"><div id="wall-selected"></div><div class="row-actions"><button type="button" id="wall-reconnect" class="icon-btn" title="${t("Обновить")}">${icon("refresh")}</button><button type="button" id="wall-snapshot" class="icon-btn" title="${t("Фотоаппарат")}" aria-label="${t("Фотоаппарат")}">${icon("photo")}</button><button type="button" id="wall-to-archive" class="icon-btn" title="${t("Архив")}" aria-label="${t("Архив")}">${icon("archive")}</button></div></div></div><aside class="wall-inspector" id="wall-inspector"></aside></div><footer class="wall-status"><span><i class="dot online"></i> VWSHub 0.8.5</span><span id="wall-streams">${stateText("Соединение с потоками…", "Connecting streams…")}</span><span id="wall-clock"></span></footer></section>`;
        for (const [id, tile] of retained) {
          const placeholder = $("[data-tile='" + id + "']");
          if (placeholder) {
            placeholder.replaceWith(tile);
            const item = players.get(id);
            if (item?.video.paused) item.video.play().catch(() => {});
            const index = visibleCells.findIndex((c) => c?.uid === id);
            const source = camera(item.camera_id);
            tile.setAttribute("aria-label", source.name);
            const name = tile.querySelector("header strong");
            name.textContent = source.name;
            name.title = source.name;
            tile.querySelector("footer span").textContent =
              deviceLabel(source) +
              (source.protocol === "dvrip"
                ? ` / CH ${Number(source.channel || 0) + 1}`
                : "");
            tile.querySelector(".wall-channel").textContent = String(
              m.page * capacity() + index + 1,
            ).padStart(2, "0");
          }
        }
        $("#wall-tree-list").scrollTop = treeScroll;
        requestAnimationFrame(() => {
          if (!disposed && $("#wall-tree-list"))
            $("#wall-tree-list").scrollTop = treeScroll;
        });
        $$("[data-tree-mode]").forEach((button) =>
          on(button, "click", () => {
            m.treeMode = button.dataset.treeMode;
            treeScroll = 0;
            render();
          }),
        );
        on($("#wall-tree-toggle"), "click", () => {
          m.tree = !m.tree;
          $(".wall-body").classList.toggle("no-tree", !m.tree);
        });
        on($("#wall-inspector-toggle"), "click", () => {
          m.inspector = !m.inspector;
          $(".wall-body").classList.toggle("with-inspector", m.inspector);
          if (m.inspector) inspector();
          else {
            ptzCleanup?.();
            ptzCleanup = null;
          }
        });
        on($("#wall-search"), "input", (e) => {
          captureTree();
          treeQuery = e.target.value;
          $("#wall-tree-list").innerHTML = treeHTML();
          bindTree();
        });
        on($("#wall-group"), "change", (e) => {
          m.group = e.target.value;
          setGroup();
        });

        $$("button[data-layout]").forEach((b) =>
          on(b, "click", () => {
            useLayout(b.dataset.layout);
            m.page = 0;
            focusRestore = null;
            render();
          }),
        );
        on($("#wall-prev"), "click", () => {
          m.page--;
          focusRestore = null;
          render();
        });
        on($("#wall-next"), "click", () => {
          m.page++;
          focusRestore = null;
          render();
        });
        on($("#wall-sequence"), "click", () => {
          if (sequence) {
            clearInterval(sequence);
            sequence = null;
          } else
            sequence = setInterval(() => {
              const count = Math.ceil(m.cells.length / capacity());
              if (!disposed && count > 1) {
                m.page = (m.page + 1) % count;
                render();
              }
            }, 15000);
          $("#wall-sequence").classList.toggle("active", !!sequence);
          $("#wall-sequence").setAttribute("aria-pressed", String(!!sequence));
        });
        on($("#view-save"), "click", save);
        on($("#view-export"), "click", () =>
          H.downloadJSON(
            model.serialize(m.layout, m.cells),
            "vwshub-view.json",
          ),
        );
        on($("#view-import"), "click", () =>
          H.pickJSON(async (value) => {
            const v = model.normalize(value, cameras);
            useLayout(v.layout);
            m.cells = v.cells.map((c) =>
              c ? make(c.camera_id, c.stream) : null,
            );
            m.page = 0;
            m.group = "";
            focusRestore = null;
            render();
            save();
            if (v.unavailable)
              toast(
                stateText(
                  "Недоступные камеры оставлены пустыми: ",
                  "Unavailable cameras left blank: ",
                ) + v.unavailable,
                "warning",
              );
          }),
        );
        on($("#wall-fullscreen"), "click", () => {
          if (document.fullscreenElement) document.exitFullscreen?.();
          else
            $(".wall-monitor")
              .requestFullscreen?.()
              .catch(() =>
                toast(
                  stateText(
                    "Полноэкранный режим недоступен",
                    "Fullscreen is unavailable",
                  ),
                  "warning",
                ),
              );
        });
        on($("#wall-reconnect"), "click", () => {
          const s = m.cells.find((c) => c?.uid === selected);
          if (s) {
            const item = players.get(s.uid);
            item?.hls?.destroy();
            players.delete(s.uid);
            attach(s);
          }
        });
        on($("#wall-snapshot"), "click", snapshot);
        on($("#wall-to-archive"), "click", () => {
          const c = selectedCamera();
          if (
            c?.protocol === "dvrip" &&
            (user.role === "admin" || user.archive_access)
          )
            onArchive(c.id);
        });
        $$("[data-focus]").forEach((b) =>
          on(b, "click", (e) => {
            e.stopPropagation();
            focus(Number(b.dataset.focus));
          }),
        );
        $$("[data-remove]").forEach((b) =>
          on(b, "click", (e) => {
            e.stopPropagation();
            remove(Number(b.dataset.remove));
          }),
        );
        $$("[data-quality]").forEach((s) =>
          on(s, "change", () => {
            m.cells.find((c) => c?.uid === Number(s.dataset.quality)).stream =
              s.value;
            render();
          }),
        );
        $$(".wall-tile").forEach((el) => {
          on(el, "click", () => select(Number(el.dataset.tile)));
          on(el, "dblclick", (e) => {
            if (!e.target.closest("button,select"))
              focus(Number(el.dataset.tile));
          });
          on(el, "keydown", (e) => {
            if (e.key === "0" && !e.target.closest("button,select")) {
              e.preventDefault();
              zoom(1, 0, 0);
            }
            if (e.key === "Enter" && !e.target.closest("button,select"))
              focus(Number(el.dataset.tile));
          });
          on(el, "contextmenu", (e) => {
            e.preventDefault();
            select(Number(el.dataset.tile));
            contextMenu(e.clientX, e.clientY);
          });
          on(el, "dragstart", (e) => {
            if (e.target.closest("video,button,select")) {
              e.preventDefault();
              return;
            }
            e.dataTransfer.setData(
              "application/x-vwshub-tile",
              el.dataset.tile,
            );
          });
          const stage = el.querySelector(".wall-video");
          const getCell = () =>
            m.cells.find((c) => c?.uid === Number(el.dataset.tile));
          const zoom = (value, x, y) => {
            const c = getCell(),
              v = el.querySelector("video"),
              r = stage.getBoundingClientRect();
            if (!c || !v.videoWidth) return;
            Object.assign(
              c,
              model.pan(
                value,
                x,
                y,
                r.width,
                r.height,
                v.videoWidth,
                v.videoHeight,
              ),
            );
            v.style.transformOrigin = "center";
            v.style.transform = `translate(${c.x}px,${c.y}px) scale(${c.zoom})`;
            v.dataset.zoom = c.zoom;
            stage.classList.toggle("is-zoomed", c.zoom > 1);
            el.draggable = c.zoom <= 1;
          };
          on(
            stage,
            "wheel",
            (e) => {
              const c = getCell(),
                v = el.querySelector("video");
              if (!v.videoWidth) return;
              e.preventDefault();
              const r = stage.getBoundingClientRect(),
                old = c.zoom || 1,
                z = Math.max(
                  1,
                  Math.min(8, old * Math.exp(-e.deltaY * 0.0015)),
                ),
                ratio = z / old;
              zoom(
                z,
                (c.x || 0) * ratio +
                  (1 - ratio) * (e.clientX - r.left - r.width / 2),
                (c.y || 0) * ratio +
                  (1 - ratio) * (e.clientY - r.top - r.height / 2),
              );
            },
            { passive: false },
          );
          let drag = null;
          on(stage, "pointerdown", (e) => {
            const c = getCell();
            if (
              e.button !== 0 ||
              !c ||
              !(c.zoom > 1) ||
              e.target.closest("button")
            )
              return;
            e.preventDefault();
            select(c.uid);
            drag = {
              id: e.pointerId,
              x: e.clientX,
              y: e.clientY,
              panX: c.x || 0,
              panY: c.y || 0,
            };
            stage.setPointerCapture(e.pointerId);
            stage.classList.add("is-panning");
          });
          on(stage, "pointermove", (e) => {
            if (drag && drag.id === e.pointerId)
              zoom(
                getCell().zoom,
                drag.panX + e.clientX - drag.x,
                drag.panY + e.clientY - drag.y,
              );
          });
          const endPan = (e) => {
            if (drag && drag.id === e.pointerId) {
              drag = null;
              stage.classList.remove("is-panning");
              if (stage.hasPointerCapture(e.pointerId))
                stage.releasePointerCapture(e.pointerId);
            }
          };
          on(stage, "pointerup", endPan);
          on(stage, "pointercancel", endPan);
          on(stage, "lostpointercapture", () => {
            drag = null;
            stage.classList.remove("is-panning");
          });
          on(el, "keydown", (e) => {
            if (e.key === "0" && !e.target.closest("button,select")) {
              e.preventDefault();
              zoom(1, 0, 0);
            }
          });
        });
        $$(".wall-grid > *").forEach((el) => {
          on(el, "dragover", (e) => {
            e.preventDefault();
            el.classList.add("drop-target");
          });
          on(el, "dragleave", () => el.classList.remove("drop-target"));
          on(el, "drop", (e) => {
            e.preventDefault();
            const collection = e.dataTransfer.getData(
              "application/x-vwshub-collection",
            );
            if (collection) {
              try {
                const data = JSON.parse(collection);
                if (
                  ["space", "zone", "device", "unassigned"].includes(
                    data.selection?.kind,
                  )
                )
                  setCollection(data.selection, data.label);
              } catch (_) {}
              return;
            }
            const source = Number(
                e.dataTransfer.getData("application/x-vwshub-tile"),
              ),
              dest = el.dataset.tile
                ? m.cells.findIndex((c) => c?.uid === Number(el.dataset.tile))
                : m.page * capacity() + Number(el.dataset.empty);
            if (source) {
              const i = m.cells.findIndex((c) => c?.uid === source);
              if (i < 0) return;
              while (m.cells.length <= dest) m.cells.push(null);
              [m.cells[i], m.cells[dest]] = [m.cells[dest], m.cells[i]];
              render();
            } else
              place(
                e.dataTransfer.getData("text/plain"),
                el.dataset.tile ? Number(el.dataset.tile) : null,
                Number(el.dataset.empty),
              );
          });
        });
        $$("[data-empty]").forEach((b) =>
          on(b, "click", () => choose(Number(b.dataset.empty))),
        );
        bindTree();
        select(selected);
        updateClock();
        requestAnimationFrame(() => {
          if (disposed) return;
          const active = cells.filter(Boolean),
            limit = Math.max(1, Number(settings.max_live_streams) || 16);
          active.slice(0, limit).forEach(attach);
          active.slice(limit).forEach((cell) => {
            const overlay = $("#live-overlay-" + cell.uid),
              badge = $("#live-status-" + cell.uid);
            badge.textContent = stateText("Лимит", "Limit");
            badge.dataset.state = "limited";
            overlay.innerHTML = `${icon("grid")}<strong>${stateText("Лимит потоков сервера", "Server stream limit")}: ${limit}</strong><button type="button" class="btn btn-sm">${stateText("Открыть отдельно", "Open separately")}</button>`;
            on(overlay.querySelector("button"), "click", (e) => {
              e.stopPropagation();
              focus(cell.uid);
            });
          });
          summary();
        });
      }
      function buttonIcon(id, symbol, disabled = false) {
        return `<button class="icon-btn" id="${id}" ${disabled ? "disabled" : ""}>${icon(symbol)}</button>`;
      }
      function save() {
        try {
          localStorage.setItem(
            key,
            JSON.stringify(model.serialize(m.layout, m.cells)),
          );
          toast("Сохранено");
        } catch (e) {
          toast(e.message, "error");
        }
      }
      function setGroup() {
        const space = groups.find((g) => g.id === m.group);
        setCollection(
          space ? { kind: "space", id: space.id } : { kind: "all" },
          space?.name || "",
        );
      }
      function selectedCamera() {
        return camera(m.cells.find((c) => c?.uid === selected)?.camera_id);
      }
      function select(id) {
        selected = id;
        $$(".wall-tile").forEach((el) =>
          el.classList.toggle("selected", Number(el.dataset.tile) === id),
        );
        const c = selectedCamera();
        $("#wall-selected").innerHTML =
          `${icon("camera")}<strong>${h(c?.name || stateText("Камера не выбрана", "No camera selected"))}</strong><small>${h(c ? deviceLabel(c) : "")}</small>`;
        $("#wall-to-archive").disabled =
          !c ||
          c.protocol !== "dvrip" ||
          !(user.role === "admin" || user.archive_access);
        if (m.inspector) inspector();
      }
      function inspector() {
        ptzCleanup?.();
        ptzCleanup = null;
        const c = selectedCamera(),
          el = $("#wall-inspector");
        el.innerHTML = `<div class="wall-inspector-head"><strong>${stateText("Активная камера", "Selected camera")}</strong>${icon("camera")}</div>${c ? `<div class="wall-inspector-body"><h2>${h(c.name)}</h2><dl><dt>IP</dt><dd>${h(c.ip)}</dd><dt>${t("Протокол подключения")}</dt><dd>${c.protocol === "dvrip" ? "DVRIP" : "ONVIF / RTSP"}</dd><dt>${t("Канал")}</dt><dd>${Number(c.channel || 0) + 1}</dd></dl><button class="btn btn-sm" id="inspector-photo">${icon("photo")}${t("Фотоаппарат")}</button>${user.role === "admin" ? `<button class="btn btn-sm" id="inspector-device">${icon("settings")}${t("Устройства")}</button><div id="live-ptz"><button class="btn btn-sm" id="live-ptz-open">PTZ</button></div>` : ""}</div>` : ""}`;
        on($("#inspector-photo"), "click", snapshot);
        on($("#inspector-device"), "click", () => H.showView("devices"));
        on($("#live-ptz-open"), "click", () => {
          if (window.VWSDevices.mountPTZ)
            ptzCleanup = window.VWSDevices.mountPTZ($("#live-ptz"), c, {
              api: H.api,
              isAdmin: user.role === "admin",
              onError: (m) => toast(m, "error"),
              onSuccess: toast,
            });
        });
      }
      function place(id, target = null, emptyIndex = 0) {
        if (!camera(id)) return;
        const group = groups.find((g) => g.id === m.group);
        if (group && !group.camera_ids.includes(id)) m.group = "";
        const dest = target
          ? m.cells.findIndex((c) => c?.uid === target)
          : m.page * capacity() + emptyIndex;
        if (dest < 0) return;
        while (m.cells.length <= dest) m.cells.push(null);
        m.cells[dest] = make(id);
        selected = m.cells[dest].uid;
        render();
      }
      function choose(index) {
        H.modal(
          stateText("Выбрать камеру", "Select camera"),
          "",
          `<div class="form-stack">${cameras.map((c) => `<button type="button" class="btn" data-pick="${h(c.id)}" style="justify-content:flex-start">${icon("camera")}${h(c.name)}</button>`).join("") || `<span class="muted">${t("У вас пока нет доступных камер")}</span>`}</div>`,
        );
        document.querySelectorAll("[data-pick]").forEach(
          (b) =>
            (b.onclick = () => {
              H.closeModal();
              place(b.dataset.pick, null, index);
            }),
        );
      }
      function focus(id) {
        const i = m.cells.findIndex((c) => c?.uid === id);
        if (i < 0) return;
        if (focusRestore) {
          useLayout(focusRestore.layout);
          m.page = focusRestore.page;
          focusRestore = null;
        } else {
          focusRestore = { layout: m.layout, page: m.page };
          useLayout("1");
          m.page = i;
        }
        selected = id;
        render();
      }
      function remove(id) {
        m.cells = m.cells.map((c) => (c?.uid === id ? null : c));
        while (m.cells.length && !m.cells.at(-1)) m.cells.pop();
        render();
      }
      async function snapshot() {
        const c = selectedCamera();
        if (!c) return;
        const slot = m.cells.find((x) => x?.uid === selected),
          v = $("#live-video-" + slot.uid);
        const format = settings.snapshot_format || "jpeg";
        try {
          let blob;
          if (v?.videoWidth) {
            const canvas = document.createElement("canvas");
            canvas.width = v.videoWidth;
            canvas.height = v.videoHeight;
            canvas.getContext("2d").drawImage(v, 0, 0);
            blob = await new Promise((resolve) =>
              canvas.toBlob(resolve, "image/" + format, 0.95),
            );
          } else {
            const res = await fetch(
              "/api/cameras/" +
                encodeURIComponent(c.id) +
                "/snapshot?format=" +
                format,
              { credentials: "same-origin" },
            );
            if (!res.ok) {
              const data = await res.json();
              throw new Error(data.error || "Snapshot failed");
            }
            blob = await res.blob();
          }
          if (!blob) throw new Error("Snapshot failed");
          const url = URL.createObjectURL(blob),
            a = document.createElement("a");
          a.href = url;
          a.download = `${c.name.replace(/[^\p{L}\p{N}._-]+/gu, "-")}-${Date.now()}.${format === "jpeg" ? "jpg" : format}`;
          a.click();
          setTimeout(() => URL.revokeObjectURL(url), 3000);
        } catch (e) {
          toast(e.message, "error");
        }
      }
      function contextMenu(x, y) {
        context?.remove();
        context = document.createElement("div");
        context.className = "wall-context";
        const actions = [
          [
            "expand",
            stateText("Развернуть / вернуть", "Expand / restore"),
            () => focus(selected),
          ],
          ["photo", t("Фотоаппарат"), snapshot],
          ["refresh", t("Обновить"), () => $("#wall-reconnect").click()],
          ["archive", t("Архив"), () => $("#wall-to-archive").click()],
          [
            "close",
            stateText("Убрать с экрана", "Remove from view"),
            () => remove(selected),
          ],
        ];
        for (const [symbol, label, fn] of actions) {
          const b = document.createElement("button");
          b.innerHTML = `${icon(symbol)}<span>${h(label)}</span>`;
          if (symbol === "archive") b.disabled = $("#wall-to-archive").disabled;
          b.onclick = () => {
            context.remove();
            fn();
          };
          context.append(b);
        }
        (document.fullscreenElement || document.body).append(context);
        context.style.left =
          Math.max(8, Math.min(x, innerWidth - context.offsetWidth - 8)) + "px";
        context.style.top =
          Math.max(8, Math.min(y, innerHeight - context.offsetHeight - 8)) +
          "px";
      }
      function summary() {
        const states = $$(".wall-stream-status");
        const el = $("#wall-streams");
        if (el)
          el.textContent = `${stateText("Видео", "Video")}: ${states.filter((n) => n.dataset.state === "playing").length} / ${states.length}`;
      }
      function attach(cell, attempt = 0) {
        if (disposed || players.has(cell.uid)) return;
        const video = $("#live-video-" + cell.uid),
          overlay = $("#live-overlay-" + cell.uid),
          badge = $("#live-status-" + cell.uid);
        if (!video) return;
        const item = {
          video,
          hls: null,
          stream: cell.stream,
          camera_id: cell.camera_id,
        };
        players.set(cell.uid, item);
        const set = (status, text) => {
          badge.dataset.state = status;
          badge.textContent = text;
          summary();
        };
        const fail = () => {
          if (disposed || !video.isConnected) return;
          set("error", stateText("Нет связи", "Offline"));
          overlay.hidden = false;
          overlay.innerHTML = `${icon("camera")}<strong>${stateText("Нет видеосигнала", "No video signal")}</strong><button type="button" class="btn btn-sm">${icon("refresh")}${stateText("Повторить", "Retry")}</button>`;
          overlay.querySelector("button").onclick = (e) => {
            e.stopPropagation();
            item.hls?.destroy();
            players.delete(cell.uid);
            attach(cell);
          };
        };
        set("connecting", stateText("Соединение", "Connecting"));
        overlay.hidden = false;
        overlay.innerHTML = `<span class="spin"></span><strong>${stateText("Подключение", "Connecting")}</strong>`;
        video.onplaying = () => {
          overlay.hidden = true;
          set("playing", "LIVE");
        };
        video.onerror = fail;
        const url = `/live/${encodeURIComponent(cell.camera_id)}/${cell.stream}/index.m3u8?consumer=${consumer}`;
        if (window.Hls?.isSupported()) {
          const hls = new Hls({
            liveSyncDurationCount: 3,
            lowLatencyMode: false,
            maxBufferLength: 12,
          });
          item.hls = hls;
          hls.on(Hls.Events.MANIFEST_PARSED, () => video.play().catch(fail));
          hls.on(Hls.Events.ERROR, (_e, data) => {
            if (!data.fatal || disposed || players.get(cell.uid) !== item)
              return;
            hls.destroy();
            players.delete(cell.uid);
            if (data.type === Hls.ErrorTypes.NETWORK_ERROR && attempt < 2)
              later(() => attach(cell, attempt + 1), 2000 * (attempt + 1));
            else fail();
          });
          hls.loadSource(url);
          hls.attachMedia(video);
        } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
          video.src = url;
          video.play().catch(fail);
        } else fail();
      }
      function updateClock() {
        const el = $("#wall-clock");
        if (el)
          el.textContent =
            H.state.branding.show_clock === false
              ? ""
              : new Date().toLocaleString(
                  H.state.language === "en" ? "en-GB" : "ru-RU",
                );
      }
      on(document, "pointerdown", (e) => {
        if (!e.target.closest(".wall-context")) context?.remove();
      });
      on(document, "keydown", (e) => {
        if (e.target.closest("input,select,textarea,button,.modal")) return;
        if (e.key === "Escape" && focusRestore) {
          focus(selected);
          return;
        }
        if (["1", "2", "3", "4"].includes(e.key)) {
          useLayout(String(Number(e.key) ** 2));
          m.page = 0;
          focusRestore = null;
          render();
        }
        if (e.ctrlKey && e.key.toLowerCase() === "s") {
          e.preventDefault();
          save();
        }
        if (e.key === "ArrowRight" && !$("#wall-next").disabled)
          $("#wall-next").click();
        if (e.key === "ArrowLeft" && !$("#wall-prev").disabled)
          $("#wall-prev").click();
      });
      on(window, "vwshub:catalog", () => {
        if (disposed) return;
        const old = m.cells.filter(Boolean).length;
        m.cells = model.reconcile(m.cells, cameras);
        if (focusRestore && !m.cells.some((c) => c?.uid === selected)) {
          useLayout(focusRestore.layout);
          m.page = focusRestore.page;
          focusRestore = null;
        }
        if (m.group && !groups.some((g) => g.id === m.group)) {
          m.group = "";
          m.title = "";
        }
        render();
        if (m.cells.filter(Boolean).length < old)
          toast(
            stateText(
              "Недоступные камеры убраны с видеостены",
              "Unavailable cameras removed from the video wall",
            ),
            "warning",
          );
      });
      if (matchMedia("(max-width:560px)").matches) m.tree = false;
      render();
      const clock = setInterval(updateClock, 1000);
      return () => {
        disposed = true;
        life.abort();
        clearInterval(clock);
        clearInterval(sequence);
        for (const timer of timers) clearTimeout(timer);
        stopPlayers();
        context?.remove();
        m.cells = m.cells.map((c) =>
          c
            ? {
                camera_id: c.camera_id,
                stream: c.stream,
                visibility_revision: c.visibility_revision || 0,
                ...(c.origin_id
                  ? { origin_id: c.origin_id, source_id: c.source_id }
                  : {}),
              }
            : null,
        );
      };
    },
  };
})();
