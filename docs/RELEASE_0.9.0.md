# WVW 0.9.0 — итоговый отчёт

## 1. Реализованные функции

Web Video Workspace объединяет существующие просмотр, архив, устройства, пространства и зоны с обновлёнными темами, хранением изображений, локализацией, административным управлением оборудованием, отдельным звуком Live и поддержкой HEVC. Рабочие подключения, ID, ключи, права и внутренние имена `VWSHUB_*` сохранены. Пользовательские данные не входят в исходники или пакет релиза.

## 2–3. Изменённые и новые файлы

Точный список относительно исходного commit `f97323d` приведён в приложении ниже. `BUILD_INFO.json` содержит SHA-256 каждого публичного файла пакета; сам manifest проверяется отдельно. В поставку входят исходники, закреплённые клиентские ресурсы, тесты и документация. Снимки визуальных тестов используют только синтетические данные.

## 4. Настройки физических устройств

Каталог «Устройства» отделён от административного «Управления оборудованием». Аппаратные настройки сгруппированы по смыслу: обзор, система, время/NTP, сеть, каналы/видео, запись, названия/наложения, хранилище, пользователи и обслуживание. Сетевые сведения в обзоре расположены перед временем и обслуживанием.

Доступные операции определяются протоколом, возможностями и правами устройства. Изменяются известные параметры с сохранением неизвестных полей и соседних каналов; ревизия защищает от устаревшей формы. Результат подтверждается повторным чтением. «Команда принята» при потере связи или несовпадении результата не превращается в «Сохранено». Неподдерживаемые поля не имитируются.

## 5. Звук Live

FFprobe проверяет аудиодорожку конкретного RTSP-профиля. После подтверждения пользователь включает звук нажатием; отдельный AAC-HLS поток не меняет видео. Смена камеры, профиля, раздела, скрытие вкладки, ошибка и отзыв доступа останавливают поток. Звук архива проверяется отдельно; переговоры с камерой не реализованы.

## 6. Архив

Плеер, предупреждения, состояния загрузки/ошибки/пустого результата и кнопки используют тему сайта. При ожидании следующей записи сохраняется последний кадр, доступны увеличение и перемещение изображения. Выбор пространства/зоны фильтрует камеры; скачивание использует выделенный отрезок шкалы. Слайдер переходит из разрыва к ближайшей записи, разрывы и позиция имеют отдельные цвета. Скорости и метки времени не обрезаются на узких экранах.

## 7. Темы и кастомизация

Светлая и тёмная темы имеют независимые палитры из 13 основных токенов. Основные цвета выделены круглыми образцами, дополнительные раскрываются отдельно. Предпросмотр показывает миниатюру рабочего интерфейса с камерой, выбором, кнопками и статусом. Цвет текста акцентной кнопки выбирается вручную или через «Авто»; сохранение проверяет контраст. Черновик не теряется из-за фонового обновления каталога или сохранения другой формы. Настройки плотности и углов удалены из меню согласно ТЗ; прежние ключи сохранены для совместимости.

## 8. Изображения и миграция

Логотип, favicon и аватары проверяются и хранятся на сервере как PNG/JPEG/WebP в `data/images/<sha256>.<ext>`. В JSON остаются ссылки `/images/...`. Логотип и favicon независимы; загруженное изображение имеет приоритет над библиотечным значком и стандартным логотипом. Старые Data URI мигрируют после защитной копии, повторный запуск безопасен. Backup и восстановление включают изображения; восстановление старых inline-данных, JSON, ключей и секрета сеанса использует одну транзакцию с журналом отката.

## 9. Фактические форматы архива

| Формат | Реальный результат |
| --- | --- |
| MP4 | Фрагментированный MP4 с копированием исходного видео |
| AVI | RIFF AVI, перекодирование в MPEG-4 Part 2 / YUV420P; поток не содержит окончательного индекса перемотки |
| Исходный поток | Подтверждённый Annex B H.264/HEVC (`.h264`/`.h265`), очищенный от фирменной обёртки |

Экспорт содержит только видео. Исходный поток не является побайтовой копией фирменного файла и не содержит контейнерных временных меток. H265X и неподтверждённые кодеки не выдаются под ложным расширением.

## 10. Локализация

Поставляются 28 полных по набору ключей локальных словарей: ru, en, ar, be, bn, cs, da, nl, fa, fi, fr, de, hi, hu, id, it, ja, ko, zh-CN, nb-NO, pl, pt-BR, es, sv, zh-TW, tr, uk, vi. В каждом 1463 ключа; проверены аргументы, даты/числа, множественные формы, английский fallback и RTL. Переводы автоматические с правками; редактура носителями всех языков не проводилась.

