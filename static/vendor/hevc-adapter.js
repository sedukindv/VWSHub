/* WVW integration of hevc-cam01-fmp4; the pinned decoder bundle is loaded lazily. */
(() => {
  'use strict';
  const original = {
    MS: window.MediaSource || window.ManagedMediaSource,
    isTypeSupported: (window.MediaSource || window.ManagedMediaSource)?.isTypeSupported,
    addSourceBuffer: (window.MediaSource || window.ManagedMediaSource)?.prototype.addSourceBuffer,
    decodingInfo: navigator.mediaCapabilities?.decodingInfo?.bind(navigator.mediaCapabilities),
  };
  const nativeCache = new Map(), nativeCodecs = new Set();
  let refs = 0, handle = null, initialization = null, scriptPromise = null,
    initError = '', errorAt = 0, loadAttempts = 0, generation = 0, enabledState = false, pendingInstall = false;
  const MAX_FALLBACKS = 2;
  const TEXT = {
    off: 'Поддержка HEVC выключена', enabled: 'Поддержка HEVC включена', ready: 'HEVC-плагин готов',
    httpsrequired: 'Для воспроизведения HEVC необходимо открыть WVW через защищённое HTTPS-соединение',
    apiunsupported: 'Браузер не поддерживает необходимые функции HEVC',
    initerror: 'Ошибка инициализации HEVC-плагина',
  };
  const error = (code, message) => Object.assign(new Error(message || TEXT[code]), { code });
  const timeout = (promise, ms, message) => new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(error('initerror', message)), ms);
    Promise.resolve(promise).then(value => { clearTimeout(timer); resolve(value); }, reason => { clearTimeout(timer); reject(reason); });
  });
  function prerequisites() {
    return typeof WebAssembly === 'object' && typeof Worker === 'function' && typeof MediaSource === 'function' &&
      typeof VideoEncoder === 'function' && typeof VideoEncoder.isConfigSupported === 'function' &&
      typeof VideoFrame === 'function' && typeof EncodedVideoChunk === 'function' &&
      typeof window.Hls === 'function' && /^1\.7\./.test(window.Hls.version || '') && window.Hls.isSupported();
  }
  function status(enabled) {
    enabledState = enabled === true;
    const state = !enabledState ? 'off' : !window.isSecureContext || location.protocol !== 'https:' ? 'httpsrequired' :
      !prerequisites() ? 'apiunsupported' : initError ? 'initerror' : handle ? 'ready' : 'enabled';
    return { state, message: state === 'initerror' && initError ? `${TEXT[state]}: ${initError}` : TEXT[state] };
  }
  function notify() { window.dispatchEvent(new CustomEvent('vwshub:hevc-status', { detail: status(enabledState) })); }
  function codecKey(value) { return String(value || '').toLowerCase(); }
  function shouldTranscode(mime) {
    const codec = String(mime).match(/(?:hvc1|hev1)\.[a-z0-9.]+/i)?.[0];
    return !codec || !nativeCodecs.has(codecKey(codec));
  }
  async function verifyNative(meta) {
    if (!meta.codec_string || !original.MS || !original.isTypeSupported || !original.addSourceBuffer || !original.decodingInfo ||
      !(meta.width > 0 && meta.height > 0 && meta.framerate > 0)) return false;
    const key = JSON.stringify([meta.codec_string, meta.width, meta.height, meta.framerate, meta.bitrate]);
    if (nativeCache.has(key)) return nativeCache.get(key);
    const task = (async () => {
      const mime = `video/mp4; codecs="${meta.codec_string}"`;
      try {
        if (!original.isTypeSupported.call(original.MS, mime)) return false;
        const support = await timeout(original.decodingInfo({ type: 'media-source', video: {
          contentType: mime, width: meta.width, height: meta.height,
          bitrate: meta.bitrate > 0 ? meta.bitrate : meta.width * meta.height * meta.framerate,
          framerate: meta.framerate,
        } }), 1800, 'Проверка нативного HEVC не завершилась');
        if (!support.supported) return false;
        const supported = await new Promise(resolve => {
          let ms, video, url, timer, onSourceOpen, done = false;
          const finish = value => {
            if (done) return;
            done = true; clearTimeout(timer);
            if (ms && onSourceOpen) ms.removeEventListener('sourceopen', onSourceOpen);
            if (video) { video.removeAttribute('src'); video.load(); }
            if (url) URL.revokeObjectURL(url);
            resolve(value);
          };
          try {
            ms = new original.MS(); video = document.createElement('video');
            video.muted = true; video.disableRemotePlayback = true;
            timer = setTimeout(() => finish(false), 1800);
            onSourceOpen = () => {
              if (done) return;
              try { const sb = original.addSourceBuffer.call(ms, mime); ms.removeSourceBuffer(sb); finish(true); }
              catch (_) { finish(false); }
            };
            ms.addEventListener('sourceopen', onSourceOpen, { once: true });
            url = URL.createObjectURL(ms); video.src = url; video.load();
          } catch (_) { finish(false); }
        });
        if (supported) nativeCodecs.add(codecKey(meta.codec_string));
        return supported;
      } catch (_) { return false; }
    })();
    if (nativeCache.size >= 128) nativeCache.clear();
    nativeCache.set(key, task);
    return task;
  }
  function loadPlugin() {
    if (window.WVWHevcPlugin) return Promise.resolve(window.WVWHevcPlugin);
    if (scriptPromise) return scriptPromise;
    if (loadAttempts >= 2) return Promise.reject(error('initerror', 'Не удалось загрузить локальные ресурсы HEVC. Обновите страницу.'));
    loadAttempts++;
    scriptPromise = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      const timer = setTimeout(() => finish(error('initerror', 'Истекло время загрузки ресурсов HEVC')), 8000);
      let done = false;
      function finish(reason) {
        if (done) return;
        done = true; clearTimeout(timer); script.onload = script.onerror = null;
        if (reason) { script.remove(); scriptPromise = null; reject(reason); }
        else resolve(window.WVWHevcPlugin);
      }
      script.src = '/static/vendor/hevc-plugin.js?v=0.1.12-core1.7.0';
      script.onload = () => finish(window.WVWHevcPlugin ? null : error('initerror', 'Локальный HEVC-плагин не найден'));
      script.onerror = () => finish(error('initerror', 'Не удалось загрузить локальный HEVC-плагин'));
      document.head.appendChild(script);
    });
    return scriptPromise;
  }
  async function initialize() {
    if (handle) return handle;
    if (initialization) return initialization;
    // A timed-out upstream promise cannot be cancelled. Do not let its late
    // global uninstall race a new installation; wait for it to settle first.
    if (pendingInstall) throw error('initerror', 'Предыдущая инициализация HEVC ещё завершается. Обновите страницу.');
    const epoch = ++generation;
    initialization = (async () => {
      const plugin = await loadPlugin();
      if (plugin?.version !== '0.1.12' || plugin?.coreVersion !== '1.7.0') throw error('initerror', 'Несовместимая версия HEVC-плагина');
      pendingInstall = true;
      const pending = Promise.resolve().then(() => plugin.attachHevcSupport({
        workerUrl: '/static/vendor/hevc/transcode-worker.js', wasmUrl: '/static/vendor/hevc/hevc-decode.js',
        wasmBinaryUrl: '/static/vendor/hevc/hevc-decode.wasm', forceTranscode: true,
        poolSize: 1, fps: 12, bitrate: 1500000, logLevel: 'warn', shouldTranscode,
      }));
      pending.then(value => { try { if (epoch !== generation) value?.uninstall?.(); } finally { pendingInstall = false; } }, () => { pendingInstall = false; });
      const value = await timeout(pending, 8000, 'Истекло время инициализации HEVC-плагина');
      if (epoch !== generation) throw error('initerror', 'Инициализация HEVC отменена');
      if (!value || typeof value.uninstall !== 'function' || MediaSource.prototype.addSourceBuffer === original.addSourceBuffer) {
        value?.uninstall?.(); throw error('apiunsupported');
      }
      handle = value; initError = ''; notify(); return handle;
    })();
    try { return await initialization; }
    finally { initialization = null; }
  }
  function idleCleanup() {
    if (refs) return;
    generation++;
    handle?.uninstall(); handle = null;
    notify();
  }
  async function prepare(meta, enabled) {
    enabledState = enabled === true;
    if (meta?.codec === 'h264') return { mode: 'h264', container: 'ts', attach: () => () => {}, release() {} };
    // Preserve the established TS player when FFprobe itself is absent. This
    // does not claim a codec and never enables HEVC software processing.
    if (meta?.codec === 'unknown' && meta.reason_code === 'ffprobe_unavailable' && meta.legacy_ts_allowed === true)
      return { mode: 'legacy', container: 'ts', attach: () => () => {}, release() {} };
    if (meta?.codec !== 'hevc') throw error('unknown', meta?.reason || 'Кодек этого Live-профиля не определён. Повторите проверку позже.');
    if (await verifyNative(meta)) return { mode: 'native', container: 'fmp4', attach: () => () => {}, release() {} };
    const availability = status(enabled);
    if (availability.state === 'off') throw error('off', 'Браузер не воспроизводит HEVC напрямую. Администратор может включить поддержку HEVC в настройках.');
    if (availability.state === 'httpsrequired' || availability.state === 'apiunsupported') throw error(availability.state);
    if (initError && Date.now() - errorAt < 15000) throw error('initerror', initError);
    if (!(meta.width > 0 && meta.height > 0)) throw error('unknown', 'Размер изображения HEVC не подтверждён');
    if (refs >= MAX_FALLBACKS) throw error('capacity', 'Для защиты компьютера одновременно доступны две HEVC-камеры с браузерной обработкой. Закройте другую камеру.');
    refs++;
    let released = false, attached = false, detach = () => {};
    const release = () => {
      if (released) return;
      released = true; detach(); refs--; idleCleanup();
    };
    try {
      const codec = meta.width * meta.height > 2073600 ? 'avc1.640033' : meta.width * meta.height > 921600 ? 'avc1.64002a' : 'avc1.640028';
      const support = await timeout(VideoEncoder.isConfigSupported({ codec, width: meta.width, height: meta.height,
        bitrate: 1500000, framerate: 12, avc: { format: 'avc' } }), 3000, 'Проверка кодировщика браузера не завершилась');
      if (!support.supported) throw error('apiunsupported');
      await initialize();
      return {
        mode: 'plugin', container: 'fmp4', release,
        attach(hls) {
          if (released || attached) throw error('initerror', 'HEVC-плеер уже подключён или закрыт');
          attached = true;
          const buffers = new Set();
          const events = window.Hls.Events;
          const created = (_event, data) => { for (const track of Object.values(data?.tracks || {})) if (track.buffer) buffers.add(track.buffer); };
          const computeDetach = window.WVWHevcPlugin.attachHlsComputeAware(hls);
          hls.on(events.BUFFER_CREATED, created);
          hls.on(events.DESTROYING, release);
          detach = () => {
            hls.off(events.BUFFER_CREATED, created); hls.off(events.DESTROYING, release);
            computeDetach?.();
            for (const buffer of buffers) { try { buffer.__wvwDestroy?.(); } catch (_) {} }
            buffers.clear();
          };
          return release;
        },
      };
    } catch (reason) {
      const safe = reason?.code ? reason : error('initerror');
      if (!reason?.code) console.warn('[WVW HEVC] Initialization failed', reason);
      initError = safe.message || TEXT.initerror; errorAt = Date.now();
      release(); notify(); throw safe;
    }
  }
  window.WVWHevc = { status, prepare };
})();
