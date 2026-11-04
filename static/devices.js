/* VWSHub device console. Reads first; every write is an explicit operator action. */
(() => {
  "use strict";
  const esc = (v) =>
    String(v ?? "").replace(
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
  const svg = (name = "device") =>
    window.VWSIcons.html(
      {
        device: "server",
        camera: "webcam",
        warning: "triangle-alert",
        disk: "hard-drive",
      }[name] || name,
    );
  const titles = {
    location: ["Время и синхронизация", "Time and synchronization"],
    ntp: ["NTP", "NTP"],
    general: ["Система", "System"],
    recording: ["Запись", "Recording"],
    encoder: ["Каналы и видео", "Channels and video"],
    network: ["Сеть", "Network"],
    dhcp: ["DHCP", "DHCP"],
    dns: ["DNS", "DNS"],
    osd: ["Названия и маски", "Names and privacy masks"],
    imaging: ["Изображение", "Image"],
    maintenance: ["Обслуживание", "Maintenance"],
    digital: ["Цифровые каналы", "Digital channels"],
    storage: ["Хранилище", "Storage"],
    users: ["Пользователи и доступ", "Accounts and access"],
    ptz: ["PTZ", "PTZ"],
    info: ["Обзор устройства", "Device overview"],
  };
  function createDialogFocus(doc) {
    const stack=[];
    const focusable=scope=>Array.from(scope.querySelectorAll('button:not(:disabled),a[href],input:not(:disabled):not([type=hidden]),select:not(:disabled),textarea:not(:disabled),[tabindex]:not([tabindex="-1"])')).filter(node=>!node.disabled && !node.closest("[hidden],[inert]") && node.getClientRects().length);
    const keydown=event=>{
      const top=stack.at(-1);
      if(!top?.scope.isConnected) return;
      if(event.key==="Escape") {
        event.preventDefault();event.stopPropagation();top.cancel();
      } else if(event.key==="Tab") {
        const nodes=focusable(top.scope),first=nodes[0],last=nodes.at(-1);
        if(!first) {event.preventDefault();top.scope.focus();return;}
        if(!top.scope.contains(doc.activeElement) || (event.shiftKey ? doc.activeElement===first : doc.activeElement===last)) {
          event.preventDefault();event.stopPropagation();(event.shiftKey?last:first).focus();
        }
      }
    };
    doc.addEventListener("keydown",keydown,true);
    return {
      push(scope,cancel,returnTo=doc.activeElement) {
        const entry={scope,cancel,returnTo};stack.push(entry);
        return {close(restore=true) {
          const index=stack.indexOf(entry);if(index<0)return;
          const wasTop=index===stack.length-1;stack.splice(index,1);
          if(!restore || !wasTop)return;
          queueMicrotask(()=>{
            const current=stack.at(-1);
            if(returnTo?.isConnected && !returnTo.disabled && (!current || current.scope.contains(returnTo))) returnTo.focus();
            else if(current?.scope.isConnected) (focusable(current.scope)[0] || current.scope).focus();
          });
        }};
      },
      dispose() {stack.length=0;doc.removeEventListener("keydown",keydown,true);}
    };
  }
  function mount(options) {
    const {
      root,
      cameras = [],
      isAdmin = true,
      onError = () => {},
      onSuccess = () => {},
    } = options;
    const en = (options.language || document.documentElement.lang).startsWith(
        "en",
      ),
      t = (ru, eng) => window.vwsTranslate?.(ru) || (en ? eng : ru);
    const title = (key) => titles[key]?.[en ? 1 : 0] || key;
    let disposed = false,
      category = "all",
      search = "",
      dialog = null,
      aborter = null,
      version = 0,
      selected = null,
      cap = null,
      active = "info",
      ptzStop = null,
      dialogFocus = null,
      dialogOrigin = null,
      finishConfirmation = null;
    const cameraGroups = new Map();
    cameras.forEach((cam) => {
      const key = cam.recorder_id || [cam.protocol, cam.ip, cam.port].join("|");
      if (!cameraGroups.has(key))
        cameraGroups.set(key, { ...cam, members: [] });
      cameraGroups.get(key).members.push(cam);
    });
    const devices = [...cameraGroups.values()];
    const q = (selector, scope = root) => scope.querySelector(selector);
    const qa = (selector, scope = root) =>
      Array.from(scope.querySelectorAll(selector));
    const fail = (e) => {
      if (!disposed && e.name !== "AbortError") onError(e.message || String(e));
    };
    const request = async (path, body = {}, signal = aborter?.signal) => {
      const payload = { cam_id: selected?.id, ...body };
      if (options.api)
        return options.api(path, { method: "POST", body: payload, signal });
      const response = await fetch(path, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": window.VWSHUB_BOOTSTRAP?.csrf_token || "",
        },
        body: JSON.stringify(payload),
        signal,
      });
      const data = await response.json();
      if (!response.ok || data.error)
        throw new Error(data.error || "Device request failed");
      return data;
    };
    const empty = (message) =>
      `<div class="dv-empty">${svg("device")}<p>${esc(message)}</p></div>`;
    const busy = () =>
      `<div class="dv-empty" role="status"><span class="dv-spinner"></span><p>${t("Запрос к устройству…", "Reading device…")}</p></div>`;
    const field = (label, content, hint = "") =>
      `<label class="dv-field"><span>${esc(label)}</span>${content}${hint ? `<small>${esc(hint)}</small>` : ""}</label>`;
    const note = (text) =>
      `<div class="dv-note">${svg("warning")}<p>${esc(text)}</p></div>`;
    if (!isAdmin) {
      root.innerHTML = empty(
        t(
          "Управление устройствами доступно администратору.",
          "Device management requires an administrator.",
        ),
      );
      return () => {};
    }
    const focusScope=createDialogFocus(document);
    function board() {
      const counts = {
        all: devices.length,
        dvrip: devices.filter((c) => c.protocol === "dvrip").length,
        onvif: devices.filter((c) => c.protocol !== "dvrip").length,
      };
      root.innerHTML = `<section class="dv-page"><header class="dv-heading page-head"><div><p class="eyebrow">${t("ОБОРУДОВАНИЕ", "HARDWARE")}</p><h1>${t("Управление оборудованием", "Hardware management")}</h1><p>${t("Настройки регистраторов и камер в одном рабочем пространстве.", "Configure recorders and cameras in one workspace.")}</p></div><div class="page-actions"><span class="dv-total">${devices.length} ${t("устройств", "devices")}</span><button type="button" class="btn btn-primary" id="device-add-recorder">${options.hub?.icon("plus") || "+"}${t("Каталог устройств", "Device catalog")}</button></div></header><div class="dv-board-toolbar"><div class="dv-category-tabs" role="tablist">${[
        ["all", t("Все устройства", "All devices")],
        ["dvrip", t("XM / регистраторы", "XM / recorders")],
        ["onvif", t("IP / ONVIF", "IP / ONVIF")],
      ]
        .map(
          ([id, name]) =>
            `<button type="button" role="tab" aria-selected="${category === id}" class="${category === id ? "active" : ""}" data-category="${id}">${name}<span>${counts[id]}</span></button>`,
        )
        .join(
          "",
        )}</div><input class="field" data-device-search aria-label="${t("Поиск устройств", "Find devices")}" placeholder="${t("Название или IP", "Name or IP")}" value="${esc(search)}"></div><div class="dv-grid" data-device-grid></div></section>`;
      const sticky = document.createElement("div");
      sticky.className = "page-sticky";
      const head = q(".dv-heading"),
        toolbar = q(".dv-board-toolbar");
      head.before(sticky);
      sticky.append(head, toolbar);
      q("#device-add-recorder").onclick = () => options.hub.showView("cameras");
      qa("[data-category]").forEach(
        (b) =>
          (b.onclick = () => {
            category = b.dataset.category;
            board();
          }),
      );
      q("[data-device-search]").oninput = (e) => {
        search = e.target.value;
        cards();
      };
      cards();
    }
    function cards() {
      const matches = devices.filter(
        (c) =>
          (category === "all" ||
            (category === "dvrip"
              ? c.protocol === "dvrip"
              : c.protocol !== "dvrip")) &&
          `${c.name} ${c.recorder_name || ""} ${c.ip}`
            .toLowerCase()
            .includes(search.toLowerCase()),
      );
      q("[data-device-grid]").innerHTML = matches.length
        ? matches
            .map(
              (c) =>
                `<div class="dv-card-wrap"><button type="button" class="dv-card" data-open-device="${esc(c.id)}"><span class="dv-card-icon">${svg(c.protocol === "dvrip" ? "device" : "camera")}</span><span class="dv-card-copy"><b data-no-i18n>${esc(c.recorder_name || c.name)}</b><small data-no-i18n>${esc(c.ip)} · ${c.protocol === "dvrip" ? "DVRIP" : "ONVIF"}</small><span>${c.members.length} ${t("канал(ов) в проекте", "project channel(s)")}</span></span><span class="dv-card-open">${t("Настроить", "Configure")} →</span></button><button type="button" class="icon-btn dv-rename" data-rename-recorder="${esc(c.id)}" title="${t("Имя регистратора", "Recorder name")}" aria-label="${t("Имя регистратора", "Recorder name")}">${options.hub?.icon("edit") || "✎"}</button></div>`,
            )
            .join("")
        : empty(
            t(
              "Устройства не найдены. Добавьте подключение в разделе «Камеры».",
              "No devices found. Add a connection in Cameras.",
            ),
          );
      qa("[data-rename-recorder]").forEach(
        (b) =>
          (b.onclick = () =>
            window.VWSAdmin.renameRecorder(
              options.hub,
              devices.find((c) => c.id === b.dataset.renameRecorder),
              options.onCatalogChanged,
            )),
      );
      qa("[data-open-device]").forEach(
        (b) =>
          (b.onclick = () =>
            open(devices.find((c) => c.id === b.dataset.openDevice))),
      );
    }
    function close(restoreFocus = true) {
      ++version;
      finishConfirmation?.(false,false);
      ptzStop?.();
      ptzStop = null;
      aborter?.abort();
      dialog?.remove();
      dialog = null;
      dialogFocus?.close(restoreFocus);
      dialogFocus = null;
      dialogOrigin = null;
    }
    function webURL(cam) {
      try {
        if (!cam.ip || /[\s/@?#\\]/.test(cam.ip)) return "";
        return new URL(
          `http://${cam.ip.includes(":") ? "[" + cam.ip + "]" : cam.ip}${(cam.web_port || (cam.protocol === "onvif" && cam.port)) ? ":" + Number(cam.web_port || cam.port) : ""}`,
        ).href;
      } catch (_) {
        return "";
      }
    }
    async function open(cam) {
      const origin=dialog ? dialogOrigin : document.activeElement;
      close(false);
      dialogOrigin=origin;
      selected = cam;
      active = "info";
      aborter = new AbortController();
      const generation = ++version;
      dialog = document.createElement("div");
      dialog.className = "dv-backdrop";
      dialog.innerHTML = `<section class="dv-dialog" role="dialog" aria-modal="true" aria-labelledby="dv-dialog-title" tabindex="-1"><header class="dv-dialog-heading"><span class="dv-card-icon">${svg(cam.protocol === "dvrip" ? "device" : "camera")}</span><div><h2 id="dv-dialog-title" data-no-i18n>${esc(cam.recorder_name || cam.name)}</h2><p data-no-i18n>${esc(cam.ip)} · ${cam.protocol === "dvrip" ? "XM / DVRIP" : "ONVIF"}</p></div><a class="btn btn-sm" data-web target="_blank" rel="noopener noreferrer">${svg("link")} ${t("Веб-интерфейс", "Web interface")}</a><button type="button" class="icon-btn" data-refresh aria-label="${t("Обновить", "Refresh")}">${svg("refresh")}</button><button type="button" class="icon-btn" data-close aria-label="${t("Закрыть", "Close")}">${svg("close")}</button></header><div class="dv-dialog-main" data-workspace>${busy()}</div></section>`;
      document.body.append(dialog);
      dialogFocus=focusScope.push(q(".dv-dialog",dialog),()=>close(),origin);
      q("[data-close]", dialog).onclick = () => close();
      q("[data-refresh]", dialog).onclick = () => open(selected);
      const web = q("[data-web]", dialog),
        href = webURL(cam);
      web.hidden = !href;
      if (href) web.href = href;
      q("[data-close]", dialog).focus();
      try {
        cap = await request("/api/device/capabilities");
        if (disposed || generation !== version || !dialog) return;
        draw();
      } catch (e) {
        if (generation === version && dialog) {
          q("[data-workspace]", dialog).innerHTML = empty(e.message);
          fail(e);
        }
      }
    }
    function draw() {
      ptzStop?.();
      ptzStop = null;
      const xm = selected.protocol === "dvrip",
        tabs = xm
          ? [
              "info",
              ...(cap.sections || []).map((s) => s.id).filter((id) => !["ntp", "dhcp", "dns"].includes(id)),
              "storage",
              "users",
              ...(cap.capabilities?.ptz ? ["ptz"] : []),
            ]
          : [
              "info",
              ...(cap.capabilities?.encoder ? ["encoder"] : []),
              ...(cap.capabilities?.imaging ? ["imaging"] : []),
              "network",
              ...(cap.capabilities?.time || cap.capabilities?.ntp_read ? ["location"] : []),
              "users",
              ...(cap.capabilities?.ptz ? ["ptz"] : []),
            ];
      q("[data-workspace]", dialog).innerHTML =
        `<nav class="dv-side-tabs" aria-label="${t("Настройки устройства", "Device settings")}">${tabs.map((id) => `<button type="button" data-section="${id}" class="${active === id ? "active" : ""}">${title(id)}</button>`).join("")}</nav><div class="dv-section"><header class="dv-section-heading"><div><span>${xm ? "XM / DVRIP" : "ONVIF"}</span><h3>${title(active)}</h3></div><span class="dv-connected">${t("Связь установлена", "Connected")}</span></header><div data-content></div></div>`;
      qa("[data-section]", dialog).forEach(
        (b) =>
          (b.onclick = () => {
            active = b.dataset.section;
            draw();
          }),
      );
      const content = q("[data-content]", dialog);
      if (active === "info") readInfo(content);
      else if (active === "storage") readStorage(content);
      else if (active === "users") readUsers(content);
      else if (active === "ptz") readPTZ(content);
      else if (xm) readConfig(content, active, Number(selected.channel || 0));
      else if (active === "network") readONVIFNetwork(content);
      else if (active === "location") readONVIFTime(content);
      else readONVIFSettings(content, active);
    }
    const isCurrent = (content, generation) =>
      !disposed && dialog && content.isConnected && version === generation;
    async function confirmAction(warning, phrase, destructive = false) {
      return new Promise((resolve) => {
        if (!dialog) {
          resolve(false);
          return;
        }
        finishConfirmation?.(false,false);
        const returnTo=document.activeElement;
        const panel = document.createElement("div");
        panel.className = "dv-confirm-backdrop";
        panel.innerHTML = `<section class="dv-confirm" role="alertdialog" aria-modal="true" aria-labelledby="dv-confirm-title" aria-describedby="dv-confirm-message" tabindex="-1"><div class="dv-confirm-icon">${svg("warning")}</div><h3 id="dv-confirm-title">${t("Подтвердите действие", "Confirm operation")}</h3><p id="dv-confirm-message">${esc(warning)}</p>${phrase ? field(t("Введите точное имя устройства", "Type the exact device name"), `<input class="field" data-phrase autocomplete="off" placeholder="${esc(phrase)}">`) : ""}<label class="dv-accept"><input type="checkbox" data-accept> ${t("Я понимаю последствия и подтверждаю действие", "I understand and confirm this action")}</label><div class="dv-action-row"><button class="btn" data-cancel>${t("Отмена", "Cancel")}</button><button class="btn ${destructive ? "btn-danger" : "btn-primary"}" data-confirm disabled>${t("Подтвердить", "Confirm")}</button></div></section>`;
        dialog.append(panel);
        let settled=false;
        const finish=(accepted,restore=true)=>{
          if(settled)return;settled=true;
          if(finishConfirmation===finish)finishConfirmation=null;
          panel.remove();resolve(accepted);confirmationFocus.close(restore);
        };
        const confirmationFocus=focusScope.push(q(".dv-confirm",panel),()=>finish(false),returnTo);
        finishConfirmation=finish;
        const validate = () =>
          (q("[data-confirm]", panel).disabled =
            !q("[data-accept]", panel).checked ||
            (phrase && q("[data-phrase]", panel).value !== phrase));
        q("[data-accept]", panel).onchange = validate;
        q("[data-phrase]", panel)?.addEventListener("input", validate);
        q("[data-cancel]", panel).onclick = () => finish(false);
        q("[data-confirm]", panel).onclick = () => finish(true);
        (q("[data-phrase]", panel) || q("[data-accept]", panel)).focus();
      });
    }
    function infoTable(data) {
      const labels = {
        Manufacturer:["Производитель","Manufacturer"], Model:["Модель","Model"], DeviceType:["Тип устройства","Device type"],
        SerialNumber:["Серийный номер","Serial number"], SerialNo:["Серийный номер","Serial number"],
        SoftWareVersion:["Прошивка","Firmware"], FirmwareVersion:["Прошивка","Firmware"],
        HardWare:["Аппаратная платформа","Hardware platform"], HardWareVersion:["Версия оборудования","Hardware version"], Hardware:["Аппаратная платформа","Hardware platform"], HardwareVersion:["Версия оборудования","Hardware version"], ProtocolVersion:["Версия протокола","Protocol version"],
        BuildTime:["Дата прошивки","Build time"], VideoInChannel:["Аналоговые каналы","Analog inputs"], DigChannel:["IP-каналы","IP inputs"],
        ChannelNum:["Каналы","Channels"], AudioInChannel:["Аудиовходы","Audio inputs"],
        HostIP:["IP-адрес","IP address"], GateWay:["Шлюз","Gateway"], Gateway:["Шлюз","Gateway"], Submask:["Маска подсети","Subnet mask"],
        HostName:["Сетевое имя","Network name"], MAC:["MAC-адрес","MAC address"], HttpPort:["HTTP-порт","HTTP port"],
        TCPPort:["Порт управления","Management port"], UDPPort:["UDP-порт","UDP port"], RTSPPort:["RTSP-порт","RTSP port"],
      };
      const entries=Object.entries(data || {}).filter(([key,value])=>labels[key] && value!==null && typeof value!=="object");
      if (!entries.length)return empty(t("Данные не предоставлены", "No information reported"));
      return `<dl class="dv-info">${entries.map(([key,value])=>`<div><dt>${esc(t(...labels[key]))}</dt><dd data-no-i18n>${esc(value)}</dd></div>`).join("")}</dl>`;
    }

    function deviceClock(value) {
      if(typeof value==="string")return value.replace("T"," ");
      const clock=value?.LocalDateTime || value?.UTCDateTime;
      const d=clock?.Date, time=clock?.Time;
      if(!d || !time)return "—";
      const pad=n=>String(n).padStart(2,"0");
      return `${d.Year}-${pad(d.Month)}-${pad(d.Day)} ${pad(time.Hour)}:${pad(time.Minute)}:${pad(time.Second)}${value.UTCDateTime && !value.LocalDateTime ? " UTC" : ""}`;
    }
    function serviceStates(services) {
      const labels={network:["Сеть","Network"],management:["Управление","Management"],live:["Живое видео","Live video"],archive:["Архив","Archive"],audio:["Аудио","Audio"]};
      return `<dl class="dv-service-states">${Object.entries(labels).map(([key,label])=>`<div><dt>${esc(t(...label))}</dt><dd class="${services?.[key]==="confirmed" ? "confirmed" : "unknown"}">${esc(services?.[key]==="confirmed" ? t("Подтверждено","Confirmed") : t("Не проверено","Not checked"))}</dd></div>`).join("")}</dl>`;
    }
    async function readInfo(content) {
      const generation = version;
      content.innerHTML = busy();
      try {
        const data = await request("/api/device/system", { action: "read" });
        if (!isCurrent(content, generation)) return;
        const httpPort=Number(data.network_display?.HttpPort || data.network_display?.HTTPPort);
        if(Number.isInteger(httpPort) && httpPort>=1 && httpPort<=65535){
          const link=q("[data-web]",dialog),url=webURL({...selected,web_port:httpPort});
          if(link && url)link.href=url;
        }
        content.innerHTML = `<div class="dv-two-columns"><section class="dv-panel"><h4>${t("Об устройстве", "Device details")}</h4>${infoTable(data.system_info)}${serviceStates(data.services)}</section><section class="dv-panel"><h4>${t("Сетевые сведения", "Network details")}</h4>${infoTable(data.network_display || (Array.isArray(data.network) ? {} : data.network || {}))}</section><section class="dv-panel dv-wide"><h4>${t("Время и обслуживание", "Time and maintenance")}</h4><p class="dv-clock">${esc(deviceClock(data.time))}</p><div class="dv-action-row"><button class="btn" data-time ${cap.capabilities?.time && data.time != null ? "" : "disabled hidden"}>${t("Синхронизировать время", "Synchronize time")}</button><button class="btn btn-danger" data-reboot ${cap.capabilities?.reboot ? "" : "disabled"}>${t("Перезапустить регистратор", "Restart recorder")}</button></div><p class="dv-muted">${t("Изменение времени влияет на временную шкалу архива. Перезагрузка временно отключит все каналы.", "Clock changes affect archive timestamps. A reboot temporarily disconnects every channel.")}</p></section></div>`;
        q("[data-time]", content).onclick = async () => {
          if (
            !(await confirmAction(
              t(
                "Синхронизировать часы устройства со временем этого компьютера?",
                "Synchronize the device clock with this computer?",
              ),
            ))
          )
            return;
          const now = new Date(),
            p = (n) => String(n).padStart(2, "0"),
            local = `${now.getFullYear()}-${p(now.getMonth() + 1)}-${p(now.getDate())}T${p(now.getHours())}:${p(now.getMinutes())}:${p(now.getSeconds())}`;
          try {
            const result=await request("/api/device/system", {
              action: "time",
              utc: now.toISOString(),
              local_time: local,
            });
            (result.saved === false ? onError : onSuccess)(result.message || t("Команда установки времени отправлена", "Time update sent"));
            readInfo(content);
          } catch (e) {
            fail(e);
          }
        };
        q("[data-reboot]", content).onclick = async (event) => {
          const trigger=event.currentTarget;
          if(trigger.disabled)return;
          if (
            !(await confirmAction(
              t(
                "Перезагрузить устройство? Все подключённые к нему каналы временно будут недоступны.",
                "Reboot this device? All its channels will temporarily be unavailable.",
              ),
              selected.recorder_name || selected.name,
            ))
          )
            return;
          try {
            trigger.disabled=true;
            const result=await request("/api/device/system", {
              action: "reboot",
              confirm: true,
              device_name: selected.recorder_name || selected.name,
            });
            onSuccess(
              result.message || t("Команда перезапуска отправлена; завершение ещё не подтверждено", "Restart requested; completion is not confirmed yet"),
            );
            const check=document.createElement("button");
            check.className="btn"; check.type="button";
            check.textContent=t("Проверить доступность после перезапуска", "Check availability after restart");
            check.onclick=()=>readInfo(content);
            trigger.after(check);
          } catch (e) {
            trigger.disabled=false; fail(e);
          }
        };
      } catch (e) {
        if (isCurrent(content, generation))
          content.innerHTML = empty(e.message);
        fail(e);
      }
    }
    function contextLabel(f) {
      const path = f.path,
        dayIndex = path.indexOf("TimeSection");
      if (dayIndex >= 0) {
        const day = Number(path[dayIndex + 1]),
          slot = Number(path[dayIndex + 2]);
        return `${(en ? ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"] : ["Воскресенье", "Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"])[day] || day} · ${t("интервал", "period")} ${slot + 1}`;
      }
      return path
        .slice(0, -1)
        .filter((p) => typeof p === "string")
        .map((p) =>
          en
            ? p.replace(/([a-z])([A-Z])/g, "$1 $2")
            : {
                MainFormat: "Основной поток",
                ExtraFormat: "Субпоток",
                Video: "Видео",
                Audio: "Звук",
                TimeTitle: "Время",
                ChannelTitle: "Имя канала",
              }[p] || p,
        )
        .join(" / ");
    }
    function configInput(f, i) {
      const attr = `data-field="${i}" ${f.editable ? "" : "disabled"}`;
      if (f.type === "boolean")
        return `<label class="dv-toggle"><input type="checkbox" ${attr} ${f.value ? "checked" : ""}><span>${t("Включено", "Enabled")}</span></label>`;
      if (f.type === "select")
        return `<select class="select" ${attr}>${f.options.map((v) => `<option data-no-i18n ${v === f.value ? "selected" : ""} value="${esc(v)}">${esc({ ConfigRecord: t("По расписанию", "Scheduled"), ManualRecord: t("Ручная запись", "Manual recording"), ClosedRecord: t("Остановить запись", "Stop recording"), OverWrite: t("Перезаписывать старые", "Overwrite oldest"), StopRecord: t("Остановить запись", "Stop recording"), Never: t("Никогда", "Never") }[v] || v)}</option>`).join("")}</select>`;
      if (f.type === "schedule") {
        const parts = /^(\d+) ([\d:]+)-([\d:]+)$/.exec(f.value);
        return `<div class="dv-schedule-value" data-schedule="${i}"><input class="field" type="number" min="0" max="65535" value="${parts?.[1] || 0}" aria-label="${t("Маска включения", "Enabled mask")}" data-mask><input class="field" type="text" pattern="[0-2][0-9]:[0-5][0-9]:[0-5][0-9]" value="${parts?.[2] || "00:00:00"}" aria-label="${t("Начало", "Start")}" data-start><span>—</span><input class="field" type="text" value="${parts?.[3] || "24:00:00"}" aria-label="${t("Конец", "End")}" data-end></div>`;
      }
      return `<input class="field" ${attr} type="${f.type === "number" ? "number" : "text"}" ${f.type === "number" ? `min="${f.min}" max="${f.max}" step="${f.step}"` : ""} value="${esc(f.value)}">`;
    }
    async function readConfig(content, section, channel) {
      const generation = version;
      content.innerHTML = busy();
      try {
        const data = await request("/api/device/config", { section, channel });
        if (!isCurrent(content, generation)) return;
        const fields = (data.fields || []).filter(f => f.display !== false);
        content.innerHTML = `<div class="dv-scope-row"><span class="dv-scope">${data.scope === "channel" ? t("Настройки выбранного канала", "Selected channel settings") : data.scope === "interface" ? t("Сетевые интерфейсы устройства", "Device network interfaces") : t("Настройки всего устройства", "Whole-device settings")}</span>${data.channel_count ? field(t("Канал", "Channel"), `<select class="select" data-config-channel>${Array.from({ length: data.channel_count }, (_, i) => `<option value="${i}" ${i === channel ? "selected" : ""}>${t("Канал", "Channel")} ${i + 1}</option>`).join("")}</select>`) : ""}${["location","ntp"].includes(section) ? '<div class="dv-network-subtabs"><button type="button" class="btn btn-sm" data-subsection="location">Дата и время</button><button type="button" class="btn btn-sm" data-subsection="ntp">NTP</button></div>' : ""}${section === "network" ? '<div class="dv-network-subtabs"><button class="btn btn-sm" data-subsection="dhcp">DHCP</button><button class="btn btn-sm" data-subsection="dns">DNS</button></div>' : ""}</div>${["network", "dhcp", "dns", "digital"].includes(section) ? note(t("Смена сетевых параметров может прервать соединение. После смены IP обновите адрес подключения в разделе «Камеры».", "Network changes may disconnect the device. Update its connection address in Cameras afterward.")) : ""}${section === "maintenance" ? note(t("Автоматическое удаление файлов удаляет старые записи без возможности восстановления. Для включения потребуется подтверждение имени устройства.", "Automatic deletion permanently removes older recordings. Enabling it requires the device name.")) : ""}<form data-config-form>${!fields.length ? note(t("Подтверждённых параметров для редактирования нет. Неизвестные настройки сохраняются без изменений.", "No verified editable settings. Unknown configuration is preserved.")) : ""}<div class="dv-fields">${fields.map((f, i) => field(t(f.label, f.key.replace(/([a-z])([A-Z])/g, "$1 $2")), configInput(f, i), f.context || contextLabel(f))).join("")}</div><footer class="dv-form-footer"><span>${t("Показаны поддержанные параметры. Неизвестные поля сохраняются без изменений.", "Only verified fields are shown. Unknown configuration is preserved.")}</span><button class="btn btn-primary" type="submit" ${fields.some((f) => f.editable) ? "" : "disabled"}>${svg("check")} ${t("Применить", "Apply changes")}</button></footer></form>`;
        q("[data-config-channel]", content)?.addEventListener("change", (e) =>
          readConfig(content, section, Number(e.target.value)),
        );
        qa("[data-subsection]", content).forEach((b)=>{
          b.setAttribute("aria-pressed",String(b.dataset.subsection===section));
          b.onclick=()=>readConfig(content,b.dataset.subsection,channel);
        });
        q("[data-config-form]", content).onsubmit = async (e) => {
          e.preventDefault();
          const changes = [];
          fields.forEach((f, i) => {
            if (!f.editable) return;
            const input = q(`[data-field="${i}"]`, content),
              schedule = q(`[data-schedule="${i}"]`, content);
            let value;
            if (schedule)
              value = `${q("[data-mask]", schedule).value} ${q("[data-start]", schedule).value}-${q("[data-end]", schedule).value}`;
            else if (f.type === "boolean") value = input.checked;
            else if (f.type === "number") value = Number(input.value);
            else value = input.value;
            if (JSON.stringify(value) !== JSON.stringify(f.value))
              changes.push({ path: f.path, value });
          });
          if (!changes.length) {
            onSuccess(t("Нет изменений", "No changes"));
            return;
          }
          const dangerous =
            ["network", "dhcp", "dns", "digital"].includes(section) ||
            (section === "maintenance" &&
              changes.some(
                (c) =>
                  c.path.includes("AutoDeleteFilesDays") && Number(c.value) > 0,
              ));
          if (
            dangerous &&
            !(await confirmAction(
              t(
                "Эти настройки могут прервать подключение или изменить хранение записей. Проверьте значения перед применением.",
                "These settings may disconnect the device or alter recording retention. Review the values before applying.",
              ),
              selected.recorder_name || selected.name,
            ))
          )
            return;
          const button = q('button[type="submit"]', content);
          button.disabled = true;
          try {
            const result = await request("/api/device/config", {
              section,
              channel,
              revision: data.revision,
              changes,
              confirm: true,
              ...(dangerous
                ? { device_name: selected.recorder_name || selected.name }
                : {}),
            });
            (result.saved === false && !result.restart_required
              ? onError
              : onSuccess)(
              result.message || t("Настройки отправлены", "Settings sent"),
            );
            if (isCurrent(content, generation))
              readConfig(content, section, channel);
          } catch (error) {
            fail(error);
            button.disabled = false;
          }
        };
      } catch (e) {
        if (isCurrent(content, generation))
          content.innerHTML = empty(e.message);
        fail(e);
      }
    }
    async function readStorage(content) {
      const generation = version;
      content.innerHTML = busy();
      try {
        const data = await request("/api/device/storage");
        if (!isCurrent(content, generation)) return;
        content.innerHTML = `${note(data.warning)}<div class="dv-storage-grid">${(data.disks || []).map((d, i) => `<article class="dv-storage-card">${svg("disk")}<h4>${d.kind === "sd" ? "SD" : d.kind === "hdd" ? "HDD" : t("Носитель", "Storage")} ${d.serial + 1} · ${t("раздел", "partition")} ${d.partition + 1}</h4><span class="dv-connected">${t("Обнаружен", "Detected")}</span><dl><dt>${t("Объём", "Capacity")}</dt><dd>${(d.total_mb / 1024).toFixed(1)} GB</dd><dt>${t("Свободно", "Free")}</dt><dd>${(d.free_mb / 1024).toFixed(1)} GB</dd><dt>${t("Состояние", "Status")}</dt><dd>${esc(d.status)}</dd></dl><button class="btn btn-danger" data-format="${i}">${t("Форматировать", "Format storage")}</button></article>`).join("") || empty(t("Диск/раздел не подтверждён устройством. Форматирование отключено.", "No disk or partition was confirmed. Formatting is disabled."))}</div>`;
        qa("[data-format]", content).forEach(
          (b) =>
            (b.onclick = async () => {
              const d = data.disks[Number(b.dataset.format)],
                warning =
                  d.kind === "sd"
                    ? t(
                        "ВСЕ записи на SD-карте будут безвозвратно удалены.",
                        "ALL recordings on this SD card will be permanently erased.",
                      )
                    : t(
                        "Будут безвозвратно удалены ВСЕ записи выбранного носителя: для HDD регистратора — записи ВСЕХ камер; для SD-карты — все записи на этой карте. Это нельзя отменить.",
                        "ALL recordings will be permanently erased: for recorder HDD, recordings of ALL its cameras; for an SD card, every recording on that card. This cannot be undone.",
                      );
              if (
                !(await confirmAction(
                  warning,
                  selected.recorder_name || selected.name,
                  true,
                ))
              )
                return;
              b.disabled = true;
              try {
                await request("/api/device/storage/format", {
                  serial: d.serial,
                  partition: d.partition,
                  device_name: selected.recorder_name || selected.name,
                  confirmation: "ERASE_ALL_RECORDINGS",
                  confirm: true,
                });
                onSuccess(
                  t(
                    "Команда форматирования принята. Дождитесь завершения на устройстве.",
                    "Format command accepted. Wait for completion on the device.",
                  ),
                );
              } catch (e) {
                fail(e);
              } finally {
                b.disabled = false;
              }
            }),
        );
      } catch (e) {
        if (isCurrent(content, generation))
          content.innerHTML = empty(e.message);
        fail(e);
      }
    }
    async function readUsers(content) {
      const generation = version;
      content.innerHTML = busy();
      try {
        const data = await request("/api/device/users");
        if (!isCurrent(content, generation)) return;
        const users = data.users || [],
          groups = data.groups || [];
        content.innerHTML = `${note(t("Это учётные записи самого оборудования. После смены пароля текущего подключения обновите его в разделе «Камеры».", "These accounts belong to the hardware. After changing its connection account password, update Cameras."))}<div class="dv-users-table">${users.map((u) => `<div><b data-no-i18n>${esc(u.Name || u.Username)}</b><span data-no-i18n>${esc(u.Group || u.UserLevel || "—")}</span><small>${u.Reserved ? t("Зарезервирован", "Reserved") : ""}</small></div>`).join("")}</div><form data-user-form><div class="dv-fields">${field(t("Действие", "Action"), `<select class="select" name="action"><option value="create">${t("Создать", "Create")}</option><option value="update">${t("Изменить группу", "Change group")}</option><option value="password">${t("Изменить пароль", "Change password")}</option><option value="delete">${t("Удалить", "Delete")}</option></select>`)}${field(t("Логин устройства", "Device login"), '<input class="field" name="username" autocomplete="off" required maxlength="32">')}${field(t("Группа / роль", "Group / role"), `<select class="select" name="group">${groups.map((g) => `<option data-no-i18n value="${esc(g.Name)}">${esc(g.Name)}</option>`).join("")}</select>`)}${field(t("Новый пароль", "New password"), '<input class="field" type="password" name="password" autocomplete="new-password">')}${data.protocol === "dvrip" ? field(t("Прежний пароль (для смены)", "Old password (when changing)"), '<input class="field" type="password" name="old_password" autocomplete="off">') : ""}${field(t("Комментарий", "Comment"), '<input class="field" name="comment" maxlength="100">')}</div><footer class="dv-form-footer"><span>${t("Изменение применяется к выбранному устройству.", "Changes apply to this device.")}</span><button class="btn btn-primary" type="submit">${t("Выполнить", "Apply")}</button></footer></form>`;
        q("[data-user-form]", content).onsubmit = async (e) => {
          e.preventDefault();
          const form = e.currentTarget,
            body = Object.fromEntries(new FormData(form));
          if (
            !(await confirmAction(
              t(
                "Изменить учётные записи оборудования? Удаление или смена доступа может прервать подключение.",
                "Modify hardware accounts? Removing or changing access may disconnect clients.",
              ),
              selected.recorder_name || selected.name,
              body.action === "delete",
            ))
          )
            return;
          try {
            if (body.action === "password") delete body.group;
            await request("/api/device/users", { ...body, confirm: true });
            onSuccess(
              t("Ответ устройства получен", "Device response received"),
            );
            readUsers(content);
          } catch (error) {
            fail(error);
          }
        };
      } catch (e) {
        if (isCurrent(content, generation))
          content.innerHTML = empty(e.message);
        fail(e);
      }
    }
    async function readONVIFSettings(content, kind) {
      const generation = version,
        profiles = (cap.profiles || []).filter((p) =>
          kind === "encoder" ? p.encoder_token : p.video_source_token,
        );
      let token = profiles[0]?.token || "";
      content.innerHTML =
        field(
          t("Профиль", "Profile"),
          `<select class="select" data-profile>${profiles.map((p) => `<option value="${esc(p.token)}">${esc(p.name || p.token)}</option>`).join("")}</select>`,
        ) + `<div data-settings>${busy()}</div>`;
      q("[data-profile]", content).onchange = (e) => {
        token = e.target.value;
        read();
      };
      read();
      async function read() {
        const profile = token,
          box = q("[data-settings]", content);
        box.innerHTML = busy();
        try {
          const data = await request("/api/device/" + kind, {
            profile_token: profile,
          });
          if (!isCurrent(content, generation) || profile !== token) return;
          const settings = data.settings || {},
            ranges = data.options || {};
          let descriptors = [];
          if (kind === "encoder") {
            descriptors = [
              ["fps", t("Кадры/с", "Frames per second")],
              ["bitrate", t("Битрейт, кбит/с", "Bitrate, kbit/s")],
              ["quality", t("Качество", "Quality")],
            ]
              .filter(([key]) => settings[key] != null)
              .map(([key, label]) => ({
                key,
                label,
                value: settings[key],
                range: ranges[key],
              }));
          } else
            descriptors = Object.keys(settings).map((key) => ({
              key,
              label: en ? key : LABEL_IMAGE[key] || key,
              value: settings[key],
              range: ranges[key],
            }));
          box.innerHTML = `<form data-onvif-form><div class="dv-fields">${kind === "encoder" ? field(t("Кодек", "Codec"), `<input class="field" disabled value="${esc(settings.encoding || "—")}">`) + field(t("Разрешение", "Resolution"), `<select class="select" name="resolution" ${(ranges.resolutions || []).length ? "" : "disabled"}>${(ranges.resolutions || []).map((r) => `<option value="${r.width}x${r.height}" ${r.width === settings.width && r.height === settings.height ? "selected" : ""}>${r.width}×${r.height}</option>`).join("")}</select>`) : ""}${descriptors.map((d) => field(d.label, `<input class="field" name="${esc(d.key)}" type="number" step="${d.key === "quality" ? 0.1 : 1}" value="${esc(d.value)}" ${d.range ? `min="${d.range.Min}" max="${d.range.Max}"` : "disabled"}>`)).join("")}</div><footer class="dv-form-footer"><span>${t("Диапазоны сообщены устройством.", "Ranges reported by the device.")}</span><button class="btn btn-primary" type="submit">${t("Применить", "Apply")}</button></footer></form>`;
          q("[data-onvif-form]", box).onsubmit = async (e) => {
            e.preventDefault();
            const body = {};
            new FormData(e.currentTarget).forEach((v, k) => {
              if (k === "resolution") {
                [body.width, body.height] = v.split("x").map(Number);
              } else body[k] = Number(v);
            });
            try {
              const result = await request("/api/device/" + kind, {
                profile_token: profile,
                settings: body,
              });
              if (result.saved === false) onError(result.message);
              else onSuccess(result.message || t("Настройки применены", "Settings applied"));
              read();
            } catch (error) {
              fail(error);
            }
          };
        } catch (e) {
          if (isCurrent(content, generation)) box.innerHTML = empty(e.message);
          fail(e);
        }
      }
    }
    async function readONVIFTime(content) {
      const generation = version;
      content.innerHTML = busy();
      try {
        const data = await request("/api/device/onvif/ntp");
        if (!isCurrent(content, generation)) return;
        content.innerHTML = note(t("Изменение синхронизации влияет на временную шкалу архива. Порт и интервал NTP не входят в стандарт ONVIF и здесь не изменяются.", "Synchronization changes affect archive timestamps. NTP port and interval are outside this ONVIF operation and are preserved.")) +
          `<form data-onvif-ntp><div class="dv-fields">${field(t("Синхронизация NTP", "NTP synchronization"), `<label class="dv-toggle"><input type="checkbox" name="enabled" ${data.enabled === true ? "checked" : ""} ${data.mode_writable ? "" : "disabled"}><span>${data.enabled === null ? t("Режим не подтверждён", "Mode not reported") : t("Использовать NTP", "Use NTP")}</span></label>`)}${field(t("Серверы из DHCP", "Servers from DHCP"), `<label class="dv-toggle"><input type="checkbox" name="from_dhcp" ${data.from_dhcp ? "checked" : ""} ${data.writable ? "" : "disabled"}><span>DHCP</span></label>`)}${field(t("NTP-серверы", "NTP servers"), `<textarea class="field" name="servers" rows="4" spellcheck="false" data-no-i18n ${data.writable ? "" : "readonly"}>${esc((data.servers || []).join("\n"))}</textarea>`, t("IP-адрес или DNS-имя, каждый сервер с новой строки", "IP address or DNS name, one server per line"))}</div>${data.dhcp_servers?.length ? `<p class="dv-muted">${t("Получено из DHCP", "Received from DHCP")}: <span data-no-i18n>${esc(data.dhcp_servers.join(", "))}</span></p>` : ""}<footer class="dv-form-footer"><span>${data.writable ? `${t("Максимум серверов", "Maximum servers")}: ${data.max_servers}` : t("Устройство не подтвердило редактирование NTP. Доступно только чтение.", "The device did not confirm NTP editing. Read only.")}</span><button type="submit" class="btn btn-primary" ${data.writable ? "" : "disabled"}>${t("Применить", "Apply changes")}</button></footer></form>`;
        const form = q("[data-onvif-ntp]", content);
        form.onsubmit = async (event) => {
          event.preventDefault();
          const settings = {}, f = form.elements;
          if (f.from_dhcp.checked !== data.from_dhcp) settings.from_dhcp = f.from_dhcp.checked;
          const servers = f.servers.value.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
          if (JSON.stringify(servers) !== JSON.stringify(data.servers)) settings.servers = servers;
          if (data.mode_writable && f.enabled.checked !== data.enabled) settings.enabled = f.enabled.checked;
          if (!Object.keys(settings).length) { onSuccess(t("Нет изменений", "No changes")); return; }
          if (!(await confirmAction(t("Изменить синхронизацию времени устройства? Это может повлиять на временную шкалу архива.", "Change device time synchronization? This may affect archive timestamps.")))) return;
          const submit = q('[type="submit"]', form); submit.disabled = true;
          try {
            const result = await request("/api/device/onvif/ntp", {settings, revision:data.revision, confirm:true});
            (result.saved === false ? onError : onSuccess)(result.message);
            if (isCurrent(content, generation)) readONVIFTime(content);
          } catch (error) { submit.disabled = false; fail(error); }
        };
      } catch (error) {
        if (isCurrent(content, generation)) content.innerHTML = empty(error.message);
        fail(error);
      }
    }
    async function readONVIFNetwork(content) {
      const generation = version;
      content.innerHTML = busy();
      try {
        const data = await request("/api/device/onvif/network");
        if (!isCurrent(content, generation)) return;
        const interfaces = data.interfaces || [];
        content.innerHTML =
          note(
            t(
              "Изменение сети может отключить камеру. MAC показан только для чтения.",
              "Network changes may disconnect the camera. MAC is read-only.",
            ),
          ) +
          `<form data-onvif-network><div class="dv-fields">${field(t("Интерфейс", "Interface"), `<select class="select" name="token">${interfaces.map((i) => `<option value="${esc(i.token)}">${esc(i.Info?.Name || i.token)} · ${esc(i.Info?.HwAddress || "—")}</option>`).join("")}</select>`)}${field("DHCP", '<label class="dv-toggle"><input type="checkbox" name="dhcp" checked><span>DHCP</span></label>')}${field("IPv4", '<input class="field" name="address" placeholder="192.0.2.10">')}${field(t("Префикс маски", "Network prefix"), '<input class="field" type="number" name="prefix" min="1" max="32" value="24">')}${field(t("Шлюз", "Gateway"), '<input class="field" name="gateway">')}${field("DNS 1", '<input class="field" name="dns1">')}${field("DNS 2", '<input class="field" name="dns2">')}</div><footer class="dv-form-footer"><span>${t("Текущие адреса", "Current addresses")}: ${esc(JSON.stringify(interfaces.map((i) => i.IPv4?.Config)))}</span><button class="btn btn-primary" type="submit">${t("Применить сеть", "Apply network")}</button></footer></form>`;
        const form = q("[data-onvif-network]", content);
        const populate = () => {
          const item = interfaces.find(
              (i) => String(i.token) === form.elements.token.value,
            ),
            cfg = item?.IPv4?.Config || {},
            manual = cfg.Manual?.[0] || cfg.FromDHCP;
          form.elements.dhcp.checked = !!cfg.DHCP;
          form.elements.address.value = manual?.Address || "";
          form.elements.prefix.value = manual?.PrefixLength || 24;
          form.elements.gateway.value = data.gateway?.IPv4Address?.[0] || "";
          const dns = data.dns?.DNSManual || data.dns?.DNSFromDHCP || [];
          form.elements.dns1.value = dns[0]?.IPv4Address || "";
          form.elements.dns2.value = dns[1]?.IPv4Address || "";
        };
        form.elements.token.onchange = populate;
        populate();
        q("[data-onvif-network]", content).onsubmit = async (e) => {
          e.preventDefault();
          const f = e.currentTarget;
          if (
            !(await confirmAction(
              t(
                "Изменить сеть камеры? После смены адреса обновите подключение вручную.",
                "Change camera network? Update its connection afterward.",
              ),
              selected.recorder_name || selected.name,
            ))
          )
            return;
          const settings = {
            token: f.elements.token.value,
            dhcp: f.elements.dhcp.checked,
            address: f.elements.address.value,
            prefix: Number(f.elements.prefix.value),
            gateway: f.elements.gateway.value,
            dns: [f.elements.dns1.value, f.elements.dns2.value].filter(Boolean),
          };
          try {
            const result = await request("/api/device/onvif/network", {
              settings,
              confirm: true,
              device_name: selected.recorder_name || selected.name,
            });
            (result.saved === false ? onError : onSuccess)(result.message);
          } catch (error) {
            fail(error);
          }
        };
      } catch (e) {
        if (isCurrent(content, generation))
          content.innerHTML = empty(e.message);
        fail(e);
      }
    }
    function readPTZ(content) {
      ptzStop = mountPTZ(content, selected, {
        api: options.api,
        isAdmin,
        onError,
        onSuccess,
        caps: cap,
      });
    }
    board();
    return () => {
      disposed = true;
      close(false);
      focusScope.dispose();
    };
  }
  function mountPTZ(root, camera, options = {}) {
    const en = document.documentElement.lang.startsWith("en"),
      t = (ru, eng) => window.vwsTranslate?.(ru) || (en ? eng : ru);
    const controller = new AbortController();
    let disposed = false,
      moving = false,
      busy = false,
      timer = 0,
      profile = "",
      caps = options.caps || null;
    const xm = camera.protocol === "dvrip";
    const api = async (body, detached = false) => {
      const payload = { cam_id: camera.id, profile_token: profile, ...body },
        signal = detached ? undefined : controller.signal;
      if (options.api)
        return options.api("/api/device/ptz", {
          method: "POST",
          body: payload,
          signal,
        });
      const r = await fetch("/api/device/ptz", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": window.VWSHUB_BOOTSTRAP?.csrf_token || "",
        },
        body: JSON.stringify(payload),
        signal,
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || "PTZ request failed");
      return d;
    };
    const fail = (e) => {
      if (!disposed && e.name !== "AbortError") options.onError?.(e.message);
    };
    const stop = () => {
      const was = moving;
      moving = false;
      clearInterval(timer);
      timer = 0;
      if (was && !xm) api({ action: "stop" }, true).catch(() => {});
    };
    async function draw() {
      if (disposed) return;
      if (options.isAdmin === false) {
        root.textContent = t(
          "Управление PTZ доступно администратору.",
          "PTZ requires an administrator.",
        );
        return;
      }
      if (!caps) {
        root.innerHTML =
          '<div class="dv-empty"><span class="dv-spinner"></span></div>';
        try {
          if (options.api)
            caps = await options.api("/api/device/capabilities", {
              method: "POST",
              body: { cam_id: camera.id },
              signal: controller.signal,
            });
          else {
            const r = await fetch("/api/device/capabilities", {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                "X-CSRF-Token": window.VWSHUB_BOOTSTRAP?.csrf_token || "",
              },
              body: JSON.stringify({ cam_id: camera.id }),
              signal: controller.signal,
            });
            caps = await r.json();
            if (!r.ok)
              throw new Error(caps.error || "Capability request failed");
          }
        } catch (e) {
          if (!disposed) root.textContent = e.message;
          fail(e);
          return;
        }
      }
      if (disposed) return;
      if (!caps.capabilities?.ptz) {
        root.innerHTML = `<p class="dv-muted">${t("Устройство не подтвердило поддержку PTZ.", "The device did not report PTZ support.")}</p>`;
        return;
      }
      const profiles = (caps.profiles || []).filter((p) => p.ptz);
      profile = profiles[0]?.token || "";
      root.innerHTML = `<div class="dv-mini-ptz"><p class="dv-muted">${xm ? t("Короткие шаги PTZ через регистратор.", "Short PTZ steps through the recorder.") : t("Удерживайте направление; отпустите для остановки.", "Hold a direction; release to stop.")}</p>${xm ? `<label class="dv-field"><span>${t("Канал PTZ", "PTZ channel")}</span><input class="field" type="number" data-channel min="1" max="256" value="${Number(camera.channel || 0) + 1}"></label>` : `<label class="dv-field"><span>${t("Профиль", "Profile")}</span><select class="select" data-profile>${profiles.map((p) => `<option value="${esc(p.token)}">${esc(p.name || p.token)}</option>`).join("")}</select></label>`}<div class="dv-ptz-pad">${[
        ["↖", -1, 1],
        ["↑", 0, 1],
        ["↗", 1, 1],
        ["←", -1, 0],
        ["■", 0, 0],
        ["→", 1, 0],
        ["↙", -1, -1],
        ["↓", 0, -1],
        ["↘", 1, -1],
      ]
        .map(
          ([label, p, ti]) =>
            `<button class="btn" type="button" data-pan="${p}" data-tilt="${ti}" aria-label="PTZ ${label}">${label}</button>`,
        )
        .join(
          "",
        )}</div><div class="dv-action-row"><button type="button" class="btn" data-zoom="-1">− ${t("Зум", "Zoom")}</button><button type="button" class="btn" data-zoom="1">+ ${t("Зум", "Zoom")}</button></div><div class="dv-preset-controls">${xm ? `<label class="dv-field"><span>${t("Позиция", "Preset")}</span><input class="field" data-preset type="number" min="1" max="255" value="1"></label>` : `<label class="dv-field"><span>${t("Позиция", "Preset")}</span><select class="select" data-preset></select></label><input class="field" data-preset-name placeholder="${t("Имя новой позиции", "New preset name")}" maxlength="64">`}<div class="dv-action-row"><button type="button" class="btn" data-preset-action="goto">${t("Перейти", "Go")}</button><button type="button" class="btn" data-preset-action="save">${t("Сохранить", "Save")}</button><button type="button" class="btn btn-danger" data-preset-action="remove">${t("Удалить", "Remove")}</button></div></div></div>`;
      const channel = () =>
        xm ? Number(root.querySelector("[data-channel]").value) - 1 : undefined;
      root.querySelector("[data-profile]")?.addEventListener("change", (e) => {
        stop();
        profile = e.target.value;
        presets();
      });
      async function move(button) {
        if (busy || disposed) return;
        busy = true;
        try {
          await api({
            action: "move",
            pan: Number(button.dataset.pan || 0) * 0.5,
            tilt: Number(button.dataset.tilt || 0) * 0.5,
            zoom: Number(button.dataset.zoom || 0) * 0.5,
            channel: channel(),
          });
        } catch (e) {
          fail(e);
          stop();
        } finally {
          busy = false;
        }
      }
      root.querySelectorAll("[data-pan],[data-zoom]").forEach((button) => {
        const isStop =
          button.dataset.pan === "0" && button.dataset.tilt === "0";
        const start = () => {
          if (isStop) {
            stop();
            api({ action: "stop", channel: channel() }).catch(fail);
            return;
          }
          if (xm) {
            move(button);
            return;
          }
          if (moving) return;
          moving = true;
          move(button);
          timer = setInterval(() => {
            if (moving) move(button);
          }, 350);
        };
        if (xm) button.onclick = start;
        else {
          button.onpointerdown = (e) => {
            e.preventDefault();
            button.setPointerCapture(e.pointerId);
            start();
          };
          button.onpointerup = stop;
          button.onpointercancel = stop;
          button.onlostpointercapture = stop;
          button.onblur = stop;
          button.onkeydown = (e) => {
            if (["Enter", " "].includes(e.key) && !e.repeat) {
              e.preventDefault();
              start();
            }
          };
          button.onkeyup = (e) => {
            if (["Enter", " "].includes(e.key)) {
              e.preventDefault();
              stop();
            }
          };
        }
      });
      async function presets() {
        if (xm) return;
        try {
          const result = await api({ action: "presets" });
          if (disposed) return;
          root.querySelector("[data-preset]").innerHTML = (result.presets || [])
            .map(
              (p) =>
                `<option value="${esc(p.token)}">${esc(p.name || p.token)}</option>`,
            )
            .join("");
        } catch (e) {
          fail(e);
        }
      }
      root.querySelectorAll("[data-preset-action]").forEach(
        (button) =>
          (button.onclick = async () => {
            stop();
            const token = root.querySelector("[data-preset]").value,
              name =
                root.querySelector("[data-preset-name]")?.value ||
                t("Позиция ", "Preset ") + token;
            if (
              button.dataset.presetAction === "remove" &&
              !window.confirm(
                t("Удалить позицию PTZ?", "Remove this PTZ preset?"),
              )
            )
              return;
            try {
              await api({
                action: button.dataset.presetAction,
                preset_token: token,
                name,
                channel: channel(),
              });
              options.onSuccess?.(
                t("Команда позиции отправлена", "Preset command sent"),
              );
              presets();
            } catch (e) {
              fail(e);
            }
          }),
      );
      presets();
    }
    const lost = () => stop();
    window.addEventListener("blur", lost);
    document.addEventListener("visibilitychange", lost);
    draw();
    return () => {
      if (disposed) return;
      stop();
      disposed = true;
      controller.abort();
      window.removeEventListener("blur", lost);
      document.removeEventListener("visibilitychange", lost);
    };
  }
  const LABEL_IMAGE = {
    Brightness: "Яркость",
    Contrast: "Контраст",
    ColorSaturation: "Насыщенность",
    Sharpness: "Резкость",
  };
  if(typeof module==="object" && module.exports)module.exports={createDialogFocus};
  else window.VWSDevices = { mount, mountPTZ };
})();