## 11. Перезапуск

Физический регистратор перезапускается отдельной административной командой после подтверждения точного имени. Повтор заблокирован на 60 секунд; подтверждение отправки отделено от проверки возвращения устройства. Перезапуск приложения находится в серверных настройках и доступен только при явно заданном оператором массиве `VWSHUB_RESTART_COMMAND`, без shell.

## 12–13. Переход на WVW и GitHub

Публичное название и версия заменены на Web Video Workspace / WVW 0.9.0. По последнему указанию пользователя стандартными изображениями стали предоставленные `logo.png` и `favicon.png`; подготовленные SVG оставлены для совместимости. Репозиторий переименован в `sedukindv/WVW`. Форматы `vwshub.*`, сервисные пути и ID не переименованы. Стандартное старое имя мигрирует с защитной копией, собственное имя сохраняется.

## 14–16. Проверки и найденные проблемы

Фактические результаты, ссылки CI и границы покрытия приведены в [TEST_REPORT.md](../TEST_REPORT.md). Проверены все 9 основных разделов, две темы и 9 ширин; отдельно вход/первый запуск, диалоги, клавиатура, состояния архива, AAC, логотип и аватар после сохранения/перезагрузки. Исправлены выравнивание действий и форм, длинное меню, мобильные значки раскладок, отступы select, контраст активных элементов, состояния плеера, вложенный фокус диалогов, reduced motion, потеря черновиков и закрытие мобильного меню при фоновом обновлении. Визуальные эталоны проверяются отдельным прогоном без автоматического принятия новых снимков.

## 17. Ограничения и установка

HEVC использует проверку кодека конкретного канала/профиля, сначала нативный путь и затем локальный Worker/WASM/WebCodecs по HTTPS. Сервер копирует HEVC в fMP4, не перекодируя его в H.264. На документ разрешено до двух программных плееров; возможности и нагрузка зависят от браузера/компьютера. Chrome и Edge проверены в Linux CI; Windows, Firefox и Safari требуют отдельного прогона.

HTTPS Installer — отдельный компонент Debian/Ubuntu: локальный CA, DNS/IP SAN, проверяемая настройка существующего Apache/Nginx, продление, откат и публичный пакет доверия Windows. Он не включается при обычном запуске приложения. Полная установка на реальном systemd/proxy и импорт CA в Windows не выполнялись; автоматические Linux-тесты используют временные каталоги и имитации служб, а OpenSSL проверяется настоящей утилитой. Инструкции: [HTTPS](../scripts/https/README.md), [HEVC](../scripts/hevc/README.md), [обновление и откат](UPGRADE_0.9.0.md).

Перед обновлением остановите службу, сохраните полную папку данных со скрытыми ключами/изображениями и прежнее окружение. Обновите код/зависимости целиком и используйте прежний `VWSHUB_DATA_DIR`. Откат выполняется прежним кодом и полной копией данных до обновления. Веб-backup имеет лимит 16 МБ; для больших установок предусмотрена полная файловая копия при остановленной службе.

## 18. Проверки на физическом оборудовании

Физические регистраторы не подключались. На целевых моделях остаются проверка поддержки команд прошивкой, фактический readback сетевых/видеопараметров, возвращение после reboot, микрофон и аудиопрофили, PTZ, накопители, точность архива и длительная нагрузка. Эти проверки не помечены как пройденные. Встроенная ограниченная диагностика оборудования предназначена для следующей итерации с журналами пользователя.

## Приложение: публичные файлы

Список сформирован по содержимому файлов относительно исходной версии. Полный список хешей находится в `BUILD_INFO.json`.

### Изменены (42)

- `.gitattributes`
- `.github/workflows/tests.yml`
- `.gitignore`
- `CHANGELOG.md`
- `README.md`
- `TEST_REPORT.md`
- `THIRD_PARTY_NOTICES.txt`
- `app.py`
- `hub/__init__.py`
- `hub/backup.py`
- `hub/catalog.py`
- `hub/core.py`
- `hub/devices.py`
- `hub/diagnostics.py`
- `hub/media.py`
- `hub/store.py`
- `hub/transfers.py`
- `hub/workspace.py`
- `static/admin-tools.js`
- `static/app.css`
- `static/app.js`
- `static/archive-core.js`
- `static/archive-workspace.css`
- `static/archive-workspace.js`
- `static/auth.js`
- `static/devices.css`
- `static/devices.js`
- `static/infrastructure.css`
- `static/infrastructure.js`
- `static/live.css`
- `static/live.js`
- `static/workspace.css`
- `templates/index.html`
- `templates/login.html`
- `templates/setup.html`
- `tests/archive_core.test.cjs`
- `tests/test_catalog.py`
- `tests/test_core.py`
- `tests/test_devices.py`
- `tests/test_media.py`
- `tests/test_mux_integration.py`
- `tests/test_transfers.py`

