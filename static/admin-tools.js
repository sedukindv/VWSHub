/* Explicit catalog operations and backup restore, shared by administration pages. */
(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const download = (url) => {
    const link = document.createElement("a");
    link.href = url;
    link.download = "";
    link.click();
  };
  function exportCameras(H) {
    const { t, icon } = H;
    H.modal(
      "Экспорт камер",
      "",
      `<div class="form-stack"><p class="help">${t("Экспорт включает подключения, группы и имена устройств. По умолчанию пароли исключены.")}</p><label class="check-item"><input type="checkbox" id="export-passwords"><span>${t("Включить пароли устройств")}<small>${t("Файл с паролями храните в защищённом месте.")}</small></span></label></div>`,
      `<span></span><button class="btn btn-primary" id="export-cameras-go">${icon("download")}${t("Скачать JSON")}</button>`,
    );
    $("#export-cameras-go").onclick = () => {
      download(
        "/api/cameras/export" +
          ($("#export-passwords").checked ? "?include_passwords=1" : ""),
      );
      H.closeModal();
    };
  }
  function importCameras(H, done) {
    const { t, h, icon } = H;
    let catalog = null;
    H.modal(
      "Импорт камер",
      "",
      `<div class="form-stack"><div class="notice" id="import-feedback" role="status">${t("Выберите JSON, экспортированный из VWSHub.")}</div>${H.formField("Файл камер", '<input type="file" id="camera-import-file" class="field file-field" accept=".json,application/json">')}${H.formField("Режим импорта", `<select id="camera-import-mode" class="select"><option value="add">${t("Добавить новые камеры")}</option><option value="update">${t("Обновить камеры с совпадающим ID")}</option></select>`)}<p class="help" id="import-mode-help">${t("Совпадающие подключения сохраняются. Текущие камеры не удаляются.")}</p><div id="camera-import-preview"></div></div>`,
      `<span class="modal-note">JSON · 16 МБ</span><button class="btn btn-primary" id="camera-import-go" disabled>${icon("upload")}${t("Импортировать")}</button>`,
    );
    $("#camera-import-mode").onchange = () => {
      $("#import-mode-help").textContent = t(
        $("#camera-import-mode").value === "update"
          ? "Совпавшие ID заменят параметры подключения и группы. Пустой пароль сохраняет прежний."
          : "Совпадающие подключения сохраняются. Текущие камеры не удаляются.",
      );
    };
    $("#camera-import-file").onchange = async (e) => {
      const box = $("#import-feedback"),
        button = $("#camera-import-go");
      catalog = null;
      button.disabled = true;
      $("#camera-import-preview").replaceChildren();
      try {
        const file = e.target.files[0];
        if (!file) return;
        if (file.size > 16 * 1024 * 1024)
          throw new Error(t("JSON не больше 16 МБ"));
        const data = JSON.parse(await file.text());
        if (
          data.format !== "vwshub.cameras" ||
          data.version !== 1 ||
          !Array.isArray(data.cameras) ||
          data.cameras.length > 4096
        )
          throw new Error(t("Неверный файл камер VWSHub"));
        catalog = data;
        box.className = "notice";
        box.textContent = `${t("Камеры")}: ${data.cameras.length} · ${t("Группы")}: ${Array.isArray(data.groups) ? data.groups.length : 0}`;
        $("#camera-import-preview").innerHTML =
          `<div class="import-preview">${data.cameras
            .slice(0, 12)
            .map(
              (c) =>
                `<div>${icon("camera")}<span>${h(c.name || "—")}</span><small>${h(c.ip || "")}</small></div>`,
            )
            .join(
              "",
            )}</div>${data.cameras.length > 12 ? `<p class="help">+${data.cameras.length - 12}</p>` : ""}`;
        button.disabled = !data.cameras.length;
      } catch (error) {
        box.className = "notice error";
        box.textContent = error.message;
      }
    };
    $("#camera-import-go").onclick = async () => {
      if (!catalog) return;
      const button = $("#camera-import-go"),
        box = $("#import-feedback");
      button.disabled = true;
      try {
        const result = await H.api("/api/cameras/import", {
          method: "POST",
          body: { ...catalog, mode: $("#camera-import-mode").value },
        });
        H.closeModal();
        await done();
        H.toast(
          `${t("Импортировано")}: ${result.imported} · ${t("Пропущено")}: ${result.skipped}`,
        );
      } catch (error) {
        if (box.isConnected) {
          box.className = "notice error";
          box.textContent = error.message;
          button.disabled = false;
        }
      }
    };
  }
  function recorder(H, done) {
    const { t, icon } = H;
    H.modal(
      "Добавить регистратор",
      "",
      `<form id="recorder-form" class="form-stack"><div id="recorder-feedback" class="notice form-feedback" role="status">${t("При сохранении приложение прочитает доступные каналы и добавит новые камеры. Существующие подключения сохраняются.")}</div>${H.formField("Имя регистратора", H.input("name", "", 'required maxlength="150"'))}<div class="form-grid">${H.formField("Протокол подключения", `<select class="select" name="protocol"><option value="dvrip">XM / XMEye · DVRIP</option><option value="onvif">ONVIF</option></select>`)}${H.formField("Порт устройства", H.input("port", 34567, 'type="number" min="1" max="65535" required'))}${H.formField("Адрес устройства", H.input("ip", "", 'required maxlength="253"'))}${H.formField("Порт RTSP", H.input("rtsp_port", 554, 'type="number" min="1" max="65535" required'))}${H.formField("Логин устройства", H.input("username", "", 'autocomplete="off"'))}${H.formField("Пароль устройства", H.input("password", "", 'type="password" autocomplete="new-password"'))}</div><section><h3 class="form-section-title">${icon("folder")}${t("Группы камеры")}</h3>${H.groupChecks([])}</section></form>`,
      `<button class="btn" id="recorder-probe">${icon("link")}${t("Проверить каналы")}</button><button class="btn btn-primary" type="submit" form="recorder-form" id="recorder-save">${icon("plus")}${t("Добавить все каналы")}</button>`,
    );
    const form = $("#recorder-form"),
      box = $("#recorder-feedback");
    form.elements.protocol.onchange = () => {
      form.elements.port.value =
        form.elements.protocol.value === "dvrip" ? 34567 : 80;
    };
    const data = () => {
      const f = new FormData(form);
      return {
        ...Object.fromEntries(f),
        port: Number(f.get("port")),
        rtsp_port: Number(f.get("rtsp_port")),
        group_ids: f.getAll("group_ids"),
      };
    };
    const busy = (value) => {
      if (form.isConnected) {
        $("#recorder-probe").disabled = value;
        $("#recorder-save").disabled = value;
      }
    };
    $("#recorder-probe").onclick = async () => {
      if (!form.reportValidity()) return;
      busy(true);
      box.className = "notice form-feedback";
      box.textContent = t("Читаем каналы регистратора…");
      try {
        const result = await H.api("/api/recorders/probe", {
          method: "POST",
          body: data(),
        });
        box.textContent = `${t("Доступных каналов")}: ${result.channels.length}. ${result.channels
          .slice(0, 8)
          .map((c) => c.name)
          .join(" · ")}`;
      } catch (error) {
        box.className = "notice error form-feedback";
        box.textContent = error.message;
      } finally {
        busy(false);
      }
    };
    form.onsubmit = async (e) => {
      e.preventDefault();
      busy(true);
      box.className = "notice form-feedback";
      box.textContent = t("Добавляем каналы регистратора…");
      try {
        const result = await H.api("/api/recorders", {
          method: "POST",
          body: data(),
        });
        H.closeModal();
        await done({ refreshStatus: true });
        H.toast(
          `${t("Добавлено камер")}: ${result.created.length} · ${t("Сохранено существующих")}: ${result.skipped.length}`,
        );
      } catch (error) {
        if (box.isConnected) {
          box.className = "notice error form-feedback";
          box.textContent = error.message;
        }
      } finally {
        busy(false);
      }
    };
  }
  function renameRecorder(H, device, done) {
    H.modal(
      "Имя регистратора",
      "",
      `<form id="recorder-name-form" class="form-stack">${H.formField("Имя регистратора", H.input("name", device.recorder_name || device.name, 'required maxlength="150"'))}<p class="help">${H.t("Это имя используется на сайте. Имя и настройки оборудования сохраняются.")}</p></form>`,
      `<span></span><button type="submit" form="recorder-name-form" class="btn btn-primary">${H.icon("check")}${H.t("Сохранить")}</button>`,
    );
    $("#recorder-name-form").onsubmit = async (e) => {
      e.preventDefault();
      const button = document.querySelector('[form="recorder-name-form"]');
      button.disabled = true;
      try {
        await H.api(
          "/api/recorders/" + encodeURIComponent(device.recorder_id),
          { method: "PATCH", body: { name: e.target.elements.name.value } },
        );
        H.closeModal();
        await done();
        H.toast("Сохранено");
      } catch (error) {
        H.toast(error.message, "error");
        if (button.isConnected) button.disabled = false;
      }
    };
  }
  function restore(H) {
    const { t, h, icon } = H;
    let file = null,
      verified = null;
    H.modal(
      "Восстановить backup",
      "",
      `<div class="form-stack"><div class="notice" id="restore-feedback" role="status">${t("Backup заменит пользователей, камеры, группы, оформление и ключи. Перед заменой автоматически сохранится копия текущих данных; все сеансы завершатся.")}</div>${H.formField("ZIP backup", '<input class="field file-field" type="file" accept=".zip,application/zip" id="restore-file">')}<div id="restore-summary"></div><div id="restore-confirm-box" hidden>${H.formField("Для восстановления введите RESTORE", '<input class="field" id="restore-confirm" autocomplete="off" spellcheck="false">')}</div></div>`,
      `<span class="modal-note">ZIP · 16 МБ</span><button class="btn btn-danger" id="restore-go" disabled>${icon("upload")}${t("Восстановить")}</button>`,
    );
    $("#restore-file").onchange = async (e) => {
      file = e.target.files[0];
      verified = null;
      $("#restore-go").disabled = true;
      $("#restore-confirm-box").hidden = true;
      $("#restore-summary").replaceChildren();
      $("#restore-confirm").value = "";
      const box = $("#restore-feedback");
      if (!file) return;
      try {
        if (file.size > 16 * 1024 * 1024)
          throw new Error(t("ZIP не больше 16 МБ"));
        box.className = "notice";
        box.textContent = t("Проверяем структуру, ключи и связи backup…");
        const payload = new FormData();
        payload.append("file", file);
        const result = await H.api("/api/backup/inspect", {
          method: "POST",
          body: payload,
        });
        verified = result.backup;
        box.textContent = t(
          "Backup проверен. Убедитесь, что знаете пароль одного из администраторов этой копии.",
        );
        $("#restore-summary").innerHTML =
          `<dl class="kv"><div><dt>${t("Камеры")}</dt><dd>${verified.cameras}</dd></div><div><dt>${t("Группы")}</dt><dd>${verified.groups}</dd></div><div><dt>${t("Пользователи")}</dt><dd>${verified.users}</dd></div><div><dt>${t("Администраторы backup")}</dt><dd>${verified.admins.map(h).join(", ")}</dd></div></dl>`;
        $("#restore-confirm-box").hidden = false;
      } catch (error) {
        box.className = "notice error";
        box.textContent = error.message;
      }
    };
    $("#restore-confirm").oninput = () => {
      $("#restore-go").disabled =
        !verified || $("#restore-confirm").value !== "RESTORE";
    };
    $("#restore-go").onclick = async () => {
      if (!file || !verified || $("#restore-confirm").value !== "RESTORE")
        return;
      const button = $("#restore-go"),
        box = $("#restore-feedback");
      button.disabled = true;
      $("#restore-file").disabled = true;
      box.className = "notice";
      box.textContent = t(
        "Сохраняем текущую конфигурацию и восстанавливаем backup…",
      );
      const payload = new FormData();
      payload.append("file", file);
      payload.append("sha256", verified.sha256);
      payload.append("confirmation", "RESTORE");
      try {
        await H.api("/api/backup/restore", { method: "POST", body: payload });
        location.assign("/login");
      } catch (error) {
        if (box.isConnected) {
          box.className = "notice error";
          box.textContent = error.message;
          button.disabled = false;
          $("#restore-file").disabled = false;
        }
      }
    };
  }
  function clearLogs(H, kind, done) {
    const { t, icon } = H;
    H.modal(
      "Очистить журнал",
      "",
      `<p class="help">${t(kind === "hardware" ? "Удалить текущий журнал оборудования и его ротации? Сначала скачайте диагностику, если она нужна для разбора проблемы." : "Удалить журнал действий и его ротации? Само событие очистки останется в новом журнале.")}</p>`,
      `<span></span><button id="logs-confirm-clear" class="btn btn-danger">${icon("trash")}${t("Очистить")}</button>`,
    );
    $("#logs-confirm-clear").onclick = async (e) => {
      e.target.disabled = true;
      try {
        await H.api("/api/logs/clear", {
          method: "POST",
          body: { kind, confirm: true },
        });
        H.closeModal();
        await done();
      } catch (error) {
        H.toast(error.message, "error");
        if (e.target.isConnected) e.target.disabled = false;
      }
    };
  }
  window.VWSAdmin = {
    exportCameras,
    importCameras,
    recorder,
    renameRecorder,
    restore,
    clearLogs,
    download,
  };
})();
