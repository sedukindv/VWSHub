/* VWSHub 0.8 application shell and administration. No external UI dependencies. */
(() => {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s),
    $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const boot = JSON.parse($("#bootstrap-data").textContent);
  window.VWSHUB_BOOTSTRAP = boot;
  const state = {
    ...boot,
    user: boot.user,
    cameras: [],
    groups: [],
    users: [],
    view: "live",
    statuses: {},
    statusLoaded: false,
    cameraSearch: "",
    cameraFilters: { group: "", recorder: "", protocol: "", status: "" },
    recorders: [],
    statusRefreshing: false,
    logKind: "audit",
    settings: null,
    archiveId: "",
    liveGroup: "",
    language: boot.user?.language || boot.public_settings?.language || "ru",
  };
  const EN = {
    Навигация: "Navigation",
    "Сеанс завершён": "Your session has ended",
    "JSON не больше 2 МБ": "JSON must not exceed 2 MB",
    "Изображение слишком большое": "Image is too large",
    Просмотр: "Live view",
    Архив: "Archive",
    Камеры: "Cameras",
    Группы: "Groups",
    Пользователи: "Users",
    Устройства: "Devices",
    Логи: "Logs",
    Кастомизация: "Appearance",
    Настройки: "Settings",
    Профиль: "Profile",
    "Рабочее пространство": "Workspace",
    УПРАВЛЕНИЕ: "MANAGEMENT",
    МОНИТОРИНГ: "MONITORING",
    СИСТЕМА: "SYSTEM",
    "Свернуть меню": "Collapse sidebar",
    "Развернуть меню": "Expand sidebar",
    Выйти: "Sign out",
    Администратор: "Administrator",
    "Просмотр без управления": "Viewer",
    "Добавить камеру": "Add camera",
    Обновить: "Refresh",
    "Поиск камер": "Search cameras",
    "Все протоколы": "All protocols",
    Название: "Name",
    Подключение: "Connection",
    Статус: "Status",
    "Группы камеры": "Camera groups",
    Действия: "Actions",
    "В сети": "Online",
    "Не в сети": "Offline",
    "Не проверен": "Not checked",
    Изменить: "Edit",
    Клонировать: "Clone",
    Удалить: "Delete",
    "Камеры и каналы": "Cameras and channels",
    "Подключайте регистраторы и IP-камеры, объединяйте их в группы.":
      "Connect recorders and IP cameras, and organize them into groups.",
    Автопоиск: "Discover devices",
    Сохранить: "Save",
    Сохранено: "Saved",
    Закрыть: "Close",
    "Проверить подключение": "Test connection",
    "Название камеры": "Camera name",
    "Протокол подключения": "Connection protocol",
    "Аналоговые камеры (DVRIP)": "Analog cameras (DVRIP)",
    "Каналы XM / XMEye": "XM / XMEye recorder channels",
    "IP-камеры (ONVIF / RTSP)": "IP cameras (ONVIF / RTSP)",
    "Стандартные IP-камеры": "Standard IP cameras",
    "Адрес устройства": "Device address",
    "IP-адрес или имя узла": "IP address or hostname",
    "Порт устройства": "Device port",
    "Порт RTSP": "RTSP port",
    Канал: "Channel",
    "Путь RTSP": "RTSP path",
    "Дополнительный RTSP-путь": "Substream RTSP path",
    "Логин устройства": "Device login",
    "Пароль устройства": "Device password",
    "Пусто — сохранить прежний пароль":
      "Leave blank to keep the existing password",
    "Параметры подключения": "Connection settings",
    "Учётные данные устройства": "Device credentials",
    "Выберите одну или несколько групп.": "Select one or more groups.",
    "Нет групп": "No groups",
    "Группы камер": "Camera groups",
    "Организуйте камеры по расположению и назначайте доступ пользователям.":
      "Organize cameras by location and assign user access.",
    "Создать группу": "Create group",
    "Импорт групп": "Import groups",
    "Экспорт групп": "Export groups",
    Смотреть: "Watch",
    "Название группы": "Group name",
    "Камеры группы": "Group cameras",
    "Доступ и учётные записи": "Accounts and access",
    "Назначайте группы и отдельно разрешайте просмотр архива.":
      "Assign groups and grant archive access separately.",
    "Добавить пользователя": "Add user",
    Логин: "Login",
    Псевдоним: "Display name",
    Роль: "Role",
    "Доступ к архиву": "Archive access",
    Разрешён: "Allowed",
    Запрещён: "Denied",
    "Только просмотр": "Viewer",
    "Новый пароль": "New password",
    "Доступные группы": "Allowed groups",
    "Разрешить архив": "Allow archive playback",
    Язык: "Language",
    "Изображение профиля": "Profile image",
    "Выбрать изображение": "Choose image",
    "Удалить изображение": "Remove image",
    Тема: "Theme",
    Автоматическая: "Automatic",
    Светлая: "Light",
    Тёмная: "Dark",
    "Системный журнал": "System log",
    "Действия администраторов и события сервера. Пароли в журнал не записываются.":
      "Administrator actions and server events. Passwords are excluded from the log.",
    Время: "Time",
    Пользователь: "User",
    Событие: "Event",
    Подробности: "Details",
    "Название и оформление": "Branding and appearance",
    "Оформление применяется ко всем пользователям и странице входа.":
      "Appearance applies to all users and the sign-in page.",
    "Название сайта": "Site name",
    Подпись: "Subtitle",
    "Основной цвет": "Accent color",
    Логотип: "Logo",
    Фавикон: "Favicon",
    "Плавная анимация": "Motion and transitions",
    "Включить анимацию": "Enable animations",
    "Сервер и ресурсы": "Server and resources",
    "Настройте нагрузку, форматы и общие параметры сервера.":
      "Configure capacity, formats and common server settings.",
    Процессор: "CPU",
    "Оперативная память": "Memory",
    "Свободно на диске": "Free disk space",
    "Общие параметры": "General settings",
    "Часовой пояс": "Time zone",
    "Язык по умолчанию": "Default language",
    "Формат снимков": "Snapshot format",
    "Формат архива": "Archive format",
    "Профиль ресурсов": "Resource profile",
    Стандартный: "Standard",
    Максимальный: "Maximum",
    Свой: "Custom",
    "Одновременных live-потоков": "Concurrent live streams",
    "Одновременных архивов": "Concurrent archive streams",
    "Буфер архива, МБ": "Archive buffer, MB",
    "Ожидание сети, с": "Network idle timeout, sec",
    "Потоков FFmpeg": "FFmpeg threads",
    "Применить настройки": "Apply settings",
    "Обслуживание сервера": "Server maintenance",
    "Резервная копия": "Backup",
    "Скачать backup": "Download backup",
    "Перезапустить сервер": "Restart server",
    Версия: "Version",
    Разработчик: "Developer",
    "Время работы": "Uptime",
    "Чистый интерфейс. Прямой архив.": "A focused workspace. A direct archive.",
    "У вас пока нет доступных камер": "No cameras available",
    "Добавьте камеры или попросите администратора назначить группы.":
      "Add cameras or ask an administrator to assign groups.",
    "Загрузка…": "Loading…",
    "Ничего не найдено": "No results",
    "Выберите другой запрос.": "Try a different search.",
    "Группа создана": "Group created",
    "Камера сохранена": "Camera saved",
    "Пользователь сохранён": "User saved",
    "Настройки сохранены": "Settings saved",
    "Оформление сохранено": "Appearance saved",
    "Мой профиль": "My profile",
    "Изображение и псевдоним отображаются вместо логина.":
      "Your image and display name appear instead of your login.",
    "Текущий пароль": "Current password",
    "Новый пароль профиля": "New account password",
    "Найденные устройства": "Discovered devices",
    "Поиск выполняется только по вашему запросу.":
      "Discovery runs only on request.",
    "Локальная подсеть для DVRIP (необязательно)":
      "Local DVRIP subnet (optional)",
    "Найти устройства": "Find devices",
    Найдено: "Found",
    Добавить: "Add",
    "Состояние проверяется только при открытии страницы и по кнопке «Обновить».":
      "Status is checked only when this page opens and when you press Refresh.",
    "Удалить группу? Камеры останутся в системе.":
      "Delete this group? Cameras will remain in the system.",
    "Удалить камеру из системы?": "Remove this camera from the system?",
    "Удалить пользователя?": "Delete this user?",
    "Копия камеры создана": "Camera cloned",
    "Изменения сохранены. Окно можно закрыть крестиком или Esc.":
      "Changes saved. Close this dialog with X or Esc.",
    "Максимальный профиль увеличивает допустимое число потоков, но не производительность оборудования.":
      "The maximum profile allows more streams; it does not add hardware capacity.",
    "Backup содержит учётные записи, зашифрованные пароли устройств и ключи. Храните его в защищённом месте.":
      "A backup contains user accounts, encrypted device passwords and keys. Keep it private.",
    "Информация о сервере": "Server information",
    "Сохранять видео в MP4 без лишнего перекодирования.":
      "Use MP4 without unnecessary transcoding.",
    "Нет назначенных групп": "No assigned groups",
    "Камеры доступны только из назначенных групп.":
      "Only cameras in assigned groups are accessible.",
    Фотоаппарат: "Snapshot",
  };
  Object.assign(EN, {
    Все: "All",
    "Узел RTSP": "RTSP host",
    "Пусто — адрес устройства": "Blank uses the device address",
    "Без группы": "Ungrouped",
    Группа: "Group",
    Регистратор: "Recorder",
    "Обновить статус": "Refresh status",
    Импорт: "Import",
    Экспорт: "Export",
    "Поиск групп": "Find groups",
    Пользователь: "User",
    "Редактор групп": "Group editor",
    Чтение: "Read",
    Редактирование: "Edit",
    "Доступ к группе": "Group access",
    "Изменить название": "Rename",
    "Имя регистратора": "Recorder name",
    "Добавить регистратор": "Add recorder",
    "Проверить каналы": "Check channels",
    "Добавить все каналы": "Add all channels",
    "Доступных каналов": "Available channels",
    "Добавлено камер": "Cameras added",
    "Сохранено существующих": "Existing cameras preserved",
    "Экспорт камер": "Export cameras",
    "Импорт камер": "Import cameras",
    "Скачать JSON": "Download JSON",
    "Включить пароли устройств": "Include device passwords",
    "Файл с паролями храните в защищённом месте.":
      "Keep files containing passwords in a secure place.",
    "Экспорт включает подключения, группы и имена устройств. По умолчанию пароли исключены.":
      "Exports include connections, groups and recorder names. Passwords are omitted by default.",
    "Выберите JSON, экспортированный из VWSHub.":
      "Choose a JSON catalog exported from VWSHub.",
    "Файл камер": "Camera file",
    "Режим импорта": "Import mode",
    "Добавить новые камеры": "Add new cameras",
    "Обновить камеры с совпадающим ID": "Update cameras with matching IDs",
    "Совпадающие подключения сохраняются. Текущие камеры не удаляются.":
      "Matching connections are preserved. Existing cameras are retained.",
    "Совпавшие ID заменят параметры подключения и группы. Пустой пароль сохраняет прежний.":
      "Matching IDs replace connection settings and groups. A blank password preserves the current password.",
    Импортировано: "Imported",
    Пропущено: "Skipped",
    "JSON не больше 16 МБ": "JSON must be at most 16 MB",
    "Неверный файл камер VWSHub": "Invalid VWSHub camera catalog",
    "Это имя используется на сайте. Имя и настройки оборудования сохраняются.":
      "This label is used on the site. The hardware hostname and settings are preserved.",
    "При сохранении приложение прочитает доступные каналы и добавит новые камеры. Существующие подключения сохраняются.":
      "Saving reads the recorder channels and adds missing cameras. Existing connections are preserved.",
    "Читаем каналы регистратора…": "Reading recorder channels…",
    "Добавляем каналы регистратора…": "Adding recorder channels…",
    "Названия регистраторов": "Recorder labels",
    "Имя устройства": "Device name",
    "Плотность интерфейса": "Interface density",
    Комфортная: "Comfortable",
    Компактная: "Compact",
    "Углы элементов": "Corners",
    Скруглённые: "Rounded",
    Прямые: "Square",
    "Отступ видеостены, px": "Wall gap, px",
    "Показывать часы на видеостене": "Show wall clock",
    "Диагностика оборудования": "Hardware diagnostics",
    "Локальные журналы подключений и ошибок без паролей. Ротация до 8 МБ.":
      "Local connection and error logs without passwords. Rotating storage of approximately 8 MB.",
    "Действия пользователей и диагностика оборудования без паролей и видеоданных.":
      "User activity and hardware diagnostics without passwords or video data.",
    Оборудование: "Hardware",
    Уровень: "Level",
    "последних событий": "recent events",
    Очистить: "Clear",
    "Очистить журнал": "Clear log",
    "Скачать диагностику": "Download diagnostics",
    "Удалить текущий журнал оборудования и его ротации? Сначала скачайте диагностику, если она нужна для разбора проблемы.":
      "Clear the current hardware log and its rotations? Download diagnostics first if needed for troubleshooting.",
    "Удалить журнал действий и его ротации? Само событие очистки останется в новом журнале.":
      "Clear the audit log and its rotations? The new log will retain the clear action.",
    "Снятие флажка убирает камеру только из этой группы. Подключение и остальные группы сохраняются.":
      "Unchecking a camera removes it only from this group. Its connection and other groups are preserved.",
    "Восстановить backup": "Restore backup",
    Восстановить: "Restore",
    "ZIP backup": "Backup ZIP",
    "Для восстановления введите RESTORE": "Type RESTORE to restore",
    "Администраторы backup": "Backup administrators",
    "ZIP не больше 16 МБ": "ZIP must be at most 16 MB",
    "Проверяем структуру, ключи и связи backup…":
      "Validating backup structure, encryption keys and references…",
    "Backup проверен. Убедитесь, что знаете пароль одного из администраторов этой копии.":
      "Backup validated. Make sure you know a password for one of its administrators.",
    "Сохраняем текущую конфигурацию и восстанавливаем backup…":
      "Saving the current configuration and restoring the backup…",
    "Backup заменит пользователей, камеры, группы, оформление и ключи. Перед заменой автоматически сохранится копия текущих данных; все сеансы завершатся.":
      "Restore replaces users, cameras, groups, appearance and keys. A safety copy is saved first and all sessions are signed out.",
    "Состояние проверяется при открытии страницы, после сохранения камеры и по кнопке «Обновить статус».":
      "Status is checked on opening this page, after saving a camera, and when Refresh status is selected.",
  });
  const t = (text) =>
    state.language === "en" && Object.hasOwn(EN, text) ? EN[text] : text;
  window.vwsTranslate = t;
  const h = (value) =>
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
    grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    archive:
      '<rect x="3" y="4" width="18" height="5" rx="1"/><path d="M5 9v11h14V9m-9 4h4"/>',
    camera:
      '<rect x="3" y="6" width="13" height="12" rx="2"/><path d="m16 10 5-3v10l-5-3"/>',
    photo:
      '<path d="M4 7h4l2-3h4l2 3h4v13H4z"/><circle cx="12" cy="13" r="4"/>',
    folder: '<path d="M3 6h7l2 2h9v12H3z"/>',
    users:
      '<rect x="3" y="3" width="18" height="18" rx="4"/><circle cx="10" cy="9" r="2.5"/><path d="M5.8 17c.4-2.2 1.8-3.3 4.2-3.3s3.8 1.1 4.2 3.3M16 7h2m-2 4h2m-1 4h1"/>',
    server:
      '<rect x="3" y="3" width="18" height="7" rx="2"/><rect x="3" y="14" width="18" height="7" rx="2"/><path d="M7 6h.01M7 17h.01M12 6h5M12 17h5"/>',
    settings: '<path d="M4 3v18M12 3v18M20 3v18M1 8h6m2 8h6m2-6h6"/>',
    list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
    palette:
      '<rect x="3" y="3" width="18" height="18" rx="4"/><path d="M3 9h18M9 9v12"/><path d="m12 17 4-4 2 2-4 4h-2z"/><path d="M6 6h.01M9 6h.01"/>',
    menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
    panel:
      '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18m6-13-3 4 3 4"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1 1m12 12 1 1M5 19l1-1M18 6l1-1"/>',
    moon: '<path d="M21 13A9 9 0 0 1 11 3a9 9 0 1 0 10 10z"/>',
    monitor:
      '<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8m-4-4v4"/>',
    logout: '<path d="M10 17l5-5-5-5M3 12h12M12 3h8v18h-8"/>',
    plus: '<path d="M5 12h14M12 5v14"/>',
    search: '<circle cx="10" cy="10" r="7"/><path d="m15 15 6 6"/>',
    refresh:
      '<path d="M20 7v5h-5M4 17v-5h5M5 9A7 7 0 0 1 18 6l2 6M4 12l2 6a7 7 0 0 0 12-3"/>',
    edit: '<path d="m16 3 5 5L9 20l-6 1 1-6zM13 6l5 5"/>',
    clone:
      '<rect x="8" y="8" width="13" height="13" rx="2"/><path d="M16 8V3H3v13h5"/>',
    trash: '<path d="M3 6h18M8 6V3h8v3M6 6l1 15h10l1-15M10 10v7m4-7v7"/>',
    close: '<path d="m6 6 12 12M6 18 18 6"/>',
    check: '<path d="m4 12 5 5L20 6"/>',
    download: '<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
    upload: '<path d="M12 17V5m-5 5 5-5 5 5M4 16v5h16v-5"/>',
    play: '<path d="m8 5 11 7-11 7z"/>',
    pause: '<path d="M8 5v14M16 5v14"/>',
    expand: '<path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/>',
    left: '<path d="m14 5-7 7 7 7"/>',
    right: '<path d="m10 5 7 7-7 7"/>',
    alert: '<path d="m12 3 10 18H2zM12 9v4m0 4h.01"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10h.01"/>',
    brand: '<path d="m3 5 9 15 9-15M7 5l5 8 5-8"/>',
    lock: '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V6a4 4 0 0 1 8 0v4"/>',
    link: '<path d="m9 15 6-6M7 12l-3 3a4 4 0 0 0 5 5l3-3m0-10 3-3a4 4 0 0 1 5 5l-3 3"/>',
    route:
      '<circle cx="6" cy="6" r="3"/><circle cx="18" cy="18" r="3"/><path d="M9 6h3a3 3 0 0 1 3 3v3a3 3 0 0 0 3 3"/>',
  };
  const icon = (name) =>
    `<svg viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.info}</svg>`;
  function toast(message, type = "success") {
    const el = document.createElement("div");
    el.className = `toast ${type}`;
    el.innerHTML = `${icon(type === "error" ? "alert" : type === "warning" ? "info" : "check")}<span>${h(t(message))}</span>`;
    $("#toast-root").append(el);
    setTimeout(() => el.remove(), 6000);
  }
  async function api(url, options = {}) {
    const opts = {
      credentials: "same-origin",
      ...options,
      headers: { "X-CSRF-Token": state.csrf_token, ...options.headers },
    };
    if (
      opts.body &&
      typeof opts.body !== "string" &&
      !(opts.body instanceof FormData)
    ) {
      opts.body = JSON.stringify(opts.body);
      opts.headers["Content-Type"] = "application/json";
    }
    const res = await fetch(url, opts);
    if (res.status === 401) {
      location.href = "/login";
      throw new Error("Сеанс завершён");
    }
    let data = {};
    if (res.headers.get("content-type")?.includes("json"))
      data = await res.json();
    if (!res.ok || data.success === false)
      throw new Error(data.error || `HTTP ${res.status}`);
    return data;
  }
  function downloadJSON(value, name) {
    const blob = new Blob([JSON.stringify(value, null, 2)], {
        type: "application/json",
      }),
      url = URL.createObjectURL(blob),
      a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 3000);
  }
  function pickJSON(callback) {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".json,application/json";
    input.onchange = async () => {
      try {
        const file = input.files[0];
        if (!file) return;
        if (file.size > 2 * 1024 * 1024) throw new Error("JSON не больше 2 МБ");
        await callback(JSON.parse(await file.text()));
      } catch (e) {
        toast(e.message, "error");
      }
    };
    input.click();
  }
  async function readImage(file, size = 256) {
    if (!file) return "";
    if (!["image/png", "image/jpeg", "image/webp"].includes(file.type))
      throw new Error("PNG / JPEG / WebP");
    if (file.size > 10 * 1024 * 1024)
      throw new Error("Изображение не больше 10 МБ");
    const url = URL.createObjectURL(file);
    try {
      const img = new Image();
      img.src = url;
      await img.decode();
      const ratio = Math.min(1, size / Math.max(img.width, img.height)),
        canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(img.width * ratio));
      canvas.height = Math.max(1, Math.round(img.height * ratio));
      canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
      let data = canvas.toDataURL("image/png");
      if (data.length > 340000) data = canvas.toDataURL("image/webp", 0.8);
      if (data.length > 340000) throw new Error("Изображение слишком большое");
      return data;
    } finally {
      URL.revokeObjectURL(url);
    }
  }
  const avatar = (u) =>
    u?.avatar
      ? `<span class="avatar"><img src="${h(u.avatar)}" alt=""></span>`
      : `<span class="avatar">${h((u?.alias || u?.username || "?").slice(0, 1).toUpperCase())}</span>`;
  let fieldSequence = 0;
  function formField(label, contents, help = "") {
    let target = "";
    contents = contents.replace(
      /<(input|select|textarea)\b([^>]*)>/i,
      (tag, kind, attributes) => {
        const existing = attributes.match(/\bid="([^"]+)"/i);
        target = existing ? existing[1] : `vws-field-${++fieldSequence}`;
        return existing ? tag : `<${kind} id="${target}"${attributes}>`;
      },
    );
    return `<div class="form-field"><label${target ? ` for="${h(target)}"` : ""}>${h(t(label))}</label>${contents}${help ? `<small>${h(t(help))}</small>` : ""}</div>`;
  }
  function input(name, value = "", extra = "") {
    return `<input class="field" name="${name}" value="${h(value)}" ${extra}>`;
  }
  const button = (id, label, symbol = "plus", cls = "") =>
    `<button type="button" id="${id}" class="btn ${cls}">${icon(symbol)}${h(t(label))}</button>`;
  const ib = (action, id, label, symbol) =>
    `<button type="button" class="icon-btn" data-action="${action}" data-id="${h(id)}" title="${h(t(label))}" aria-label="${h(t(label))}">${icon(symbol)}</button>`;
  function page(title, desc, actions, body, kicker = "VWSHUB WORKSPACE") {
    const template = document.createElement("template");
    template.innerHTML = body;
    const toolbar = [...template.content.children].find((el) =>
      el.classList.contains("toolbar"),
    );
    const pinned = toolbar?.outerHTML || "";
    toolbar?.remove();
    return `<section class="page"><div class="page-sticky"><div class="page-head"><div><span class="eyebrow">${h(t(kicker))}</span><h1>${h(t(title))}</h1><p>${h(t(desc))}</p></div><div class="page-actions">${actions || ""}</div></div>${pinned}</div>${template.innerHTML}</section>`;
  }
  function empty(title, desc, action = "") {
    return `<div class="empty-state">${icon("camera")}<h2>${h(t(title))}</h2><p>${h(t(desc))}</p>${action}</div>`;
  }
  function modal(title, desc, body, foot = "", wide = false) {
    $("#modal-root").innerHTML =
      `<div class="modal-backdrop"><section class="modal ${wide ? "modal-wide" : ""}" role="dialog" aria-modal="true" aria-labelledby="modal-title"><header class="modal-head"><div><h2 id="modal-title">${h(t(title))}</h2><p>${h(t(desc))}</p></div><button type="button" class="icon-btn" data-close aria-label="${t("Закрыть")}">${icon("close")}</button></header><div class="modal-body">${body}</div>${foot ? `<footer class="modal-foot">${foot}</footer>` : ""}</section></div>`;
    const feedback = $("#modal-root .form-feedback");
    if (feedback) $("#modal-root .modal-head").after(feedback);
    $$("[data-close]", $("#modal-root")).forEach(
      (b) => (b.onclick = closeModal),
    );
    requestAnimationFrame(() =>
      $(
        "input:not([type=hidden]),select,button",
        $("#modal-root .modal-body"),
      )?.focus(),
    );
    $$("[data-check-search]", $("#modal-root")).forEach((search) => {
      search.oninput = () => {
        const query = search.value.toLowerCase().trim();
        $$(".check-item", search.closest(".check-picker")).forEach((row) => {
          row.hidden = !(row.dataset.search || row.textContent)
            .toLowerCase()
            .includes(query);
        });
      };
    });
    return $("#modal-root .modal");
  }
  function closeModal() {
    $("#modal-root").replaceChildren();
  }
  let cleanup = null,
    pageGeneration = 0;
  const nav = [
    ["live", "Просмотр", "grid", 0],
    ["archive", "Архив", "archive", 0],
    ["cameras", "Камеры", "camera", 1],
    ["groups", "Группы", "folder", 0],
    ["users", "Пользователи", "users", 1],
    ["devices", "Устройства", "server", 1],
    ["logs", "Логи", "list", 1],
    ["customize", "Кастомизация", "palette", 1],
    ["settings", "Настройки", "settings", 1],
  ];
  function allowed(view) {
    return nav.some(
      ([v, , , admin]) =>
        v === view &&
        (!admin ||
          state.user.role === "admin" ||
          (v === "cameras" && state.cameras.some((c) => c.can_edit))) &&
        (v !== "archive" ||
          state.user.role === "admin" ||
          state.user.archive_access),
    );
  }
  function applyBrand() {
    const b = state.branding;
    document.documentElement.style.setProperty(
      "--accent",
      b.accent || "#526cf5",
    );
    document.body.dataset.motion = b.motion === false ? "off" : "on";
    document.body.dataset.density = b.density || "comfortable";
    document.body.dataset.corners = b.corners || "rounded";
    document.documentElement.style.setProperty(
      "--wall-gap",
      `${Number(b.wall_gap ?? 3)}px`,
    );
    document.title = b.name || "VWSHub";
    $("#brand").innerHTML =
      `<span class="brand-mark">${b.logo ? `<img src="${h(b.logo)}" alt="">` : icon("brand")}</span><span class="brand-copy"><strong>${h(b.name)}</strong><small>${h(b.subtitle)}</small></span>`;
    if (b.favicon) {
      let link = $("#site-favicon");
      if (!link) {
        link = document.createElement("link");
        link.id = "site-favicon";
        link.rel = "icon";
        document.head.append(link);
      }
      link.href = b.favicon;
    } else $("#site-favicon")?.remove();
  }
  function renderShell() {
    document.documentElement.lang = state.language;
    $("#navigation").setAttribute("aria-label", t("Навигация"));
    $("#theme-switch").setAttribute("aria-label", t("Тема"));
    $("#sidebar-collapse").setAttribute(
      "aria-label",
      t(
        document.body.classList.contains("is-collapsed")
          ? "Развернуть меню"
          : "Свернуть меню",
      ),
    );
    $("#logout").setAttribute("aria-label", t("Выйти"));
    document.documentElement.dataset.theme = state.user.theme || "auto";
    applyBrand();
    let category = "";
    $("#navigation").innerHTML = nav
      .filter(([view]) => allowed(view))
      .map(([view, label, symbol]) => {
        const next = ["live", "archive"].includes(view)
          ? "МОНИТОРИНГ"
          : ["logs", "customize", "settings"].includes(view)
            ? "СИСТЕМА"
            : "УПРАВЛЕНИЕ";
        const caption =
          next === category ? "" : `<div class="nav-caption">${t(next)}</div>`;
        category = next;
        return `${caption}<button type="button" class="nav-item ${state.view === view ? "active" : ""}" data-view="${view}" title="${h(t(label))}">${icon(symbol)}<span>${h(t(label))}</span>${view === "live" ? `<span class="nav-count">${state.cameras.length}</span>` : ""}</button>`;
      })
      .join("");
    $$("[data-view]", $("#navigation")).forEach(
      (b) => (b.onclick = () => showView(b.dataset.view)),
    );
    $("#workspace-label").textContent = t("Рабочее пространство");
    $("#section-title").textContent = t(
      nav.find((n) => n[0] === state.view)?.[1] || "Просмотр",
    );
    $("#sidebar-collapse").innerHTML =
      `${icon("panel")}<span>${t(document.body.classList.contains("is-collapsed") ? "Развернуть меню" : "Свернуть меню")}</span>`;
    $("#mobile-menu").innerHTML = icon("menu");
    $("#theme-switch").innerHTML = [
      ["auto", "monitor"],
      ["light", "sun"],
      ["dark", "moon"],
    ]
      .map(
        ([value, symbol]) =>
          `<button type="button" data-theme="${value}" class="${(state.user.theme || "auto") === value ? "active" : ""}" aria-label="${t(value === "auto" ? "Автоматическая" : value === "light" ? "Светлая" : "Тёмная")}">${icon(symbol)}</button>`,
      )
      .join("");
    $$("[data-theme]", $("#theme-switch")).forEach(
      (b) =>
        (b.onclick = async () => {
          state.user.theme = b.dataset.theme;
          renderShell();
          try {
            await api("/api/profile/theme", {
              method: "POST",
              body: { theme: state.user.theme },
            });
          } catch (e) {
            toast(e.message, "error");
          }
        }),
    );
    $("#user-button").innerHTML =
      `${avatar(state.user)}<span class="user-copy"><strong>${h(state.user.alias || state.user.username)}</strong><small>${t(state.user.role === "admin" ? "Администратор" : Object.values(state.user.group_access || {}).includes("edit") ? "Редактор групп" : "Просмотр без управления")}</small></span>`;
    $("#user-button").onclick = openProfile;
    $("#logout").innerHTML = icon("logout");
    $("#logout").title = t("Выйти");
  }
  async function loadData() {
    const promises = [
      api("/api/cameras"),
      api("/api/groups"),
      api("/api/recorders"),
    ];
    if (state.user.role === "admin") promises.push(api("/api/users"));
    const values = await Promise.all(promises);
    state.cameras = values[0];
    state.groups = values[1];
    state.recorders = values[2] || [];
    state.users = values[3] || [];
    if (!state.cameras.some((c) => c.id === state.archiveId))
      state.archiveId =
        state.cameras.find((c) => c.protocol === "dvrip")?.id || "";
  }
  async function showView(view, extra = {}) {
    if (!allowed(view)) return;
    cleanup?.();
    cleanup = null;
    ++pageGeneration;
    state.view = view;
    document.body.dataset.view = view;
    document.body.classList.remove("menu-open");
    renderShell();
    const main = $("#main-content");
    try {
      if (view === "live")
        cleanup = window.VWSLive.mount({
          root: main,
          cameras: state.cameras,
          groups: state.groups,
          user: state.user,
          settings: state.public_settings,
          groupId: extra.groupId,
          hub: H,
          onArchive: (id) => {
            state.archiveId = id;
            showView("archive");
          },
        });
      else if (view === "archive")
        cleanup = window.VMSArchive.mount({
          root: main,
          cameras: state.cameras,
          groups: state.groups,
          selectedId: state.archiveId,
          api,
          language: state.language,
          onSelect: (id) => (state.archiveId = id),
          onError: (m) => toast(m, "error"),
          onSuccess: toast,
        });
      else if (view === "cameras") renderCameras();
      else if (view === "groups") renderGroups();
      else if (view === "users") renderUsers();
      else if (view === "devices")
        cleanup = window.VWSDevices.mount({
          root: main,
          cameras: state.cameras,
          isAdmin: state.user.role === "admin",
          hub: H,
          onCatalogChanged: async ({ refreshStatus = false } = {}) => {
            if (refreshStatus) state.statusLoaded = false;
            await loadData();
            await showView("devices");
            if (refreshStatus) refreshStatuses();
          },
          api,
          onError: (m) => toast(m, "error"),
          onSuccess: toast,
        });
      else if (view === "logs") await renderLogs();
      else if (view === "customize") renderCustomize();
      else if (view === "settings") await renderSettings();
    } catch (e) {
      toast(e.message, "error");
      main.innerHTML = empty("Ничего не найдено", e.message);
    }
  }

  function renderCameras() {
    const main = $("#main-content"),
      scroll = main.scrollTop,
      admin = state.user.role === "admin",
      f = state.cameraFilters,
      q = state.cameraSearch.toLowerCase();
    const filtered = state.cameras.filter((c) => {
      const status = state.statuses[c.id];
      return (
        `${c.name} ${c.ip} ${c.recorder_name || ""} ${c.protocol} ${Number(c.channel || 0) + 1}`
          .toLowerCase()
          .includes(q) &&
        (!f.group ||
          (f.group === "__none"
            ? !c.group_ids?.length
            : c.group_ids?.includes(f.group))) &&
        (!f.recorder || c.recorder_id === f.recorder) &&
        (!f.protocol || c.protocol === f.protocol) &&
        (!f.status ||
          (f.status === "unknown"
            ? !status
            : f.status === "online"
              ? status?.online === true
              : status?.online === false))
      );
    });
    const select = (id, label, values, value) =>
      `<label class="camera-filter"><span>${t(label)}</span><select id="${id}" class="select"><option value="">${t("Все")}</option>${values.map(([key, name]) => `<option value="${h(key)}" ${key === value ? "selected" : ""}>${h(id === "camera-group-filter" || id === "camera-recorder-filter" ? name : t(name))}</option>`).join("")}</select></label>`;
    const rows = filtered
      .map((c) => {
        const status = state.statuses[c.id];
        const actions = admin
          ? ib("camera-edit", c.id, "Изменить", "edit") +
            ib("camera-clone", c.id, "Клонировать", "clone") +
            ib("camera-delete", c.id, "Удалить", "trash")
          : c.can_edit
            ? ib("camera-rename", c.id, "Изменить название", "edit")
            : "";
        return `<tr><td><div class="cell-name"><span class="cell-icon">${icon(c.protocol === "dvrip" ? "server" : "camera")}</span><div><strong>${h(c.name)}</strong><small>${c.protocol === "dvrip" ? `DVRIP · CH ${Number(c.channel || 0) + 1}` : "ONVIF / RTSP"}</small></div></div></td><td><strong class="recorder-label">${h(c.recorder_name || c.ip)}</strong><span class="type-code">${h(c.ip)}:${h(c.port)}</span><div class="small-muted">RTSP ${h(c.rtsp_port || 554)}</div></td><td><span class="badge ${status?.online ? "green" : status ? "red" : ""}" title="${h(status?.reason || t("Не проверен"))}"><i class="dot ${status?.online ? "online" : status ? "offline" : ""}"></i>${t(status?.online ? "В сети" : status ? "Не в сети" : "Не проверен")}</span>${status?.method === "rtsp" ? `<small class="status-source">RTSP</small>` : ""}</td><td><div class="badge-list">${(c.group_names || []).map((name) => `<span class="badge blue">${h(name)}</span>`).join("") || "—"}</div></td><td class="actions-column"><div class="table-actions">${actions || '<span class="small-muted">—</span>'}</div></td></tr>`;
      })
      .join("");
    main.innerHTML = page(
      "Камеры и каналы",
      "Подключайте регистраторы и IP-камеры, объединяйте их в группы.",
      admin
        ? button("camera-discover", "Автопоиск", "search") +
            button("camera-add", "Добавить камеру", "plus", "btn-primary")
        : "",
      `<div class="toolbar camera-toolbar"><div class="camera-search-row"><div class="search">${icon("search")}<input id="camera-search" class="field" value="${h(state.cameraSearch)}" placeholder="${t("Поиск камер")}" aria-label="${t("Поиск камер")}"></div><div class="row-actions"><span class="muted result-count">${filtered.length} / ${state.cameras.length}</span>${admin ? button("camera-import", "Импорт", "upload") + button("camera-export", "Экспорт", "download") : ""}<button class="btn" id="camera-refresh" ${state.statusRefreshing ? "disabled" : ""}>${icon("refresh")}${t("Обновить статус")}</button></div></div><div class="camera-filters">${select("camera-group-filter", "Группа", [...state.groups.map((g) => [g.id, g.name]), ["__none", "Без группы"]], f.group)}${select(
        "camera-recorder-filter",
        "Регистратор",
        state.recorders.map((r) => [r.id, `${r.name} · ${r.ip}`]),
        f.recorder,
      )}${select(
        "camera-protocol-filter",
        "Протокол подключения",
        [
          ["dvrip", "DVRIP"],
          ["onvif", "ONVIF / RTSP"],
        ],
        f.protocol,
      )}${select(
        "camera-status-filter",
        "Статус",
        [
          ["online", "В сети"],
          ["offline", "Не в сети"],
          ["unknown", "Не проверен"],
        ],
        f.status,
      )}</div></div>${rows ? `<div class="table-wrap"><table class="catalog-table"><thead><tr>${["Название", "Подключение", "Статус", "Группы камеры", "Действия"].map((label) => `<th ${label === "Действия" ? 'class="actions-column"' : ""}>${t(label)}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table></div><p class="status-note">${t("Состояние проверяется при открытии страницы, после сохранения камеры и по кнопке «Обновить статус».")}</p>` : empty(state.cameras.length ? "Ничего не найдено" : "У вас пока нет доступных камер", "Выберите другой запрос.")}`,
    );
    main.scrollTop = scroll;
    if (admin) {
      $("#camera-add").onclick = () => openCamera();
      $("#camera-discover").onclick = openDiscovery;
      $("#camera-import").onclick = () =>
        window.VWSAdmin.importCameras(H, async () => {
          state.statusLoaded = false;
          await loadData();
          renderShell();
          renderCameras();
        });
      $("#camera-export").onclick = () => window.VWSAdmin.exportCameras(H);
    }
    $("#camera-refresh").onclick = refreshStatuses;
    $("#camera-search").oninput = (e) => {
      const pos = e.target.selectionStart;
      state.cameraSearch = e.target.value;
      renderCameras();
      main.scrollTop = 0;
      $("#camera-search").focus({ preventScroll: true });
      $("#camera-search").setSelectionRange(pos, pos);
    };
    for (const [suffix, key] of [
      ["group", "group"],
      ["recorder", "recorder"],
      ["protocol", "protocol"],
      ["status", "status"],
    ])
      $("#camera-" + suffix + "-filter").onchange = (e) => {
        f[key] = e.target.value;
        renderCameras();
        main.scrollTop = 0;
      };
    $$("[data-action]", main).forEach(
      (b) =>
        (b.onclick = async () => {
          const c = state.cameras.find((c) => c.id === b.dataset.id);
          try {
            if (b.dataset.action === "camera-edit") openCamera(c);
            if (b.dataset.action === "camera-rename") openCameraName(c);
            if (b.dataset.action === "camera-clone") {
              const result = await api(
                "/api/cameras/" + encodeURIComponent(c.id) + "/clone",
                { method: "POST", body: {} },
              );
              state.statusLoaded = false;
              await loadData();
              renderCameras();
              openCamera(state.cameras.find((x) => x.id === result.camera.id));
              toast("Копия камеры создана");
            }
            if (
              b.dataset.action === "camera-delete" &&
              confirm(t("Удалить камеру из системы?"))
            ) {
              await api("/api/cameras/" + encodeURIComponent(c.id), {
                method: "DELETE",
              });
              await loadData();
              renderCameras();
            }
          } catch (error) {
            toast(error.message, "error");
          }
        }),
    );
    if (!state.statusLoaded && !state.statusRefreshing) refreshStatuses();
  }
  function openCameraName(camera) {
    modal(
      "Изменить название",
      "",
      `<form id="camera-name-form">${formField("Название камеры", input("name", camera.name, 'required maxlength="150"'))}</form>`,
      `<span></span><button type="submit" form="camera-name-form" class="btn btn-primary">${icon("check")}${t("Сохранить")}</button>`,
    );
    $("#camera-name-form").onsubmit = async (e) => {
      e.preventDefault();
      try {
        await api("/api/cameras/" + encodeURIComponent(camera.id), {
          method: "PATCH",
          body: { name: e.target.elements.name.value },
        });
        await loadData();
        closeModal();
        renderCameras();
        toast("Сохранено");
      } catch (error) {
        toast(error.message, "error");
      }
    };
  }
  async function refreshStatuses() {
    if (state.statusRefreshing) return;
    state.statusLoaded = true;
    state.statusRefreshing = true;
    const generation = pageGeneration,
      b = $("#camera-refresh");
    if (b) b.disabled = true;
    try {
      const result = await api("/api/cameras/status", {
        method: "POST",
        body: { camera_ids: state.cameras.map((c) => c.id) },
      });
      state.statuses = result.status || {};
    } catch (error) {
      toast(error.message, "error");
    } finally {
      state.statusRefreshing = false;
      if (state.view === "cameras" && generation === pageGeneration)
        renderCameras();
      else if (b?.isConnected) b.disabled = false;
    }
  }
  function cameraCount(n) {
    if (state.language === "en")
      return `${n} ${n === 1 ? "camera" : "cameras"}`;
    const a = n % 10,
      b = n % 100;
    return `${n} ${a === 1 && b !== 11 ? "камера" : a >= 2 && a <= 4 && (b < 12 || b > 14) ? "камеры" : "камер"}`;
  }
  function groupChecks(chosen = [], name = "group_ids") {
    return state.groups.length
      ? `<div class="check-picker">${state.groups.length > 6 ? `<input class="field" type="search" data-check-search aria-label="${t("Поиск групп")}" placeholder="${t("Поиск групп")}">` : ""}<div class="check-list">${state.groups.map((g) => `<label class="check-item" data-search="${h(g.name)}"><input type="checkbox" name="${name}" value="${h(g.id)}" ${chosen.includes(g.id) ? "checked" : ""}><span>${h(g.name)}<small>${cameraCount(g.camera_ids.length)}</small></span></label>`).join("")}</div></div>`
      : `<span class="muted">${t("Нет групп")}</span>`;
  }
  function groupAccessChecks(user) {
    return `<div class="check-picker"><input class="field" type="search" data-check-search placeholder="${t("Поиск групп")}" aria-label="${t("Поиск групп")}"><div class="check-list">${
      state.groups
        .map((g) => {
          const checked = user.group_ids?.includes(g.id),
            level = user.group_access?.[g.id] || "read";
          return `<div class="check-item group-access-row" data-search="${h(g.name)}"><label><input type="checkbox" name="group_ids" value="${h(g.id)}" ${checked ? "checked" : ""}><span>${h(g.name)}</span></label><select class="select" name="access_${h(g.id)}" aria-label="${h(t("Доступ к группе") + " " + g.name)}" ${checked ? "" : "disabled"}><option value="read" ${level === "read" ? "selected" : ""}>${t("Чтение")}</option><option value="edit" ${level === "edit" ? "selected" : ""}>${t("Редактирование")}</option></select></div>`;
        })
        .join("") || `<span class="help">${t("Нет групп")}</span>`
    }</div></div>`;
  }
  function openCamera(camera = null) {
    let c = camera
      ? { ...camera, password: "" }
      : {
          id: "",
          name: "",
          protocol: "dvrip",
          ip: "",
          port: 34567,
          rtsp_port: 554,
          channel: 0,
          username: "",
          password: "",
          rtsp_path: "",
          rtsp_sub_path: "",
          group_ids: [],
        };
    const body = `<form id="camera-form" class="form-stack"><div id="camera-feedback" class="form-feedback" role="status" hidden></div><section><h3 class="form-section-title">${icon("camera")}${t("Параметры подключения")}</h3><div class="form-stack">${formField("Название камеры", input("name", c.name, 'required maxlength="150"'))}<div class="protocol-options">${[
      ["dvrip", "Аналоговые камеры (DVRIP)", "Каналы XM / XMEye"],
      ["onvif", "IP-камеры (ONVIF / RTSP)", "Стандартные IP-камеры"],
    ]
      .map(
        ([value, title, sub]) =>
          `<label class="protocol-option"><input type="radio" name="protocol" value="${value}" ${c.protocol === value ? "checked" : ""}><span><strong>${t(title)}</strong><small>${t(sub)}</small></span></label>`,
      )
      .join(
        "",
      )}</div><div class="form-grid">${formField("Адрес устройства", input("ip", c.ip, `required placeholder="${t("IP-адрес или имя узла")}"`))}${formField("Порт устройства", input("port", c.port, 'type="number" min="1" max="65535" required'))}<div id="camera-channel-field">${formField("Канал", `<select class="select" name="channel">${Array.from({ length: 128 }, (_, i) => `<option value="${i}" ${Number(c.channel) === i ? "selected" : ""}>${i + 1}</option>`).join("")}</select>`)}</div>${formField("Порт RTSP", input("rtsp_port", c.rtsp_port || 554, 'type="number" min="1" max="65535" required'))}<div class="wide form-stack" id="camera-path-field">${formField("Узел RTSP", input("rtsp_host", c.rtsp_host || "", 'maxlength="253"'), "Пусто — адрес устройства")}${formField("Путь RTSP", input("rtsp_path", c.rtsp_path || ""))}${formField("Дополнительный RTSP-путь", input("rtsp_sub_path", c.rtsp_sub_path || ""))}</div></div></div></section><section><h3 class="form-section-title">${icon("lock")}${t("Учётные данные устройства")}</h3><div class="form-grid">${formField("Логин устройства", input("username", c.username || "", 'autocomplete="off"'))}${formField("Пароль устройства", input("password", "", 'type="password" autocomplete="new-password"'), c.id ? "Пусто — сохранить прежний пароль" : "")}</div></section><section><h3 class="form-section-title">${icon("folder")}${t("Группы камеры")}</h3>${groupChecks(c.group_ids || [])}<p class="help" style="margin-top:9px">${t("Выберите одну или несколько групп.")}</p></section></form>`;
    modal(
      c.id ? "Изменить" : "Добавить камеру",
      "",
      body,
      `<span class="modal-note" id="camera-saved-note">${t("IP-адрес или имя узла")}</span><div class="row-actions">${button("camera-test", "Проверить подключение", "link")}<button type="submit" form="camera-form" class="btn btn-primary">${icon("check")}${t("Сохранить")}</button></div>`,
    );
    const form = $("#camera-form");
    function syncProtocol(change = false) {
      const protocol = $("[name=protocol]:checked", form).value;
      $("#camera-channel-field").hidden = protocol !== "dvrip";
      $("#camera-path-field").hidden = protocol === "dvrip";
      if (change)
        $("[name=port]", form).value = protocol === "dvrip" ? 34567 : 80;
    }
    $$("[name=protocol]", form).forEach(
      (r) => (r.onchange = () => syncProtocol(true)),
    );
    syncProtocol();
    const data = () => {
      const f = new FormData(form);
      return {
        id: c.id,
        name: String(f.get("name")).trim(),
        ip: String(f.get("ip")).trim(),
        protocol: f.get("protocol"),
        port: Number(f.get("port")),
        rtsp_port: Number(f.get("rtsp_port")),
        channel: Number(f.get("channel")),
        username: f.get("username"),
        password: f.get("password"),
        rtsp_host: f.get("rtsp_host"),
        rtsp_path: f.get("rtsp_path"),
        rtsp_sub_path: f.get("rtsp_sub_path"),
        group_ids: f.getAll("group_ids"),
      };
    };
    form.onsubmit = async (e) => {
      e.preventDefault();
      const b = $("[form=camera-form]");
      b.disabled = true;
      try {
        const result = await api("/api/cameras", {
          method: "POST",
          body: data(),
        });
        c = { ...c, ...result.camera };
        state.statusLoaded = false;
        await loadData();
        renderShell();
        if (state.view === "cameras") renderCameras();
        else refreshStatuses();
        if ($("#camera-saved-note"))
          $("#camera-saved-note").textContent = t(
            "Изменения сохранены. Окно можно закрыть крестиком или Esc.",
          );
        $("[name=password]", form).value = "";
        toast("Камера сохранена");
      } catch (err) {
        toast(err.message, "error");
      } finally {
        if (b.isConnected) b.disabled = false;
      }
    };
    $("#camera-test").onclick = async () => {
      if (!form.reportValidity()) return;
      const box = $("#camera-feedback"),
        b = $("#camera-test");
      box.hidden = false;
      box.className = "notice form-feedback";
      box.textContent = t("Загрузка…");
      b.disabled = true;
      try {
        const result = await api("/api/cameras/test", {
          method: "POST",
          body: data(),
        });
        box.className =
          result.ok === false
            ? "notice error form-feedback"
            : "notice form-feedback";
        box.textContent =
          result.ok === false ? result.error || "Нет соединения" : t("В сети");
      } catch (err) {
        box.className = "notice error form-feedback";
        box.textContent = err.message;
      } finally {
        b.disabled = false;
      }
    };
  }

  function renderGroups() {
    const admin = state.user.role === "admin",
      q = (state.groupSearch || "").toLowerCase();
    const list = state.groups.filter((g) => g.name.toLowerCase().includes(q));
    const cards = list
      .map((g) => {
        const cams = state.cameras.filter((c) => g.camera_ids.includes(c.id));
        return `<article class="group-card"><header class="group-card-head"><div><h2>${h(g.name)}</h2><small>${cameraCount(cams.length)}</small></div><span class="group-icon">${icon("folder")}</span></header><div class="group-preview">${Array.from({ length: 4 }, (_, i) => `<span>${icon(cams[i] ? "camera" : "grid")}</span>`).join("")}</div><div class="badge-list group-camera-badges">${cams
          .slice(0, 3)
          .map(
            (c) =>
              `<span class="badge" title="${h(c.name)}">${h(c.name)}</span>`,
          )
          .join(
            "",
          )}${cams.length > 3 ? `<span class="badge">+${cams.length - 3}</span>` : ""}</div><footer class="group-card-foot"><button class="btn btn-sm" data-watch="${h(g.id)}">${icon("play")}${t("Смотреть")}</button><div class="row-actions">${admin || g.access === "edit" ? ib("group-edit", g.id, "Изменить", "edit") : ""}${admin ? ib("group-delete", g.id, "Удалить", "trash") : ""}</div></footer></article>`;
      })
      .join("");
    $("#main-content").innerHTML = page(
      "Группы камер",
      "Организуйте камеры по расположению и назначайте доступ пользователям.",
      admin
        ? button("groups-import", "Импорт групп", "upload") +
            button("groups-export", "Экспорт групп", "download") +
            button("group-add", "Создать группу", "plus", "btn-primary")
        : "",
      `<div class="toolbar"><div class="search">${icon("search")}<input class="field" type="search" id="group-search" value="${h(state.groupSearch || "")}" placeholder="${t("Поиск групп")}" aria-label="${t("Поиск групп")}"></div><span class="muted">${list.length} / ${state.groups.length}</span></div>${cards ? `<div class="group-grid">${cards}</div>` : empty("Нет групп", admin ? "Организуйте камеры по расположению и назначайте доступ пользователям." : "Нет назначенных групп")}`,
    );
    $("#group-search").oninput = (e) => {
      const pos = e.target.selectionStart;
      state.groupSearch = e.target.value;
      renderGroups();
      $("#group-search").focus({ preventScroll: true });
      $("#group-search").setSelectionRange(pos, pos);
    };
    $$("[data-watch]").forEach(
      (b) => (b.onclick = () => showView("live", { groupId: b.dataset.watch })),
    );
    if (admin) {
      $("#group-add").onclick = () => openGroup();
      $("#groups-export").onclick = () =>
        downloadJSON(
          { format: "vwshub.groups", version: 1, groups: state.groups },
          "vwshub-groups.json",
        );
      $("#groups-import").onclick = () =>
        pickJSON(async (data) => {
          await api("/api/groups/import", { method: "POST", body: data });
          await loadData();
          renderGroups();
          toast("Сохранено");
        });
    }
    $$("[data-action]", $("#main-content")).forEach(
      (b) =>
        (b.onclick = async () => {
          const group = state.groups.find((g) => g.id === b.dataset.id);
          try {
            if (b.dataset.action === "group-edit") openGroup(group);
            if (
              b.dataset.action === "group-delete" &&
              confirm(t("Удалить группу? Камеры останутся в системе."))
            ) {
              await api("/api/groups/" + encodeURIComponent(group.id), {
                method: "DELETE",
              });
              await loadData();
              renderGroups();
            }
          } catch (error) {
            toast(error.message, "error");
          }
        }),
    );
  }
  function openGroup(group = null) {
    const g = group || { id: "", name: "", camera_ids: [] },
      admin = state.user.role === "admin";
    const cameras = admin
      ? state.cameras
      : state.cameras.filter((c) => g.camera_ids.includes(c.id));
    modal(
      group ? "Изменить" : "Создать группу",
      "",
      `<form id="group-form" class="form-stack">${formField("Название группы", input("name", g.name, 'required maxlength="100"'))}<p class="help">${t("Снятие флажка убирает камеру только из этой группы. Подключение и остальные группы сохраняются.")}</p><div class="check-picker"><input type="search" class="field" data-check-search placeholder="${t("Поиск камер")}" aria-label="${t("Поиск камер")}"><div class="check-list">${cameras.map((c) => `<div class="check-item group-camera-row" data-search="${h(c.name + " " + c.ip)}"><label><input type="checkbox" name="camera_ids" value="${h(c.id)}" ${g.camera_ids.includes(c.id) ? "checked" : ""}><span>${h(c.ip)}${c.protocol === "dvrip" ? ` · CH ${Number(c.channel || 0) + 1}` : ""}</span></label><input class="field" name="camera_name_${h(c.id)}" value="${h(c.name)}" required maxlength="150" aria-label="${h(t("Название камеры") + " " + c.name)}"></div>`).join("") || `<span class="muted">${t("У вас пока нет доступных камер")}</span>`}</div></div></form>`,
      `<span></span><button type="submit" form="group-form" class="btn btn-primary">${icon("check")}${t("Сохранить")}</button>`,
    );
    $("#group-form").onsubmit = async (e) => {
      e.preventDefault();
      const f = new FormData(e.target),
        members = f.getAll("camera_ids"),
        names = {};
      for (const c of cameras)
        if (members.includes(c.id) && f.get("camera_name_" + c.id) !== c.name)
          names[c.id] = f.get("camera_name_" + c.id);
      const button = document.querySelector('[form="group-form"]');
      button.disabled = true;
      try {
        await api("/api/groups", {
          method: "POST",
          body: {
            id: g.id,
            name: f.get("name"),
            camera_ids: members,
            camera_names: names,
          },
        });
        await loadData();
        closeModal();
        renderGroups();
        toast("Сохранено");
      } catch (error) {
        toast(error.message, "error");
        if (button.isConnected) button.disabled = false;
      }
    };
  }
  function renderUsers() {
    const rows = state.users
      .map(
        (u) =>
          `<tr><td><div class="cell-name">${avatar(u)}<div><strong>${h(u.alias || u.username)}</strong><small>${t("Логин")}: ${h(u.username)}</small></div></div></td><td><span class="badge ${u.role === "admin" ? "blue" : ""}">${t(u.role === "admin" ? "Администратор" : "Пользователь")}</span></td><td><div class="badge-list">${u.role === "admin" ? '<span class="small-muted">Все группы</span>' : (u.group_ids || []).map((id) => `<span class="badge">${h(state.groups.find((g) => g.id === id)?.name || id)} · ${t(u.group_access?.[id] === "edit" ? "Редактирование" : "Чтение")}</span>`).join("") || '<span class="small-muted">—</span>'}</div></td><td><span class="badge ${u.role === "admin" || u.archive_access ? "green" : ""}">${t(u.role === "admin" || u.archive_access ? "Разрешён" : "Запрещён")}</span></td><td><div class="table-actions">${ib("user-edit", u.username, "Изменить", "edit")}${u.username !== state.user.username ? ib("user-delete", u.username, "Удалить", "trash") : ""}</div></td></tr>`,
      )
      .join("");
    $("#main-content").innerHTML = page(
      "Доступ и учётные записи",
      "Назначайте группы и отдельно разрешайте просмотр архива.",
      button("user-add", "Добавить пользователя", "plus", "btn-primary"),
      `<div class="table-wrap"><table><thead><tr>${["Псевдоним", "Роль", "Доступные группы", "Доступ к архиву", "Действия"].map((x) => `<th>${t(x)}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table></div>`,
    );
    $("#user-add").onclick = () => openUser();
    $$("[data-action]").forEach(
      (b) =>
        (b.onclick = async () => {
          const u = state.users.find((x) => x.username === b.dataset.id);
          if (b.dataset.action === "user-edit") openUser(u);
          else if (confirm(t("Удалить пользователя?"))) {
            try {
              await api("/api/users/" + encodeURIComponent(u.username), {
                method: "DELETE",
              });
              await loadData();
              renderUsers();
            } catch (e) {
              toast(e.message, "error");
            }
          }
        }),
    );
  }
  function openUser(user = null) {
    const u = user || {
      username: "",
      alias: "",
      role: "viewer",
      avatar: "",
      group_ids: [],
      archive_access: false,
      language: state.language,
    };
    let image = u.avatar || "";
    modal(
      user ? "Изменить" : "Добавить пользователя",
      "",
      `<form id="user-form" class="form-stack"><div class="upload-preview"><span id="user-image">${avatar(u)}</span><div>${button("user-image-add", "Выбрать изображение", "upload")}<input type="file" id="user-image-file" class="file-hidden" accept="image/png,image/jpeg,image/webp"></div></div><div class="form-grid">${formField("Логин", input("username", u.username, `required maxlength="80" ${user ? "readonly" : ""}`))}${formField("Псевдоним", input("alias", u.alias || "", 'maxlength="100"'))}${formField("Роль", `<select class="select" name="role"><option value="viewer" ${u.role === "viewer" ? "selected" : ""}>${t("Пользователь")}</option><option value="admin" ${u.role === "admin" ? "selected" : ""}>${t("Администратор")}</option></select>`)}${formField("Новый пароль", input("password", "", 'type="password" autocomplete="new-password" minlength="10" ' + (user ? "" : "required")))}${formField("Язык", `<select class="select" name="language"><option value="ru" ${u.language === "ru" ? "selected" : ""}>Русский</option><option value="en" ${u.language === "en" ? "selected" : ""}>English</option></select>`)}</div><div id="viewer-permissions" class="form-stack"><div class="form-field"><label>${t("Доступные группы")}</label>${groupAccessChecks(u)}<small>${t("Камеры доступны только из назначенных групп.")}</small></div><label class="check-item"><input type="checkbox" name="archive_access" ${u.archive_access ? "checked" : ""}><span>${t("Разрешить архив")}</span></label></div></form>`,
      `<span class="modal-note">${t("Доступ к архиву")}</span><button class="btn btn-primary" type="submit" form="user-form">${icon("check")}${t("Сохранить")}</button>`,
    );
    const f = $("#user-form"),
      sync = () =>
        ($("#viewer-permissions").hidden =
          $("[name=role]", f).value === "admin");
    $$(".group-access-row", f).forEach((row) => {
      $("input[type=checkbox]", row).onchange = (e) => {
        $("select", row).disabled = !e.target.checked;
      };
    });
    $("[name=role]", f).onchange = sync;
    sync();
    $("#user-image-add").onclick = () => $("#user-image-file").click();
    $("#user-image-file").onchange = async (e) => {
      try {
        image = await readImage(e.target.files[0], 128);
        $("#user-image").innerHTML = avatar({ ...u, avatar: image });
      } catch (err) {
        toast(err.message, "error");
      }
    };
    f.onsubmit = async (e) => {
      e.preventDefault();
      const data = Object.fromEntries(new FormData(f));
      data.group_ids = new FormData(f).getAll("group_ids");
      data.group_access = Object.fromEntries(
        data.group_ids.map((id) => [
          id,
          f.elements.namedItem("access_" + id).value,
        ]),
      );
      data.archive_access = $("[name=archive_access]", f).checked;
      data.avatar = image;
      try {
        await api(
          user ? "/api/users/" + encodeURIComponent(u.username) : "/api/users",
          { method: user ? "PUT" : "POST", body: data },
        );
        await loadData();
        closeModal();
        renderUsers();
        if (u.username === state.user.username) {
          state.user = await api("/api/profile");
          renderShell();
        }
        toast("Пользователь сохранён");
      } catch (err) {
        toast(err.message, "error");
      }
    };
  }

  async function renderLogs() {
    const generation = pageGeneration,
      kind = state.logKind || "audit",
      hardware = kind === "hardware";
    const data = await api(hardware ? "/api/hardware/logs" : "/api/logs");
    if (generation !== pageGeneration) return;
    const logs = data.logs || [];
    const rows = logs
      .map((entry) => {
        const detail = hardware
          ? { device: entry.device, ...entry.detail }
          : entry.detail || "";
        return `<tr><td class="log-time">${h(entry.time || entry.timestamp || entry.at || "")}</td><td>${h(hardware ? entry.level || "info" : entry.actor || entry.user || "system")}</td><td><span class="badge ${entry.level === "error" ? "red" : ""}">${h(entry.action || entry.event || "")}</span></td><td class="log-detail">${h(typeof detail === "object" ? JSON.stringify(detail) : detail)}</td></tr>`;
      })
      .join("");
    $("#main-content").innerHTML = page(
      "Системный журнал",
      "Действия пользователей и диагностика оборудования без паролей и видеоданных.",
      button("logs-refresh", "Обновить", "refresh") +
        (hardware
          ? button("logs-export", "Скачать диагностику", "download")
          : "") +
        button("logs-clear", "Очистить", "trash", "btn-danger"),
      `<div class="toolbar"><div class="segmented"><button class="${hardware ? "" : "active"}" data-log-kind="audit">${t("Действия")}</button><button class="${hardware ? "active" : ""}" data-log-kind="hardware">${t("Оборудование")}</button></div><span class="muted">${logs.length} ${t("последних событий")}</span></div><div class="table-wrap"><table><thead><tr>${["Время", hardware ? "Уровень" : "Пользователь", "Событие", "Подробности"].map((label) => `<th>${t(label)}</th>`).join("")}</tr></thead><tbody>${rows || '<tr><td colspan="4">—</td></tr>'}</tbody></table></div>`,
    );
    const refresh = () =>
      renderLogs().catch((error) => toast(error.message, "error"));
    $("#logs-refresh").onclick = refresh;
    $("#logs-clear").onclick = () =>
      window.VWSAdmin.clearLogs(H, kind, refresh);
    if (hardware)
      $("#logs-export").onclick = () =>
        window.VWSAdmin.download("/api/hardware/logs/export");
    $$("[data-log-kind]").forEach(
      (b) =>
        (b.onclick = () => {
          state.logKind = b.dataset.logKind;
          refresh();
        }),
    );
  }
  function renderCustomize() {
    const b = state.branding;
    let logo = b.logo || "",
      favicon = b.favicon || "";
    $("#main-content").innerHTML = page(
      "Название и оформление",
      "Оформление применяется ко всем пользователям и странице входа.",
      `<button type="submit" form="brand-form" class="btn btn-primary">${icon("check")}${t("Сохранить")}</button>`,
      `<form id="brand-form" class="settings-grid"><div class="panel"><div class="panel-head"><h2 class="panel-title">${t("Кастомизация")}</h2>${icon("palette")}</div><div class="panel-body form-stack"><div class="form-grid">${formField("Название сайта", input("name", b.name, 'required maxlength="80"'))}${formField("Подпись", input("subtitle", b.subtitle, 'maxlength="80"'))}</div><div class="form-grid">${formField("Названия регистраторов", `<select class="select" name="recorder_labels"><option value="ip" ${b.recorder_labels !== "name" ? "selected" : ""}>IP</option><option value="name" ${b.recorder_labels === "name" ? "selected" : ""}>${t("Имя устройства")}</option></select>`)}${formField("Плотность интерфейса", `<select class="select" name="density"><option value="comfortable" ${b.density !== "compact" ? "selected" : ""}>${t("Комфортная")}</option><option value="compact" ${b.density === "compact" ? "selected" : ""}>${t("Компактная")}</option></select>`)}${formField("Углы элементов", `<select class="select" name="corners"><option value="rounded" ${b.corners !== "square" ? "selected" : ""}>${t("Скруглённые")}</option><option value="square" ${b.corners === "square" ? "selected" : ""}>${t("Прямые")}</option></select>`)}${formField("Отступ видеостены, px", input("wall_gap", b.wall_gap ?? 3, 'type="number" min="0" max="12"'))}</div><label class="check-item"><input type="checkbox" name="show_clock" ${b.show_clock !== false ? "checked" : ""}><span>${t("Показывать часы на видеостене")}</span></label>${formField("Основной цвет", `<div class="row-actions"><input name="accent" type="color" class="field" style="width:70px;padding:5px" value="${h(b.accent)}"><div class="color-swatches">${["#526cf5", "#13a08a", "#e58c35", "#a363e8", "#d85570", "#2877bb"].map((color) => `<button type="button" data-color="${color}" style="background:${color}" aria-label="${color}"></button>`).join("")}</div></div>`)}<label class="check-item"><input type="checkbox" name="motion" ${b.motion !== false ? "checked" : ""}><span>${t("Включить анимацию")}</span></label></div><div class="modal-foot"><span class="modal-note">VWSHub 0.8</span><button class="btn btn-primary" type="submit">${icon("check")}${t("Сохранить")}</button></div></div><div class="form-stack"><div class="panel"><div class="panel-head"><h2 class="panel-title">${t("Логотип")}</h2></div><div class="panel-body"><div class="upload-preview"><span class="brand-mark" id="logo-preview" style="width:76px;height:76px">${logo ? `<img src="${h(logo)}" alt="">` : icon("brand")}</span><div class="form-stack">${button("logo-upload", "Выбрать изображение", "upload")}${button("logo-clear", "Удалить изображение", "close")}</div></div></div></div><div class="panel"><div class="panel-head"><h2 class="panel-title">${t("Фавикон")}</h2></div><div class="panel-body"><div class="upload-preview"><span id="favicon-preview" class="avatar">${favicon ? `<img src="${h(favicon)}" alt="">` : "V"}</span><div class="form-stack">${button("favicon-upload", "Выбрать изображение", "upload")}${button("favicon-clear", "Удалить изображение", "close")}</div></div></div></div></div></form><input id="branding-file" class="file-hidden" type="file" accept="image/png,image/jpeg,image/webp">`,
    );
    let target = "logo";
    $("#logo-upload").onclick = () => {
      target = "logo";
      $("#branding-file").click();
    };
    $("#favicon-upload").onclick = () => {
      target = "favicon";
      $("#branding-file").click();
    };
    $("#logo-clear").onclick = () => {
      logo = "";
      $("#logo-preview").innerHTML = icon("brand");
    };
    $("#favicon-clear").onclick = () => {
      favicon = "";
      $("#favicon-preview").textContent = "V";
    };
    $("#branding-file").onchange = async (e) => {
      try {
        const data = await readImage(
          e.target.files[0],
          target === "logo" ? 256 : 64,
        );
        if (target === "logo") {
          logo = data;
          $("#logo-preview").innerHTML = `<img src="${h(data)}" alt="">`;
        } else {
          favicon = data;
          $("#favicon-preview").innerHTML = `<img src="${h(data)}" alt="">`;
        }
      } catch (err) {
        toast(err.message, "error");
      }
    };
    $$("[data-color]").forEach(
      (n) =>
        (n.onclick = () =>
          ($("[name=accent]", $("#brand-form")).value = n.dataset.color)),
    );
    $("#brand-form").onsubmit = async (e) => {
      e.preventDefault();
      const f = new FormData(e.target);
      try {
        const result = await api("/api/branding", {
          method: "POST",
          body: {
            name: f.get("name"),
            subtitle: f.get("subtitle"),
            accent: f.get("accent"),
            motion: $("[name=motion]", e.target).checked,
            recorder_labels: f.get("recorder_labels"),
            density: f.get("density"),
            corners: f.get("corners"),
            wall_gap: Number(f.get("wall_gap")),
            show_clock: $("[name=show_clock]", e.target).checked,
            logo,
            favicon,
          },
        });
        state.branding = result.branding;
        applyBrand();
        toast("Оформление сохранено");
      } catch (err) {
        toast(err.message, "error");
      }
    };
  }
  async function renderSettings() {
    const gen = pageGeneration;
    $("#main-content").innerHTML =
      '<div class="loading-page"><span class="spin"></span></div>';
    const data = await api("/api/settings");
    if (gen !== pageGeneration) return;
    state.settings = data;
    const s = data.settings,
      r = s.resources || {},
      m = data.metrics || {},
      fmt = (v) =>
        v === null || v === undefined ? "—" : Number(v).toFixed(1) + "%",
      gb = (n) => (Number(n || 0) / 1073741824).toFixed(1) + " GB";
    $("#main-content").innerHTML = page(
      "Сервер и ресурсы",
      "Настройте нагрузку, форматы и общие параметры сервера.",
      button("settings-refresh", "Обновить", "refresh") +
        `<button type="submit" form="settings-form" class="btn btn-primary">${icon("check")}${t("Применить настройки")}</button>`,
      `<div class="metric-grid"><div class="metric"><span>${t("Процессор")}</span><strong>${fmt(m.cpu_percent)}</strong><div class="meter"><i style="width:${Number(m.cpu_percent) || 0}%"></i></div></div><div class="metric"><span>${t("Оперативная память")}</span><strong>${fmt(m.memory_percent)}</strong><div class="meter"><i style="width:${Number(m.memory_percent) || 0}%"></i></div></div><div class="metric"><span>${t("Свободно на диске")}</span><strong>${gb(m.disk?.free)}</strong><span>${gb(m.disk?.total)}</span></div></div><div class="settings-grid"><form id="settings-form" class="form-stack"><div class="panel"><div class="panel-head"><h2 class="panel-title">${t("Общие параметры")}</h2></div><div class="panel-body form-grid">${formField("Часовой пояс", input("timezone", s.timezone, 'required list="timezones"') + '<datalist id="timezones"><option>Asia/Omsk</option><option>Europe/Moscow</option><option>UTC</option><option>Europe/Berlin</option></datalist>')}${formField("Язык по умолчанию", `<select class="select" name="language"><option value="ru" ${s.language === "ru" ? "selected" : ""}>Русский</option><option value="en" ${s.language === "en" ? "selected" : ""}>English</option></select>`)}${formField("Формат снимков", `<select class="select" name="snapshot_format">${["jpeg", "png", "webp"].map((x) => `<option value="${x}" ${s.snapshot_format === x ? "selected" : ""}>${x.toUpperCase()}</option>`).join("")}</select>`)}${formField("Формат архива", '<select class="select" name="archive_format"><option value="mp4">MP4</option></select>', "Сохранять видео в MP4 без лишнего перекодирования.")}</div></div><div class="panel"><div class="panel-head"><h2 class="panel-title">${t("Профиль ресурсов")}</h2></div><div class="panel-body form-stack">${formField(
        "Профиль ресурсов",
        `<select class="select" name="resource_profile">${[
          ["standard", "Стандартный"],
          ["maximum", "Максимальный"],
          ["custom", "Свой"],
        ]
          .map(
            ([value, title]) =>
              `<option value="${value}" ${r.profile === value ? "selected" : ""}>${t(title)}</option>`,
          )
          .join("")}</select>`,
      )}<div class="notice">${t("Максимальный профиль увеличивает допустимое число потоков, но не производительность оборудования.")}</div><div class="form-grid" id="resource-fields">${[
        ["max_live_streams", "Одновременных live-потоков", 1, 128],
        ["max_archive_streams", "Одновременных архивов", 1, 16],
        ["archive_buffer_mb", "Буфер архива, МБ", 2, 128],
        ["archive_idle_seconds", "Ожидание сети, с", 30, 600],
        ["ffmpeg_threads", "Потоков FFmpeg", 0, 32],
      ]
        .map(([key, title, min, max]) =>
          formField(
            title,
            input(
              key,
              r[key],
              `type="number" min="${min}" max="${max}" required`,
            ),
          ),
        )
        .join(
          "",
        )}</div><label class="check-item"><input type="checkbox" name="hardware_diagnostics" ${s.diagnostics?.enabled !== false ? "checked" : ""}><span>${t("Диагностика оборудования")}<small>${t("Локальные журналы подключений и ошибок без паролей. Ротация до 8 МБ.")}</small></span></label></div><div class="modal-foot"><span></span><button type="submit" class="btn btn-primary">${icon("check")}${t("Применить настройки")}</button></div></div></form><div class="form-stack"><div class="panel"><div class="panel-head"><h2 class="panel-title">${t("Информация о сервере")}</h2>${icon("server")}</div><div class="panel-body"><dl class="kv"><div><dt>${t("Версия")}</dt><dd>VWSHub 0.8</dd></div><div><dt>${t("Разработчик")}</dt><dd>sedukindv</dd></div><div><dt>GitHub</dt><dd><a href="https://github.com/sedukindv/VWSHub" target="_blank" rel="noopener">sedukindv/VWSHub ↗</a></dd></div><div><dt>${t("Время работы")}</dt><dd>${Math.floor(Number(m.uptime_seconds || 0) / 3600)}h ${Math.floor((Number(m.uptime_seconds || 0) % 3600) / 60)}m</dd></div><div><dt>RAM / process</dt><dd>${m.process_memory_mb ?? "—"} MB</dd></div></dl></div></div><div class="panel"><div class="panel-head"><h2 class="panel-title">${t("Обслуживание сервера")}</h2></div><div class="panel-body form-stack"><p class="help">${t("Backup содержит учётные записи, зашифрованные пароли устройств и ключи. Храните его в защищённом месте.")}</p>${button("server-backup", "Скачать backup", "download")}${button("server-restore", "Восстановить backup", "upload")}${data.capabilities?.restart ? button("server-restart", "Перезапустить сервер", "refresh") : ""}</div></div></div></div>`,
    );
    $("#settings-refresh").onclick = () =>
      renderSettings().catch((e) => toast(e.message, "error"));
    const form = $("#settings-form"),
      sync = () => {
        const profile = $("[name=resource_profile]", form).value,
          preset = {
            standard: [16, 4, 16, 180, 2],
            maximum: [64, 12, 64, 300, 0],
          }[profile];
        $$("input", $("#resource-fields")).forEach((n, i) => {
          n.disabled = profile !== "custom";
          if (preset) n.value = preset[i];
        });
      };
    $("[name=resource_profile]", form).onchange = sync;
    sync();
    form.onsubmit = async (e) => {
      e.preventDefault();
      const f = new FormData(form),
        resources = { profile: f.get("resource_profile") };
      for (const key of [
        "max_live_streams",
        "max_archive_streams",
        "archive_buffer_mb",
        "archive_idle_seconds",
        "ffmpeg_threads",
      ])
        if (f.has(key)) resources[key] = Number(f.get(key));
      try {
        const result = await api("/api/settings", {
          method: "POST",
          body: {
            timezone: f.get("timezone"),
            language: f.get("language"),
            snapshot_format: f.get("snapshot_format"),
            archive_format: f.get("archive_format"),
            resources,
            diagnostics: {
              enabled: $("[name=hardware_diagnostics]", form).checked,
            },
          },
        });
        state.public_settings = {
          ...state.public_settings,
          ...result.settings,
          max_live_streams:result.settings.resources.max_live_streams,
          resource_profile:result.settings.resources.profile,
        };
        toast("Настройки сохранены");
        renderSettings();
      } catch (err) {
        toast(err.message, "error");
      }
    };
    $("#server-restore").onclick = () => window.VWSAdmin.restore(H);
    $("#server-backup").onclick = () => {
      if (
        confirm(
          t(
            "Backup содержит учётные записи, зашифрованные пароли устройств и ключи. Храните его в защищённом месте.",
          ),
        )
      )
        location.href = "/api/backup";
    };
    $("#server-restart")?.addEventListener("click", async () => {
      if (confirm(t("Перезапустить сервер") + "?"))
        try {
          await api("/api/server/restart", {
            method: "POST",
            body: { confirm: true },
          });
          toast("Сохранено");
        } catch (e) {
          toast(e.message, "error");
        }
    });
  }
  function openProfile() {
    const u = state.user;
    let image = u.avatar || "";
    modal(
      "Мой профиль",
      "Изображение и псевдоним отображаются вместо логина.",
      `<form id="profile-form" class="form-stack"><div class="upload-preview"><span id="profile-image">${avatar(u)}</span><div class="form-stack">${button("profile-image-add", "Выбрать изображение", "upload")}${button("profile-image-remove", "Удалить изображение", "close")}</div><input class="file-hidden" id="profile-image-file" type="file" accept="image/png,image/jpeg,image/webp"></div><div class="form-grid">${formField("Логин", input("login", u.username, "disabled"))}${formField("Псевдоним", input("alias", u.alias || u.username, 'maxlength="100"'))}${formField("Язык", `<select class="select" name="language"><option value="ru" ${state.language === "ru" ? "selected" : ""}>Русский</option><option value="en" ${state.language === "en" ? "selected" : ""}>English</option></select>`)}${formField(
        "Тема",
        `<select class="select" name="theme">${[
          ["auto", "Автоматическая"],
          ["light", "Светлая"],
          ["dark", "Тёмная"],
        ]
          .map(
            ([value, title]) =>
              `<option value="${value}" ${u.theme === value ? "selected" : ""}>${t(title)}</option>`,
          )
          .join("")}</select>`,
      )}${formField("Текущий пароль", input("current_password", "", 'type="password" autocomplete="current-password"'))}${formField("Новый пароль профиля", input("password", "", 'type="password" autocomplete="new-password" minlength="10"'))}</div></form>`,
      `<span class="modal-note">${t(u.role === "admin" ? "Администратор" : "Пользователь")}</span><button type="submit" form="profile-form" class="btn btn-primary">${icon("check")}${t("Сохранить")}</button>`,
    );
    $("#profile-image-add").onclick = () => $("#profile-image-file").click();
    $("#profile-image-remove").onclick = () => {
      image = "";
      $("#profile-image").innerHTML = avatar({ ...u, avatar: "" });
    };
    $("#profile-image-file").onchange = async (e) => {
      try {
        image = await readImage(e.target.files[0], 128);
        $("#profile-image").innerHTML = avatar({ ...u, avatar: image });
      } catch (err) {
        toast(err.message, "error");
      }
    };
    $("#profile-form").onsubmit = async (e) => {
      e.preventDefault();
      const f = Object.fromEntries(new FormData(e.target));
      f.avatar = image;
      try {
        const result = await api("/api/profile", { method: "POST", body: f });
        state.user = result.user;
        state.language = result.user.language;
        try {
          localStorage.setItem("vwshub.language", state.language);
        } catch (_) {}
        closeModal();
        renderShell();
        showView(state.view);
        toast("Сохранено");
      } catch (err) {
        toast(err.message, "error");
      }
    };
  }
  function openDiscovery() {
    modal(
      "Автопоиск",
      "Поиск выполняется только по вашему запросу.",
      `<div class="form-stack">${formField("Локальная подсеть для DVRIP (необязательно)", input("subnet", "", 'id="discovery-subnet" placeholder="CIDR /24"'))}${button("discovery-start", "Найти устройства", "search", "btn-primary")}<div id="discovery-results"></div></div>`,
    );
    $("#discovery-start").onclick = async () => {
      const b = $("#discovery-start"),
        container = $("#discovery-results");
      b.disabled = true;
      container.innerHTML =
        '<div class="card-loading"><span class="spin"></span></div>';
      try {
        const result = await api("/api/discovery", {
          method: "POST",
          body: { timeout: 3, subnet: $("#discovery-subnet").value.trim() },
        });
        if (!container.isConnected) return;
        container.innerHTML = `${(result.warnings || []).map((x) => `<div class="notice warning">${h(x)}</div>`).join("")}<div class="form-stack" style="margin-top:14px">${result.devices.map((d, i) => `<div class="check-item"><span style="flex:1"><strong>${h(d.ip)}:${h(d.port)}</strong><small>${h(d.detected_by || d.protocol)}</small></span><button class="btn btn-sm" data-discovered="${i}">${t("Добавить")}</button></div>`).join("") || `<p class="muted">${t("Ничего не найдено")}</p>`}</div>`;
        $$("[data-discovered]", container).forEach(
          (n) =>
            (n.onclick = () =>
              openCamera({
                ...result.devices[Number(n.dataset.discovered)],
                username: "",
                password: "",
                group_ids: [],
                channel: 0,
              })),
        );
      } catch (e) {
        if (container.isConnected)
          container.innerHTML = `<div class="notice error">${h(e.message)}</div>`;
      } finally {
        if (b.isConnected) b.disabled = false;
      }
    };
  }
  const H = {
    api,
    t,
    h,
    icon,
    toast,
    modal,
    closeModal,
    downloadJSON,
    pickJSON,
    state,
    formField,
    groupChecks,
    reload: loadData,
    input,
    readImage,
    showView,
  };
  window.VWSHub = H;
  $("#sidebar-collapse").onclick = () => {
    document.body.classList.toggle("is-collapsed");
    try {
      localStorage.setItem(
        "vwshub.sidebar",
        document.body.classList.contains("is-collapsed")
          ? "collapsed"
          : "expanded",
      );
    } catch (_) {}
    renderShell();
  };
  $("#mobile-menu").onclick = () => document.body.classList.toggle("menu-open");
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeModal();
      document.body.classList.remove("menu-open");
    }
    if (e.key === "Tab" && $("#modal-root .modal")) {
      const nodes = $$(
        "button:not(:disabled),input:not(:disabled):not([type=hidden]),select:not(:disabled),textarea:not(:disabled),a[href]",
        $("#modal-root"),
      ).filter((el) => el.getClientRects().length);
      if (nodes.length) {
        if (e.shiftKey && document.activeElement === nodes[0]) {
          e.preventDefault();
          nodes.at(-1).focus();
        } else if (!e.shiftKey && document.activeElement === nodes.at(-1)) {
          e.preventDefault();
          nodes[0].focus();
        }
      }
    }
  });
  async function init() {
    try {
      if (localStorage.getItem("vwshub.sidebar") === "collapsed")
        document.body.classList.add("is-collapsed");
    } catch (_) {}
    renderShell();
    $("#main-content").innerHTML =
      '<div class="loading-page"><span class="spin"></span></div>';
    try {
      const current = await api("/api/bootstrap");
      Object.assign(state, current);
      state.language = state.user.language || state.public_settings.language;
      window.VWSHUB_BOOTSTRAP = current;
      await loadData();
      renderShell();
      showView("live");
    } catch (e) {
      $("#main-content").innerHTML = empty("Ничего не найдено", e.message);
      toast(e.message, "error");
    }
  }
  init();
})();
