/* DVR archive workspace: a single selection model, no native video controls. */
(() => {
  "use strict";
  const C = window.VMSArchiveCore;
  let saved = null,
    locale = "ru-RU";
  const english = {
    Архив: "Archive",
    АРХИВ: "ARCHIVE",
    "Архив видеозаписей": "Recording archive",
    "Камера / канал": "Camera / channel",
    "Дата архива": "Archive date",
    "Предыдущий день": "Previous day",
    "Следующий день": "Next day",
    Период: "Period",
    Обновить: "Refresh",
    "Архив на весь экран": "Fullscreen archive",
    "Нет DVRIP-каналов": "No DVRIP channels",
    "Начало периода": "Period start",
    "Конец периода": "Period end",
    "Измените период и нажмите «Обновить».":
      "Change the period and press Refresh.",
    "Камера не выбрана": "No camera selected",
    "Видеозапись регистратора": "Recorder footage",
    "Управление воспроизведением": "Playback controls",
    "Предыдущая запись": "Previous recording",
    "Следующая запись": "Next recording",
    Воспроизвести: "Play",
    Пауза: "Pause",
    "Скорость воспроизведения": "Playback speed",
    "Уменьшить изображение": "Zoom image out",
    "Увеличить изображение": "Zoom image in",
    "Сбросить увеличение": "Reset image zoom",
    "Сохранить снимок": "Save snapshot",
    "Звук архива: проверка микрофона": "Archive sound: checking microphone",
    "Видео архива. Колесо — увеличение, двойной щелчок — увеличить или сбросить, пробел — пауза.":
      "Archive video. Wheel: zoom; double-click: zoom or reset; Space: pause.",
    "Шкала архива и экспорт": "Archive timeline and export",
    "Шкала времени": "Timeline",
    "Предыдущая запись на шкале": "Previous recording on timeline",
    "Следующая запись на шкале": "Next recording on timeline",
    "При завершении записи перейти к следующей, минуя промежуток":
      "Continue with the next available recording, skipping the gap",
    "Пропускать паузы": "Skip gaps",
    "Сдвинуть шкалу назад": "Pan timeline back",
    "Сдвинуть шкалу вперёд": "Pan timeline forward",
    "Уменьшить масштаб шкалы": "Zoom timeline out",
    "Увеличить масштаб шкалы": "Zoom timeline in",
    "Показать весь период": "Show entire period",
    "Весь период": "Entire period",
    "Вид шкалы времени": "Timeline appearance",
    Интервалы: "Intervals",
    Слайдер: "Continuous bar",
    "Шкала времени архива. Стрелки — переход, протягивание — выделение.":
      "Archive timeline. Arrow keys: seek; drag: select a clip.",
    "Начало выделения. Стрелки — изменить на секунду.":
      "Selection start. Arrow keys: adjust by one second.",
    "Конец выделения. Стрелки — изменить на секунду.":
      "Selection end. Arrow keys: adjust by one second.",
    "Позиция воспроизведения": "Playback position",
    "Позиция не выбрана": "No position selected",
    "Щелчок — просмотр · протяните — фрагмент · колесо — масштаб":
      "Click: play · drag: select a clip · wheel: zoom time",
    "Протяните по шкале для выделения. Ручки меняют границы фрагмента.":
      "Drag across the timeline to select a clip. Drag the handles to adjust its boundaries.",
    Запись: "Recording",
    Фрагмент: "Clip",
    Позиция: "Position",
    Выделить: "Select clip",
    "Фрагмент не выбран": "No clip selected",
    "Выделите нужный участок на шкале":
      "Select the required range on the timeline",
    Точно: "Fine-tune",
    "Снять выделение": "Clear selection",
    "Скачать фрагмент": "Download clip",
    "Начало фрагмента": "Clip start",
    "Конец фрагмента": "Clip end",
    Применить: "Apply",
    "Выбранный фрагмент": "Selected clip",
    "В выделении нет записей": "There are no recordings in this selection",
    "В диапазоне есть пропуски: будет выгружена доступная запись.":
      "This range contains gaps. Only available footage will be exported.",
    "Примените новые границы фрагмента.":
      "Apply the new clip boundaries first.",
    "Готово к поиску": "Ready to search",
    "Архив готов к просмотру": "Archive is ready",
    "Выберите дату и камеру.": "Choose a date and camera.",
    "Поиск записей": "Searching recordings",
    "Поиск записей…": "Searching recordings…",
    "Запрашиваем архив регистратора…": "Requesting the recorder archive…",
    "Выберите момент на шкале": "Choose a moment on the timeline",
    "Нажмите на зелёный участок, чтобы открыть запись.":
      "Click a green section to open the recording.",
    "Записей за этот период нет": "No recordings in this period",
    "Выберите другой день или измените период.":
      "Choose another day or adjust the period.",
    "Загрузка записи": "Loading recording",
    "Загрузка записи…": "Loading recording…",
    "Подключаемся к архиву регистратора…":
      "Connecting to the recorder archive…",
    "В этот момент нет записи": "No recording at this time",
    "Выберите записанный участок или включите слайдер для перехода к ближайшей записи.":
      "Gaps remain visible on the timeline.",
    "Не удалось открыть архив": "Could not open the archive",
    "Проверьте доступность регистратора и FFmpeg.":
      "Check the recorder connection and FFmpeg.",
    "К следующей записи": "Next available recording",
    Повторить: "Retry",
    "Нет загруженных записей": "No recordings loaded",
    "Буферизация архива…": "Buffering archive…",
    "На повышенной скорости изображение может задерживаться: скорость чтения ограничена диском регистратора и сетью.":
      "At higher speeds, video may pause while buffering. Reading speed depends on the recorder disk and network.",
    "В списке архива нет файла, содержащего выбранное время. Обновите список записей для этой камеры.":
      "The archive list has no file for this time. Refresh the recordings for this camera.",
    "Регистратор не передал видеофайл за отведённое время. Проверьте путь записи и подключение к регистратору.":
      "The recorder did not deliver video in time. Check the recording and recorder connection.",
    "Браузер не смог запустить видео. Повторите переход по шкале.":
      "The browser could not start playback. Seek on the timeline again.",
    "Укажите корректный период: начало раньше конца.":
      "Enter a valid period: the start must be before the end.",
    "Регистратор вернул некорректный список записей.":
      "The recorder returned an invalid recording list.",
    "Полноэкранный режим недоступен в этом браузере.":
      "Fullscreen is unavailable in this browser.",
    "Сначала откройте видеозапись.": "Open a recording first.",
    "Фрагмент должен находиться внутри загруженного периода, начало — раньше конца.":
      "The clip must be inside the loaded period, with its start before its end.",
    "Регистратор завершил передачу раньше конца файла. Позиция сохранена.":
      "The recorder ended the transfer before the file ended. The current position has been preserved.",
    "Видео недоступно или кодек не поддерживается браузером. Проверьте выбранную камеру, время, регистратор и FFmpeg, затем повторите.":
      "Video is unavailable or its codec is unsupported. Check the camera, time, recorder and FFmpeg, then retry.",
    "Загрузка фрагмента архива": "Archive clip download",
    "Экспорт запрошен. Состояние загрузки отображается в браузере.":
      "Export requested. Check download progress in your browser.",
    "Не удалось открыть архивный звук. Проверьте наличие аудио в выбранной записи.":
      "Could not play archive sound. Check whether this recording contains audio.",
    "Включить звук архивной записи (по умолчанию не запрашивается)":
      "Enable archive sound (not requested by default)",
    "Устройство не подтвердило включённый микрофон":
      "The device did not confirm an enabled microphone",
    "Звук выключен на устройстве": "Sound is disabled on the device",
    "Микрофон включён; формат архивного звука проверяется при запуске":
      "The microphone is enabled; archive audio format will be checked on playback",
    "Формат архивного звука не поддерживается":
      "The archive audio format is unsupported",
    "Камера не предоставлена пользователю":
      "This camera is not assigned to the user",
    "Доступ к архиву запрещён": "Archive access is not permitted",
    "Требуется авторизация": "Sign in to continue",
    "Камера не найдена": "Camera not found",
    "FFmpeg не установлен": "FFmpeg is not installed",
    "Достигнут лимит архивных сеансов сервера":
      "The server archive-session limit has been reached",
    "Не удалось получить записи выбранного канала":
      "Could not retrieve recordings for the selected channel",
    "Не удалось открыть архив выбранного канала":
      "Could not open the archive for the selected channel",
    "Нет файла выбранного канала в этом диапазоне. Обновите архив.":
      "No file for this channel exists in this range. Refresh the archive.",
    "Запрос архива отменён": "Archive request cancelled",
    "Запрос архива отменён или уже запущен":
      "Archive request cancelled or already active",
    "Регистратор долго не отвечает. Повторите запрос или уменьшите период.":
      "The recorder is taking too long. Retry or choose a shorter period.",
    "В записи нет поддерживаемого медиа":
      "The recording contains no supported media",
    "В записи нет поддерживаемого звука":
      "The recording contains no supported audio",
    "Регистратор не передал видеокадры":
      "The recorder did not send video frames",
    "Установите DVRIP-зависимость из requirements.txt":
      "Install the DVRIP dependency from requirements.txt",
    "Не удалось прочитать состояние микрофона":
      "Could not read the microphone status",
    "Устройство не подтвердило поддерживаемый включённый микрофон":
      "The device did not confirm a supported, enabled microphone",
    "Не удалось прочитать архив. Проверьте регистратор, канал и доступность записи.":
      "Could not read the archive. Check the recorder, channel and recording availability.",
    "Начало периода должно быть раньше конца":
      "The period start must be before its end",
    "Неизвестный режим архива": "Unknown archive mode",
    "Некорректный путь записи": "Invalid recording path",
    "Для просмотра выберите точный файл архива":
      "Choose an archive file to play",
    "Время: ГГГГ-ММ-ДД ЧЧ:ММ[:СС]": "Time: YYYY-MM-DD HH:MM[:SS]",
    "Для воспроизведения архива требуется точный путь файла записи":
      "An exact recording-file path is required for archive playback",
    "Некорректный номер канала архива": "Invalid archive channel number",
    "Файл принадлежит другому каналу регистратора":
      "The file belongs to a different recorder channel",
    "Регистратор вернул некорректный список записей":
      "The recorder returned an invalid recording list",
    "Архив XMEye доступен для DVRIP-каналов":
      "XMEye archive is available for DVRIP channels",
    "Формат архивного звука не поддерживается (доступен G.711 A-law 8 кГц)":
      "Unsupported archive audio format (G.711 A-law 8 kHz is supported)",
  };
  Object.assign(english, {
    Группа: "Group",
    "Все камеры": "All cameras",
    "Поиск камеры": "Find camera",
    "Выберите камеру": "Choose a camera",
    "Ничего не найдено": "Nothing found",
    Слайдер: "Slider",
    "Показан последний кадр. Загружаем выбранную запись…":
      "Last frame shown. Loading the selected recording…",
    "Выберите записанный участок или включите слайдер для перехода к ближайшей записи.":
      "Choose recorded footage or enable Slider to jump to the nearest recording.",
  });
  function translate(value) {
    if (locale !== "en-GB" || typeof value !== "string") return value;
    const trimmed = value.trim();
    let result = Object.hasOwn(english, trimmed) ? english[trimmed] : undefined;
    if (result === undefined) {
      result = trimmed
        .replace(/^Ошибка:\s*/, "Error: ")
        .replace(/^Экспорт не выполнен:\s*/, "Export failed: ")
        .replace(/^Экспорт:\s*/, "Export: ")
        .replace(/^Время регистратора\s*·/, "Recorder time ·")
        .replace(/(\d+) отрезков/g, "$1 intervals")
        .replace(/ записи$/, " of footage")
        .replace(/ · перетащите изображение$/, " · drag image to pan");
      for (const [ru, en] of Object.entries(english)) {
        if (result.startsWith("Error: " + ru)) result = "Error: " + en;
        if (result.startsWith("Export failed: " + ru))
          result = "Export failed: " + en;
        if (result.startsWith("Export: " + ru)) result = "Export: " + en;
      }
    }
    return value.replace(trimmed, result);
  }
  const escape = (value) =>
    String(value ?? "").replace(
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
  const paths = {
    archive:
      '<rect x="3" y="4" width="18" height="5" rx="1"/><path d="M5 9v11h14V9m-9 4h4"/>',
    camera:
      '<path d="M4 7h4l2-3h4l2 3h4a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1z"/><circle cx="12" cy="13" r="4"/>',
    play: '<path d="m8 5 11 7-11 7z"/>',
    pause: '<path d="M8 5v14M16 5v14"/>',
    prev: '<path d="m14 5-7 7 7 7M4 5v14"/>',
    next: '<path d="m10 5 7 7-7 7M20 5v14"/>',
    left: '<path d="m14 6-6 6 6 6"/>',
    right: '<path d="m10 6 6 6-6 6"/>',
    minus: '<path d="M5 12h14"/>',
    plus: '<path d="M5 12h14M12 5v14"/>',
    zoom: '<circle cx="10" cy="10" r="6"/><path d="m15 15 5 5M7 10h6m-3-3v6"/>',
    fit: '<path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5M8 12h8"/>',
    expand: '<path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/>',
    download: '<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
    close: '<path d="m6 6 12 12M6 18 18 6"/>',
    refresh:
      '<path d="M20 7v5h-5M4 17v-5h5M5 9a7 7 0 0 1 12-4l3 7M4 12l3 7a7 7 0 0 0 12-4"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/>',
    selection: '<path d="M8 4H4v16h4m8-16h4v16h-4M9 12h6"/>',
    alert: '<path d="m12 3 10 18H2zM12 9v4m0 4h.01"/>',
    skip: '<path d="m4 5 7 7-7 7M13 5l7 7-7 7"/>',
    mic: '<path d="M12 3a3 3 0 0 1 3 3v6a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3zM5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-4 0h8"/>',
    list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
  };
  const icon = (name) =>
    `<svg viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.clock}</svg>`;
  const btn = (id, name, label, extra = "") =>
    `<button type="button" id="${id}" class="icon-btn" title="${label}" aria-label="${label}" ${extra}>${icon(name)}</button>`;
  const clock = (ms) =>
    Number.isFinite(ms)
      ? new Date(ms).toLocaleTimeString(locale, {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        })
      : "—";
  const date = (ms) =>
    Number.isFinite(ms)
      ? new Date(ms).toLocaleDateString(locale, {
          day: "2-digit",
          month: "short",
        })
      : "";
  const duration = (ms) => {
    const s = Math.round(ms / 1000),
      en = locale === "en-GB";
    return s >= 3600
      ? `${Math.floor(s / 3600)} ${en ? "h" : "ч"} ${Math.floor((s % 3600) / 60)} ${en ? "min" : "мин"}`
      : s >= 60
        ? `${Math.floor(s / 60)} ${en ? "min" : "мин"} ${s % 60} ${en ? "s" : "с"}`
        : `${s} ${en ? "s" : "с"}`;
  };
  const abortError = (error) => error?.name === "AbortError";

  function mount(options) {
    locale = options.language === "en" ? "en-GB" : "ru-RU";
    const { root, api, onSelect = () => {} } = options;
    const onError = (message) => options.onError?.(translate(String(message))),
      onSuccess = (message) => options.onSuccess?.(translate(String(message)));
    const cameras = options.cameras.filter((c) => c.protocol === "dvrip");
    const groups = (options.groups || []).filter((g) =>
      cameras.some((c) => g.camera_ids.includes(c.id)),
    );
    let cameraQuery = "";

    const valid = (id) => cameras.some((c) => String(c.id) === String(id));
    // Prefer the selected camera from the caller; if the caller has not persisted
    // a selection yet, preserve the last valid archive camera across remounts.
    const requested = valid(options.selectedId)
      ? String(options.selectedId)
      : saved && valid(saved.camId)
        ? String(saved.camId)
        : String(cameras[0]?.id || "");
    if (!saved) {
      const day = C.local(Date.now()).slice(0, 10),
        range = C.dayRange(day);
      saved = {
        camId: requested,
        day,
        custom: false,
        draftStart: C.local(range.start),
        draftEnd: C.local(range.end),
        range,
        view: { ...range },
        records: [],
        intervals: [],
        loaded: false,
        cursor: null,
        selection: null,
        speed: 1,
        skipGaps: true,
      };
    }
    const m = saved;
    if (!groups.some((g) => g.id === m.groupId)) m.groupId = "";
    if (m.camId !== requested) {
      m.camId = requested;
      m.loaded = false;
      m.records = [];
      m.intervals = [];
      m.selection = null;
      m.cursor = null;
    }
    // Keep the parent view state in sync even on the first archive mount. Without
    // this, leaving and reopening Archive can silently fall back to camera #1.
    if (requested) onSelect(requested);
    let audioEnabled = false,
      audioSupported = false,
      videoPlayId = null,
      soundPlayId = null,
      soundCameraId = null;
    const newPlayId = () =>
      [...crypto.getRandomValues(new Uint8Array(16))]
        .map((n) => n.toString(16).padStart(2, "0"))
        .join("");
    const cancelRemote = (camId, playId) => {
      if (camId && playId)
        api("/api/archive/stop", {
          method: "POST",
          body: { cam_id: camId, play_id: playId },
          keepalive: true,
        }).catch(() => {});
    };
    const life = new AbortController(),
      signal = life.signal;
    let disposed = false,
      searchAbort = null,
      searchGeneration = 0,
      hideTimer = 0,
      loadTimer = 0,
      playGeneration = 0,
      loading = false;
    let playbackBase = null,
      playbackEnd = null,
      playbackRecordEnd = null,
      playbackRecordPath = "",
      playbackCameraId = null,
      status = m.loaded ? "ready" : "idle",
      error = "",
      wantPlay = false,
      timelineDrag = null;
    let zoom = { scale: 1, x: 0, y: 0 },
      pointers = new Map(),
      pan = null,
      pinch = null,
      precise = false,
      preciseDirty = false,
      selectionMode = false,
      followCursor = true;
    const $ = (selector) => root.querySelector(selector);
    const on = (el, event, fn, opts = {}) =>
      el?.addEventListener(event, fn, { ...opts, signal });
    const camera = () => cameras.find((c) => String(c.id) === String(m.camId));
    const selectedCameraId = () => {
      const select = $("#arc-camera");
      const id =
        select && select.value !== ""
          ? String(select.value)
          : String(m.camId || "");
      return valid(id) ? id : "";
    };
    const dom =
      () => `<section class="archive-console" aria-label="Архив видеозаписей">
      <div class="arc-toolbar"><div class="arc-title">${icon("archive")}<h1>Архив</h1></div><div class="arc-toolbar-main"><div class="arc-field arc-group-field"><label for="arc-group">Группа</label><select id="arc-group" class="select"><option value="">${translate("Все камеры")}</option>${groups.map((g) => `<option value="${escape(g.id)}" ${m.groupId === g.id ? "selected" : ""}>${escape(g.name)}</option>`).join("")}</select></div><div class="arc-field arc-camera-field"><label for="arc-camera">Камера / канал</label><div class="arc-camera-choice"><input type="search" id="arc-camera-search" class="field" placeholder="Поиск камеры" aria-label="Поиск камеры"><select id="arc-camera" class="select" ${!cameras.length ? "disabled" : ""}>${cameras.length ? cameras.map((c) => `<option value="${escape(String(c.id))}" ${String(c.id) === String(m.camId) ? "selected" : ""}>${escape(c.name)} · CH ${Number(c.channel || 0) + 1}</option>`).join("") : `<option>${translate("Нет DVRIP-каналов")}</option>`}</select></div></div><div class="arc-field"><label for="arc-date">Дата архива</label><div class="arc-date-navigation">${btn("arc-day-prev", "left", "Предыдущий день")}<input id="arc-date" type="date" class="field" value="${m.day}" aria-label="Дата архива">${btn("arc-day-next", "right", "Следующий день")}</div></div><button type="button" id="arc-period" class="btn btn-sm" aria-expanded="${m.custom}">${icon("clock")} Период</button></div><div class="arc-toolbar-actions"><button type="button" id="arc-search" class="btn" ${!cameras.length ? "disabled" : ""}>${icon("refresh")} Обновить</button>${btn("arc-fullscreen", "expand", "Архив на весь экран")}</div><div class="arc-custom-period" id="arc-custom-period" ${m.custom ? "" : "hidden"}><div class="arc-time-range"><div class="arc-field"><label for="arc-from">Начало периода</label><input class="field" type="datetime-local" step="1" id="arc-from" value="${m.draftStart}"></div><span class="arc-time-range-sep">—</span><div class="arc-field"><label for="arc-to">Конец периода</label><input class="field" type="datetime-local" step="1" id="arc-to" value="${m.draftEnd}"></div></div><span>Измените период и нажмите «Обновить».</span></div></div>
      <div class="arc-body"><div class="arc-viewer" id="arc-viewer" tabindex="0" aria-label="Видео архива. Колесо — увеличение, двойной щелчок — увеличить или сбросить, пробел — пауза."><div class="arc-video-layer" id="arc-video-layer"><video id="arc-video" playsinline preload="auto" disableRemotePlayback></video><canvas id="arc-last-frame" class="arc-last-frame" hidden aria-hidden="true"></canvas><audio id="arc-audio" preload="none"></audio></div><div class="arc-hud"><div><b id="arc-camera-title">${escape(camera()?.name || translate("Камера не выбрана"))}</b><small id="arc-video-time">Видеозапись регистратора</small></div><span class="arc-camera-chip">${icon("archive")} АРХИВ</span></div><div class="arc-state" id="arc-state" role="status" aria-live="polite"></div><span class="arc-zoom-indicator" id="arc-zoom-indicator" hidden></span><div class="arc-player-controls" id="arc-player-controls" aria-label="Управление воспроизведением"><div class="arc-controls-start">${btn("arc-player-prev", "prev", "Предыдущая запись")}<button type="button" id="arc-play" class="arc-primary-play" aria-label="Воспроизвести">${icon("play")}</button>${btn("arc-player-next", "next", "Следующая запись")}<span class="arc-timecode" id="arc-timecode">—</span><select id="arc-speed" aria-label="Скорость воспроизведения">${[0.25, 0.5, 1, 1.5, 2, 4].map((n) => `<option value="${n}" ${m.speed === n ? "selected" : ""}>${locale === "en-GB" ? String(n) : String(n).replace(".", ",")}×</option>`).join("")}</select></div><div class="arc-controls-end">${btn("arc-zoom-out", "minus", "Уменьшить изображение")}<span id="arc-zoom-value" class="arc-zoom-value">1×</span>${btn("arc-zoom-in", "plus", "Увеличить изображение")}${btn("arc-zoom-reset", "fit", "Сбросить увеличение")}${btn("arc-snapshot", "camera", "Сохранить снимок")}${btn("arc-audio-toggle", "mic", "Звук архива: проверка микрофона", 'disabled aria-pressed="false"')}${btn("arc-player-fullscreen", "expand", "Архив на весь экран")}</div></div></div></div>
      <section class="arc-timeline-section" aria-label="Шкала архива и экспорт"><div class="arc-transport"><div><span class="arc-section-label">${icon("clock")}<span id="arc-range-label">Шкала времени</span></span><span class="arc-current-time" id="arc-current-time">—</span></div><div>${btn("arc-record-prev", "prev", "Предыдущая запись на шкале")}${btn("arc-record-next", "next", "Следующая запись на шкале")}<button type="button" class="btn btn-sm" id="arc-skip-gaps" aria-pressed="${m.skipGaps}" title="При завершении записи перейти к следующей, минуя промежуток">${icon("skip")}<span>Пропускать паузы</span></button><select id="arc-timeline-style" class="select select-sm" aria-label="Вид шкалы времени"><option value="records">Интервалы</option><option value="continuous">Слайдер</option></select>${btn("arc-time-back", "left", "Сдвинуть шкалу назад")}${btn("arc-time-out", "minus", "Уменьшить масштаб шкалы")}<button type="button" class="btn btn-sm" id="arc-time-fit" title="Показать весь период">Весь период</button>${btn("arc-time-in", "plus", "Увеличить масштаб шкалы")}${btn("arc-time-forward", "right", "Сдвинуть шкалу вперёд")}</div></div>
      <p class="arc-speed-warning" id="arc-speed-warning" role="status" hidden>На повышенной скорости изображение может задерживаться: скорость чтения ограничена диском регистратора и сетью.</p><div class="arc-timeline-window"><div class="arc-ruler" id="arc-ruler"></div><div class="arc-track" id="arc-track" role="group" tabindex="0" aria-label="Шкала времени архива. Стрелки — переход, протягивание — выделение."><span class="arc-track-label" id="arc-track-label"></span><div class="arc-recordings" id="arc-recordings"></div><div class="arc-selection" id="arc-selection" hidden><button class="arc-handle start" data-handle="start" role="slider" aria-label="Начало выделения. Стрелки — изменить на секунду."></button><button class="arc-handle end" data-handle="end" role="slider" aria-label="Конец выделения. Стрелки — изменить на секунду."></button></div><div class="arc-playhead" id="arc-playhead" role="slider" tabindex="0" aria-label="Позиция воспроизведения" aria-valuemin="0" aria-valuemax="100" hidden></div></div></div><div class="arc-timeline-hint"><p id="arc-timeline-hint">Щелчок — просмотр · протяните — фрагмент · колесо — масштаб</p><div class="arc-legend"><span><i></i>Запись</span><span><i class="selection"></i>Фрагмент</span><span><i class="cursor"></i>Позиция</span></div></div>
      <div class="arc-export-bar"><button type="button" class="btn btn-sm" id="arc-select-mode" aria-pressed="false">${icon("selection")} Выделить</button><div class="arc-export-copy"><small id="arc-selection-title">Фрагмент не выбран</small><strong id="arc-selection-label">Выделите нужный участок на шкале</strong><small id="arc-selection-coverage"></small></div><div class="arc-export-actions"><button type="button" class="btn btn-sm" id="arc-precise" aria-expanded="false" disabled>Точно</button>${btn("arc-clear-selection", "close", "Снять выделение", "disabled")}<button type="button" class="btn btn-primary" id="arc-export" disabled>${icon("download")} Скачать фрагмент</button></div><div class="arc-selection-fields" id="arc-selection-fields" hidden><div class="arc-field"><label for="arc-selection-start">Начало фрагмента</label><input type="datetime-local" step="1" class="field" id="arc-selection-start"></div><div class="arc-field"><label for="arc-selection-end">Конец фрагмента</label><input type="datetime-local" step="1" class="field" id="arc-selection-end"></div><button type="button" class="btn btn-sm" id="arc-selection-apply">Применить</button></div></div></section><footer class="arc-status"><span id="arc-status-text" role="status">Готово к поиску</span><span>Время регистратора · ${camera() ? escape(camera().ip) : "—"}</span></footer></section>`;
    root.innerHTML = dom();
    const sound = $("#arc-audio");
    const video = $("#arc-video"),
      viewer = $("#arc-viewer"),
      layer = $("#arc-video-layer"),
      track = $("#arc-track");

    function freezeFrame() {
      const canvas = $("#arc-last-frame");
      if (video.readyState >= 2 && video.videoWidth && video.videoHeight) {
        try {
          canvas.width = video.videoWidth;
          canvas.height = video.videoHeight;
          canvas.getContext("2d").drawImage(video, 0, 0);
          canvas.hidden = false;
          viewer.classList.add("has-frame");
        } catch (_) {
          canvas.hidden = true;
        }
      }
    }
    function clearFrame() {
      const canvas = $("#arc-last-frame");
      canvas.hidden = true;
      canvas.width = 0;
      canvas.height = 0;
    }
    function stopPlayback(preserveFrame = false) {
      if (preserveFrame) freezeFrame();
      else {
        clearFrame();
        viewer.classList.remove("has-frame");
      }
      stopAudio();
      cancelRemote(playbackCameraId, videoPlayId);
      videoPlayId = null;
      ++playGeneration;
      clearTimeout(loadTimer);
      loadTimer = 0;
      loading = false;
      wantPlay = false;
      video.pause();
      video.removeAttribute("src");
      video.load();
      delete video.dataset.archiveCameraId;
      playbackBase = null;
      playbackEnd = null;
      playbackRecordEnd = null;
      playbackRecordPath = "";
      playbackCameraId = null;
    }
    function showControls() {
      if (disposed) return;
      viewer.classList.add("controls-visible");
      clearTimeout(hideTimer);
      hideTimer = setTimeout(() => {
        if (!disposed) viewer.classList.remove("controls-visible");
      }, 2200);
    }
    function setState(next, message = "") {
      status = next;
      viewer.dataset.playerState = next;
      viewer.setAttribute(
        "aria-busy",
        String(next === "loading" || next === "searching"),
      );
      error = message;
      const display = $("#arc-state");
      const states = {
        idle: ["archive", "Архив готов к просмотру", "Выберите дату и камеру."],
        searching: ["spin", "Поиск записей", "Запрашиваем архив регистратора…"],
        ready: [
          "play",
          "Выберите момент на шкале",
          "Нажмите на зелёный участок, чтобы открыть запись.",
        ],
        empty: [
          "archive",
          "Записей за этот период нет",
          "Выберите другой день или измените период.",
        ],
        loading: [
          "spin",
          "Загрузка записи",
          $("#arc-last-frame").hidden
            ? "Подключаемся к архиву регистратора…"
            : "Показан последний кадр. Загружаем выбранную запись…",
        ],
        gap: [
          "clock",
          "В этот момент нет записи",
          "Выберите записанный участок или включите слайдер для перехода к ближайшей записи.",
        ],
        error: [
          "alert",
          "Не удалось открыть архив",
          message || "Проверьте доступность регистратора и FFmpeg.",
        ],
        paused: ["play", "Пауза", ""],
      };
      if (next === "playing" || (next === "paused" && video.videoWidth)) {
        display.hidden = true;
        display.innerHTML = "";
      } else {
        const [symbol, title, note] = states[next] || states.ready;
        display.hidden = false;
        display.innerHTML = `${symbol === "spin" ? '<span class="arc-spinner"></span>' : icon(symbol)}<strong>${escape(title)}</strong><p>${escape(note)}</p>${next === "ready" || next === "paused" ? '<button type="button" class="btn btn-sm" data-action="play">Воспроизвести</button>' : next === "gap" && C.adjacent(m.intervals, m.cursor, 1) ? '<button type="button" class="btn btn-sm" data-action="next">К следующей записи</button>' : next === "error" ? '<button type="button" class="btn btn-sm" data-action="retry">Повторить</button>' : ""}`;
      }
      const pauseAction =
        next === "playing" || (next === "loading" && wantPlay);
      $("#arc-play").innerHTML = icon(pauseAction ? "pause" : "play");
      $("#arc-play").setAttribute(
        "aria-label",
        pauseAction ? "Пауза" : "Воспроизвести",
      );
      $("#arc-play").disabled = !m.intervals.length || next === "searching";
      updateAudioButton();
      $("#arc-status-text").textContent =
        next === "searching"
          ? "Поиск записей…"
          : next === "error"
            ? "Ошибка: " + message
            : next === "loading"
              ? "Загрузка записи…"
              : m.loaded
                ? `${m.intervals.length} отрезков · ${duration(m.intervals.reduce((sum, r) => sum + r.end - r.start, 0))} записи`
                : "Готово к поиску";
    }
    function updateCursor(follow = false) {
      const cursor = m.cursor,
        valid = Number.isFinite(cursor),
        pct = valid
          ? ((cursor - m.view.start) / (m.view.end - m.view.start)) * 100
          : -1;
      $("#arc-current-time").textContent = valid ? clock(cursor) : "—";
      $("#arc-timecode").textContent = valid ? clock(cursor) : "—";
      $("#arc-video-time").textContent = valid
        ? `${date(cursor)} · ${clock(cursor)}`
        : "Видеозапись регистратора";
      if (follow && followCursor && valid && (pct < 0 || pct > 100)) {
        m.view = C.viewWindow(
          m.range.start,
          m.range.end,
          m.view.end - m.view.start,
          cursor,
          0.3,
        );
        renderTimeline();
        return;
      }
      const head = $("#arc-playhead");
      head.hidden = !valid || pct < 0 || pct > 100;
      if (!head.hidden) head.style.left = `${pct}%`;
      head.setAttribute(
        "aria-valuenow",
        String(Math.round(C.clamp(pct, 0, 100))),
      );
      head.setAttribute(
        "aria-valuetext",
        valid ? `${date(cursor)} ${clock(cursor)}` : "Позиция не выбрана",
      );
    }
    function updateSelection(working = m.selection) {
      const win = $("#arc-selection"),
        span = m.view.end - m.view.start;
      const visible =
        working && working.end > m.view.start && working.start < m.view.end;
      win.hidden = !visible;
      if (visible) {
        win.style.left = `${C.clamp(((working.start - m.view.start) / span) * 100, 0, 100)}%`;
        win.style.width = `${((Math.min(working.end, m.view.end) - Math.max(working.start, m.view.start)) / span) * 100}%`;
        win.querySelector(".start").hidden = working.start < m.view.start;
        win.querySelector(".end").hidden = working.end > m.view.end;
      }
      if (working) {
        win.querySelectorAll("[data-handle]").forEach((handle) => {
          const edge = handle.dataset.handle;
          handle.setAttribute(
            "aria-valuemin",
            String(edge === "start" ? m.range.start : working.start + 1000),
          );
          handle.setAttribute(
            "aria-valuemax",
            String(edge === "start" ? working.end - 1000 : m.range.end),
          );
          handle.setAttribute("aria-valuenow", String(working[edge]));
          handle.setAttribute(
            "aria-valuetext",
            date(working[edge]) + " " + clock(working[edge]),
          );
        });
      }
      const selected = Boolean(working),
        covered = C.coverage(m.intervals, working);
      $("#arc-selection-title").textContent = selected
        ? "Выбранный фрагмент"
        : "Фрагмент не выбран";
      $("#arc-selection-label").textContent = selected
        ? `${date(working.start)} ${clock(working.start)} — ${date(working.end)} ${clock(working.end)} · ${duration(working.end - working.start)}`
        : "Выделите нужный участок на шкале";
      $("#arc-selection-coverage").textContent = selected
        ? covered === 0
          ? "В выделении нет записей"
          : covered < working.end - working.start
            ? "В диапазоне есть пропуски: будет выгружена доступная запись."
            : ""
        : "";
      if (!selected) preciseDirty = false;
      if (preciseDirty)
        $("#arc-selection-coverage").textContent =
          "Примените новые границы фрагмента.";
      $("#arc-export").disabled =
        !selected ||
        covered <= 0 ||
        !m.loaded ||
        status === "searching" ||
        preciseDirty;
      $("#arc-precise").disabled = !selected;
      $("#arc-clear-selection").disabled = !selected;
      $("#arc-selection-fields").hidden = !selected || !precise;
      $("#arc-precise").setAttribute(
        "aria-expanded",
        String(selected && precise),
      );
      if (
        selected &&
        !$("#arc-selection-fields").contains(document.activeElement)
      ) {
        $("#arc-selection-start").value = C.local(working.start);
        $("#arc-selection-end").value = C.local(working.end);
      }
    }
    function renderTimeline() {
      const start = m.view.start,
        end = m.view.end,
        span = end - start;
      const count = track.clientWidth < 480 ? 4 : 8;
      $("#arc-ruler").innerHTML = Array.from({ length: count + 1 }, (_, i) => {
        const t = start + (span * i) / count;
        return `<span class="arc-tick ${i === 0 ? "first" : i === count ? "last" : ""}" style="left:${(i / count) * 100}%">${escape(new Date(t).toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit", ...(span < 300000 ? { second: "2-digit" } : {}) }))}${i === 0 || i === count ? `<small>${escape(date(t))}</small>` : ""}</span>`;
      }).join("");
      $("#arc-recordings").innerHTML = m.intervals
        .filter((r) => r.end > start && r.start < end)
        .map(
          (r) =>
            `<span class="arc-recording" style="left:${Math.max(0, ((r.start - start) / span) * 100)}%;width:${((Math.min(r.end, end) - Math.max(r.start, start)) / span) * 100}%" title="${clock(r.start)} — ${clock(r.end)}"></span>`,
        )
        .join("");
      $("#arc-track-label").textContent = m.loaded
        ? `${camera()?.name || ""} · ${m.intervals.length} ${locale === "en-GB" ? "intervals" : "отрезков"}`
        : translate(
            status === "searching"
              ? "Поиск записей…"
              : "Нет загруженных записей",
          );
      $("#arc-range-label").textContent =
        `${date(m.range.start)} · ${duration(span)}`;
      $("#arc-time-fit").textContent =
        span >= m.range.end - m.range.start - 1
          ? "Весь период"
          : duration(span);
      $("#arc-time-out").disabled = span >= m.range.end - m.range.start - 1;
      $("#arc-time-in").disabled =
        span <= Math.min(60000, m.range.end - m.range.start);
      $("#arc-time-back").disabled = m.view.start <= m.range.start;
      $("#arc-time-forward").disabled = m.view.end >= m.range.end;
      updateCursor();
      updateSelection();
    }
    function recordPath(record) {
      return String(record?.FilePath || record?.FileName || "").trim();
    }
    function recordStart(record) {
      return C.time(record?.BeginTime);
    }
    function recordEnd(record) {
      return C.time(record?.EndTime);
    }
    function recordingAt(ms) {
      // Playback must be started by the exact DVR file path. On a number of
      // Xiongmai/XMEye-derived firmwares PlayMode=ByTime ignores Parameter.Channel
      // and silently returns channel 0. ByName honours the channel encoded in the
      // filename/path returned by OPFileQuery.
      const matches = m.records.filter(
        (r) =>
          recordPath(r) &&
          Number.isFinite(recordStart(r)) &&
          Number.isFinite(recordEnd(r)) &&
          recordStart(r) <= ms &&
          ms < recordEnd(r),
      );
      const wanted = Number(camera()?.channel ?? 0);
      const channelMatches = matches.filter(
        (r) =>
          r.Channel !== undefined &&
          r.Channel !== null &&
          Number.isFinite(Number(r.Channel)) &&
          Number(r.Channel) === wanted,
      );
      // Do not fall back to a matching timestamp from another channel. If the
      // recorder returned an unexpected path, fail closed instead of showing CH1.
      return channelMatches.at(-1) || null;
    }
    function playbackURL(
      endpoint,
      start,
      end,
      camId = selectedCameraId(),
      path = "",
      mode = "files",
      playId = "",
    ) {
      // Pin camera identity and the recorder's exact file path in the URL. Do not
      // use ByTime here: some DVRs ignore the channel on time-based playback.
      return (
        "/api/" +
        endpoint +
        "?" +
        new URLSearchParams({
          cam_id: String(camId || ""),
          mode,
          path: String(path || ""),
          start: C.local(start, " "),
          end: C.local(end, " "),
          t: String(Date.now()),
          ...(playId ? { play_id: playId } : {}),
        })
      );
    }
    function seek(ms, autoplay = true) {
      if (!m.loaded || !m.intervals.length) return;
      const camId = selectedCameraId();
      if (!valid(camId)) return;
      if (String(camId) !== String(m.camId)) {
        switchArchiveCamera(camId);
        return;
      }
      let target = C.clamp(
        Math.floor(ms / 1000) * 1000,
        m.range.start,
        m.range.end - 1000,
      );
      if ($("#arc-timeline-style").value === "continuous")
        target = C.nearest(m.intervals, target);
      const interval = C.intervalAt(m.intervals, target);
      followCursor = true;
      m.cursor = target;
      updateCursor(true);
      if (!interval) {
        stopPlayback();
        setState("gap");
        showControls();
        return;
      }
      const record = recordingAt(target),
        path = recordPath(record),
        fileEnd = recordEnd(record);
      if (!record || !path || !Number.isFinite(fileEnd) || fileEnd <= target) {
        stopPlayback();
        setState(
          "error",
          "В списке архива нет файла, содержащего выбранное время. Обновите список записей для этой камеры.",
        );
        showControls();
        return;
      }
      // Each play request is limited to the actual recorder file. This avoids the
      // fragile multi-hour ByTime response and guarantees the path belongs to the
      // selected camera/channel. Seeking opens the file containing the target.
      const streamEnd = Math.min(m.range.end, fileEnd);
      stopPlayback(true);
      playbackBase = target;
      playbackEnd = streamEnd;
      playbackRecordEnd = fileEnd;
      playbackRecordPath = path;
      playbackCameraId = String(camId);
      wantPlay = autoplay;
      const generation = ++playGeneration;
      video.playbackRate = m.speed;
      video.dataset.archiveCameraId = String(camId);
      setState("loading");
      loading = true;
      videoPlayId = newPlayId();
      video.src = playbackURL(
        "playback",
        target,
        streamEnd,
        camId,
        path,
        "files",
        videoPlayId,
      );
      video.load();
      if (autoplay)
        video.play().catch((e) => {
          if (
            !disposed &&
            generation === playGeneration &&
            !abortError(e) &&
            e.name === "NotAllowedError"
          ) {
            wantPlay = false;
            loading = false;
            clearTimeout(loadTimer);
            setState("paused");
            showControls();
          }
        });
      loadTimer = setTimeout(() => {
        if (disposed || generation !== playGeneration || !loading) return;
        stopPlayback();
        setState(
          "error",
          "Регистратор не передал видеофайл за отведённое время. Проверьте путь записи и подключение к регистратору.",
        );
      }, 125000);
    }
    function playToggle() {
      if (status === "searching" || !m.intervals.length) return;
      if (wantPlay && video.hasAttribute("src") && !video.ended) {
        wantPlay = false;
        clearTimeout(loadTimer);
        loading = false;
        video.pause();
        setState("paused");
        showControls();
        return;
      }
      if (video.hasAttribute("src") && status === "paused" && !video.ended) {
        wantPlay = true;
        video.play().catch(() => {
          setState(
            "error",
            "Браузер не смог запустить видео. Повторите переход по шкале.",
          );
        });
      } else {
        const target = C.intervalAt(m.intervals, m.cursor)
          ? m.cursor
          : (C.adjacent(m.intervals, m.cursor ?? -Infinity, 1)?.start ??
            m.intervals[0].start);
        seek(target);
      }
      showControls();
    }
    function nextRecord(direction) {
      const interval = C.adjacent(
        m.intervals,
        Number.isFinite(m.cursor)
          ? m.cursor
          : direction < 0
            ? Infinity
            : -Infinity,
        direction,
      );
      if (interval) seek(interval.start);
    }
    async function search({ retainCursor = false } = {}) {
      const activeCamId = selectedCameraId();
      if (!valid(activeCamId)) return;
      if (m.camId !== activeCamId) {
        m.camId = activeCamId;
        onSelect(activeCamId);
        m.cursor = null;
      }
      const draft = m.custom
        ? {
            start: C.time($("#arc-from").value),
            end: C.time($("#arc-to").value),
          }
        : C.dayRange($("#arc-date").value);
      if (
        !draft ||
        ![draft.start, draft.end].every(Number.isFinite) ||
        draft.end - draft.start < 1000
      ) {
        onError("Укажите корректный период: начало раньше конца.");
        return;
      }
      if (!m.custom) {
        $("#arc-from").value = C.local(draft.start);
        $("#arc-to").value = C.local(draft.end);
      }
      m.draftStart = $("#arc-from").value;
      m.draftEnd = $("#arc-to").value;
      m.day = $("#arc-date").value;
      searchAbort?.abort();
      searchAbort = new AbortController();
      const generation = ++searchGeneration,
        camId = activeCamId;
      stopPlayback();
      m.range = draft;
      m.view = { ...draft };
      m.records = [];
      m.intervals = [];
      m.selection = null;
      m.loaded = false;
      if (!retainCursor) m.cursor = null;
      setState("searching");
      renderTimeline();
      $("#arc-search").disabled = true;
      try {
        const records = await api(
          "/api/recordings?" +
            new URLSearchParams({
              cam_id: camId,
              start: C.local(draft.start, " "),
              end: C.local(draft.end, " "),
              mode: "files",
            }),
          { signal: searchAbort.signal },
        );
        if (
          disposed ||
          generation !== searchGeneration ||
          camId !== m.camId ||
          camId !== selectedCameraId()
        )
          return;
        if (!Array.isArray(records))
          throw new Error("Регистратор вернул некорректный список записей.");
        m.records = records;
        m.intervals = C.normalize(records, draft.start, draft.end);
        m.loaded = true;
        m.cursor =
          retainCursor && Number.isFinite(m.cursor)
            ? C.clamp(m.cursor, draft.start, draft.end - 1000)
            : (m.intervals[0]?.start ?? null);
        setState(m.intervals.length ? "ready" : "empty");
        renderTimeline();
      } catch (e) {
        if (disposed || generation !== searchGeneration || abortError(e))
          return;
        setState("error", e.message);
        renderTimeline();
      } finally {
        if (
          !disposed &&
          generation === searchGeneration &&
          camId === selectedCameraId()
        )
          $("#arc-search").disabled = !cameras.length;
      }
    }
    function changeDay(offset) {
      const d = new Date((C.dayRange($("#arc-date").value) || m.range).start);
      d.setDate(d.getDate() + offset);
      $("#arc-date").value = C.local(d.getTime()).slice(0, 10);
      m.custom = false;
      $("#arc-custom-period").hidden = true;
      $("#arc-period").setAttribute("aria-expanded", "false");
      search();
    }
    function changeScale(
      factor,
      anchor = (m.view.start + m.view.end) / 2,
      ratio = 0.5,
    ) {
      followCursor = false;
      const span = C.clamp(
        (m.view.end - m.view.start) * factor,
        Math.min(60000, m.range.end - m.range.start),
        m.range.end - m.range.start,
      );
      m.view = C.viewWindow(m.range.start, m.range.end, span, anchor, ratio);
      renderTimeline();
    }
    function moveWindow(direction) {
      followCursor = false;
      m.view = C.viewWindow(
        m.range.start,
        m.range.end,
        m.view.end - m.view.start,
        (m.view.start + m.view.end) / 2 +
          direction * (m.view.end - m.view.start) * 0.6,
      );
      renderTimeline();
    }
    function applyZoom(next, px = 0, py = 0) {
      zoom = C.zoomPoint(
        zoom.scale,
        next,
        zoom.x,
        zoom.y,
        px,
        py,
        layer.clientWidth,
        layer.clientHeight,
      );
      video.style.transform = `translate(${zoom.x}px,${zoom.y}px) scale(${zoom.scale})`;
      viewer.classList.toggle("is-zoomed", zoom.scale > 1);
      $("#arc-zoom-value").textContent = `${Number(zoom.scale.toFixed(1))}×`;
      $("#arc-zoom-indicator").hidden = zoom.scale <= 1;
      $("#arc-zoom-indicator").textContent =
        `${Number(zoom.scale.toFixed(1))}× · перетащите изображение`;
    }
    function fullscreen() {
      if (document.fullscreenElement) document.exitFullscreen?.();
      else if (
        !document.fullscreenEnabled ||
        !$(".archive-console").requestFullscreen
      )
        onError("Полноэкранный режим недоступен в этом браузере.");
      else
        $(".archive-console")
          .requestFullscreen()
          .catch(() =>
            onError("Полноэкранный режим недоступен в этом браузере."),
          );
    }
    function stopAudio() {
      cancelRemote(soundCameraId, soundPlayId);
      soundPlayId = null;
      soundCameraId = null;
      sound.pause();
      sound.removeAttribute("src");
      sound.load();
    }
    function updateAudioButton() {
      const button = $("#arc-audio-toggle");
      if (!button) return;
      button.disabled = !audioSupported || !playbackRecordPath;
      button.setAttribute("aria-pressed", String(audioEnabled));
      button.classList.toggle("active", audioEnabled);
    }
    function audioFailure() {
      if (disposed) return;
      audioEnabled = false;
      audioSupported = false;
      stopAudio();
      updateAudioButton();
      onError(
        "Не удалось открыть архивный звук. Проверьте наличие аудио в выбранной записи.",
      );
    }
    function startAudio() {
      if (
        !audioEnabled ||
        !audioSupported ||
        !playbackRecordPath ||
        playbackBase === null
      )
        return;
      stopAudio();
      soundPlayId = newPlayId();
      soundCameraId = playbackCameraId;
      const point = Math.min(
        playbackEnd - 1000,
        playbackBase +
          (Number.isFinite(video.currentTime) ? video.currentTime * 1000 : 0),
      );
      sound.src = playbackURL(
        "archive/audio",
        point,
        playbackEnd,
        playbackCameraId,
        playbackRecordPath,
        "files",
        soundPlayId,
      );
      sound.playbackRate = m.speed;
      sound.play().catch(audioFailure);
    }
    async function loadAudioCapabilities() {
      audioSupported = false;
      audioEnabled = false;
      stopAudio();
      updateAudioButton();
      const camId = String(m.camId);
      try {
        const result = await api(
          "/api/archive/capabilities?" +
            new URLSearchParams({ cam_id: camId, refresh: "1" }),
          { signal },
        );
        if (disposed || camId !== String(m.camId)) return;
        audioSupported =
          result.audio?.enabled === true && result.audio?.supported === true;
        const button = $("#arc-audio-toggle");
        button.title = audioSupported
          ? "Включить звук архивной записи (по умолчанию не запрашивается)"
          : result.audio?.reason ||
            "Устройство не подтвердило включённый микрофон";
        button.setAttribute("aria-label", button.title);
        updateAudioButton();
      } catch (_) {
        if (!disposed) updateAudioButton();
      }
    }
    function snapshot() {
      if (!video.videoWidth) {
        onError("Сначала откройте видеозапись.");
        return;
      }
      const canvas = document.createElement("canvas");
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      canvas.getContext("2d").drawImage(video, 0, 0);
      canvas.toBlob(
        (blob) => {
          if (!blob) return;
          const a = document.createElement("a"),
            url = URL.createObjectURL(blob);
          a.href = url;
          a.download = `archive-${m.camId}-${C.local(m.cursor).replace(/[:T]/g, "-")}.jpg`;
          a.click();
          setTimeout(() => URL.revokeObjectURL(url), 2000);
        },
        "image/jpeg",
        0.95,
      );
    }
    function exportSelection() {
      if (
        !m.selection ||
        !m.loaded ||
        preciseDirty ||
        C.coverage(m.intervals, m.selection) <= 0
      )
        return;
      // Keep error JSON in an isolated same-origin frame, never navigate the app
      // or buffer a potentially multi-hour MP4 into browser RAM.
      const frame = document.createElement("iframe");
      frame.hidden = true;
      frame.title = translate("Загрузка фрагмента архива");
      frame.addEventListener("load", () => {
        try {
          const text = frame.contentDocument?.body?.textContent || "";
          if (!text.trim()) return;
          const payload = JSON.parse(text);
          if (payload.error) {
            onError("Экспорт: " + payload.error);
            if (!disposed && $("#arc-status-text"))
              $("#arc-status-text").textContent =
                "Экспорт не выполнен: " + payload.error;
          }
          frame.remove();
        } catch (_) {
          /* attachment downloads do not expose a document */
        }
      });
      frame.src = playbackURL(
        "download",
        m.selection.start,
        m.selection.end,
        selectedCameraId(),
        "",
        "time",
      );
      document.body.append(frame);
      setTimeout(() => frame.remove(), 6 * 3600 * 1000);
      $("#arc-status-text").textContent =
        "Экспорт запрошен. Состояние загрузки отображается в браузере.";
    }

    // Search controls use a separate draft range; editing inputs never changes
    // the identity or timestamps of already loaded footage.
    function invalidate() {
      searchAbort?.abort();
      ++searchGeneration;
      stopPlayback();
      m.loaded = false;
      m.records = [];
      m.intervals = [];
      m.selection = null;
      setState("idle");
      renderTimeline();
    }
    function switchArchiveCamera(selectedId) {
      if (!valid(selectedId)) return;
      // Update identity BEFORE invalidating/rendering so every derived label and
      // subsequent request points to the selected camera, not the previous one.
      audioEnabled = false;
      audioSupported = false;
      stopAudio();
      m.camId = selectedId;
      onSelect(selectedId);
      m.cursor = null;
      m.day = $("#arc-date").value || m.day;
      invalidate();
      $("#arc-camera-title").textContent = camera()?.name || "";
      $(".arc-status > span:last-child").textContent =
        `Время регистратора · ${camera()?.ip || "—"} · CH ${Number(camera()?.channel || 0) + 1}`;
      applyZoom(1);
      loadAudioCapabilities();
      search();
    }
    function filteredCameras() {
      const group = groups.find((g) => g.id === m.groupId);
      return cameras.filter(
        (c) =>
          (!group || group.camera_ids.includes(c.id)) &&
          `${c.name} ${c.ip} ${c.recorder_name || ""} ${Number(c.channel || 0) + 1}`
            .toLowerCase()
            .includes(cameraQuery),
      );
    }
    function cameraOptions() {
      const filtered = filteredCameras(),
        select = $("#arc-camera");
      const has = filtered.some((c) => String(c.id) === String(m.camId));
      select.innerHTML =
        (!has
          ? `<option value="">${filtered.length ? translate("Выберите камеру") : translate("Ничего не найдено")}</option>`
          : "") +
        filtered
          .map(
            (c) =>
              `<option value="${escape(c.id)}" ${String(c.id) === String(m.camId) ? "selected" : ""}>${escape(c.name)} · CH ${Number(c.channel || 0) + 1}</option>`,
          )
          .join("");
      select.disabled = !filtered.length;
    }
    on($("#arc-group"), "change", () => {
      m.groupId = $("#arc-group").value;
      cameraOptions();
    });
    on($("#arc-camera-search"), "input", (e) => {
      cameraQuery = e.target.value.toLowerCase().trim();
      cameraOptions();
    });
    cameraOptions();
    on($("#arc-camera"), "change", () =>
      switchArchiveCamera($("#arc-camera").value),
    );
    on($("#arc-date"), "change", () => {
      invalidate();
      m.custom = false;
      $("#arc-custom-period").hidden = true;
      $("#arc-period").setAttribute("aria-expanded", "false");
      search();
    });
    on($("#arc-day-prev"), "click", () => changeDay(-1));
    on($("#arc-day-next"), "click", () => changeDay(1));
    on($("#arc-period"), "click", () => {
      m.custom = !m.custom;
      $("#arc-custom-period").hidden = !m.custom;
      $("#arc-period").setAttribute("aria-expanded", String(m.custom));
      if (!m.custom) search();
    });
    on($("#arc-search"), "click", () => {
      loadAudioCapabilities();
      search();
    });
    on($("#arc-fullscreen"), "click", fullscreen);
    on($("#arc-player-fullscreen"), "click", fullscreen);
    on($("#arc-play"), "click", playToggle);
    on($("#arc-player-prev"), "click", () => nextRecord(-1));
    on($("#arc-record-prev"), "click", () => nextRecord(-1));
    on($("#arc-player-next"), "click", () => nextRecord(1));
    on($("#arc-record-next"), "click", () => nextRecord(1));
    on($("#arc-state"), "click", (e) => {
      const action = e.target.closest("[data-action]")?.dataset.action;
      if (action === "play") playToggle();
      if (action === "next") nextRecord(1);
      if (action === "retry") {
        if (m.loaded && m.intervals.length)
          seek(m.cursor ?? m.intervals[0].start);
        else search();
      }
    });
    on($("#arc-speed"), "change", () => {
      m.speed = Number($("#arc-speed").value);
      video.playbackRate = m.speed;
      sound.playbackRate = m.speed;
      $("#arc-speed-warning").hidden = m.speed <= 1;
      showControls();
    });
    on($("#arc-skip-gaps"), "click", () => {
      m.skipGaps = !m.skipGaps;
      $("#arc-skip-gaps").setAttribute("aria-pressed", String(m.skipGaps));
    });
    on($("#arc-time-in"), "click", () => changeScale(0.5));
    on($("#arc-time-out"), "click", () => changeScale(2));
    on($("#arc-time-fit"), "click", () => {
      m.view = { ...m.range };
      renderTimeline();
    });
    on($("#arc-time-back"), "click", () => moveWindow(-1));
    on($("#arc-time-forward"), "click", () => moveWindow(1));
    on($("#arc-zoom-in"), "click", () => {
      applyZoom(zoom.scale * 1.25);
      showControls();
    });
    on($("#arc-zoom-out"), "click", () => {
      applyZoom(zoom.scale / 1.25);
      showControls();
    });
    on($("#arc-zoom-reset"), "click", () => {
      applyZoom(1);
      showControls();
    });
    on($("#arc-snapshot"), "click", snapshot);
    on(viewer, "pointermove", showControls);
    on(viewer, "pointerdown", showControls);
    on(viewer, "focusin", showControls);
    on(
      layer,
      "wheel",
      (e) => {
        if (!video.videoWidth) return;
        e.preventDefault();
        const r = layer.getBoundingClientRect();
        applyZoom(
          zoom.scale * (e.deltaY < 0 ? 1.15 : 1 / 1.15),
          e.clientX - r.left - r.width / 2,
          e.clientY - r.top - r.height / 2,
        );
        showControls();
      },
      { passive: false },
    );
    on(layer, "dblclick", (e) => {
      if (!video.videoWidth) return;
      const r = layer.getBoundingClientRect();
      applyZoom(
        zoom.scale > 1 ? 1 : 2,
        e.clientX - r.left - r.width / 2,
        e.clientY - r.top - r.height / 2,
      );
      showControls();
    });
    on(layer, "pointerdown", (e) => {
      if (e.button !== 0) return;
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      layer.setPointerCapture(e.pointerId);
      if (pointers.size === 2) {
        const [a, b] = [...pointers.values()];
        pinch = {
          distance: Math.hypot(a.x - b.x, a.y - b.y),
          scale: zoom.scale,
        };
        pan = null;
      } else if (zoom.scale > 1) {
        pan = {
          id: e.pointerId,
          x: e.clientX,
          y: e.clientY,
          baseX: zoom.x,
          baseY: zoom.y,
        };
        viewer.classList.add("is-panning");
      }
    });
    on(layer, "pointermove", (e) => {
      if (!pointers.has(e.pointerId)) return;
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pinch && pointers.size === 2) {
        const [a, b] = [...pointers.values()];
        applyZoom(
          (pinch.scale * Math.hypot(a.x - b.x, a.y - b.y)) /
            Math.max(1, pinch.distance),
        );
      } else if (pan?.id === e.pointerId) {
        zoom.x = C.clamp(
          pan.baseX + e.clientX - pan.x,
          (-layer.clientWidth * (zoom.scale - 1)) / 2,
          (layer.clientWidth * (zoom.scale - 1)) / 2,
        );
        zoom.y = C.clamp(
          pan.baseY + e.clientY - pan.y,
          (-layer.clientHeight * (zoom.scale - 1)) / 2,
          (layer.clientHeight * (zoom.scale - 1)) / 2,
        );
        video.style.transform = `translate(${zoom.x}px,${zoom.y}px) scale(${zoom.scale})`;
      }
    });
    const releasePointer = (e) => {
      pointers.delete(e.pointerId);
      pinch = null;
      pan = null;
      viewer.classList.remove("is-panning");
    };
    on(layer, "pointerup", releasePointer);
    on(layer, "pointercancel", releasePointer);
    on(layer, "lostpointercapture", releasePointer);
    on($("#arc-audio-toggle"), "click", () => {
      audioEnabled = !audioEnabled;
      if (audioEnabled) startAudio();
      else stopAudio();
      updateAudioButton();
    });
    on(sound, "error", () => {
      if (sound.hasAttribute("src")) audioFailure();
    });
    on($("#arc-timeline-style"), "change", () => {
      track.classList.toggle(
        "continuous",
        $("#arc-timeline-style").value === "continuous",
      );
      try {
        localStorage.setItem(
          "vwshub.archive.timelineStyle",
          $("#arc-timeline-style").value,
        );
      } catch (_) {}
      renderTimeline();
    });
    on($("#arc-export"), "click", exportSelection);
    on($("#arc-clear-selection"), "click", () => {
      m.selection = null;
      precise = false;
      updateSelection();
    });
    on($("#arc-select-mode"), "click", () => {
      selectionMode = !selectionMode;
      $("#arc-select-mode").setAttribute("aria-pressed", String(selectionMode));
      $("#arc-timeline-hint").textContent = selectionMode
        ? "Протяните по шкале для выделения. Ручки меняют границы фрагмента."
        : "Щелчок — просмотр · протяните — фрагмент · колесо — масштаб";
    });
    on($("#arc-precise"), "click", () => {
      precise = !precise;
      preciseDirty = false;
      updateSelection();
      if (precise) $("#arc-selection-start").focus();
    });
    const markPreciseDraft = () => {
      preciseDirty =
        !!m.selection &&
        (C.time($("#arc-selection-start").value) !== m.selection.start ||
          C.time($("#arc-selection-end").value) !== m.selection.end);
      updateSelection();
    };
    on($("#arc-selection-start"), "input", markPreciseDraft);
    on($("#arc-selection-end"), "input", markPreciseDraft);
    on($("#arc-selection-apply"), "click", () => {
      const start = C.time($("#arc-selection-start").value),
        end = C.time($("#arc-selection-end").value);
      if (
        start === null ||
        end === null ||
        end - start < 1000 ||
        start < m.range.start ||
        end > m.range.end
      ) {
        onError(
          "Фрагмент должен находиться внутри загруженного периода, начало — раньше конца.",
        );
        return;
      }
      m.selection = C.selection(start, end, m.range.start, m.range.end);
      preciseDirty = false;
      $("#arc-selection-apply").focus();
      updateSelection();
    });

    const at = (clientX) => {
      const r = track.getBoundingClientRect();
      return (
        m.view.start +
        C.clamp((clientX - r.left) / Math.max(1, r.width), 0, 1) *
          (m.view.end - m.view.start)
      );
    };
    on(track, "pointerdown", (e) => {
      if (!m.loaded || !m.intervals.length || ![0, 1].includes(e.button))
        return;
      if ($("#arc-selection-fields").contains(document.activeElement))
        document.activeElement.blur();
      preciseDirty = false;
      const handle = e.target.closest("[data-handle]")?.dataset.handle || "";
      timelineDrag = {
        id: e.pointerId,
        x: e.clientX,
        time: at(e.clientX),
        last: at(e.clientX),
        handle,
        old: m.selection && { ...m.selection },
        mode: e.altKey || e.button === 1 ? "pan" : "select",
        view: { ...m.view },
        moved: false,
        working: null,
      };
      track.setPointerCapture(e.pointerId);
      track.classList.add("is-dragging");
      e.preventDefault();
    });
    on(track, "pointermove", (e) => {
      const d = timelineDrag;
      if (!d || d.id !== e.pointerId) return;
      d.last = at(e.clientX);
      if (Math.abs(e.clientX - d.x) > 4) d.moved = true;
      if (d.mode === "pan") {
        followCursor = false;
        const delta =
          ((d.x - e.clientX) / Math.max(1, track.clientWidth)) *
          (d.view.end - d.view.start);
        m.view = C.viewWindow(
          m.range.start,
          m.range.end,
          d.view.end - d.view.start,
          (d.view.start + d.view.end) / 2 + delta,
        );
        renderTimeline();
        return;
      }
      let start = d.time,
        end = d.last;
      if (d.handle === "start" && d.old) {
        start = Math.min(d.last, d.old.end - 1000);
        end = d.old.end;
      }
      if (d.handle === "end" && d.old) {
        start = d.old.start;
        end = Math.max(d.last, d.old.start + 1000);
      }
      d.working = C.selection(start, end, m.range.start, m.range.end);
      if (d.moved || d.handle) updateSelection(d.working);
    });
    on(track, "pointerup", (e) => {
      const d = timelineDrag;
      if (!d || d.id !== e.pointerId) return;
      timelineDrag = null;
      track.classList.remove("is-dragging");
      if (d.mode === "pan") return;
      if (d.handle || d.moved || selectionMode) {
        m.selection =
          d.working || C.selection(d.time, d.last, m.range.start, m.range.end);
        updateSelection();
      } else {
        updateSelection();
        seek(d.time);
      }
    });
    on(track, "pointercancel", () => {
      timelineDrag = null;
      track.classList.remove("is-dragging");
      updateSelection();
    });
    on(
      track,
      "wheel",
      (e) => {
        e.preventDefault();
        if (!e.shiftKey && Math.abs(e.deltaX) < Math.abs(e.deltaY)) {
          const r = track.getBoundingClientRect();
          changeScale(
            e.deltaY < 0 ? 0.65 : 1 / 0.65,
            at(e.clientX),
            (e.clientX - r.left) / r.width,
          );
        } else moveWindow((e.deltaX || e.deltaY) > 0 ? 1 : -1);
      },
      { passive: false },
    );
    on(track, "keydown", (e) => {
      const handle = e.target.closest("[data-handle]")?.dataset.handle;
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
      e.preventDefault();
      const step = (e.shiftKey ? 10 : 1) * 1000,
        direction = e.key === "ArrowLeft" ? -1 : 1;
      if (handle && m.selection) {
        const s = { ...m.selection },
          min = handle === "start" ? m.range.start : s.start + 1000,
          max = handle === "start" ? s.end - 1000 : m.range.end;
        s[handle] =
          e.key === "Home"
            ? min
            : e.key === "End"
              ? max
              : C.clamp(s[handle] + direction * step, min, max);
        m.selection = s;
        updateSelection();
        return;
      }
      let target = m.cursor ?? m.intervals[0]?.start ?? m.range.start;
      if (e.key === "Home") target = m.range.start;
      else if (e.key === "End") target = m.range.end - 1000;
      else target += direction * step;
      seek(target);
    });
    on($(".archive-console"), "keydown", (e) => {
      if (e.target.closest("input,select,textarea,button")) return;
      if (e.code === "Space") {
        e.preventDefault();
        playToggle();
      }
      if (e.key === "Escape" && zoom.scale > 1) applyZoom(1);
      if (e.key === "+" || e.key === "=") {
        e.preventDefault();
        applyZoom(zoom.scale * 1.25);
        showControls();
      }
      if (e.key === "-") {
        e.preventDefault();
        applyZoom(zoom.scale / 1.25);
        showControls();
      }
    });

    on(video, "playing", () => {
      if (
        !video.hasAttribute("src") ||
        playbackBase === null ||
        String(playbackCameraId) !== String(m.camId) ||
        String(video.dataset.archiveCameraId) !== String(m.camId)
      )
        return;
      clearTimeout(loadTimer);
      loading = false;
      wantPlay = true;
      video.playbackRate = m.speed;
      setState("playing");
      viewer.classList.add("has-frame");
      clearFrame();
      if (audioEnabled) {
        if (!sound.hasAttribute("src")) startAudio();
        else sound.play().catch(audioFailure);
      }
    });
    on(video, "loadeddata", () => {
      if (video.videoWidth) {
        viewer.classList.add("has-frame");
        clearFrame();
      }
      updateAudioButton();
    });
    on(video, "pause", () => sound.pause());
    on(video, "canplay", () => {
      if (String(video.dataset.archiveCameraId) !== String(m.camId)) return;
      if (!wantPlay && status === "loading") {
        clearTimeout(loadTimer);
        loading = false;
        setState("paused");
      }
    });
    on(video, "waiting", () => {
      if (
        !video.hasAttribute("src") ||
        !wantPlay ||
        String(playbackCameraId) !== String(m.camId) ||
        String(video.dataset.archiveCameraId) !== String(m.camId)
      )
        return;
      // `waiting` is normal during transient DVR/network jitter. Before the first
      // frame it may show the loading overlay; after playback began, do not
      // replace the image with a blocking overlay or stop the stream. Keep the
      // last frame visible and show a non-destructive status until `playing` fires.
      if (loading) {
        setState("loading");
        return;
      }
      const statusText = $("#arc-status-text");
      if (statusText) statusText.textContent = "Буферизация архива…";
    });
    on(video, "timeupdate", () => {
      if (
        playbackBase === null ||
        !Number.isFinite(video.currentTime) ||
        String(playbackCameraId) !== String(m.camId) ||
        String(video.dataset.archiveCameraId) !== String(m.camId)
      )
        return;
      const current = playbackBase + video.currentTime * 1000;
      m.cursor = Math.min(playbackEnd, current);
      updateCursor(true);
    });
    on(video, "ended", () => {
      if (
        playbackEnd === null ||
        playbackBase === null ||
        !video.ended ||
        String(playbackCameraId) !== String(m.camId)
      )
        return;
      const actual = Math.min(
          playbackEnd,
          playbackBase + video.currentTime * 1000,
        ),
        complete = playbackEnd - actual <= 3000;
      const next = m.records.find(
        (r) =>
          recordPath(r) !== playbackRecordPath &&
          Number.isFinite(recordStart(r)) &&
          recordStart(r) >= playbackRecordEnd - 1000 &&
          recordStart(r) < m.range.end,
      );
      m.cursor = complete ? playbackEnd : actual;
      updateCursor(true);
      if (
        complete &&
        wantPlay &&
        next &&
        (m.skipGaps || recordStart(next) - playbackRecordEnd <= 1500)
      )
        seek(Math.max(m.range.start, recordStart(next)), true);
      else {
        wantPlay = false;
        sound.pause();
        setState("paused");
        showControls();
        if (!complete)
          $("#arc-status-text").textContent =
            "Регистратор завершил передачу раньше конца файла. Позиция сохранена.";
      }
    });
    on(video, "error", () => {
      if (
        disposed ||
        !video.hasAttribute("src") ||
        String(playbackCameraId) !== String(m.camId) ||
        String(video.dataset.archiveCameraId) !== String(m.camId)
      )
        return;
      clearTimeout(loadTimer);
      loading = false;
      wantPlay = false;
      setState(
        "error",
        "Видео недоступно или кодек не поддерживается браузером. Проверьте выбранную камеру, время, регистратор и FFmpeg, затем повторите.",
      );
      showControls();
    });
    on(document, "fullscreenchange", () => {
      if (!disposed) {
        applyZoom(zoom.scale);
        renderTimeline();
      }
    });
    const resize = new ResizeObserver(() => {
      if (!disposed) {
        applyZoom(zoom.scale);
        renderTimeline();
      }
    });
    resize.observe(viewer);
    renderTimeline();
    setState(
      !cameras.length
        ? "empty"
        : m.loaded
          ? m.intervals.length
            ? "ready"
            : "empty"
          : "idle",
    );
    try {
      const preferred = localStorage.getItem("vwshub.archive.timelineStyle");
      if (["records", "continuous"].includes(preferred)) {
        $("#arc-timeline-style").value = preferred;
        track.classList.toggle("continuous", preferred === "continuous");
      }
    } catch (_) {}
    $("#arc-speed-warning").hidden = m.speed <= 1;
    function translateUI() {
      if (locale !== "en-GB" || disposed) return;
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      let node;
      while ((node = walker.nextNode())) {
        if (
          node.parentElement?.closest(
            "#arc-camera-title,#arc-camera,#arc-group,#arc-track-label",
          )
        )
          continue;
        const text = translate(node.nodeValue);
        if (text !== node.nodeValue) node.nodeValue = text;
      }
      root
        .querySelectorAll("[title],[aria-label],[aria-valuetext],[placeholder]")
        .forEach((el) => {
          if (
            el.closest(
              "#arc-camera-title,#arc-camera,#arc-group,#arc-track-label",
            )
          )
            return;
          for (const attribute of [
            "title",
            "aria-label",
            "aria-valuetext",
            "placeholder",
          ]) {
            if (el.hasAttribute(attribute)) {
              const value = el.getAttribute(attribute),
                text = translate(value);
              if (text !== value) el.setAttribute(attribute, text);
            }
          }
        });
    }
    const translations = new MutationObserver(translateUI);
    if (locale === "en-GB") {
      translateUI();
      translations.observe(root, {
        subtree: true,
        childList: true,
        characterData: true,
        attributes: true,
        attributeFilter: [
          "title",
          "aria-label",
          "aria-valuetext",
          "placeholder",
        ],
      });
    }
    if (cameras.length) {
      loadAudioCapabilities();
      if (!m.loaded) search();
    }
    function dispose() {
      if (disposed) return;
      disposed = true;
      translations.disconnect();
      ++searchGeneration;
      searchAbort?.abort();
      life.abort();
      resize.disconnect();
      clearTimeout(hideTimer);
      stopPlayback();
    }
    return dispose;
  }
  window.VMSArchive = { mount };
})();