### Добавлены (97)

- `.github/workflows/hevc-browser.yml`
- `.github/workflows/visual-review.yml`
- `docs/BRANDING.md`
- `docs/RELEASE_0.9.0.md`
- `docs/UPGRADE_0.9.0.md`
- `hub/appearance.py`
- `hub/failures.py`
- `hub/images.py`
- `hub/localization.py`
- `hub/proxy.py`
- `hub/resources.py`
- `scripts/build-hevc-assets.cjs`
- `scripts/build-hevc-assets.sh`
- `scripts/check-hevc-assets.cjs`
- `scripts/hevc/README.md`
- `scripts/hevc/entry.js`
- `scripts/hevc/package-lock.json`
- `scripts/hevc/package.json`
- `scripts/https/README.md`
- `scripts/https/install.sh`
- `scripts/https/vwshub-https.py`
- `scripts/https/windows/install-vwshub-ca.ps1`
- `static/brand/favicon.png`
- `static/brand/logo.png`
- `static/brand/wvw-favicon.svg`
- `static/brand/wvw-logo.svg`
- `static/brand/wvw-mark.svg`
- `static/i18n.js`
- `static/locales/ar.json`
- `static/locales/be.json`
- `static/locales/bn.json`
- `static/locales/cs.json`
- `static/locales/da.json`
- `static/locales/de.json`
- `static/locales/en.json`
- `static/locales/es.json`
- `static/locales/fa.json`
- `static/locales/fi.json`
- `static/locales/fr.json`
- `static/locales/hi.json`
- `static/locales/hu.json`
- `static/locales/id.json`
- `static/locales/it.json`
- `static/locales/ja.json`
- `static/locales/ko.json`
- `static/locales/nb-NO.json`
- `static/locales/nl.json`
- `static/locales/pl.json`
- `static/locales/plurals.json`
- `static/locales/pt-BR.json`
- `static/locales/ru.json`
- `static/locales/sv.json`
- `static/locales/tr.json`
- `static/locales/uk.json`
- `static/locales/vi.json`
- `static/locales/zh-CN.json`
- `static/locales/zh-TW.json`
- `static/themes.js`
- `static/vendor/hevc-adapter.js`
- `static/vendor/hevc-plugin.js`
- `static/vendor/hevc/HEVC-CORE-LICENSE.txt`
- `static/vendor/hevc/HEVC-PLUGIN-LICENSE.txt`
- `static/vendor/hevc/MP4BOX-LICENSE.txt`
- `static/vendor/hevc/hevc-decode.js`
- `static/vendor/hevc/hevc-decode.wasm`
- `static/vendor/hevc/manifest.json`
- `static/vendor/hevc/transcode-worker.js`
- `tests/auth.test.cjs`
- `tests/browser/.gitignore`
- `tests/browser/README.md`
- `tests/browser/archive-states.spec.cjs`
- `tests/browser/branding.spec.cjs`
- `tests/browser/create_test_tls.py`
- `tests/browser/dialogs.spec.cjs`
- `tests/browser/fixture_server.py`
- `tests/browser/flows.spec.cjs`
- `tests/browser/hardware_fixture.py`
- `tests/browser/helpers.cjs`
- `tests/browser/hevc-https.config.cjs`
- `tests/browser/hevc-https.spec.cjs`
- `tests/browser/matrix.spec.cjs`
- `tests/browser/navigation.spec.cjs`
- `tests/browser/package-lock.json`
- `tests/browser/package.json`
- `tests/browser/playwright.config.cjs`
- `tests/browser/snapshots/REVIEW.md`
- `tests/devices_focus.test.cjs`
- `tests/hevc_adapter.test.cjs`
- `tests/i18n_dom.test.cjs`
- `tests/i18n_theme.test.cjs`
- `tests/live_hevc_lifecycle.test.cjs`
- `tests/test_https_installer.py`
- `tests/test_https_proxy.py`
- `tests/test_image_restore_atomicity.py`
- `tests/test_settings_concurrency.py`
- `tests/test_v090_foundation.py`
- `tests/ui_foundation.test.cjs`

Отдельно добавлены **162** PNG-эталона в `tests/browser/snapshots/chromium/matrix.spec.cjs/`: 9 разделов × 2 темы × 9 ширин. Их имена и SHA-256 перечислены в manifest.

Архив пользовательских скриншотов исключён из текущего публичного дерева. Git-история сохранена. Папка данных, ключи, приватные вложения, журналы, зависимости разработки и результаты тестовых запусков в релизный ZIP не добавляются.
