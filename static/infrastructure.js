/* VWSHub 0.8.5: physical inventory, spaces, zones and resource access. */
(() => {
  "use strict";
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [
    ...root.querySelectorAll(selector),
  ];
  function iconPicker(host, current = "folder", H, onChange = () => {}) {
    const { h, icon } = H,
      L = (ru, en) => (H.state.language === "en" ? en : ru);
    let selected = current,
      query = "",
      offset = 0,
      category = "all";
    const recommended = [
      "folder",
      "building-2",
      "house",
      "warehouse",
      "store",
      "school",
      "hospital",
      "factory",
      "door-open",
      "map-pin",
      "parking-square",
      "trees",
      "shield",
      "briefcase-business",
      "landmark",
      "monitor",
      "server",
      "video",
    ];
    host.innerHTML = `<input type="hidden" name="icon" value="${h(current)}"><details class="infra-icon-picker"><summary><span data-picked-icon>${window.VWSIcons.html(current, "folder")}</span><span data-picked-name>${h(current)}</span>${icon("chevron-down")}</summary><div class="infra-icon-controls"><label class="search-field">${icon("search")}<input type="search" aria-label="${h(L("Поиск значка", "Search icons"))}" placeholder="${h(L("Поиск значка", "Search icons"))}"></label><div class="infra-icon-grid"></div><div class="infra-icon-pages"><button type="button" class="icon-btn" data-icon-prev aria-label="${h(L("Назад", "Previous"))}">${icon("chevron-left")}</button><small data-icon-count></small><button type="button" class="icon-btn" data-icon-next aria-label="${h(L("Далее", "Next"))}">${icon("chevron-right")}</button></div></div></details>`;
    const categories = {
      all: null,
      buildings:
        /building|house|warehouse|store|school|hospital|factory|door|landmark|church|hotel/,
      security: /camera|webcam|video|cctv|shield|lock|eye|alarm/,
      people: /user|person|contact|baby|accessibility/,
      network:
        /server|network|router|wifi|ethernet|cable|cloud|monitor|computer/,
      nature: /tree|flower|leaf|mountain|sun|moon|cloud|rain|snow/,
      tools: /wrench|hammer|tool|settings|sliders|pencil|brush|ruler/,
    };
    const words = {
      камера: ["camera", "webcam", "cctv", "video"],
      склад: ["warehouse"],
      дом: ["house", "building"],
      здание: ["building"],
      магазин: ["store"],
      папка: ["folder"],
      сервер: ["server"],
      человек: ["user", "person"],
      замок: ["lock"],
      глаз: ["eye"],
      настройки: ["settings", "sliders"],
      школа: ["school"],
      офис: ["building", "briefcase"],
    };
    const labels = [
      ["all", L("Все значки", "All icons")],
      ["buildings", L("Объекты", "Buildings")],
      ["security", L("Наблюдение и безопасность", "Surveillance and security")],
      ["people", L("Люди", "People")],
      ["network", L("Техника и сеть", "Devices and network")],
      ["nature", L("Природа", "Nature")],
      ["tools", L("Инструменты", "Tools")],
    ];
    const select = document.createElement("select");
    select.className = "select infra-icon-category";
    select.setAttribute("aria-label", L("Категория значка", "Icon category"));
    select.innerHTML = labels
      .map(
        ([value, label]) =>
          '<option value="' + value + '">' + h(label) + "</option>",
      )
      .join("");
    $(".infra-icon-controls", host).insertBefore(
      select,
      $(".infra-icon-grid", host),
    );
    select.onchange = () => {
      category = select.value;
      offset = 0;
      render();
    };
    function render() {
      const aliases = query
        ? Object.entries(words)
            .filter(
              ([word]) => word.startsWith(query) || query.startsWith(word),
            )
            .flatMap(([, names]) => names)
        : [];
      const all = window.VWSIcons.names.filter(
        (name) =>
          (!categories[category] || categories[category].test(name)) &&
          (!query ||
            name.includes(query) ||
            aliases.some((alias) => name.includes(alias))),
      );
      const names = query
        ? all
        : [
            ...new Set([
              ...recommended.filter(
                (name) =>
                  window.VWSIcons.has(name) &&
                  (!categories[category] || categories[category].test(name)),
              ),
              ...all,
            ]),
          ];
      const slice = names.slice(offset, offset + 72);
      $(".infra-icon-grid", host).innerHTML = slice
        .map(
          (name) =>
            `<button type="button" class="icon-btn ${name === selected ? "selected" : ""}" data-icon="${h(name)}" title="${h(name)}" aria-label="${h(name)}">${window.VWSIcons.html(name)}</button>`,
        )
        .join("");
      $("[data-icon-count]", host).textContent =
        `${names.length ? offset + 1 : 0}–${Math.min(offset + 72, names.length)} / ${names.length}`;
      $("[data-icon-prev]", host).disabled = offset === 0;
      $("[data-icon-next]", host).disabled = offset + 72 >= names.length;
      $$("[data-icon]", host).forEach(
        (control) =>
          (control.onclick = () => {
            selected = control.dataset.icon;
            $("input[name=icon]", host).value = selected;
            $("[data-picked-icon]", host).innerHTML =
              window.VWSIcons.html(selected);
            $("[data-picked-name]", host).textContent = selected;
            $("details", host).open = false;
            render();
            onChange(selected);
          }),
      );
    }
    $("input[type=search]", host).oninput = (event) => {
      query = event.target.value.toLowerCase().trim();
      offset = 0;
      render();
    };
    $("[data-icon-prev]", host).onclick = () => {
      offset = Math.max(0, offset - 72);
      render();
    };
    $("[data-icon-next]", host).onclick = () => {
      offset += 72;
      render();
    };
    render();
  }

  function mount({ root, mode, hub: H }) {
    const { h, api, icon } = H,
      S = H.state;
    const L = (ru, en) => (S.language === "en" ? en : ru);
    const plural = (count, forms, en) =>
      `${count} ${S.language === "en" ? (count === 1 ? en[0] : en[1]) : forms[new Intl.PluralRules("ru").select(count) === "one" ? 0 : new Intl.PluralRules("ru").select(count) === "few" ? 1 : 2]}`;
    const admin = S.user.role === "admin";
    const feature = (name) => admin || !!S.user.permissions?.[name];
    let disposed = false;
    const sources = () => [
      ...new Map(
        (S.inventory || []).flatMap((d) =>
          d.channels.map((c) => [c.id, { ...c, parent: d }]),
        ),
      ).values(),
    ];
    const button = (
      action,
      title,
      symbol = "plus",
      primary = false,
      extra = "",
    ) =>
      `<button type="button" class="btn ${primary ? "btn-primary" : ""}" data-do="${action}" ${extra}>${icon(symbol)}<span>${h(title)}</span></button>`;
    const action = (name, id, title, symbol, disabled = false) =>
      `<button type="button" class="icon-btn" data-do="${name}" data-id="${h(id)}" title="${h(title)}" aria-label="${h(title)}" ${disabled ? "disabled" : ""}>${icon(symbol)}</button>`;
    const field = (label, contents, help = "") =>
      H.formField(label, contents, help);
    const input = (name, value = "", extra = "") =>
      `<input class="field" name="${name}" value="${h(value)}" ${extra}>`;
    const badge = (text, type = "") =>
      `<span class="infra-badge ${type}">${h(text)}</span>`;
    const hiddenMark = (count = "") =>
      `<span class="infra-hidden-mark" role="img" aria-label="${h(L("Скрытая камера", "Hidden camera"))}" title="${h(L("Скрытая камера", "Hidden camera"))}">${icon("eye-off")}${count ? `<small>${h(count)}</small>` : ""}</span>`;
    const feedback = `<div class="form-feedback infra-feedback" role="status" aria-live="polite" hidden></div>`;
    function message(modal, text, error = false) {
      const box = $(".infra-feedback", modal);
      box.hidden = false;
      box.classList.toggle("error", error);
      box.textContent = text;
    }
    const loading = () =>
      `<span class="spin"></span>${h(L("Проверяем…", "Checking…"))}`;
    async function changed({ close = true, refreshStatus = false } = {}) {
      if (close) H.closeModal();
      await H.reload();
      if (!disposed) await H.showView(mode);
      if (refreshStatus) {
        void (async () => {
          try {
            const data = await api("/api/inventory/status", {
              method: "POST",
              body: {},
            });
            S.statuses = data.status;
            S.statusLoaded = true;
            window.dispatchEvent(new CustomEvent("vwshub:status"));
          } catch (error) {
            H.toast(error.message, "error");
          }
        })();
      }
    }
    function run(task) {
      return (...args) =>
        Promise.resolve(task(...args)).catch((error) =>
          H.toast(error.message, "error"),
        );
    }
    function page(title, description, actions, body, toolbar = "") {
      root.innerHTML = H.page(
        title,
        description,
        actions,
        toolbar + body,
        "VWSHUB 0.8.5",
      );
      $("[data-do=import]", root)?.addEventListener("click", () =>
        importDialog(
          mode === "cameras"
            ? "devices"
            : mode === "groups"
              ? "spaces"
              : "users",
        ),
      );
      $("[data-do=export]", root)?.addEventListener("click", () =>
        exportDialog(
          mode === "cameras"
            ? "devices"
            : mode === "groups"
              ? "spaces"
              : "users",
        ),
      );
    }
    const transferActions = () =>
      button("import", L("Импорт", "Import"), "upload") +
      button("export", L("Экспорт", "Export"), "download");
    function confirmDialog(title, description, perform) {
      const modal = H.modal(
        title,
        description,
        feedback,
        button("confirm", L("Подтвердить", "Confirm"), "check", true),
      );
      $("[data-do=confirm]", modal).onclick = async (event) => {
        const control = event.currentTarget;
        control.disabled = true;
        try {
          await perform();
          await changed();
          H.toast(L("Готово", "Done"));
        } catch (error) {
          message(modal, error.message, true);
          control.disabled = false;
        }
      };
    }
    function searchWithin(container, selector = "[data-search]") {
      const search = $("[data-search-input]", container);
      if (search)
        search.oninput = () => {
          const query = search.value.toLocaleLowerCase().trim();
          $$(selector, container).forEach(
            (row) =>
              (row.hidden = !row.dataset.search
                .toLocaleLowerCase()
                .includes(query)),
          );
        };
    }
    function status(camera) {
      const data = S.statuses?.[camera.id];
      const online = typeof data === "boolean" ? data : data?.online;
      return {
        key:
          online === true ? "online" : online === false ? "offline" : "unknown",
        text:
          online === true
            ? L("В сети", "Online")
            : online === false
              ? L("Не в сети", "Offline")
              : L("Не проверен", "Not checked"),
      };
    }

    function inventory() {
      S.inventoryFilters ??= {
        query: "",
        kind: "",
        protocol: "",
        status: "",
        hidden: false,
      };
      const f = S.inventoryFilters;
      const toolbar = `${admin ? `<details class="infra-display-options"><summary>${icon("sliders-horizontal")}${h(L("Отображение устройств", "Device display"))}${icon("chevron-down")}</summary><div class="infra-display-fields">${field(L("Подписи в просмотре", "Labels in Live view"), `<select class="select" data-device-labels><option value="ip" ${S.branding.recorder_labels !== "name" ? "selected" : ""}>IP</option><option value="name" ${S.branding.recorder_labels === "name" ? "selected" : ""}>${h(L("Имя устройства", "Device name"))}</option></select>`)}</div></details>` : ""}<div class="toolbar infra-toolbar"><label class="search-field">${icon("search")}<input type="search" data-inventory-search value="${h(f.query)}" placeholder="${h(L("Имя, адрес, регистратор или канал…", "Name, address, recorder or channel…"))}" aria-label="${h(L("Поиск устройств", "Search devices"))}"></label><select class="select" data-filter="kind" aria-label="${h(L("Тип устройства", "Device type"))}"><option value="">${h(L("Все устройства", "All devices"))}</option><option value="recorder">${h(L("Регистраторы", "Recorders"))}</option><option value="camera">${h(L("IP-камеры", "IP cameras"))}</option></select><select class="select" data-filter="protocol" aria-label="${h(L("Протокол", "Protocol"))}"><option value="">${h(L("Все протоколы", "All protocols"))}</option><option>DVRIP</option><option>ONVIF</option></select><select class="select" data-filter="status" aria-label="${h(L("Статус", "Status"))}"><option value="">${h(L("Любой статус", "Any status"))}</option><option value="online">${h(L("В сети", "Online"))}</option><option value="offline">${h(L("Не в сети", "Offline"))}</option><option value="unknown">${h(L("Не проверен", "Not checked"))}</option></select><label class="infra-check"><input type="checkbox" data-hidden ${f.hidden ? "checked" : ""}>${h(L("Скрытые", "Hidden"))}</label></div>`;
      const cards = (S.inventory || [])
        .map((device) => {
          const title =
            device.kind === "recorder"
              ? L("Видеорегистратор", "Recorder")
              : L("IP-камера", "IP camera");
          const rows = device.channels
            .map((camera) => {
              const checked = status(camera);
              return `<div class="inventory-channel ${camera.is_hidden ? "is-hidden-source" : ""}" data-channel="${h(camera.id)}" data-search="${h([device.name, device.ip, camera.name, Number(camera.channel || 0) + 1].join(" "))}" data-hidden-source="${!!camera.is_hidden}" data-status="${checked.key}"><span class="infra-source-icon">${icon(device.kind === "recorder" ? "webcam" : "camera")}</span><div class="infra-name"><strong>${h(camera.name)}</strong><small>${h(device.kind === "recorder" ? L("Канал ", "Channel ") + (Number(camera.channel || 0) + 1) : device.ip)}</small></div><span class="infra-channel-state">${camera.is_hidden ? badge(L("Скрыта", "Hidden"), "muted") : badge(checked.text, checked.key)}</span><div class="infra-actions">${!camera.is_hidden && feature("live") ? action("watch", camera.id, L("Смотреть", "Watch"), "play") : ""}${camera.can_edit ? action("source", camera.id, camera.can_manage ? L("Имя и видимость", "Name and visibility") : L("Имя камеры", "Camera name"), "pencil") : ""}${camera.can_manage ? action("visibility", camera.id, camera.is_hidden ? L("Показать камеру", "Show camera") : L("Скрыть камеру", "Hide camera"), camera.is_hidden ? "eye" : "eye-off") : ""}${camera.can_manage ? action("delete-source", camera.id, L("Удалить канал из VWSHub", "Remove channel from VWSHub"), "trash-2") : ""}</div></div>`;
            })
            .join("");
          const hidden = device.channels.filter((c) => c.is_hidden).length;
          return `<details class="inventory-device" data-device="${h(device.id)}" data-kind="${device.kind}" data-protocol="${h(device.protocol.toUpperCase())}" ${S.inventoryOpen?.[device.id] !== false ? "open" : ""}><summary><span class="inventory-kind">${icon(device.kind === "recorder" ? "server" : "camera")}</span><div class="infra-name"><strong>${h(device.name)}</strong><small>${h(title)} · ${h(device.ip)}:${h(device.port)} · ${h(device.protocol.toUpperCase())}</small></div><span class="inventory-count">${device.channels.length} ${h(L("кан.", "ch."))}${hidden ? ` · ${hidden} ${h(L("скрыто", "hidden"))}` : ""}</span><div class="infra-actions">${device.can_edit ? action("device", device.id, L("Изменить устройство / каналы", "Edit device / channels"), "settings-2") + action("delete-device", device.id, L("Удалить устройство из VWSHub", "Remove device from VWSHub"), "trash-2") : ""}</div><span class="inventory-chevron">${icon("chevron-down")}</span></summary><div class="inventory-channels">${rows || `<p class="infra-inline-empty">${h(L("Каналы ещё не добавлены. Откройте устройство и выберите доступные каналы.", "No channels added. Open this device and select its available channels."))}</p>`}</div></details>`;
        })
        .join("");
      page(
        L("Устройства", "Devices"),
        L(
          "Подключения, каналы и видимость камер. Имена меняются только в VWSHub.",
          "Connections, channels and camera visibility. Names are local to VWSHub.",
        ),
        transferActions() +
          button(
            "status",
            L("Проверить статус", "Check status"),
            "refresh-cw",
          ) +
          (admin
            ? button("discover", L("Автопоиск", "Discover"), "radar")
            : "") +
          (feature("create_devices")
            ? button(
                "add",
                L("Добавить устройство", "Add device"),
                "plus",
                true,
              )
            : ""),
        `<div class="infra-result-count" aria-live="polite"></div><div class="inventory-list"><div class="infra-list-head inventory-list-head"><span>${h(L("Устройство / канал", "Device / channel"))}</span><span>${h(L("Состояние", "Status"))}</span><span>${h(L("Действия", "Actions"))}</span></div>${cards}</div><div class="infra-no-results" hidden>${h(L("Ничего не найдено. Измените фильтры или включите скрытые камеры.", "No results. Adjust filters or show hidden cameras."))}</div>`,
        toolbar,
      );
      $("[data-device-labels]", root)?.addEventListener(
        "change",
        run(async (event) => {
          const result = await api("/api/branding", {
            method: "POST",
            body: { recorder_labels: event.target.value },
          });
          S.branding = result.branding;
          H.toast(L("Подписи устройств сохранены", "Device labels saved"));
        }),
      );
      function filter() {
        let visible = 0,
          parents = 0;
        $$("[data-device]", root).forEach((card) => {
          const parentMatch =
            (!f.kind || card.dataset.kind === f.kind) &&
            (!f.protocol || card.dataset.protocol === f.protocol);
          let count = 0;
          $$("[data-channel]", card).forEach((row) => {
            row.hidden =
              !parentMatch ||
              (!f.hidden && row.dataset.hiddenSource === "true") ||
              !!(f.status && row.dataset.status !== f.status) ||
              !row.dataset.search
                .toLocaleLowerCase()
                .includes(f.query.toLocaleLowerCase().trim());
            if (!row.hidden) count++;
          });
          const device = (S.inventory || []).find(
            (d) => d.id === card.dataset.device,
          );
          const empty =
            device.channels.length === 0 &&
            parentMatch &&
            !f.status &&
            `${device.name} ${device.ip}`
              .toLocaleLowerCase()
              .includes(f.query.toLocaleLowerCase().trim());
          card.hidden = !count && !empty;
          visible += count;
          if (!card.hidden) parents++;
          if (f.query && count) card.open = true;
        });
        $(".infra-result-count", root).textContent = L(
          `Устройств: ${parents} · Камер и каналов: ${visible}`,
          `Devices: ${parents} · Cameras and channels: ${visible}`,
        );
        $(".infra-no-results", root).hidden = parents > 0;
      }
      $("[data-inventory-search]", root).oninput = (event) => {
        f.query = event.target.value;
        filter();
      };
      $$("[data-filter]", root).forEach((select) => {
        select.value = f[select.dataset.filter];
        select.onchange = () => {
          f[select.dataset.filter] = select.value;
          filter();
        };
      });
      $("[data-hidden]", root).onchange = (event) => {
        f.hidden = event.target.checked;
        filter();
      };
      $$("[data-device]", root).forEach(
        (card) =>
          (card.ontoggle = () => {
            S.inventoryOpen ??= {};
            S.inventoryOpen[card.dataset.device] = card.open;
          }),
      );
      root.addEventListener("click", onInventoryClick);
      function onInventoryClick(event) {
        const control = event.target.closest("[data-do]");
        if (!control) return;
        const name = control.dataset.do,
          id = control.dataset.id;
        if (control.closest("summary")) event.preventDefault();
        const camera = sources().find((c) => c.id === id),
          device = (S.inventory || []).find((d) => d.id === id);
        if (name === "add") deviceDialog();
        if (name === "device") deviceDialog(device);
        if (name === "source") sourceDialog(camera);
        if (name === "watch") H.showView("live", { cameraId: id });
        if (name === "visibility")
          run(async () => {
            await api(`/api/inventory/channels/${encodeURIComponent(id)}`, {
              method: "PATCH",
              body: { is_hidden: !camera.is_hidden },
            });
            await changed({ close: false });
          })();
        if (name === "delete-source")
          confirmDialog(
            L("Удалить канал?", "Remove channel?"),
            L(
              `«${camera.name}» будет удалена из VWSHub и всех пространств. Записи на оборудовании сохранятся.`,
              `“${camera.name}” will be removed from VWSHub and every space. Recordings on the hardware remain.`,
            ),
            () =>
              api(`/api/inventory/channels/${encodeURIComponent(id)}`, {
                method: "DELETE",
                body: { confirm: true },
              }),
          );
        if (name === "delete-device")
          confirmDialog(
            L("Удалить устройство?", "Remove device?"),
            L(
              `«${device.name}» и все его каналы будут удалены из VWSHub. Данные на оборудовании сохранятся.`,
              `“${device.name}” and all its channels will be removed from VWSHub. Data on the hardware remains.`,
            ),
            () =>
              api(`/api/inventory/${encodeURIComponent(id)}`, {
                method: "DELETE",
                body: { confirm: true },
              }),
          );
        if (name === "discover") discoveryDialog();
        if (name === "status")
          run(async () => {
            control.disabled = true;
            try {
              const data = await api("/api/inventory/status", {
                method: "POST",
                body: {},
              });
              S.statuses = data.status;
              S.statusLoaded = true;
              window.dispatchEvent(new CustomEvent("vwshub:status"));
            } finally {
              control.disabled = false;
            }
          })();
      }
      filter();
      const updateStatuses = () => {
        const byId = new Map(sources().map((c) => [c.id, c]));
        $$("[data-channel]", root).forEach((row) => {
          const source = byId.get(row.dataset.channel);
          if (!source) return;
          const checked = status(source);
          row.dataset.status = checked.key;
          if (!source.is_hidden)
            $(".infra-channel-state", row).innerHTML = badge(
              checked.text,
              checked.key,
            );
        });
        filter();
      };
      window.addEventListener("vwshub:status", updateStatuses);
      return () => {
        root.removeEventListener("click", onInventoryClick);
        window.removeEventListener("vwshub:status", updateStatuses);
      };
    }

    function sourceDialog(camera) {
      const modal = H.modal(
        L("Камера / канал", "Camera / channel"),
        camera.parent.name,
        `${feedback}<form id="source-form" class="form-stack">${field(L("Локальное имя", "Local name"), input("name", camera.name, 'required maxlength="150"'))}${camera.can_manage ? `<label class="infra-check"><input type="checkbox" name="visible" ${!camera.is_hidden ? "checked" : ""}>${h(L("Показывать в просмотре и архиве", "Show in Live and Archive"))}</label><p class="infra-help">${h(L("Скрытая камера остаётся в устройствах и пространствах. Её ячейки на видеостене становятся пустыми.", "Hidden cameras remain in Devices and Spaces. Their video wall cells become unassigned."))}</p>` : ""}</form>`,
        `<button class="btn btn-primary" form="source-form" type="submit">${icon("check")}${h(L("Сохранить", "Save"))}</button>`,
      );
      $("#source-form", modal).onsubmit = async (event) => {
        event.preventDefault();
        const form = event.target;
        try {
          const body = { name: form.elements.name.value };
          if (camera.can_manage)
            body.is_hidden = !form.elements.visible.checked;
          await api(
            `/api/inventory/channels/${encodeURIComponent(camera.id)}`,
            { method: "PATCH", body },
          );
          await changed();
        } catch (error) {
          message(modal, error.message, true);
        }
      };
    }

    function deviceDialog(device = null, preset = null) {
      const connection = {
        ...device?.channels?.[0],
        ...device?.connection,
        ...preset,
      };
      let token = null,
        detected = [],
        selection = new Map(),
        busy = false;
      const method =
        device?.connection_mode ||
        ((connection.protocol || "dvrip") === "dvrip"
          ? "dvrip"
          : connection.rtsp_path && !connection.profile_token
            ? "rtsp"
            : "onvif");
      const modal = H.modal(
        device
          ? L("Устройство и каналы", "Device and channels")
          : L("Добавить устройство", "Add device"),
        L(
          "Сначала проверьте подключение, затем выберите каналы. Названия хранятся на сайте.",
          "Check the connection, then select channels. Names are stored on this site.",
        ),
        `${feedback}<form id="device-form" class="form-stack"><div class="form-grid">${field(L("Название устройства", "Device name"), input("name", device?.name || preset?.name || "", 'required maxlength="150"'))}${field(L("Тип устройства", "Device type"), `<select class="select" name="kind" ${device ? "disabled" : ""}><option value="recorder" ${device?.kind !== "camera" ? "selected" : ""}>${h(L("Видеорегистратор", "Recorder"))}</option><option value="camera" ${device?.kind === "camera" ? "selected" : ""}>${h(L("Отдельная IP-камера", "Standalone IP camera"))}</option></select>`)}</div><div class="infra-section-label">${icon("plug-zap")}${h(L("Подключение", "Connection"))}</div><div class="form-grid">${field(L("Метод подключения", "Connection method"), `<select class="select" name="method"><option value="dvrip">DVRIP · XM / XMEye</option><option value="onvif">ONVIF</option><option value="rtsp">RTSP</option></select>`)}${field(L("Адрес устройства", "Device address"), input("ip", connection.ip || "", 'required maxlength="253" placeholder="192.168.1.10"'))}${field(L("Порт управления", "Control port"), input("port", connection.port || 34567, 'type="number" min="1" max="65535" required'))}${field(L("Порт RTSP", "RTSP port"), input("rtsp_port", connection.rtsp_port || 554, 'type="number" min="1" max="65535" required'))}</div><div class="form-grid">${field(L("Логин устройства", "Device login"), input("username", connection.username || "", 'maxlength="128" autocomplete="off"'))}${field(L("Пароль устройства", "Device password"), `<div class="infra-password">${input("password", "", 'type="password" maxlength="256" autocomplete="new-password"')}<button type="button" class="icon-btn" data-do="password" aria-label="${h(L("Показать пароль", "Show password"))}">${icon("eye")}</button></div>`, device ? L("Пусто — сохранить прежний пароль", "Leave blank to keep the existing password") : "")}</div><div data-rtsp-fields class="form-grid">${field(L("Основной путь RTSP", "Main RTSP path"), input("rtsp_path", connection.rtsp_path || "", 'maxlength="2048" placeholder="/Streaming/Channels/101"'))}${field(L("Дополнительный путь RTSP", "Substream RTSP path"), input("rtsp_sub_path", connection.rtsp_sub_path || "", 'maxlength="2048"'))}</div><div class="infra-probe-bar">${button("probe", L("Получить каналы", "Get channels"), "radar")}${button("test", L("Проверить подключение", "Test connection"), "plug-zap")}<small>${h(L("Обнаружение не меняет оборудование и не добавляет камеры автоматически.", "Discovery does not change the hardware or add cameras automatically."))}</small></div><section class="infra-probe-results" hidden></section></form>`,
        `<span class="modal-note" data-selection-summary></span><button class="btn btn-primary" form="device-form" type="submit">${icon("check")}${h(L("Сохранить", "Save"))}</button>`,
        true,
      );
      const form = $("#device-form", modal),
        results = $(".infra-probe-results", modal),
        save = $("button[type=submit]", modal);
      form.elements.method.value = method;
      if (device) {
        for (const option of form.elements.method.options)
          option.disabled =
            (option.value === "rtsp" && device.kind !== "camera") ||
            (option.value === "dvrip") !== (device.protocol === "dvrip");
      }
      function read() {
        const method = form.elements.method.value;
        return {
          id: device?.id,
          name: form.elements.name.value,
          kind: form.elements.kind.value,
          connection_mode: method,
          connection: {
            protocol: method === "dvrip" ? "dvrip" : "onvif",
            ip: form.elements.ip.value.trim(),
            port: Number(form.elements.port.value),
            rtsp_port: Number(form.elements.rtsp_port.value),
            username: form.elements.username.value,
            password: form.elements.password.value,
            ...(method !== "dvrip"
              ? {
                  rtsp_path: form.elements.rtsp_path.value,
                  rtsp_sub_path: form.elements.rtsp_sub_path.value,
                  ...(connection.profile_token
                    ? { profile_token: connection.profile_token }
                    : {}),
                }
              : {}),
          },
        };
      }
      function update() {
        const manual = form.elements.method.value === "rtsp";
        $("[data-rtsp-fields]", modal).hidden =
          form.elements.method.value === "dvrip";
        $("[data-do=probe]", modal).hidden = manual;
        form.elements.kind.querySelector("[value=recorder]").disabled = manual;
        if (manual) form.elements.kind.value = "camera";
        const isNewRecorder =
          !device && form.elements.kind.value === "recorder";
        save.disabled = busy || (isNewRecorder && (!token || !selection.size));
        $("[data-selection-summary]", modal).textContent = token
          ? L(
              `Выбрано новых каналов: ${selection.size}`,
              `New channels selected: ${selection.size}`,
            )
          : isNewRecorder
            ? L(
                "Получите каналы и выберите нужные",
                "Discover channels and select the ones you need",
              )
            : "";
      }
      function invalidateProbe() {
        token = null;
        detected = [];
        selection.clear();
        results.hidden = true;
        update();
      }
      $$("input,select", form).forEach((control) =>
        control.addEventListener("input", () => {
          if (
            control.name !== "name" &&
            !control.closest(".infra-probe-results")
          )
            invalidateProbe();
        }),
      );
      form.elements.method.onchange = () => {
        if (!device)
          form.elements.port.value =
            form.elements.method.value === "dvrip" ? 34567 : 80;
        invalidateProbe();
      };
      $("[data-do=password]", modal).onclick = () => {
        const input = form.elements.password;
        input.type = input.type === "password" ? "text" : "password";
      };
      function renderDetected() {
        const added = new Map((device?.channels || []).map((c) => [c.id, c]));
        results.hidden = false;
        results.innerHTML = `<div class="infra-section-label">${icon("webcam")}${h(L("Доступные каналы", "Available channels"))}<span class="infra-grow"></span>${button("select-new", L("Выбрать новые", "Select new"), "list-checks")}${button("select-none", L("Снять выбор", "Clear selection"), "list-x")}</div><label class="search-field">${icon("search")}<input type="search" data-search-input placeholder="${h(L("Поиск канала", "Search channels"))}" aria-label="${h(L("Поиск канала", "Search channels"))}"></label><div class="infra-channel-picker">${detected.map((channel, index) => `<label class="infra-detected" data-search="${h(channel.name + " " + (index + 1))}"><input type="checkbox" data-source="${h(channel.source_key)}" aria-label="${h(L("Выбрать канал: ", "Select channel: ") + channel.name)}" ${channel.existing_id ? "checked disabled" : selection.has(channel.source_key) ? "checked" : ""}><span>${icon("webcam")}</span><input class="field" data-channel-name="${h(channel.source_key)}" value="${h(added.get(channel.existing_id)?.name || selection.get(channel.source_key) || channel.name)}" maxlength="150" ${channel.existing_id ? "readonly" : ""} aria-label="${h(L("Имя канала", "Channel name"))}">${channel.existing_id ? badge(L("Уже добавлен", "Already added"), "muted") : badge(L("Новый", "New"), "online")}</label>`).join("")}</div>`;
        searchWithin(results);
        $$("[data-source]", results).forEach(
          (box) =>
            (box.onchange = () => {
              if (box.checked)
                selection.set(
                  box.dataset.source,
                  $$("[data-channel-name]", results).find(
                    (i) => i.dataset.channelName === box.dataset.source,
                  ).value,
                );
              else selection.delete(box.dataset.source);
              update();
            }),
        );
        $$("[data-channel-name]", results).forEach(
          (control) =>
            (control.oninput = () => {
              if (selection.has(control.dataset.channelName))
                selection.set(control.dataset.channelName, control.value);
            }),
        );
        $("[data-do=select-new]", results).onclick = () => {
          detected
            .filter((c) => !c.existing_id)
            .forEach((c) =>
              selection.set(
                c.source_key,
                $$("[data-channel-name]", results).find(
                  (i) => i.dataset.channelName === c.source_key,
                ).value,
              ),
            );
          renderDetected();
          update();
        };
        $("[data-do=select-none]", results).onclick = () => {
          selection.clear();
          renderDetected();
          update();
        };
      }
      $("[data-do=probe]", modal).onclick = async () => {
        if (!form.reportValidity() || busy) return;
        busy = true;
        update();
        message(
          modal,
          L(
            "Получаем реальные каналы устройства…",
            "Reading the device’s actual channels…",
          ),
        );
        try {
          const data = await api("/api/inventory/probe", {
            method: "POST",
            body: read(),
          });
          token = data.probe_token;
          detected = data.channels;
          selection.clear();
          renderDetected();
          message(
            modal,
            L(
              `Найдено каналов: ${detected.length}.${data.missing.length ? ` Недоступны при проверке: ${data.missing.length}; они сохранены в каталоге.` : ""} Выберите новые каналы.`,
              `Channels found: ${detected.length}.${data.missing.length ? ` Missing during this check: ${data.missing.length}; they remain in the catalog.` : ""} Select new channels.`,
            ),
          );
        } catch (error) {
          message(modal, error.message, true);
          token = null;
        } finally {
          busy = false;
          update();
        }
      };
      $("[data-do=test]", modal).onclick = async () => {
        if (!form.reportValidity() || busy) return;
        busy = true;
        update();
        message(modal, L("Проверяем подключение…", "Testing connection…"));
        try {
          const data = await api("/api/inventory/test", {
            method: "POST",
            body: read(),
          });
          message(
            modal,
            data.ok
              ? L("Подключение подтверждено", "Connection confirmed")
              : data.error || L("Нет ответа", "No response"),
            !data.ok,
          );
        } catch (error) {
          message(modal, error.message, true);
        } finally {
          busy = false;
          update();
        }
      };
      form.onsubmit = async (event) => {
        event.preventDefault();
        if (busy) return;
        busy = true;
        update();
        try {
          await api("/api/inventory", {
            method: "POST",
            body: {
              ...read(),
              ...(token ? { probe_token: token } : {}),
              selected: [...selection].map(([source_key, name]) => ({
                source_key,
                name,
              })),
            },
          });
          await changed({ refreshStatus: true });
          H.toast(L("Устройство сохранено", "Device saved"));
        } catch (error) {
          message(modal, error.message, true);
        } finally {
          busy = false;
          update();
        }
      };
      update();
    }

    function discoveryDialog() {
      const modal = H.modal(
        L("Найти устройства", "Discover devices"),
        L(
          "WS-Discovery для ONVIF и проверка DVRIP в локальной подсети.",
          "ONVIF WS-Discovery and a DVRIP check on a local subnet.",
        ),
        `${feedback}<form id="discover-form" class="form-stack">${field(L("Подсеть IPv4, необязательно", "IPv4 subnet, optional"), input("subnet", "", 'placeholder="192.168.1.0/24" maxlength="64"'))}<button class="btn btn-primary" type="submit">${icon("radar")}${h(L("Начать поиск", "Start discovery"))}</button></form><div class="infra-discovery-list"></div>`,
        "",
        true,
      );
      $("#discover-form", modal).onsubmit = async (event) => {
        event.preventDefault();
        const submit = $("button", event.target);
        submit.disabled = true;
        message(modal, L("Идёт поиск устройств…", "Searching for devices…"));
        try {
          const result = await api("/api/discovery", {
            method: "POST",
            body: { subnet: event.target.elements.subnet.value, timeout: 3 },
          });
          message(
            modal,
            L(
              `Найдено: ${result.devices.length}`,
              `Found: ${result.devices.length}`,
            ) +
              (result.warnings.length ? " · " + result.warnings.join(" ") : ""),
          );
          $(".infra-discovery-list", modal).innerHTML = result.devices
            .map(
              (d, index) =>
                `<div class="infra-reference-row"><span>${icon(d.protocol === "dvrip" ? "server" : "camera")}</span><div class="infra-name"><strong>${h(d.name)}</strong><small>${h(d.ip)}:${d.port} · ${h(d.protocol.toUpperCase())}</small></div>${button("choose", L("Подключить", "Connect"), "plus", false, `data-index="${index}"`)}</div>`,
            )
            .join("");
          $$("[data-do=choose]", modal).forEach(
            (control) =>
              (control.onclick = () =>
                deviceDialog(
                  null,
                  result.devices[Number(control.dataset.index)],
                )),
          );
        } catch (error) {
          message(modal, error.message, true);
        } finally {
          submit.disabled = false;
        }
      };
    }

    function exportDialog(kind) {
      const canProtect = kind === "devices" && admin;
      const modal = H.modal(
        L("Экспорт каталога", "Export catalog"),
        kind === "devices"
          ? L(
              "Обычный JSON содержит подключения без паролей и секретных параметров URL.",
              "Standard JSON contains connections without passwords or secret URL parameters.",
            )
          : kind === "spaces"
            ? L(
                "Файл содержит пространства, зоны и ссылки на камеры.",
                "The file contains spaces, zones and camera references.",
              )
            : L(
                "Пароли, хеши и сеансы пользователей в файл не попадают.",
                "User passwords, hashes and sessions are excluded.",
              ),
        `${feedback}<form id="export-form" class="form-stack">${canProtect ? `<label class="infra-check"><input type="checkbox" name="protected">${h(L("Защищённый экспорт с учётными данными устройств", "Protected export with device credentials"))}</label><div class="form-grid" data-export-passwords hidden>${field(L("Пароль файла", "File password"), input("passphrase", "", 'type="password" minlength="12" maxlength="256" autocomplete="new-password"'))}${field(L("Повторите пароль", "Confirm password"), input("confirmation", "", 'type="password" minlength="12" maxlength="256" autocomplete="new-password"'))}</div>` : ""}<p class="infra-help">${h(L("Будут выгружены все доступные объекты этого раздела. Импорт другого раздела выполняется отдельным файлом.", "All accessible objects in this section will be exported. Other sections use separate files."))}</p></form>`,
        `<button class="btn btn-primary" type="submit" form="export-form">${icon("download")}${h(L("Скачать JSON", "Download JSON"))}</button>`,
      );
      const form = $("#export-form", modal);
      if (canProtect)
        form.elements.protected.onchange = () => {
          $("[data-export-passwords]", modal).hidden =
            !form.elements.protected.checked;
          form.elements.passphrase.required = form.elements.protected.checked;
          form.elements.confirmation.required = form.elements.protected.checked;
        };
      form.onsubmit = async (event) => {
        event.preventDefault();
        try {
          const protectedFile = !!form.elements.protected?.checked;
          if (
            protectedFile &&
            form.elements.passphrase.value !== form.elements.confirmation.value
          )
            throw Error(L("Пароли не совпадают", "Passwords do not match"));
          const result = await api(`/api/transfers/${kind}/export`, {
            method: "POST",
            body: protectedFile
              ? { protected: true, passphrase: form.elements.passphrase.value }
              : {},
          });
          H.downloadJSON(
            result,
            `vwshub-${kind}${protectedFile ? "-protected" : ""}.json`,
          );
          H.closeModal();
        } catch (error) {
          message(modal, error.message, true);
        }
      };
    }

    function importDialog(kind) {
      let payload = null,
        preview = null;
      const modal = H.modal(
        L("Импорт каталога", "Import catalog"),
        L(
          "Сначала выберите файл и проверьте изменения. Запись произойдёт после применения.",
          "Choose a file and review the changes. Data is written when you apply the preview.",
        ),
        `${feedback}<form id="import-form" class="form-stack"><div class="form-grid">${field(L("Файл JSON, до 16 МБ", "JSON file, up to 16 MB"), '<input class="field" name="file" type="file" accept="application/json,.json" required>')}${field(L("Режим импорта", "Import mode"), `<select class="select" name="mode"><option value="add">${h(L("Добавить новые, существующие пропустить", "Add new, skip existing"))}</option><option value="merge">${h(L("Добавить новые и обновить существующие", "Add new and update existing"))}</option><option value="update">${h(L("Только обновить существующие", "Update existing only"))}</option></select>`)}</div><div data-import-secret hidden>${field(L("Пароль защищённого файла", "Protected file password"), input("passphrase", "", 'type="password" maxlength="256" autocomplete="off"'))}</div><button class="btn" type="submit">${icon("scan-eye")}${h(L("Предварительный просмотр", "Preview changes"))}</button></form><div class="infra-import-preview"></div>`,
        button(
          "apply",
          L("Применить изменения", "Apply changes"),
          "check",
          true,
          "disabled",
        ),
        true,
      );
      const form = $("#import-form", modal),
        apply = $("[data-do=apply]", modal);
      let fileSequence = 0,
        planSequence = 0,
        reading = false,
        previewBusy = false;
      const submit = $("button[type=submit]", form);
      const syncSubmit = () =>
        (submit.disabled = reading || previewBusy || !payload);
      const invalidate = () => {
        planSequence++;
        preview = null;
        apply.disabled = true;
        $(".infra-import-preview", modal).replaceChildren();
      };
      form.elements.mode.onchange = invalidate;
      form.elements.passphrase.oninput = invalidate;
      form.elements.file.onchange = async () => {
        const sequence = ++fileSequence;
        invalidate();
        payload = null;
        reading = true;
        syncSubmit();
        try {
          const file = form.elements.file.files[0];
          if (!file) return;
          if (file.size > 16 * 1024 * 1024)
            throw Error(L("Файл больше 16 МБ", "File exceeds 16 MB"));
          const raw = await file.text();
          if (sequence !== fileSequence || !form.isConnected) return;
          payload = JSON.parse(raw);
          if (!payload || typeof payload !== "object" || Array.isArray(payload))
            throw Error(
              L("Нужен JSON каталога VWSHub", "Choose a VWSHub catalog JSON"),
            );
          $("[data-import-secret]", modal).hidden =
            payload.format !== "vwshub.devices.protected";
          message(
            modal,
            L(
              "Файл прочитан. Получите предварительный просмотр.",
              "File loaded. Generate a preview.",
            ),
          );
        } catch (error) {
          if (sequence === fileSequence && form.isConnected) {
            payload = null;
            message(modal, error.message, true);
          }
        } finally {
          if (sequence === fileSequence) {
            reading = false;
            syncSubmit();
          }
        }
      };
      syncSubmit();
      form.onsubmit = async (event) => {
        event.preventDefault();
        invalidate();
        if (!payload) return;
        const sequence = planSequence;
        previewBusy = true;
        syncSubmit();
        message(
          modal,
          L(
            "Проверяем файл и права доступа…",
            "Validating file and permissions…",
          ),
        );
        try {
          const result = await api(`/api/transfers/${kind}/preview`, {
            method: "POST",
            body: {
              payload,
              mode: form.elements.mode.value,
              passphrase: form.elements.passphrase.value,
            },
          });
          if (!form.isConnected) return;
          if (sequence !== planSequence) {
            message(
              modal,
              L(
                "Параметры изменены. Получите новый предпросмотр.",
                "Options changed. Generate a new preview.",
              ),
            );
            return;
          }
          preview = result;
          const labels = {
            add: L("Добавить", "Add"),
            update: L("Обновить", "Update"),
            skip: L("Пропустить", "Skip"),
          };
          $(".infra-import-preview", modal).innerHTML =
            `<div class="infra-preview-totals">${badge(`${labels.add}: ${preview.counts.add}`, "online")}${badge(`${labels.update}: ${preview.counts.update}`)}${badge(`${labels.skip}: ${preview.counts.skip}`, "muted")}${preview.pending ? badge(L(`Ожидают ссылки: ${preview.pending}`, `Pending references: ${preview.pending}`), "warning") : ""}</div><div class="table-wrap"><table class="data-table"><thead class="infra-list-head"><tr><th>${h(L("Объект", "Object"))}</th><th>${h(L("Изменение", "Change"))}</th><th>${h(L("Примечание", "Note"))}</th></tr></thead><tbody>${preview.rows.map((row) => `<tr><td>${h(row.name)}</td><td>${h(labels[row.action])}</td><td>${h(row.reason === "admin" ? L("Администратор защищён от обычного импорта", "Administrator protected from plain import") : row.inactive ? L("Неактивен до назначения пароля", "Inactive until a password is set") : row.needs_credentials ? L("Проверьте учётные данные после импорта", "Check credentials after import") : row.pending ? L(`Неразрешённых ссылок: ${row.pending}`, `Unresolved references: ${row.pending}`) : "")}</td></tr>`).join("")}</tbody></table></div>`;
          apply.disabled = !(preview.counts.add + preview.counts.update);
          message(
            modal,
            L(
              "Проверьте список. Предварительный просмотр действителен 5 минут.",
              "Review the list. This preview is valid for 5 minutes.",
            ),
          );
        } catch (error) {
          if (form.isConnected && sequence === planSequence)
            message(modal, error.message, true);
        } finally {
          previewBusy = false;
          syncSubmit();
        }
      };
      apply.onclick = async () => {
        if (!preview) return;
        apply.disabled = true;
        try {
          await api(`/api/transfers/${kind}/apply`, {
            method: "POST",
            body: { token: preview.token },
          });
          await changed({ refreshStatus: kind === "devices" });
          H.toast(L("Импорт завершён", "Import complete"));
        } catch (error) {
          preview = null;
          message(modal, error.message, true);
        }
      };
    }

    function spacesPage() {
      const current =
        S.openSpaceId && S.groups.find((s) => s.id === S.openSpaceId);
      if (current) {
        spaceDetails(current);
        return;
      }
      S.openSpaceId = null;
      const body = S.groups.length
        ? `<div class="table-wrap"><table class="data-table infra-spaces-table"><thead class="infra-list-head"><tr><th>${h(L("Пространство", "Space"))}</th><th>${h(L("Камеры и зоны", "Cameras and zones"))}</th><th>${h(L("Доступ", "Access"))}</th><th class="actions-column">${h(L("Действия", "Actions"))}</th></tr></thead><tbody>${S.groups
            .map((space) => {
              const pending = space.members.filter((m) => !m.channel_id).length,
                hidden = space.members.filter((m) => m.is_hidden).length;
              return `<tr class="infra-space-row" data-search="${h([space.name, ...space.zones.map((z) => z.name)].join(" "))}"><td><div class="infra-table-name"><span class="infra-space-mark">${window.VWSIcons.html(space.icon, "layers-3")}</span><button class="infra-name-link" type="button" data-do="open-space" data-id="${h(space.id)}">${h(space.name)}</button></div></td><td><div class="infra-name"><strong>${h(plural(space.camera_ids.length, ["камера", "камеры", "камер"], ["camera", "cameras"]))} · ${h(plural(space.zones.length, ["зона", "зоны", "зон"], ["zone", "zones"]))}</strong><small>${h(
                space.zones
                  .map((z) => z.name)
                  .slice(0, 3)
                  .join(" · "),
              )}${space.zones.length > 3 ? " · +" + (space.zones.length - 3) : ""}</small></div><div class="infra-badge-list">${pending ? badge(L(`Ожидают камеры: ${pending}`, `Pending cameras: ${pending}`), "warning") : ""}${hidden ? hiddenMark(hidden) : ""}</div></td><td>${badge(space.can_edit ? L("Редактирование", "Edit") : L("Чтение", "Read"), space.can_edit ? "" : "muted")}</td><td class="actions-column"><div class="table-actions">${action("open-space", space.id, L("Открыть пространство", "Open space"), "arrow-up-right")}${feature("live") ? action("watch-space", space.id, L("На видеостену", "Show on wall"), "play") : ""}${space.can_edit ? action("edit-space", space.id, L("Изменить пространство", "Edit space"), "pencil") : ""}</div></td></tr>`;
            })
            .join("")}</tbody></table></div>`
        : H.empty(
            L("Пока нет пространств", "No spaces yet"),
            L(
              "Создайте пространство и разместите камеры в корне или в зонах.",
              "Create a space and organize cameras at its root or in zones.",
            ),
          );
      page(
        L("Пространства", "Spaces"),
        L(
          "Организуйте камеры по объектам и зонам без дублирования подключений.",
          "Organize cameras by location and zone without duplicating connections.",
        ),
        transferActions() +
          (feature("edit_spaces")
            ? button(
                "add-space",
                L("Создать пространство", "Create space"),
                "plus",
                true,
              )
            : ""),
        body,
        `<div class="toolbar"><label class="search-field">${icon("search")}<input type="search" data-space-search placeholder="${h(L("Поиск…", "Search…"))}" aria-label="${h(L("Поиск пространства или зоны", "Search spaces or zones"))}"></label></div>`,
      );
      $("[data-space-search]", root).oninput = (event) => {
        const query = event.target.value.toLocaleLowerCase().trim();
        $$(".infra-space-row", root).forEach(
          (card) =>
            (card.hidden = !card.dataset.search
              .toLocaleLowerCase()
              .includes(query)),
        );
      };
      $$("[data-do=open-space]", root).forEach(
        (control) =>
          (control.onclick = () => {
            S.openSpaceId = control.dataset.id;
            spacesPage();
          }),
      );
      $$("[data-do=edit-space]", root).forEach(
        (control) =>
          (control.onclick = () =>
            spaceDialog(S.groups.find((s) => s.id === control.dataset.id))),
      );
      $$("[data-do=watch-space]", root).forEach(
        (control) =>
          (control.onclick = () =>
            H.showView("live", { groupId: control.dataset.id })),
      );
      $("[data-do=add-space]", root)?.addEventListener("click", () =>
        spaceDialog(),
      );
    }

    function scopeLevel(space, zone = null) {
      return zone ? !!(space.can_edit || zone.can_edit) : !!space.can_edit;
    }
    function spaceDetails(space) {
      const all = sources(),
        byId = new Map(all.map((c) => [c.id, c]));
      const section = (zone = null) => {
        const editable = scopeLevel(space, zone),
          members = space.members.filter(
            (m) => (m.zone_id || null) === (zone?.id || null),
          );
        const ordered = members.filter((member) => member.channel_id),
          first = ordered[0]?.id,
          last = ordered.at(-1)?.id;
        return `<section class="infra-zone"><header><span class="infra-zone-icon">${window.VWSIcons.html(zone?.icon || space.icon, zone ? "map-pin" : "folder")}</span><div class="infra-name"><h2>${h(zone?.name || L("Корень пространства", "Space root"))}</h2><small>${h(plural(members.length, ["источник", "источника", "источников"], ["source", "sources"]))}</small></div><div class="infra-actions">${feature("live") ? action("watch-zone", zone?.id || "", L("На видеостену", "Show on wall"), "play") : ""}${editable ? action("members", zone?.id || "", L("Выбрать камеры", "Choose cameras"), "list-plus") : ""}${zone && editable ? action("edit-zone", zone.id, L("Изменить зону", "Edit zone"), "pencil") : ""}${zone && space.can_edit ? action("zone-up", zone.id, L("Выше", "Move up"), "arrow-up", space.zones[0]?.id === zone.id) + action("zone-down", zone.id, L("Ниже", "Move down"), "arrow-down", space.zones.at(-1)?.id === zone.id) : ""}${zone && editable ? action("delete-zone", zone.id, L("Удалить зону", "Delete zone"), "trash-2") : ""}</div></header><div class="infra-zone-members">${
          members
            .map((member) => {
              const camera =
                byId.get(member.channel_id) ||
                S.cameras.find((c) => c.id === member.channel_id);
              return `<div class="infra-reference-row"><span class="infra-source-icon">${icon(member.channel_id ? "webcam" : "unplug")}</span><div class="infra-name"><strong>${h(member.name)}</strong><small>${h(!member.channel_id ? member.source_id : camera?.parent?.name || camera?.recorder_name || "")}</small></div>${!member.channel_id ? badge(L("Ожидает камеру", "Pending camera"), "warning") : member.is_hidden ? hiddenMark() : ""}<div class="infra-actions">${member.channel_id && !member.is_hidden && feature("live") ? action("watch-source", member.channel_id, L("Смотреть", "Watch"), "play") : ""}${editable && !member.channel_id ? action("match", member.id, L("Сопоставить камеру", "Match camera"), "link") : ""}${editable && member.channel_id ? action("move", member.id, L("Переместить в зону", "Move to zone"), "folder-input") : ""}${camera?.can_edit ? action("rename", member.channel_id, L("Имя камеры", "Camera name"), "pencil") : ""}${editable && member.channel_id ? action("member-up", member.id, L("Порядок: выше", "Order: move up"), "arrow-up", member.id === first) + action("member-down", member.id, L("Порядок: ниже", "Order: move down"), "arrow-down", member.id === last) : ""}${editable ? action("detach", member.id, L("Убрать из пространства", "Remove from space"), "log-out") : ""}</div></div>`;
            })
            .join("") ||
          `<p class="infra-inline-empty">${h(L("Нет камер. Добавьте доступные источники.", "No cameras. Add accessible sources."))}</p>`
        }</div></section>`;
      };
      page(
        space.name,
        L(
          "Удаление из пространства не удаляет подключение камеры.",
          "Removing a camera from a space keeps its connection.",
        ),
        button("back", L("Все пространства", "All spaces"), "arrow-left") +
          (space.can_edit
            ? button(
                "add-zone",
                L("Создать зону", "Create zone"),
                "map-pin-plus",
                true,
              ) +
              button("edit-current", L("Изменить", "Edit"), "pencil") +
              button(
                "delete-space",
                L("Удалить пространство", "Delete space"),
                "trash-2",
              )
            : ""),
        `<div class="infra-space-detail">${section()}${space.zones.map((zone) => section(zone)).join("")}</div>`,
      );
      $("[data-do=back]", root).onclick = () => {
        S.openSpaceId = null;
        spacesPage();
      };
      $("[data-do=add-zone]", root)?.addEventListener("click", () =>
        spaceDialog(space, null, true),
      );
      $("[data-do=edit-current]", root)?.addEventListener("click", () =>
        spaceDialog(space),
      );
      $("[data-do=delete-space]", root)?.addEventListener("click", () =>
        confirmDialog(
          L("Удалить пространство?", "Delete space?"),
          L(
            `«${space.name}» и его зоны будут удалены. Подключения камер сохранятся.`,
            `“${space.name}” and its zones will be deleted. Camera connections remain.`,
          ),
          async () => {
            await api(`/api/spaces/${encodeURIComponent(space.id)}`, {
              method: "DELETE",
              body: { confirm: true },
            });
            S.openSpaceId = null;
          },
        ),
      );
      $$("[data-do]", root).forEach((control) => {
        const actionName = control.dataset.do,
          id = control.dataset.id,
          zone = space.zones.find((z) => z.id === id),
          member = space.members.find((m) => m.id === id);
        if (actionName === "members")
          control.onclick = () => memberPicker(space, zone || null);
        if (actionName === "edit-zone")
          control.onclick = () => spaceDialog(space, zone);
        if (actionName === "watch-zone")
          control.onclick = () =>
            H.showView("live", {
              groupId: space.id,
              zoneId: id || null,
              rootOnly: !id,
            });
        if (actionName === "watch-source")
          control.onclick = () => H.showView("live", { cameraId: id });
        if (actionName === "rename")
          control.onclick = () => sourceDialog(byId.get(id));
        if (actionName === "detach")
          control.onclick = () =>
            confirmDialog(
              L(
                "Убрать камеру из пространства?",
                "Remove camera from this space?",
              ),
              L(
                `«${member.name}» будет убрана только из «${space.name}».`,
                `“${member.name}” will only be removed from “${space.name}”.`,
              ),
              () =>
                api(
                  `/api/spaces/${encodeURIComponent(space.id)}/members/${encodeURIComponent(id)}`,
                  { method: "DELETE" },
                ),
            );
        if (actionName === "match")
          control.onclick = () => matchDialog(space, member);
        if (actionName === "move")
          control.onclick = () => moveDialog(space, member);
        if (actionName === "member-up" || actionName === "member-down")
          control.onclick = run(async () => {
            const members = space.members.filter(
              (m) =>
                m.channel_id &&
                (m.zone_id || null) === (member.zone_id || null),
            );
            const index = members.findIndex((m) => m.id === member.id),
              target = index + (actionName === "member-up" ? -1 : 1);
            if (target < 0 || target >= members.length) return;
            [members[index], members[target]] = [
              members[target],
              members[index],
            ];
            await api(
              `/api/spaces/${encodeURIComponent(space.id)}${member.zone_id ? "/zones/" + encodeURIComponent(member.zone_id) : ""}`,
              {
                method: "PATCH",
                body: { camera_ids: members.map((m) => m.channel_id) },
              },
            );
            await changed({ close: false });
          });
        if (actionName === "delete-zone")
          control.onclick = () =>
            confirmDialog(
              L("Удалить зону?", "Delete zone?"),
              L(
                `Камеры из «${zone.name}» вернутся в корень «${space.name}».`,
                `Cameras in “${zone.name}” will return to the root of “${space.name}”.`,
              ),
              () =>
                api(
                  `/api/spaces/${encodeURIComponent(space.id)}/zones/${encodeURIComponent(id)}`,
                  { method: "DELETE", body: { return_to_root: true } },
                ),
            );
        if (actionName === "zone-up" || actionName === "zone-down")
          control.onclick = run(async () => {
            const ids = space.zones.map((z) => z.id),
              index = ids.indexOf(id),
              target = index + (actionName === "zone-up" ? -1 : 1);
            if (target < 0 || target >= ids.length) return;
            [ids[index], ids[target]] = [ids[target], ids[index]];
            await api(`/api/spaces/${encodeURIComponent(space.id)}`, {
              method: "PATCH",
              body: { order: ids },
            });
            await changed({ close: false });
          });
      });
    }

    function spaceDialog(space = null, zone = null, newZone = false) {
      const isZone = !!zone || newZone,
        current = zone || (!isZone ? space : null);
      const modal = H.modal(
        isZone
          ? L(
              zone ? "Изменить зону" : "Создать зону",
              zone ? "Edit zone" : "Create zone",
            )
          : L(
              space ? "Изменить пространство" : "Создать пространство",
              space ? "Edit space" : "Create space",
            ),
        space?.name ||
          L(
            "Камеры можно добавить после создания.",
            "Add cameras after creating the space.",
          ),
        `${feedback}<form id="space-form" class="form-stack">${field(L("Название", "Name"), input("name", current?.name || "", 'required maxlength="100"'))}<div class="form-field"><label>${h(L("Значок", "Icon"))}</label><div data-icon-picker></div></div></form>`,
        `<button class="btn btn-primary" form="space-form" type="submit">${icon("check")}${h(L("Сохранить", "Save"))}</button>`,
      );
      iconPicker(
        $("[data-icon-picker]", modal),
        current?.icon || (isZone ? "map-pin" : "layers-3"),
        H,
      );
      $("#space-form", modal).onsubmit = async (event) => {
        event.preventDefault();
        const form = event.target;
        try {
          const url = isZone
            ? `/api/spaces/${encodeURIComponent(space.id)}/zones${zone ? "/" + encodeURIComponent(zone.id) : ""}`
            : space
              ? `/api/spaces/${encodeURIComponent(space.id)}`
              : "/api/spaces";
          const data = await api(url, {
            method: current ? "PATCH" : "POST",
            body: {
              name: form.elements.name.value,
              icon: form.elements.icon.value,
            },
          });
          if (!isZone && !space) S.openSpaceId = data.space.id;
          await changed();
        } catch (error) {
          message(modal, error.message, true);
        }
      };
    }

    function memberPicker(space, zone = null) {
      const selected = new Set(
        space.members
          .filter((m) => (m.zone_id || null) === (zone?.id || null))
          .map((m) => m.channel_id)
          .filter(Boolean),
      );
      const membership = new Map(
        space.members.filter((m) => m.channel_id).map((m) => [m.channel_id, m]),
      );
      const available = sources().filter((source) => {
        if (!source.can_edit) return false;
        const previous = membership.get(source.id);
        if (!previous || previous.zone_id === (zone?.id || null)) return true;
        return scopeLevel(
          space,
          space.zones.find((z) => z.id === previous.zone_id) || null,
        );
      });
      const modal = H.modal(
        L("Камеры пространства", "Space cameras"),
        `${space.name} / ${zone?.name || L("Корень", "Root")}`,
        `${feedback}<div class="infra-picker-note">${h(L("Камера может быть только в одном месте этого пространства. Добавлять и перемещать можно камеры с правом редактирования.", "Each camera occupies one location within this space. Adding or moving a camera requires edit access."))}</div><label class="search-field">${icon("search")}<input type="search" data-search-input placeholder="${h(L("Поиск камеры или регистратора…", "Search cameras or recorders…"))}" aria-label="${h(L("Поиск камеры", "Search cameras"))}"></label><div class="infra-picker-buttons">${button("all", L("Все найденные", "All matching"), "list-checks")}${button("none", L("Снять выбор", "Clear selection"), "list-x")}<span class="infra-picker-count"></span></div><div class="infra-source-picker">${
          available.length
            ? available
                .map((source) => {
                  const previous = membership.get(source.id),
                    other =
                      previous &&
                      (previous.zone_id || null) !== (zone?.id || null);
                  return `<label class="infra-source-option" data-search="${h(source.name + " " + source.parent.name + " " + source.ip)}"><input type="checkbox" value="${h(source.id)}" ${selected.has(source.id) ? "checked" : ""}><span>${icon(source.parent.kind === "recorder" ? "webcam" : "camera")}</span><div class="infra-name"><strong>${h(source.name)}</strong><small>${h(source.parent.name)}${other ? " · " + h(L("Переместить из: ", "Move from: ") + (space.zones.find((z) => z.id === previous.zone_id)?.name || L("Корень", "Root"))) : ""}</small></div>${source.is_hidden ? hiddenMark() : ""}</label>`;
                })
                .join("")
            : `<p class="infra-inline-empty">${h(L("Нет камер с правом редактирования", "No cameras with edit access"))}</p>`
        }</div>`,
        button(
          "save-members",
          L("Сохранить состав", "Save cameras"),
          "check",
          true,
        ),
        true,
      );
      searchWithin(modal);
      const boxes = $$(".infra-source-option input", modal);
      const count = () => {
        $(".infra-picker-count", modal).textContent = L(
          `Выбрано: ${boxes.filter((b) => b.checked).length}`,
          `Selected: ${boxes.filter((b) => b.checked).length}`,
        );
      };
      boxes.forEach((box) => (box.onchange = count));
      $("[data-do=all]", modal).onclick = () => {
        boxes
          .filter((box) => !box.closest("[data-search]").hidden)
          .forEach((box) => (box.checked = true));
        count();
      };
      $("[data-do=none]", modal).onclick = () => {
        boxes.forEach((box) => (box.checked = false));
        count();
      };
      count();
      $("[data-do=save-members]", modal).onclick = async () => {
        try {
          await api(
            `/api/spaces/${encodeURIComponent(space.id)}${zone ? "/zones/" + encodeURIComponent(zone.id) : ""}`,
            {
              method: "PATCH",
              body: {
                camera_ids: boxes.filter((b) => b.checked).map((b) => b.value),
              },
            },
          );
          await changed();
        } catch (error) {
          message(modal, error.message, true);
        }
      };
    }

    function matchDialog(space, member) {
      const options = sources().filter(
        (source) =>
          source.can_edit &&
          !space.members.some((m) => m.channel_id === source.id),
      );
      const modal = H.modal(
        L("Сопоставить камеру", "Match camera"),
        L(
          `Ссылка: ${member.name} · ${member.source_id}`,
          `Reference: ${member.name} · ${member.source_id}`,
        ),
        `${feedback}${field(L("Камера в текущем каталоге", "Camera in this catalog"), `<select class="select" name="camera"><option value="">${h(L("Выберите камеру", "Choose a camera"))}</option>${options.map((c) => `<option value="${h(c.id)}">${h(c.parent.name)} / ${h(c.name)}</option>`).join("")}</select>`)}`,
        button(
          "match-save",
          L("Сопоставить", "Match"),
          "link",
          true,
          options.length ? "" : "disabled",
        ),
      );
      $("[data-do=match-save]", modal).onclick = async () => {
        try {
          const channel_id = $("[name=camera]", modal).value;
          if (!channel_id) throw Error(L("Выберите камеру", "Choose a camera"));
          await api(
            `/api/spaces/${encodeURIComponent(space.id)}/members/${encodeURIComponent(member.id)}`,
            { method: "PATCH", body: { channel_id } },
          );
          await changed();
        } catch (error) {
          message(modal, error.message, true);
        }
      };
    }

    function moveDialog(space, member) {
      const targets = [
        ...(space.can_edit
          ? [{ id: "", name: L("Корень пространства", "Space root") }]
          : []),
        ...space.zones.filter((zone) => scopeLevel(space, zone)),
      ].filter((zone) => (zone.id || null) !== (member.zone_id || null));
      const modal = H.modal(
        L("Переместить камеру", "Move camera"),
        member.name,
        `${feedback}${field(L("Расположение", "Location"), `<select class="select" name="zone">${targets.map((z) => `<option value="${h(z.id)}">${h(z.name)}</option>`).join("")}</select>`)}`,
        button(
          "move-save",
          L("Переместить", "Move"),
          "folder-input",
          true,
          targets.length ? "" : "disabled",
        ),
      );
      $("[data-do=move-save]", modal).onclick = async () => {
        try {
          const target = $("[name=zone]", modal).value,
            camera_ids = space.members
              .filter((m) => (m.zone_id || "") === target)
              .map((m) => m.channel_id)
              .filter(Boolean);
          camera_ids.push(member.channel_id);
          await api(
            `/api/spaces/${encodeURIComponent(space.id)}${target ? "/zones/" + encodeURIComponent(target) : ""}`,
            { method: "PATCH", body: { camera_ids } },
          );
          await changed();
        } catch (error) {
          message(modal, error.message, true);
        }
      };
    }

    function usersPage() {
      const body = `<div class="table-wrap"><table class="data-table infra-users-table"><thead class="infra-list-head"><tr><th>${h(L("Пользователь", "User"))}</th><th>${h(L("Роль и статус", "Role and status"))}</th><th>${h(L("Разрешения", "Permissions"))}</th><th class="actions-column">${h(L("Действия", "Actions"))}</th></tr></thead><tbody>${S.users.map((user) => `<tr data-user-row data-search="${h(user.username + " " + user.alias)}"><td><div class="infra-name"><strong>${h(user.alias)}</strong><small>${h(user.username)}</small></div></td><td><div class="infra-badge-list">${badge(user.role === "admin" ? L("Администратор", "Administrator") : L("Пользователь", "User"))}${!user.active ? badge(L("Неактивен", "Inactive"), "warning") : ""}</div></td><td><div class="infra-badge-list">${user.permissions.live ? badge(L("Просмотр", "Live"), "muted") : ""}${user.permissions.archive_view ? badge(L("Архив", "Archive"), "muted") : ""}${user.permissions.archive_export ? badge(L("Скачивание", "Download"), "online") : ""}${user.can_edit && user.role !== "admin" ? badge(L("Редактирование", "Edit")) : ""}</div></td><td class="actions-column"><div class="table-actions">${action("edit-user", user.username, L("Изменить", "Edit"), "pencil")}${action("clone-user", user.username, L("Копировать пользователя", "Copy user"), "copy")}${user.username !== S.user.username ? action("delete-user", user.username, L("Удалить пользователя", "Delete user"), "trash-2") : ""}</div></td></tr>`).join("")}</tbody></table></div>`;
      page(
        L("Пользователи", "Users"),
        L(
          "Чтение и редактирование назначаются пространствам, зонам, устройствам и каналам.",
          "Assign read and edit access to spaces, zones, devices and channels.",
        ),
        transferActions() +
          button(
            "add-user",
            L("Добавить пользователя", "Add user"),
            "user-plus",
            true,
          ),
        body,
        `<div class="toolbar"><label class="search-field">${icon("search")}<input type="search" data-search-input placeholder="${h(L("Поиск пользователя…", "Search users…"))}" aria-label="${h(L("Поиск пользователя", "Search users"))}"></label></div>`,
      );
      searchWithin(root, "[data-user-row]");
      $("[data-do=add-user]", root).onclick = () => userDialog();
      $$("[data-do=edit-user]", root).forEach(
        (control) =>
          (control.onclick = () =>
            userDialog(S.users.find((u) => u.username === control.dataset.id))),
      );
      $$("[data-do=clone-user]", root).forEach(
        (control) =>
          (control.onclick = () =>
            userDialog(
              S.users.find((u) => u.username === control.dataset.id),
              true,
            )),
      );
      $$("[data-do=delete-user]", root).forEach(
        (control) =>
          (control.onclick = () =>
            confirmDialog(
              L("Удалить пользователя?", "Delete user?"),
              control.dataset.id,
              () =>
                api(`/api/users/${encodeURIComponent(control.dataset.id)}`, {
                  method: "DELETE",
                }),
            )),
      );
    }

    function userDialog(existing = null, copy = false) {
      const user = existing || {},
        isNew = !existing || copy,
        copyAdmin = copy && user.role === "admin";
      const grants = copyAdmin ? {} : structuredClone(user.grants || {}),
        permissions = copyAdmin
          ? {
              live: true,
              archive_view: true,
              archive_export: false,
              create_devices: false,
              edit_spaces: false,
            }
          : structuredClone(user.permissions || { live: true });
      permissions.edit_spaces ??= !!(
        permissions.create_spaces ||
        ["spaces", "zones"].some((kind) =>
          Object.values(grants[kind] || {}).includes("edit"),
        )
      );
      const role = copy ? "viewer" : user.role || "viewer";
      const scopeNames = new Map([
        ...S.groups.map((s) => ["spaces:" + s.id, s.name]),
        ...S.groups.flatMap((s) =>
          s.zones.map((z) => ["zones:" + z.id, s.name + " / " + z.name]),
        ),
        ...(S.inventory || []).map((d) => ["devices:" + d.id, d.name]),
        ...sources().map((c) => [
          "channels:" + c.id,
          c.parent.name + " / " + c.name,
        ]),
      ]);
      const grantSelect = (kind, id, parentKind = "", parentId = "") =>
        `<select class="select infra-grant" data-grant="${kind}" data-id="${h(id)}" ${parentKind ? `data-parent-kind="${parentKind}" data-parent-id="${h(parentId)}"` : ""} aria-label="${h(L("Доступ: ", "Access: ") + (scopeNames.get(kind + ":" + id) || id))}"><option value="">${h(L("Нет доступа", "No access"))}</option><option value="read" ${grants[kind]?.[id] === "read" ? "selected" : ""}>${h(L("Чтение", "Read"))}</option><option value="edit" ${grants[kind]?.[id] === "edit" ? "selected" : ""}>${h(L("Редактирование", "Edit"))}</option></select>`;
      const spaceTree = S.groups
        .map(
          (space) =>
            `<details class="infra-grant-branch" data-policy-name="${h(space.name)}"><summary><span class="infra-grant-chevron">${icon("chevron-right")}</span><span>${window.VWSIcons.html(space.icon, "layers-3")}</span><strong>${h(space.name)}</strong><small data-grant-summary></small>${grantSelect("spaces", space.id)}</summary>${space.zones.map((zone) => `<div class="infra-grant-row" data-policy-name="${h(zone.name)}"><span>${window.VWSIcons.html(zone.icon, "map-pin")}</span><span>${h(zone.name)}</span>${grantSelect("zones", zone.id, "spaces", space.id)}</div>`).join("")}</details>`,
        )
        .join("");
      const deviceTree = (S.inventory || [])
        .map(
          (device) =>
            `<details class="infra-grant-branch" data-policy-name="${h(device.name)}"><summary><span class="infra-grant-chevron">${icon("chevron-right")}</span><span>${icon(device.kind === "recorder" ? "server" : "camera")}</span><strong>${h(device.name)}</strong><small data-grant-summary></small>${grantSelect("devices", device.id)}</summary>${device.channels.map((camera) => `<div class="infra-grant-row" data-policy-name="${h(camera.name)}"><span>${icon(device.kind === "recorder" ? "webcam" : "camera")}</span><span>${h(camera.name)}${camera.is_hidden ? ` <small>${h(L("скрыта", "hidden"))}</small>` : ""}</span>${grantSelect("channels", camera.id, "devices", device.id)}</div>`).join("")}</details>`,
        )
        .join("");
      const grantSection = (label, symbol, tree) =>
        `<section class="infra-policy-section"><div class="infra-section-label">${icon(symbol)}${h(label)}</div><div class="infra-policy-toolbar"><label class="search-field">${icon("search")}<input type="search" data-policy-search placeholder="${h(L("Поиск…", "Search…"))}" aria-label="${h(L("Поиск: ", "Search: ") + label)}"></label><button type="button" class="btn btn-sm" data-policy-expand="true">${icon("list-tree")}${h(L("Развернуть всё", "Expand all"))}</button><button type="button" class="btn btn-sm" data-policy-expand="false">${icon("chevrons-down-up")}${h(L("Свернуть всё", "Collapse all"))}</button></div><div class="infra-grant-tree">${tree || `<p class="infra-help">${h(L("Ресурсов пока нет", "No resources yet"))}</p>`}</div><p class="infra-help" data-policy-empty hidden>${h(L("Ничего не найдено", "No results"))}</p></section>`;
      const check = (name, ru, en) =>
        `<label class="infra-check"><input type="checkbox" name="${name}" ${permissions[name] ? "checked" : ""}>${h(L(ru, en))}</label>`;
      const modal = H.modal(
        copy
          ? L("Копировать пользователя", "Copy user")
          : isNew
            ? L("Новый пользователь", "New user")
            : L("Редактировать пользователя", "Edit user"),
        L(
          "Управление оборудованием доступно только администратору. Удаление канала требует доступа к самому каналу или устройству.",
          "Hardware management is administrator-only. Removing a channel requires access to that channel or its physical device.",
        ),
        `${feedback}<form id="user-form" class="form-stack"><div class="form-grid">${field(L("Логин", "Login"), input("username", copy ? (user.username + "_copy").slice(0, 64) : user.username || "", `required maxlength="64" autocomplete="off" ${!isNew ? "readonly" : ""}`))}${field(L("Псевдоним", "Display name"), input("alias", user.alias || "", 'maxlength="100"'))}${field(L("Новый пароль", "New password"), input("password", "", `type="password" minlength="10" maxlength="256" autocomplete="new-password" ${!existing ? "required" : ""}`), copy ? L("Пусто — создать неактивную копию без пароля", "Leave blank to create an inactive copy without a password") : !isNew ? L("Пусто — сохранить прежний пароль", "Leave blank to keep the current password") : "")}${field(L("Роль", "Role"), `<select class="select" name="role" ${copy ? "disabled" : ""}><option value="viewer" ${role !== "admin" ? "selected" : ""}>${h(L("Пользователь", "User"))}</option><option value="admin" ${role === "admin" ? "selected" : ""}>${h(L("Администратор", "Administrator"))}</option></select>`)}</div><label class="infra-check" data-active-row><input name="active" type="checkbox" ${isNew || user.active ? "checked" : ""}>${h(L("Учётная запись активна", "Account active"))}</label><div data-admin-note class="infra-picker-note">${h(L("Администратор имеет полный доступ ко всем ресурсам и настройкам.", "Administrators have full access to every resource and setting."))}</div><div data-user-policy class="form-stack"><div class="infra-section-label">${icon("shield-check")}${h(L("Разрешения", "Permissions"))}</div><div class="infra-feature-grid">${check("live", "Просмотр видео", "Live video")}${check("archive_view", "Просмотр архива", "Archive playback")}${check("archive_export", "Скачивание архива", "Archive download")}${check("create_devices", "Добавлять устройства", "Create devices")}${check("edit_spaces", "Редактирование пространств", "Edit spaces")}</div>${grantSection(L("Пространства и зоны", "Spaces and zones"), "layers-3", spaceTree)}${grantSection(L("Устройства и каналы", "Devices and channels"), "video", deviceTree)}${user.pending_grants?.length ? `<div class="infra-picker-note">${h(L(`Ожидают сопоставления прав: ${user.pending_grants.length}`, `Pending access references: ${user.pending_grants.length}`))}<label class="infra-check"><input type="checkbox" name="clear_pending_grants">${h(L("Сбросить ожидающие назначения", "Clear pending access references"))}</label></div>` : ""}</div></form>`,
        `<button class="btn btn-primary" type="submit" form="user-form">${icon("check")}${h(L("Сохранить", "Save"))}</button>`,
        true,
      );
      const form = $("#user-form", modal);
      $$(".infra-policy-section", modal).forEach((section) => {
        const search = $("[data-policy-search]", section),
          branches = $$(".infra-grant-branch", section);
        let beforeSearch = null;
        search.oninput = () => {
          const query = search.value.trim().toLocaleLowerCase();
          if (query && !beforeSearch)
            beforeSearch = new Map(
              branches.map((branch) => [branch, branch.open]),
            );
          let found = 0;
          for (const branch of branches) {
            const parentMatch = branch.dataset.policyName
                .toLocaleLowerCase()
                .includes(query),
              rows = $$(".infra-grant-row", branch);
            let matchingRows = 0;
            for (const row of rows) {
              row.hidden =
                !!query &&
                !parentMatch &&
                !row.dataset.policyName.toLocaleLowerCase().includes(query);
              if (!row.hidden) matchingRows++;
            }
            branch.hidden = !!query && !parentMatch && !matchingRows;
            if (!branch.hidden) found++;
            if (query && !branch.hidden) branch.open = true;
            else if (!query && beforeSearch)
              branch.open = beforeSearch.get(branch) || false;
          }
          if (!query) beforeSearch = null;
          $("[data-policy-empty]", section).hidden =
            !!found || !branches.length;
        };
        $$("[data-policy-expand]", section).forEach(
          (button) =>
            (button.onclick = () => {
              branches
                .filter((branch) => !branch.hidden)
                .forEach(
                  (branch) =>
                    (branch.open = button.dataset.policyExpand === "true"),
                );
            }),
        );
      });

      function updatePolicy() {
        const isAdmin = form.elements.role.value === "admin";
        $$('[data-grant="spaces"],[data-grant="zones"]', modal).forEach(
          (select) => {
            select.options[2].disabled = !form.elements.edit_spaces.checked;
            if (!form.elements.edit_spaces.checked && select.value === "edit")
              select.value = "read";
          },
        );
        $("[data-user-policy]", modal).hidden = isAdmin;
        $("[data-admin-note]", modal).hidden = !isAdmin;
        if (!form.elements.archive_view.checked)
          form.elements.archive_export.checked = false;
        form.elements.archive_export.disabled =
          !form.elements.archive_view.checked;
        const policyIndex = new Map(
          $$("[data-grant]", modal).map((select) => [
            select.dataset.grant + ":" + select.dataset.id,
            select,
          ]),
        );
        $$("[data-parent-kind]", modal).forEach((select) => {
          const parent = policyIndex.get(
            select.dataset.parentKind + ":" + select.dataset.parentId,
          );
          select.options[0].textContent =
            parent?.value === "edit"
              ? L("Как у родителя", "Inherit parent")
              : parent?.value === "read"
                ? L("Как у родителя", "Inherit parent")
                : L("Нет доступа", "No access");
          select.disabled = parent?.value === "edit";
          if (select.disabled) select.value = "";
          select.title = select.disabled
            ? L(
                "Наследуется редактирование родителя",
                "Inherits parent edit access",
              )
            : parent?.value === "read"
              ? L(
                  "Чтение наследуется от родителя",
                  "Inherits parent read access",
                )
              : "";
        });
      }
      const refreshSummary = () => {
        $$(".infra-grant-branch", modal).forEach((branch) => {
          const parent = $("summary [data-grant]", branch),
            children = $$("[data-parent-kind]", branch),
            count = children.filter(
              (child) => child.value || parent?.value,
            ).length,
            summary = $("[data-grant-summary]", branch);
          summary.textContent = count + "/" + children.length;
          summary.title = L(
            "Дочерние ресурсы с доступом",
            "Child resources with access",
          );
        });
      };
      form.addEventListener("change", refreshSummary);
      refreshSummary();
      form.elements.role.onchange = updatePolicy;
      form.elements.archive_view.onchange = updatePolicy;
      form.elements.edit_spaces.onchange = updatePolicy;
      $$("[data-grant]", modal).forEach((select) => {
        select.addEventListener("click", (event) => event.stopPropagation());
        select.onchange = updatePolicy;
      });
      updatePolicy();
      form.onsubmit = async (event) => {
        event.preventDefault();
        const actual = { spaces: {}, zones: {}, channels: {}, devices: {} };
        $$("[data-grant]", modal)
          .filter((select) => !select.disabled && select.value)
          .forEach(
            (select) =>
              (actual[select.dataset.grant][select.dataset.id] = select.value),
          );
        const permissions = {};
        [
          "live",
          "archive_view",
          "archive_export",
          "create_devices",
          "edit_spaces",
        ].forEach((name) => (permissions[name] = form.elements[name].checked));
        const body = {
          username: form.elements.username.value,
          alias: form.elements.alias.value,
          password: form.elements.password.value,
          role: form.elements.role.value,
          active: form.elements.active.checked,
          grants: actual,
          permissions,
          clear_pending_grants: !!form.elements.clear_pending_grants?.checked,
        };
        try {
          await api(
            copy
              ? `/api/users/${encodeURIComponent(user.username)}/clone`
              : isNew
                ? "/api/users"
                : `/api/users/${encodeURIComponent(user.username)}`,
            { method: copy || isNew ? "POST" : "PUT", body },
          );
          await changed();
          H.toast(L("Пользователь сохранён", "User saved"));
        } catch (error) {
          message(modal, error.message, true);
        }
      };
    }

    let pageCleanup = null;
    if (mode === "cameras") pageCleanup = inventory();
    else if (mode === "groups") spacesPage();
    else usersPage();
    return () => {
      disposed = true;
      pageCleanup?.();
    };
  }
  window.VWSInfrastructure = { mount, iconPicker };
})();
