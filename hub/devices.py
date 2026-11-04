"""Capability-based ONVIF controls; deliberately no arbitrary vendor command proxy.

Operations follow ONVIF Media v10, Imaging v20, PTZ v20 and Device v10.
DVRIP support uses the public OpenIPC/python-dvr methods only.
"""
from __future__ import annotations

import math
import threading
import time
from datetime import datetime, timedelta, timezone
from functools import wraps
import copy
import hashlib
import ipaddress
import json
import logging
import re
import socket
import struct

from flask import jsonify, request
from .failures import failure_details


def site_device_name(runtime,cam):
    store=getattr(runtime,"store",None)
    if store and hasattr(store,"get_recorders"):
        recorder=next((r for r in store.get_recorders() if r.get("id")==cam.get("recorder_id")),None)
        if recorder:return recorder.get("name")
    return cam.get("name")


def plain(value):
    """Serialize Zeep objects without exposing credentials or internal transport state."""
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()
                if not any(s in str(k).lower() for s in ("password", "passwd", "secret", "credential"))}
    try:
        from zeep.helpers import serialize_object
        serialized = serialize_object(value)
        if isinstance(serialized, (dict, list, tuple)):
            return plain(serialized)
    except (ImportError, TypeError):
        pass
    if hasattr(value, "__dict__"):
        return plain({k: v for k, v in vars(value).items() if not k.startswith("_")})
    return str(value)


def field(obj, key, default=None):
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def number(value, label, minimum=None, maximum=None, integer=False):
    if isinstance(value, bool):
        raise ValueError(f"{label}: укажите число")
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label}: укажите число") from None
    if not math.isfinite(result) or (integer and result != int(result)):
        raise ValueError(f"{label}: недопустимое число")
    if minimum is not None and result < float(minimum):
        raise ValueError(f"{label}: минимум {minimum}")
    if maximum is not None and result > float(maximum):
        raise ValueError(f"{label}: максимум {maximum}")
    return int(result) if integer else result


def check_dvr_reply(reply):
    if isinstance(reply, dict) and "Ret" in reply and reply["Ret"] not in (100, 150, 515):
        raise RuntimeError(f"DVRIP отказал в операции (код {reply['Ret']})")
    if reply is False or reply is None:
        raise RuntimeError("DVRIP отказал в операции")
    return reply


def verified_write(expected, observed=None):
    """A successful SOAP setter is an acknowledgement, not persistence proof."""
    available=isinstance(observed,dict)
    saved=available and all(key in observed and not (isinstance(value,(int,float)) and isinstance(observed[key],bool)) and observed[key]==value for key,value in expected.items())
    return dict(accepted=True,saved=bool(saved),verification_pending=not saved,readback_available=available,
                message="Изменения подтверждены повторным чтением устройства" if saved else "Устройство приняло команду, но повторное чтение не подтвердило изменения. Проверьте настройки в фирменном интерфейсе.")



def ntp_host(address):
    """ONVIF tt:NetworkHost (installed official devicemgmt.wsdl/onvif.xsd)."""
    if not isinstance(address,str) or not address or len(address)>253 or address!=address.strip() or "%" in address:
        raise ValueError("NTP-сервер: укажите IP-адрес или DNS-имя")
    try:
        ip=ipaddress.ip_address(address)
        return {"Type":"IPv4" if ip.version==4 else "IPv6", "IPv4Address" if ip.version==4 else "IPv6Address":str(ip)}
    except ValueError:
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*\.?",address):
            raise ValueError("NTP-сервер: DNS-имя без протокола, порта и пути") from None
        return {"Type":"DNS","DNSname":address.lower().rstrip(".")}


def ntp_address(host):
    kind=field(host,"Type")
    if not isinstance(kind,str):return None
    key={"IPv4":"IPv4Address","IPv6":"IPv6Address","DNS":"DNSname"}.get(kind)
    if not key or not isinstance(field(host,key),str):return None
    try:
        normalized=ntp_host(field(host,key))
        return next(v for k,v in normalized.items() if k!="Type") if normalized["Type"]==kind else None
    except ValueError:return None


def read_onvif_ntp(device):
    method=getattr(device,"GetNTP",None)
    if not callable(method):raise NotImplementedError("Устройство не предоставляет GetNTP")
    try:raw=method()
    except Exception as exc:
        code=(str(getattr(exc,"code",""))+" "+str(exc)).lower()
        if any(v in code for v in ("actionnotsupported","optionalactionnotimplemented","notimplemented","not supported")):
            raise NotImplementedError("Устройство не поддерживает ONVIF NTP") from None
        raise
    if not isinstance(field(raw,"FromDHCP"),bool):raise NotImplementedError("Устройство не подтвердило формат ONVIF NTP")
    hosts=field(raw,"NTPManual",[]) or []
    if not isinstance(hosts,(list,tuple)) or len(hosts)>256:raise NotImplementedError("Неподдержанный список NTP-серверов")
    servers=[ntp_address(v) for v in hosts]
    maximum=None
    try:
        caps=device.GetServiceCapabilities()
        count=field(field(field(caps,"Capabilities",caps),"Network"),"NTP")
        if type(count) is int and 0<=count<=256:maximum=count
    except Exception:pass
    clock=None;mode=None
    try:
        clock=device.GetSystemDateAndTime();mode=field(clock,"DateTimeType")
        if not isinstance(mode,str) or mode not in {"NTP","Manual"}:mode=None
    except Exception:pass
    writable=bool(maximum and len(hosts)<=maximum and all(v is not None for v in servers) and callable(getattr(device,"SetNTP",None)))
    return raw,clock,dict(from_dhcp=field(raw,"FromDHCP"),servers=[v for v in servers if v is not None],
        dhcp_servers=[v for item in (field(raw,"NTPFromDHCP",[]) or []) if (v:=ntp_address(item)) is not None],
        max_servers=maximum,writable=writable,enabled=mode=="NTP" if mode else None,
        mode_writable=writable and mode is not None and isinstance(field(clock,"DaylightSavings"),bool) and callable(getattr(device,"SetSystemDateAndTime",None)),
        revision=_revision({"ntp":plain(raw),"mode":mode,"maximum":maximum}),
        note="ONVIF задаёт серверы и источник DHCP; нестандартные порт и интервал не изменяются" if writable else "Редактирование NTP не подтверждено возможностями устройства")


def register_devices(app, runtime):
    current_user, get_camera = runtime.current_user, runtime.get_camera
    onvif_connect = lambda cam: connect_onvif(runtime, cam)
    dvr_connect = lambda cam: connect_dvr(runtime, cam)
    logger = logging.getLogger("vwshub.devices")
    clients, device_locks, reboot_pending = {}, {}, {}
    cache_lock = threading.RLock()

    def endpoint(fn):
        @wraps(fn)
        def wrapped():
            me = current_user()
            if not me or me.get("role") != "admin":
                return jsonify(error="Доступ запрещён"), 403
            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                return jsonify(error="Ожидается JSON-объект"), 400
            cam = get_camera(str(data.get("cam_id") or ""))
            if not cam and hasattr(runtime,"store"):
                parent=next((d for d in runtime.store.get_recorders() if d["id"]==str(data.get("cam_id") or "")),None)
                if parent:cam={**parent.get("connection",{}),"id":parent["id"],"recorder_id":parent["id"],"name":parent["name"],"channel":0}
            if not cam:
                return jsonify(error="Устройство не найдено"), 404
            began = time.monotonic()
            journal = getattr(runtime, "hardware", None)
            try:
                # Zeep clients/requests Sessions are shared only under this device
                # lock. Reuse discovery between PTZ renewals instead of reconnecting
                # and reparsing every WSDL while the operator holds a direction.
                with cache_lock:
                    physical_key=tuple(str(cam.get(k,"")) for k in ("protocol","ip","port"))
                    device_lock = device_locks.setdefault(physical_key, threading.RLock())
                with device_lock:
                    result=fn(cam,data)
                    if not isinstance(result,tuple):
                        from .store import DataStore
                        if not hasattr(runtime,"device_health"):runtime.device_health={}
                        runtime.device_health.setdefault(DataStore.connection_key(cam),{})["management_checked"]=0 if data.get("action")=="reboot" else time.monotonic()
                    if journal: journal.record("device.operation", cam, operation=fn.__name__, duration_ms=round((time.monotonic()-began)*1000))
                    if isinstance(result,tuple):return jsonify(result[0]),result[1]
                    return jsonify(success=True, **result)
            except ValueError as exc:
                if journal: journal.record("device.rejected", cam, level="warning", operation=fn.__name__, stage=fn.__name__, error_type=type(exc).__name__, duration_ms=round((time.monotonic()-began)*1000))
                return jsonify(error=str(exc)), 400
            except NotImplementedError as exc:
                if journal:journal.record("device.unsupported",cam,operation=fn.__name__,stage=fn.__name__,result="unsupported",duration_ms=round((time.monotonic()-began)*1000))
                return jsonify(error=str(exc),error_code="unsupported",stage=fn.__name__), 501
            except Exception as exc:
                if journal: journal.record("device.failed", cam, level="error", operation=fn.__name__, stage=fn.__name__, **failure_details(exc), duration_ms=round((time.monotonic()-began)*1000))
                # SOAP/FFmpeg errors can contain entire credential-bearing URLs.
                logger.warning("Device operation %s failed on %s (%s)", fn.__name__, cam.get("id"), type(exc).__name__)
                details=failure_details(exc)
                if details["error_code"] in {"timeout","authentication","connection"}:
                    from .store import DataStore
                    if hasattr(runtime,"device_health"):
                        runtime.device_health.setdefault(DataStore.connection_key(cam),{})["management_checked"]=0
                return jsonify(error=details["description"],error_code=details["error_code"],stage=fn.__name__), 504 if details["error_code"]=="timeout" else 502
        return wrapped

    def client_for(cam):
        if cam.get("protocol") != "onvif":
            raise NotImplementedError("Эта функция доступна для совместимых ONVIF-устройств")
        signature = tuple(str(cam.get(k, "")) for k in ("id", "ip", "port", "username", "password"))
        with cache_lock:
            item = clients.get(signature)
            if item is not None and time.monotonic() - item[0] < 60:
                return item[1]
        client = onvif_connect(cam)
        with cache_lock:
            if len(clients) >= 64:
                clients.pop(min(clients, key=lambda key: clients[key][0]))
            clients[signature] = (time.monotonic(), client)
        return client

    def service_for(client, name):
        services = getattr(client, "services", {})
        return services.get(name) or getattr(client, f"create_{name}_service")()

    def profile_for(client, token):
        media = service_for(client, "media")
        cached = getattr(client, "_vms_profiles", None)
        if cached is not None and time.monotonic() - cached[0] < 30:
            profiles = cached[1]
        else:
            profiles = media.GetProfiles() or []
            client._vms_profiles = (time.monotonic(), profiles)
        profile = next((p for p in profiles if str(field(p, "token", "")) == str(token)), None) if token else next(iter(profiles), None)
        if profile is None:
            raise ValueError("Профиль видеопотока не найден")
        return media, profile

    @app.post("/api/device/capabilities", endpoint="dev_api_device_capabilities")
    @endpoint
    def capabilities(cam, data):
        if cam.get("protocol") == "dvrip":
            dvr = dvr_connect(cam)
            try:
                return xm_capabilities(dvr, cam)
            finally:
                dvr.close()
        client = client_for(cam)
        device = service_for(client, "devicemgmt")
        caps = device.GetCapabilities({"Category": "All"})
        profiles = service_for(client, "media").GetProfiles() or []
        client._vms_profiles = (time.monotonic(), profiles)
        result = []
        has_ptz, has_source, has_encoder = False, False, False
        for p in profiles:
            source = field(p, "VideoSourceConfiguration")
            encoder = field(p, "VideoEncoderConfiguration")
            ptz = field(p, "PTZConfiguration")
            ptz_supported = ptz is not None and field(caps, "PTZ") is not None
            result.append(dict(token=str(field(p, "token", "")), name=str(field(p, "Name", "Профиль")),
                               ptz=ptz_supported, video_source_token=field(source, "SourceToken", ""),
                               encoder_token=field(encoder, "token", "")))
            has_ptz = has_ptz or ptz_supported
            has_source = has_source or bool(field(source, "SourceToken"))
            has_encoder = has_encoder or bool(field(encoder, "token"))
        ntp_read=ntp_edit=False
        try:
            _,_,ntp=read_onvif_ntp(device);ntp_read=True;ntp_edit=ntp["writable"]
        except Exception:pass
        return dict(protocol="onvif", profiles=result,
                    capabilities=dict(info=True, ptz=has_ptz, imaging=has_source and field(caps, "Imaging") is not None,
                                      encoder=has_encoder, reboot=True, time=True, network=True,ntp_read=ntp_read,ntp=ntp_edit),
                    notes=["Наличие ONVIF-службы не гарантирует поддержку каждой команды: доступные диапазоны запрашиваются у устройства. Сеть читается без изменения IP."])

    @app.post("/api/device/ptz", endpoint="dev_api_device_ptz")
    @endpoint
    def ptz(cam, data):
        action = data.get("action", "stop")
        if action not in {"move", "stop", "presets", "goto", "save", "remove"}:
            raise ValueError("Неизвестная PTZ-команда")
        # Validate user input before opening any device connection.
        velocity = {k: number(data.get(k, 0), k, -1, 1) for k in ("pan", "tilt", "zoom")} if action == "move" else {}
        preset_token = str(data.get("preset_token") or "").strip()
        if action in {"goto", "remove"} and not preset_token:
            raise ValueError("Выберите предустановку")
        name = str(data.get("name") or "").strip()
        if action == "save" and (not name or len(name) > 64):
            raise ValueError("Имя предустановки должно содержать 1–64 символа")
        if cam.get("protocol") == "dvrip":
            dvr = dvr_connect(cam)
            try:
                return xm_ptz(dvr, cam, data)
            finally:
                dvr.close()
        client = client_for(cam)
        _, profile = profile_for(client, data.get("profile_token"))
        config = field(profile, "PTZConfiguration")
        if config is None:
            raise NotImplementedError("Выбранный профиль не поддерживает PTZ")
        service = service_for(client, "ptz")
        token = str(field(profile, "token"))
        if action == "move":
            # A bounded device-side timeout is essential if browser/network disappears.
            params = {"ProfileToken": token, "Timeout": timedelta(seconds=0.8), "Velocity": {}}
            if velocity["pan"] or velocity["tilt"]:
                params["Velocity"]["PanTilt"] = {"x": velocity["pan"], "y": velocity["tilt"]}
            if velocity["zoom"]:
                params["Velocity"]["Zoom"] = {"x": velocity["zoom"]}
            if not params["Velocity"]:
                service.Stop({"ProfileToken": token, "PanTilt": True, "Zoom": True})
            else:
                service.ContinuousMove(params)
        elif action == "stop":
            service.Stop({"ProfileToken": token, "PanTilt": True, "Zoom": True})
        elif action == "presets":
            return dict(presets=[dict(token=str(field(p, "token", "")), name=str(field(p, "Name", "")))
                                 for p in (service.GetPresets({"ProfileToken": token}) or [])])
        elif action == "goto":
            service.GotoPreset({"ProfileToken": token, "PresetToken": preset_token})
        elif action == "remove":
            service.RemovePreset({"ProfileToken": token, "PresetToken": preset_token})
        elif action == "save":
            params = {"ProfileToken": token, "PresetName": name}
            if preset_token:
                params["PresetToken"] = preset_token
            return dict(preset_token=str(service.SetPreset(params)))
        return dict(action=action)

    @app.post("/api/device/imaging", endpoint="dev_api_device_imaging")
    @endpoint
    def imaging(cam, data):
        settings = data.get("settings")
        allowed = {"Brightness", "Contrast", "ColorSaturation", "Sharpness"}
        if settings is not None and (not isinstance(settings, dict) or not settings or set(settings) - allowed):
            raise ValueError("Допустимы: Brightness, Contrast, ColorSaturation, Sharpness")
        client = client_for(cam)
        _, profile = profile_for(client, data.get("profile_token"))
        source = field(field(profile, "VideoSourceConfiguration"), "SourceToken")
        if not source:
            raise NotImplementedError("Профиль не содержит источник изображения")
        service = service_for(client, "imaging")
        options = service.GetOptions({"VideoSourceToken": source})
        supported = {key: plain(field(options, key)) for key in allowed if field(options, key) is not None}
        if settings is not None:
            validated = {}
            for key, value in settings.items():
                option = field(options, key)
                if option is None:
                    raise ValueError(f"Устройство не поддерживает параметр {key}")
                validated[key] = number(value, key, field(option, "Min"), field(option, "Max"))
            service.SetImagingSettings({"VideoSourceToken": source, "ImagingSettings": validated, "ForcePersistence": True})
        try:current = service.GetImagingSettings({"VideoSourceToken": source})
        except Exception:
            if settings is None:raise
            return dict(settings={},options=supported,**verified_write(validated))
        observed={key: plain(field(current, key)) for key in supported}
        return dict(settings=observed, options=supported,**(verified_write(validated,observed) if settings is not None else {}))

    @app.post("/api/device/encoder", endpoint="dev_api_device_encoder")
    @endpoint
    def encoder(cam, data):
        settings = data.get("settings")
        allowed = {"width", "height", "fps", "bitrate", "quality"}
        if settings is not None and (not isinstance(settings, dict) or not settings or set(settings) - allowed):
            raise ValueError("Неизвестные параметры видеопотока")
        client = client_for(cam)
        media, profile = profile_for(client, data.get("profile_token"))
        enc = field(profile, "VideoEncoderConfiguration")
        enc_token = field(enc, "token")
        if not enc_token:
            raise NotImplementedError("Профиль не содержит конфигурацию кодировщика")
        config = media.GetVideoEncoderConfiguration({"ConfigurationToken": enc_token})
        options = media.GetVideoEncoderConfigurationOptions({"ConfigurationToken": enc_token, "ProfileToken": field(profile, "token")})
        encoding = str(field(config, "Encoding", ""))
        codec = field(options, encoding)
        if codec is None:
            raise NotImplementedError("Устройство не сообщает диапазоны для текущего кодека")
        # BitrateRange is in the v1 extension for many cameras, not H264Options.
        extended_codec = field(field(options, "Extension"), encoding)
        bitrate_range = field(codec, "BitrateRange") or field(extended_codec, "BitrateRange")
        resolutions = field(codec, "ResolutionsAvailable", []) or []
        public_options = dict(resolutions=[dict(width=field(r, "Width"), height=field(r, "Height")) for r in resolutions],
                              fps=plain(field(codec, "FrameRateRange")), bitrate=plain(bitrate_range),
                              quality=plain(field(options, "QualityRange")))
        expected={}
        if settings is not None:
            if "width" in settings or "height" in settings:
                if not {"width", "height"} <= set(settings):
                    raise ValueError("Укажите ширину и высоту одновременно")
                width = number(settings["width"], "Ширина", 1, 16384, True)
                height = number(settings["height"], "Высота", 1, 16384, True)
                if not any(field(r, "Width") == width and field(r, "Height") == height for r in resolutions):
                    raise ValueError("Разрешение не поддерживается текущим кодеком")
                config.Resolution.Width, config.Resolution.Height = width, height
                expected.update(width=width,height=height)
            for key, path, option in (("quality", "Quality", field(options, "QualityRange")),
                                       ("fps", "FrameRateLimit", field(codec, "FrameRateRange")),
                                       ("bitrate", "BitrateLimit", bitrate_range)):
                if key not in settings:
                    continue
                if option is None:
                    raise ValueError(f"Устройство не сообщает допустимый диапазон {key}")
                validated = number(settings[key], key, field(option, "Min"), field(option, "Max"), key != "quality")
                expected[key]=validated
                if key == "quality":
                    config.Quality = validated
                else:
                    if field(config, "RateControl") is None:
                        raise NotImplementedError("Устройство не предоставляет управление частотой/битрейтом")
                    setattr(config.RateControl, path, validated)
            media.SetVideoEncoderConfiguration({"Configuration": config, "ForcePersistence": True})
            try:config = media.GetVideoEncoderConfiguration({"ConfigurationToken": enc_token})
            except Exception:return dict(settings={},options=public_options,**verified_write(expected))
        resolution, rate = field(config, "Resolution"), field(config, "RateControl")
        observed=dict(width=field(resolution, "Width"), height=field(resolution, "Height"),
                                  fps=field(rate, "FrameRateLimit"), bitrate=field(rate, "BitrateLimit"),
                                  quality=field(config, "Quality"), encoding=encoding)
        return dict(settings=observed, options=public_options,**(verified_write(expected,observed) if settings is not None else {}))

    @app.post("/api/device/system", endpoint="dev_api_device_system")
    @endpoint
    def system(cam, data):
        action = data.get("action", "read")
        if action not in {"read", "time", "reboot"}:
            raise ValueError("Неизвестная системная операция")
        # Reboot requires an explicit intent flag, preventing accidental form submits.
        if action == "reboot" and data.get("confirm") is not True:
            raise ValueError("Подтвердите перезагрузку устройства")
        if action == "reboot" and data.get("device_name") not in (cam.get("name"),site_device_name(runtime,cam)):
            raise ValueError("Для перезапуска введите точное имя регистратора")
        physical_key=tuple(str(cam.get(k,"")) for k in ("protocol","ip","port"))
        if action == "reboot" and reboot_pending.get(physical_key,0)>time.monotonic():
            return dict(error="Перезапуск уже запрошен. Дождитесь завершения и проверьте доступность устройства.",retry_after=60),409
        utc = datetime.now(timezone.utc)
        if action == "time" and data.get("utc"):
            try:
                utc = datetime.fromisoformat(str(data["utc"]).replace("Z", "+00:00"))
                if utc.tzinfo is None:
                    raise ValueError()
                utc = utc.astimezone(timezone.utc)
            except (TypeError, ValueError):
                raise ValueError("Передайте дату ISO 8601 с часовым поясом") from None
        if cam.get("protocol") == "dvrip":
            dvr = dvr_connect(cam)
            try:
                if action == "reboot":
                    # Pinned python-dvr reboot() discards the acknowledgement.
                    # Use its actual command and disconnect wait, preserving the
                    # connection during the firmware's deferred reboot window.
                    wait=getattr(dvr,"_wait_for_disconnect",None)
                    if not callable(wait) or not callable(getattr(dvr,"set_command",None)):
                        raise NotImplementedError("Адаптер не подтверждает безопасный перезапуск этой версии DVRIP")
                    reply=dvr.set_command("OPMachine",{"Action":"Reboot"})
                    check_dvr_reply(reply)
                    if not isinstance(reply,dict) or reply.get("Ret")!=100:
                        raise RuntimeError("Регистратор не подтвердил команду перезапуска")
                    reboot_pending[physical_key]=time.monotonic()+60
                    from .store import DataStore
                    if not hasattr(runtime,"device_health"):runtime.device_health={}
                    runtime.device_health.setdefault(DataStore.connection_key(cam),{})["management_checked"]=0
                    wait(15)
                    return dict(accepted=True,verification_required=True,retry_after=60,message="Регистратор принял команду. Дождитесь загрузки и проверьте доступность.")
                if action == "time":
                    # OPTimeSetting accepts an unzoned LOCAL recorder clock, whereas
                    # ONVIF accepts UTC. Require explicit local time; do not guess a
                    # vendor-specific timezone field or the server's own timezone.
                    try:
                        local_time = datetime.fromisoformat(str(data.get("local_time") or ""))
                        if local_time.tzinfo is not None:
                            raise ValueError()
                    except (TypeError, ValueError):
                        raise ValueError("Для DVRIP укажите местное время регистратора в поле local_time без часового пояса") from None
                    started=time.monotonic()
                    check_dvr_reply(dvr.set_time(local_time))
                    try:
                        observed=dvr.get_time()
                        if isinstance(observed,str):observed=datetime.fromisoformat(observed)
                        verified=isinstance(observed,datetime) and observed.tzinfo is None and abs((observed-local_time).total_seconds()-(time.monotonic()-started))<=5
                    except Exception:
                        verified=False
                    return dict(accepted=True,saved=verified,message="Местное время подтверждено повторным чтением" if verified else "Команда установки времени принята, но повторное чтение не подтвердило результат")
                notes = []
                info = check_dvr_reply(dvr.get_system_info())
                result = dict(system_info=plain(info), time=None, network=None, notes=notes,services={"network":"confirmed","management":"confirmed","live":"unverified","archive":"unverified","audio":"unverified"})
                for key, method in (("time", "get_time"), ("network", "get_netcommon")):
                    try:
                        result[key] = plain(check_dvr_reply(getattr(dvr, method)()))
                        if key=="network":result["network_display"]=network_display(result[key])
                    except Exception:
                        notes.append(f"Устройство не предоставило {key}")
                return result
            finally:
                dvr.close()
        client = client_for(cam)
        device = service_for(client, "devicemgmt")
        if action == "reboot":
            method=getattr(device,"SystemReboot",None)
            if not callable(method):raise NotImplementedError("Устройство не предоставляет SystemReboot")
            reply=method()
            reboot_pending[physical_key]=time.monotonic()+60
            return dict(accepted=True,verification_required=True,retry_after=60,message="Регистратор принял команду. Дождитесь загрузки и проверьте доступность.")
        if action == "time":
            current = device.GetSystemDateAndTime()
            started=time.monotonic()
            device.SetSystemDateAndTime({"DateTimeType": "Manual", "DaylightSavings": bool(field(current, "DaylightSavings", False)),
                                         "TimeZone": field(current, "TimeZone"),
                                         "UTCDateTime": {"Date": {"Year": utc.year, "Month": utc.month, "Day": utc.day},
                                                         "Time": {"Hour": utc.hour, "Minute": utc.minute, "Second": utc.second}}})
            try:
                observed=field(device.GetSystemDateAndTime(),"UTCDateTime")
                date,clock=field(observed,"Date"),field(observed,"Time")
                stamp=datetime(int(field(date,"Year")),int(field(date,"Month")),int(field(date,"Day")),int(field(clock,"Hour")),int(field(clock,"Minute")),int(field(clock,"Second")),tzinfo=timezone.utc)
                verified=abs((stamp-utc).total_seconds()-(time.monotonic()-started))<=5
            except Exception:
                verified=False
            return dict(accepted=True,saved=verified,message="Время UTC подтверждено повторным чтением" if verified else "Команда установки времени принята, но повторное чтение не подтвердило результат")
        result = dict(system_info=plain(device.GetDeviceInformation()), time=None, network=None, notes=[],services={"network":"confirmed","management":"confirmed","live":"unverified","archive":"unverified","audio":"unverified"})
        try:
            result["time"] = plain(device.GetSystemDateAndTime())
        except Exception:
            result["notes"].append("Устройство не предоставило время")
        try:
            result["network"] = plain(device.GetNetworkInterfaces())
        except Exception:
            result["notes"].append("Устройство не предоставило сетевые интерфейсы")
        return result

    register_xm_routes(app, runtime, endpoint, dvr_connect, client_for, service_for)


def connect_dvr(runtime, cam):
    from dvrip import DVRIPCam
    dvr = DVRIPCam(str(cam["ip"]), user=str(cam.get("username", "")),
                   password=runtime.dec_pwd(cam.get("password", "")), port=int(cam.get("port",34567)))
    try:
        dvr.connect(timeout=6)
        if not dvr.login():
            raise ConnectionError("Не удалось авторизоваться на устройстве")
        return dvr
    except Exception:
        dvr.close()
        raise


def connect_onvif(runtime, cam):
    from onvif import ONVIFCamera
    from zeep.transports import Transport
    return ONVIFCamera(str(cam["ip"]), int(cam.get("port",80)), str(cam.get("username","")),
                       runtime.dec_pwd(cam.get("password","")), transport=Transport(timeout=6,operation_timeout=6))


# Names and operations follow the XM configuration exchange format shipped in
# OpenIPC/python-dvr/doc and python-dvr's 1042/1040 getters/setters. A section is
# writable ONLY after the recorder returned an actual structure, never an ACK.
XM_SECTIONS = {
    "general": ("Общие настройки", ("General.General","General.Common","General")),
    "location": ("Дата и время", ("General.Location",)),
    "ntp": ("Синхронизация времени", ("NetWork.NetNTP",)),
    "recording": ("Запись и расписание", ("Record",)),
    "encoder": ("Сжатие и потоки", ("Simplify.Encode",)),
    "network": ("Сеть", ("NetWork.NetCommon",)),
    "dhcp": ("DHCP", ("NetWork.NetDHCP",)),
    "dns": ("DNS", ("NetWork.NetDNS",)),
    "osd": ("Экранные маски и титры", ("AVEnc.VideoWidget","VideoWidget")),
    "imaging": ("Изображение каналов", ("AVEnc.VideoColor","Camera")),
    "maintenance": ("Автообслуживание", ("General.AutoMaintain",)),
    "digital": ("Цифровые каналы", ("NetWork.DigitalChannel",)),
}
LABELS = {
    "Enable":"Включено","RecordMode":"Режим записи","PacketLength":"Длина файла, мин", "PreRecord":"Предзапись, с",
    "RecordLatch":"Постзапись тревоги, с","Redundancy":"Резервная запись","TimeSection":"Расписание",
    "AlarmMask":"Каналы тревоги","DetectMask":"Каналы детекции","RecordMask":"Каналы записи",
    "HDDOverWrite":"При заполнении носителя","OverWrite":"При заполнении носителя",
    "DateFormat":"Формат даты","DateSeparator":"Разделитель даты","TimeFormat":"Формат времени", "TimeZone":"Часовой пояс (код прошивки)",
    "HostName":"Сетевое имя","HostIP":"IP-адрес","Submask":"Маска подсети","GateWay":"Шлюз", "Gateway":"Шлюз",
    "TCPPort":"TCP-порт","HttpPort":"HTTP-порт","HTTPPort":"HTTP-порт","UDPPort":"UDP-порт","MAC":"MAC-адрес",
    "PrimaryDNS":"Основной DNS","SecondaryDNS":"Резервный DNS","Address":"Адрес","Interface":"Интерфейс",
    "Compression":"Кодек","Resolution":"Разрешение","FPS":"Кадры/с","FrameRate":"Кадры/с","BitRate":"Битрейт, кбит/с",
    "BitRateControl":"Управление битрейтом","Quality":"Качество","GOP":"Интервал I-кадров","IFrameInterval":"Интервал I-кадров",
    "AudioEnable":"Записывать звук","VideoEnable":"Записывать видео","MainFormat":"Основной поток","ExtraFormat":"Дополнительный поток",
    "Brightness":"Яркость","Contrast":"Контраст","Saturation":"Насыщенность","Sharpness":"Резкость",
    "Mirror":"Зеркально","Flip":"Перевернуть","ChannelTitle":"Имя канала","TimeTitle":"Время на изображении",
    "EncodeBlend":"Наложение в записи","PreviewBlend":"Наложение в просмотре","Name":"Название", "Rect":"Положение",
    "BackColor":"Цвет фона","FrontColor":"Цвет текста","Blend":"Прозрачность","AutoRebootDay":"День перезагрузки",
    "AutoRebootHour":"Час перезагрузки","AutoDeleteFilesDays":"Удалять файлы старше, дней","UserName":"Логин канала",
    "Port":"Порт","Protocol":"Протокол","Channel":"Канал","Interval":"Интервал","Delay":"Задержка, с",
    "MachineName":"Имя устройства","SpareAddress":"Резервный DNS","RelativePos":"Положение, 0–8192","Hue":"Оттенок",
    "UpdatePeriod":"Синхронизация, мин", "RTSPPort":"RTSP-порт", "RtspPort":"RTSP-порт",
}
ENUMS = {
    "RecordMode":["ConfigRecord","ManualRecord","ClosedRecord"],
    "HDDOverWrite":["OverWrite","StopRecord"],"OverWrite":["OverWrite","StopRecord"],
    "DateFormat":["YYMMDD","MMDDYY","DDMMYY"],"DateSeparator":["-","/","."],"TimeFormat":["24","12"],
    "BitRateControl":["CBR","VBR"],"AutoRebootDay":["Never","Everyday","Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"],
}
READ_ONLY = {"MAC","Mac","MACAddress","SerialNo","SerialNumber","Version","BuildTime","Hardware","Interface","Reserved"}
SECRET_PARTS = ("password","passwd","secret","token","encrypt","credential")


def _real_config(value):
    if isinstance(value,dict):
        return bool(value) and not ("Ret" in value or set(value)<= {"Name","SessionID"})
    return isinstance(value,list) and bool(value) and any(isinstance(v,(dict,list)) for v in value)


def _read_section(dvr, section):
    if section not in XM_SECTIONS:
        raise ValueError("Неизвестный раздел устройства")
    for name in XM_SECTIONS[section][1]:
        try:
            result=dvr.get_info(name)
            if isinstance(result,dict) and name in result: result=result[name]
            if _real_config(result): return name,result
        except (KeyError,TypeError,AttributeError):
            continue
    raise NotImplementedError("Устройство не предоставило этот раздел. Используйте его фирменный интерфейс.")


def _revision(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode()).hexdigest()


def _ip_display(value):
    if isinstance(value,str) and re.fullmatch(r"0x[0-9a-fA-F]{8}",value):
        return socket.inet_ntoa(struct.pack("<I",int(value,16)))
    return value



def network_display(value):
    """Presentation only: preserve the complete original configuration for patching."""
    if isinstance(value,list):return [network_display(v) for v in value]
    if isinstance(value,dict):
        return {key:network_display(item) if isinstance(item,(dict,list)) else _ip_display(item)
                for key,item in value.items()}
    return value


def describe_config(value, section, channel=None, ability=None):
    result=[]
    def walk(node,path=(),depth=0):
        if depth>12 or len(result)>=1000:return
        if isinstance(node,dict):
            for key,item in node.items():
                if any(s in key.lower() for s in SECRET_PARTS):continue
                walk(item,path+(key,),depth+1)
        elif isinstance(node,list):
            for i,item in enumerate(node):
                # Channel-based root arrays are constrained on the SERVER as well
                # as in the UI, so changing CH2 never patches CH1 by accident.
                if channel is not None and not path and i!=channel:continue
                walk(item,path+(i,),depth+1)
        elif isinstance(node,(str,int,float,bool)) and path:
            key=next((str(p) for p in reversed(path) if isinstance(p,str)),"")
            network=section in {"network","dhcp","dns","digital","ntp"}
            ip=network and (key in {"HostIP","Submask","GateWay","Gateway","Address","IP","IPAddress","PrimaryDNS","SecondaryDNS"} or re.fullmatch(r"0x[0-9a-fA-F]{8}",str(node)) is not None and section=="dns")
            schedule=any(p=="TimeSection" for p in path) and isinstance(node,str) and re.fullmatch(r"\d+ \d\d:\d\d:\d\d-\d\d:\d\d:\d\d",node)
            item={"path":list(path),"key":key,"label":LABELS.get(key,key),"value":_ip_display(node) if ip else node,
                  "type":"ip" if ip else "schedule" if schedule else "boolean" if isinstance(node,bool) else "number" if isinstance(node,(float,int)) else "text",
                  "editable":key not in READ_ONLY and key in LABELS}
            # Geometry, packed colors and bit masks are not writable through a
            # guessed text/numeric editor. Keep them in the merged wire object.
            opaque=key in {"FrontColor","BackColor","Blend","Rect","RelativePos","AlarmMask","DetectMask","RecordMask","TimeZone"} or "Covers" in path
            item["display"]=key in LABELS and not opaque
            if opaque:item["editable"]=False
            if section=="ntp" and key=="Name":item["label"]="NTP-сервер"
            if section=="dhcp" and isinstance(value,list) and isinstance(path[0],int):item["context"]=str(value[path[0]].get("Interface",f"Interface {path[0]+1}"))
            if schedule:item["editable"]=True
            if key in ENUMS and isinstance(node,str):item.update(type="select",options=list(dict.fromkeys([node,*ENUMS[key]])))
            if section=="encoder" and key in {"Compression","Resolution"}:
                # Decode only documented mask bits. Unknown/newer resolutions
                # remain visible as the current value; they are never invented.
                options=encoder_choices(ability,path,key,channel)
                item.update(type="select",options=list(dict.fromkeys([node,*options])),editable=bool(options))
            if item["type"]=="number":
                minimum,maximum=0,65535
                if key in {"TCPPort","HttpPort","HTTPPort","UDPPort","Port"}:minimum,maximum=1,65535
                elif key in {"FPS","FrameRate"}:minimum,maximum=-5,30
                elif key in {"Quality"}:minimum,maximum=1,6
                elif key=="PreRecord":maximum=30
                elif key=="PacketLength":minimum,maximum=1,120
                elif key=="RelativePos":maximum=8192
                elif key in {"Brightness","Contrast","Saturation","Sharpness"}:maximum=100
                elif key in {"AutoRebootHour"}:maximum=23
                elif key in {"AutoDeleteFilesDays"}:maximum=365
                elif key in {"TimeZone"}:minimum,maximum=0,33
                item.update(min=min(minimum,node),max=max(maximum,node),step=1)
            result.append(item)
    walk(value)
    return result


def encoder_choices(ability,path,key,channel):
    if not isinstance(ability,dict):return []
    stream="ExtraStream2" if "ExtraFormat" in path else "MainStream"
    info=next((v for v in ability.get("EncodeInfo",[]) if isinstance(v,dict) and v.get("StreamType")==stream and v.get("Enable") is True),{})
    mask=info.get("CompressionMask" if key=="Compression" else "ResolutionMask",0)
    if key=="Resolution":
        per_channel=ability.get("ExImageSizePerChannel" if stream!="MainStream" else "ImageSizePerChannel",[])
        if isinstance(per_channel,list) and channel is not None and channel<len(per_channel):mask=per_channel[channel]
    try:mask=int(mask,0) if isinstance(mask,str) else int(mask)
    except (TypeError,ValueError):return []
    values={7:"H.264"} if key=="Compression" else dict(enumerate(("D1","HD1","BCIF","CIF","QCIF","VGA","QVGA","SVCD","QQVGA")))
    return [value for bit,value in values.items() if mask&(1<<bit)]


def patch_config(current,section,changes,channel=None,ability=None):
    if not isinstance(changes,list) or not 1<=len(changes)<=1000:raise ValueError("Нет изменений для сохранения")
    descriptions={tuple(f["path"]):f for f in describe_config(current,section,channel,ability)}
    updated=copy.deepcopy(current)
    for change in changes:
        if not isinstance(change,dict) or not isinstance(change.get("path"),list):raise ValueError("Некорректное поле настройки")
        path=change["path"]
        if any(isinstance(p,bool) or not isinstance(p,(str,int)) for p in path):raise ValueError("Некорректный путь настройки")
        descriptor=descriptions.get(tuple(path))
        if not descriptor or not descriptor["editable"]:raise ValueError("Поле недоступно для изменения на выбранном канале")
        value=change.get("value");kind=descriptor["type"]
        target=updated
        for key in path[:-1]:target=target[key]
        original=target[path[-1]]
        if kind=="boolean":
            if not isinstance(value,bool):raise ValueError("Ожидается переключатель да/нет")
        elif kind=="number":
            value=number(value,descriptor["label"],descriptor["min"],descriptor["max"],integer=isinstance(original,int))
        elif kind=="select":
            if value not in descriptor["options"]:raise ValueError("Неизвестный вариант настройки")
        elif kind=="ip":
            try:value=str(ipaddress.IPv4Address(str(value)))
            except ValueError:raise ValueError("Некорректный IPv4-адрес") from None
            if isinstance(original,str) and original.startswith("0x"):value=f"0x{int.from_bytes(ipaddress.IPv4Address(value).packed,'little'):08X}"
        else:
            if not isinstance(value,str) or len(value)>255 or any(ord(c)<32 for c in value):raise ValueError("Некорректный текст настройки")
            if section=="ntp" and descriptor["key"]=="Name" and value and not re.fullmatch(r"(?=.{1,253}\.?$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*\.?",value):
                raise ValueError("NTP-сервер: укажите IP-адрес или DNS-имя без протокола и порта")
            if descriptor["key"]=="HostName" and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,62}",value):raise ValueError("Сетевое имя: латинские буквы, цифры, точка и дефис")
            if descriptor["key"] in {"BackColor","FrontColor"} and not re.fullmatch(r"0x[0-9A-Fa-f]{8}",value):raise ValueError("Цвет должен содержать 8 шестнадцатеричных цифр после 0x")
            if kind=="schedule":
                match=re.fullmatch(r"(\d+) (\d\d):(\d\d):(\d\d)-(\d\d):(\d\d):(\d\d)",value)
                if not match:raise ValueError("Некорректный интервал расписания")
                mask,h1,m1,s1,h2,m2,s2=map(int,match.groups())
                if not (0<=mask<=65535 and 0<=h1<=23 and 0<=m1<=59 and 0<=s1<=59 and 0<=h2<=24 and 0<=m2<=59 and 0<=s2<=59 and (h2<24 or m2==s2==0) and (mask==0 or (h1,m1,s1)<(h2,m2,s2))):
                    raise ValueError("Начало интервала должно быть раньше конца; время 00:00–24:00")
        target[path[-1]]=value
    return updated


def _has_flag(node, term):
    if isinstance(node,dict):return any((term in str(k).lower() and v is True) or _has_flag(v,term) for k,v in node.items())
    if isinstance(node,list):return any(_has_flag(v,term) for v in node)
    return False


def xm_capabilities(dvr,cam):
    info=check_dvr_reply(dvr.get_system_info())
    try:features=dvr.get_system_capabilities()
    except Exception:features={}
    ptz=_has_flag(features,"ptz")
    return dict(protocol="dvrip",system_info=plain(info),profiles=[],
                capabilities=dict(info=True,ptz=ptz,imaging=False,encoder=False,reboot=callable(getattr(dvr,"set_command",None)) and callable(getattr(dvr,"_wait_for_disconnect",None)),time=True,network=True,config=True,storage=True,users=callable(getattr(dvr,"getUsers",None))),
                sections=[dict(id=key,title=spec[0],supported=None) for key,spec in XM_SECTIONS.items()],
                notes=["Разделы проверяются при открытии. Изменяются только поля, фактически возвращённые выбранным устройством.","DVRIP управляет аналоговыми каналами через регистратор; операция применяется к выбранному каналу или всему устройству, как указано в форме."])


def xm_ptz(dvr,cam,data):
    action=data.get("action","stop");channel=int(number(data.get("channel",cam.get("channel",0)),"Канал",0,255,True))
    if action=="presets":return dict(presets=[],manual_presets=True)
    preset=number(data.get("preset_token",1) or 1,"Позиция",1,255,True)
    if action in {"goto","save","remove"}:
        command={"goto":"GotoPreset","save":"SetPreset","remove":"ClearPreset"}[action]
        check_dvr_reply(dvr.ptz(command,preset=preset,ch=channel))
        return dict(action=action,preset_token=str(preset))
    pan=number(data.get("pan",0),"pan",-1,1);tilt=number(data.get("tilt",0),"tilt",-1,1);zoom=number(data.get("zoom",0),"zoom",-1,1)
    command="ZoomTile" if zoom>0 else "ZoomWide" if zoom<0 else ("Direction"+("Left" if pan<0 else "Right" if pan>0 else "")+("Up" if tilt>0 else "Down" if tilt<0 else ""))
    if command=="Direction":command="DirectionUp"
    step=max(1,min(8,round(max(abs(pan),abs(tilt),abs(zoom),.2)*8)))
    params={"AUX":{"Number":0,"Status":"On"},"Channel":channel,"MenuOpts":"Enter","POINT":{"bottom":0,"left":0,"right":0,"top":0},"Pattern":"SetBegin","Preset":65535,"Step":step,"Tour":0}
    if action=="stop":params["Preset"]=-1;check_dvr_reply(dvr.set_command("OPPTZControl",{"Command":command,"Parameter":params}));return dict(action="stop")
    try:
        check_dvr_reply(dvr.set_command("OPPTZControl",{"Command":command,"Parameter":params}));time.sleep(.12)
    finally:
        params["Preset"]=-1
        check_dvr_reply(dvr.set_command("OPPTZControl",{"Command":command,"Parameter":params}))
    return dict(action="step",message="Короткий шаг PTZ выполнен; отправлена остановка")


def storage_inventory(dvr,cam):
    reply=dvr.send(1020,{"Name":"StorageInfo"})
    if not isinstance(reply,dict) or reply.get("Ret") not in (100,150):
        raise NotImplementedError("Устройство не предоставило StorageInfo")
    raw=reply.get("StorageInfo")
    if isinstance(raw,dict):raw=[raw]
    if not isinstance(raw,list):return []
    disks=[]
    for serial,disk in enumerate(raw):
        if not isinstance(disk,dict):continue
        physical=disk.get("PlysicalNo",disk.get("PhysicalNo",disk.get("SerialNo",serial)))
        try:physical=int(physical)
        except (ValueError,TypeError):continue
        partitions=disk.get("Partition") or disk.get("Partitions") or []
        if isinstance(partitions,dict):partitions=[partitions]
        for part_no,part in enumerate(partitions):
            if not isinstance(part,dict):continue
            def space(key):
                value=part.get(key,0)
                try:return int(value,0) if isinstance(value,str) else int(value)
                except (TypeError,ValueError):return 0
            total,free=space("TotalSpace"),space("RemainSpace")
            if total<=0:continue
            kind=str(disk.get("Type",part.get("DirverType",part.get("DriverType",""))))
            media="sd" if re.search(r"sd|tf|mmc",kind,re.I) else "hdd" if re.search(r"hdd|sata|disk",kind,re.I) else "storage"
            disks.append(dict(serial=physical,partition=int(part.get("PartNo",part_no)),kind=media,total_mb=total,free_mb=free,
                              status=str(part.get("Status",disk.get("Status","Устройство не сообщило"))),online=total>0,details=plain(part)))
    return disks


def register_xm_routes(app,runtime,endpoint,dvr_connect,client_for,service_for):
    @app.post("/api/device/config", endpoint="dev_api_device_config")
    @endpoint
    def config(cam,data):
        if cam.get("protocol")!="dvrip":raise NotImplementedError("Фирменные настройки доступны для XM/DVRIP; у ONVIF используйте соответствующие вкладки")
        section=str(data.get("section",""))
        channel=int(number(data.get("channel",cam.get("channel",0)),"Канал",0,255,True))
        dvr=dvr_connect(cam)
        try:
            name,current=_read_section(dvr,section)
            per_channel=section in {"recording","encoder","osd","imaging","digital"} and isinstance(current,list)
            selected=channel if per_channel else None
            if selected is not None and selected>=len(current):raise ValueError("Канал отсутствует в конфигурации устройства")
            revision=_revision(current)
            ability=None
            if section=="encoder":
                try:
                    answer=dvr.get_encode_capabilities()
                    if _real_config(answer):ability=answer
                except Exception:pass
            if "changes" in data:
                if data.get("confirm") is not True:raise ValueError("Подтвердите применение настроек устройства")
                if data.get("revision")!=revision:return {"error":"Настройки устройства изменились. Обновите форму перед сохранением."},409
                updated=patch_config(current,section,data["changes"],selected,ability)
                if section in {"network","dhcp","dns","digital"} and data.get("device_name") not in (cam.get("name"),site_device_name(runtime,cam)):
                    raise ValueError("Для изменения сети/цифровых каналов введите имя устройства")
                if section=="maintenance" and any("AutoDeleteFilesDays" in c["path"] and float(c.get("value",0))>0 for c in data["changes"]) and data.get("device_name") not in (cam.get("name"),site_device_name(runtime,cam)):
                    raise ValueError("Для включения автоматического удаления архива введите имя устройства")
                check_dvr_reply(dvr.set_info(name,updated))
                runtime.audit("device.config",f"device={cam['id']}; section={section}; channel={channel}")
                try:_,readback=_read_section(dvr,section)
                except Exception:return dict(section=section,saved=False,accepted=True,restart_required=section in {"network","dhcp","dns","digital"},message="Команда принята, но повторное чтение недоступно. Проверьте состояние устройства; при смене IP обновите подключение вручную.",fields=[],revision="")
                current=readback
                def value_at(value,path):
                    for key in path:value=value[key]
                    return value
                verified=all(value_at(readback,c["path"])==value_at(updated,c["path"]) for c in data["changes"])
            return dict(section=section,title=XM_SECTIONS[section][0],channel=channel,channel_count=len(current) if per_channel else None,
                        scope="channel" if per_channel else "interface" if section=="dhcp" else "device",revision=_revision(current),fields=describe_config(current,section,selected,ability),
                        saved=verified if "changes" in data else None,message=("Изменения подтверждены повторным чтением устройства" if verified else "Устройство приняло команду, но повторное чтение не подтвердило изменения. Проверьте настройки в фирменном интерфейсе.") if "changes" in data else "Неизвестные поля доступны только для чтения. Варианты кодека/разрешения подтверждаются EncodeCapability; числовые пределы соответствуют формату протокола и могут дополнительно ограничиваться прошивкой.")
        finally:dvr.close()

    @app.post("/api/device/storage", endpoint="dev_api_device_storage")
    @endpoint
    def storage(cam,data):
        if cam.get("protocol")!="dvrip":raise NotImplementedError("Универсальное форматирование ONVIF не определено. Откройте фирменный интерфейс; XM IP-камеру можно подключить по DVRIP.")
        dvr=dvr_connect(cam)
        try:
            disks=storage_inventory(dvr,cam)
            return dict(disks=disks,format_supported=bool(disks),warning="Форматирование HDD регистратора удалит записи ВСЕХ подключённых камер. Форматирование SD-карты удалит все записи с неё.")
        finally:dvr.close()

    @app.post("/api/device/storage/format", endpoint="dev_api_device_storage_format")
    @endpoint
    def format_storage(cam,data):
        if cam.get("protocol")!="dvrip":raise NotImplementedError("Форматирование поддерживается по DVRIP после проверки носителя")
        if data.get("confirm") is not True or data.get("confirmation")!="ERASE_ALL_RECORDINGS" or data.get("device_name") not in (cam.get("name"),site_device_name(runtime,cam)):
            raise ValueError("Подтвердите удаление записей всех камер и введите точное имя устройства")
        serial=int(number(data.get("serial"),"Носитель",0,255,True));partition=int(number(data.get("partition"),"Раздел",0,255,True))
        dvr=dvr_connect(cam)
        try:
            disks=storage_inventory(dvr,cam)
            if not any(d["serial"]==serial and d["partition"]==partition for d in disks):raise ValueError("Повторная проверка не подтвердила выбранный носитель. Форматирование не отправлено.")
            reply=dvr.send(1460,{"Name":"OPStorageManager","OPStorageManager":{"Action":"Clear","PartNo":partition,"SerialNo":serial}})
            check_dvr_reply(reply)
            runtime.audit("device.storage.format",f"device={cam['id']}; serial={serial}; partition={partition}")
            return dict(message="Устройство приняло команду форматирования. Дождитесь завершения и повторно прочитайте состояние носителя.")
        finally:dvr.close()

    @app.post("/api/device/users", endpoint="dev_api_device_users")
    @endpoint
    def users(cam,data):
        action=str(data.get("action","read"))
        if action not in {"read","create","update","password","delete"}:raise ValueError("Неизвестная операция с пользователями устройства")
        name=str(data.get("username","")).strip()
        if action!="read" and (not re.fullmatch(r"[A-Za-z0-9_.@-]{1,32}",name) or data.get("confirm") is not True):
            raise ValueError("Укажите логин устройства и подтвердите изменение")
        password=str(data.get("password", ""))
        if action in {"create","password"} and not 1<=len(password)<=128:raise ValueError("Укажите новый пароль длиной 1–128 символов")
        if action=="delete" and name==cam.get("username"):raise ValueError("Нельзя удалить учётную запись текущего подключения")
        if cam.get("protocol")=="dvrip":
            dvr=dvr_connect(cam)
            try:
                current=dvr.getUsers()
                if not isinstance(current,list):raise NotImplementedError("Устройство не предоставило список пользователей")
                if action!="read":
                    existing=next((u for u in current if u.get("Name")==name),None)
                    groups=dvr.getGroups()
                    group=str(data.get("group","user"))
                    if action in {"create","update"} and not any(g.get("Name")==group for g in groups):raise ValueError("Группа не существует на устройстве")
                    if action=="create":result=dvr.addUser(name,password,comment=str(data.get("comment",""))[:100],group=group)
                    elif action=="update":
                        if not existing:raise ValueError("Пользователь устройства не найден")
                        result=dvr.modifyUser(name,group=group,comment=str(data.get("comment",existing.get("Memo","")))[:100])
                    elif action=="password":
                        # Never substitute the recorder admin hash as another user's
                        # old password. The old password is explicitly supplied.
                        old=str(data.get("old_password", ""))
                        if not old:raise ValueError("Укажите прежний пароль пользователя устройства")
                        result=dvr.changePasswd(newpass=password,oldpass=dvr.sofia_hash(old),user=name)
                    else:
                        if not existing or existing.get("Reserved"):raise ValueError("Нельзя удалить отсутствующую или зарезервированную запись")
                        result=dvr.delUser(name)
                    check_dvr_reply(result);runtime.audit("device.users."+action,f"device={cam['id']}; user={name}")
                groups=dvr.getGroups()
                return dict(users=plain(dvr.getUsers() if action!="read" else current),groups=plain(groups),protocol="dvrip",
                            message="Ответ устройства получен. Некоторые прошивки требуют повторного входа после смены учётных данных.")
            finally:dvr.close()
        client=client_for(cam);device=service_for(client,"devicemgmt")
        group=data.get("group")
        if action=="password" and not group:
            existing=next((u for u in device.GetUsers() if str(field(u,"Username",""))==name),None)
            if existing is None:raise ValueError("Пользователь устройства не найден")
            group=str(field(existing,"UserLevel","User"))
        group=group or "User"
        if action in {"create","update","password"} and group not in {"Administrator","Operator","User"}:raise ValueError("Неизвестная роль ONVIF")
        if action=="create":device.CreateUsers({"User":[{"Username":name,"Password":password,"UserLevel":str(data.get("group","User"))}]})
        elif action=="update":device.SetUser({"User":[{"Username":name,"UserLevel":str(data.get("group","User"))}]})
        elif action=="password":device.SetUser({"User":[{"Username":name,"Password":password,"UserLevel":group}]})
        elif action=="delete":device.DeleteUsers({"Username":[name]})
        if action!="read":runtime.audit("device.users."+action,f"device={cam['id']}; user={name}")
        return dict(users=plain(device.GetUsers()),groups=[{"Name":n} for n in ("Administrator","Operator","User")],protocol="onvif")

    @app.post("/api/device/hostname", endpoint="dev_api_device_hostname")
    @endpoint
    def hostname(cam,data):
        if cam.get("protocol")!="onvif":raise NotImplementedError("Для XM используйте общие/сетевые настройки")
        name=str(data.get("hostname", ""))
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,62}",name):raise ValueError("Некорректное сетевое имя")
        device=service_for(client_for(cam),"devicemgmt")
        device.SetHostname({"Name":name})
        runtime.audit("device.hostname",f"device={cam['id']}")
        try:
            observed=field(device.GetHostname(),"Name")
            # DNS host labels are case-insensitive; do not require firmware to
            # preserve the capitalization used in the request.
            actual=observed.casefold() if isinstance(observed,str) else observed
            return dict(hostname=observed,**verified_write({"hostname":name.casefold()},{"hostname":actual}))
        except Exception:return dict(hostname=None,**verified_write({"hostname":name.casefold()}))

    @app.post("/api/device/onvif/ntp",endpoint="dev_api_device_onvif_ntp")
    @endpoint
    def onvif_ntp(cam,data):
        if cam.get("protocol")!="onvif":raise NotImplementedError("Для XM используйте раздел синхронизации времени")
        device=service_for(client_for(cam),"devicemgmt")
        current,clock,state=read_onvif_ntp(device)
        settings=data.get("settings")
        if settings is None:return state
        if not isinstance(settings,dict) or set(settings)-{"from_dhcp","servers","enabled"}:raise ValueError("Неизвестные параметры NTP")
        if data.get("confirm") is not True:raise ValueError("Подтвердите изменение синхронизации времени")
        if data.get("revision")!=state["revision"]:return {"error":"Настройки NTP изменились. Обновите форму."},409
        if not state["writable"]:raise NotImplementedError("Устройство не подтвердило возможность SetNTP")
        from_dhcp=settings.get("from_dhcp",state["from_dhcp"])
        if not isinstance(from_dhcp,bool):raise ValueError("NTP DHCP: требуется переключатель")
        existing=list(field(current,"NTPManual",[]) or [])
        hosts=copy.deepcopy(existing)
        if "servers" in settings:
            servers=settings["servers"]
            if not isinstance(servers,list) or len(servers)>state["max_servers"]:raise ValueError("Превышен предел NTP-серверов устройства")
            wanted=[ntp_host(v) for v in servers]
            addresses=[ntp_address(v) for v in wanted]
            if len(set(addresses))!=len(addresses):raise ValueError("NTP-серверы не должны повторяться")
            # Reuse complete unchanged host objects, including vendor Extension.
            hosts=[copy.deepcopy(next((old for old in existing if ntp_address(old)==ntp_address(new)),new)) for new in wanted]
        mode_changed="enabled" in settings and settings["enabled"]!=state["enabled"]
        if "enabled" in settings and not isinstance(settings["enabled"],bool):raise ValueError("NTP: требуется логическое значение enabled")
        if mode_changed and not state["mode_writable"]:raise NotImplementedError("Режим синхронизации не подтверждён устройством")
        if settings.get("enabled",state["enabled"]) is True and not from_dhcp and not hosts:raise ValueError("Для ручного NTP укажите хотя бы один сервер")
        mode_payload=None
        if mode_changed:
            mode_payload={"DateTimeType":"NTP" if settings["enabled"] else "Manual","DaylightSavings":bool(field(clock,"DaylightSavings",False))}
            if field(clock,"TimeZone") is not None:mode_payload["TimeZone"]=copy.deepcopy(field(clock,"TimeZone"))
            if not settings["enabled"]:
                utc=field(clock,"UTCDateTime")
                date,value=field(utc,"Date"),field(utc,"Time")
                try:datetime(int(field(date,"Year")),int(field(date,"Month")),int(field(date,"Day")),int(field(value,"Hour")),int(field(value,"Minute")),int(field(value,"Second")))
                except (ValueError,TypeError):raise NotImplementedError("Без текущего UTC-времени нельзя безопасно отключить NTP") from None
                mode_payload["UTCDateTime"]=copy.deepcopy(utc)
        changed=from_dhcp!=state["from_dhcp"] or [ntp_address(v) for v in hosts]!=state["servers"]
        if not changed and not mode_changed:return dict(**state,saved=True,accepted=True,message="Нет изменений")
        try:
            if changed:device.SetNTP({"FromDHCP":from_dhcp,"NTPManual":hosts})
            if mode_payload:device.SetSystemDateAndTime(mode_payload)
        except Exception as exc:
            code=(str(getattr(exc,"code",""))+" "+str(exc)).lower()
            if any(v in code for v in ("actionnotsupported","optionalactionnotimplemented","notimplemented","not supported")):
                raise NotImplementedError("Устройство отклонило неподдерживаемую операцию NTP") from None
            raise
        runtime.audit("device.ntp",f"device={cam['id']}; servers={len(hosts)}; mode_changed={mode_changed}")
        try:
            _,_,readback=read_onvif_ntp(device)
            verified=readback["from_dhcp"]==from_dhcp and readback["servers"]==[ntp_address(v) for v in hosts] and (not mode_changed or readback["enabled"]==settings["enabled"])
        except Exception:
            readback=state;verified=False
        return dict(**readback,accepted=True,saved=bool(verified),verification_pending=not verified,message="NTP подтверждён повторным чтением" if verified else "Команда NTP отправлена, но повторное чтение не подтвердило изменения")

    @app.post("/api/device/onvif/network", endpoint="dev_api_device_onvif_network")
    @endpoint
    def onvif_network(cam,data):
        if cam.get("protocol")!="onvif":raise NotImplementedError("Используйте сетевые разделы XM")
        device=service_for(client_for(cam),"devicemgmt")
        interfaces=device.GetNetworkInterfaces() or []
        settings=data.get("settings")
        if settings is not None:
            if not isinstance(settings,dict) or set(settings)-{"token","dhcp","address","prefix","gateway","dns"}:raise ValueError("Неизвестные сетевые параметры")
            if data.get("confirm") is not True or data.get("device_name") not in (cam.get("name"),site_device_name(runtime,cam)):raise ValueError("Подтвердите смену сети и введите имя устройства")
            token=str(settings.get("token",""))
            if not any(str(field(i,"token",""))==token for i in interfaces):raise ValueError("Сетевой интерфейс не найден")
            dhcp=settings.get("dhcp")
            if not isinstance(dhcp,bool):raise ValueError("Укажите DHCP или статический адрес")
            ipv4={"Enabled":True,"DHCP":dhcp}
            if not dhcp:
                try:address=str(ipaddress.IPv4Address(str(settings.get("address",""))))
                except ValueError:raise ValueError("Некорректный статический IPv4-адрес") from None
                ipv4["Manual"]=[{"Address":address,"PrefixLength":number(settings.get("prefix"),"Префикс",1,32,True)}]
            dns=settings.get("dns",[])
            if not isinstance(dns,list) or len(dns)>2:raise ValueError("Укажите не более двух DNS")
            try:servers=[str(ipaddress.IPv4Address(str(s))) for s in dns if s]
            except ValueError:raise ValueError("Некорректный DNS-адрес") from None
            gateway=settings.get("gateway")
            if gateway:
                try:gateway=str(ipaddress.IPv4Address(str(gateway)))
                except ValueError:raise ValueError("Некорректный шлюз") from None
            original=next(i for i in interfaces if str(field(i,"token",""))==token)
            original_cfg=field(field(original,"IPv4",{}),"Config",{})
            manual=plain(field(original_cfg,"Manual",[])) or []
            interface_changed=field(original_cfg,"DHCP")!=dhcp
            if not dhcp:
                # The form changes the primary IPv4 address, preserving additional
                # addresses that are not represented by its single address field.
                desired=ipv4["Manual"][0]
                interface_changed=interface_changed or not manual or any(manual[0].get(k)!=v for k,v in desired.items())
                ipv4["Manual"]=[desired,*manual[1:]]
            expected_dns=None;dns_changed=False;expected_gateway=None;gateway_changed=False
            if "dns" in settings:
                before_dns=plain(device.GetDNS())
                existing_dns=before_dns.get("DNSManual",[]) or []
                expected_dns={"FromDHCP":bool(dhcp and not servers),"DNSManual":[{"Type":"IPv4","IPv4Address":v} for v in servers]+[v for v in existing_dns if v.get("Type")!="IPv4"]}
                dns_changed=any(before_dns.get(k,False if k=="FromDHCP" else [])!=v for k,v in expected_dns.items())
            if gateway:
                expected_gateway=[gateway]
                gateway_changed=plain(device.GetNetworkDefaultGateway()).get("IPv4Address",[])!=expected_gateway
            # Validate/read everything before the first write. Name services first:
            # changing an interface may immediately move the device to another IP.
            if dns_changed:device.SetDNS(expected_dns)
            if gateway_changed:device.SetNetworkDefaultGateway({"IPv4Address":expected_gateway})
            response=None
            if interface_changed:response=device.SetNetworkInterfaces({"InterfaceToken":token,"NetworkInterface":{"IPv4":ipv4}})
            changed=interface_changed or dns_changed or gateway_changed
            if not changed:return dict(saved=True,accepted=True,restart_required=False,message="Нет изменений")
            runtime.audit("device.network",f"device={cam['id']}; dhcp={dhcp}")
            try:
                after=next(i for i in device.GetNetworkInterfaces() if str(field(i,"token",""))==token)
                after_cfg=plain(field(field(after,"IPv4",{}),"Config",{}))
                verified=not interface_changed or after_cfg.get("DHCP")==dhcp and (dhcp or after_cfg.get("Manual")==ipv4["Manual"])
                if dns_changed:
                    observed_dns=plain(device.GetDNS())
                    verified=verified and all(observed_dns.get(k)==v for k,v in expected_dns.items())
                if gateway_changed:verified=verified and plain(device.GetNetworkDefaultGateway()).get("IPv4Address")==expected_gateway
            except Exception:
                verified=False
            return dict(saved=bool(verified),accepted=True,verification_pending=not verified,restart_required=bool(field(response,"RebootNeeded",False)),message="Изменения подтверждены повторным чтением устройства" if verified else "Команды отправлены, но повторное чтение не подтвердило изменения. При смене адреса обновите IP подключения и проверьте устройство.")

        result=dict(interfaces=plain(interfaces),dns=None,gateway=None,protocols=None)
        for key,method in (("dns","GetDNS"),("gateway","GetNetworkDefaultGateway"),("protocols","GetNetworkProtocols")):
            try:result[key]=plain(getattr(device,method)())
            except Exception:pass
        return result

    @app.post("/api/onvif/profiles", endpoint="dev_api_onvif_profiles")
    def profiles():
        if not runtime.current_user() or runtime.current_user().get("role")!="admin":return jsonify(error="Доступ запрещён"),403
        data=request.get_json(silent=True)
        if not isinstance(data,dict):return jsonify(error="Ожидается JSON-объект"),400
        existing=runtime.get_camera(str(data.get("id", "")))
        cam={**(existing or {}),**{k:data[k] for k in ("ip","port","username") if k in data},"protocol":"onvif"}
        if data.get("password"):cam["password"]=runtime.enc_pwd(str(data["password"]))
        if not cam.get("ip"):return jsonify(error="Укажите адрес камеры"),400
        try:
            from urllib.parse import urlsplit
            client=connect_onvif(runtime,cam);media=client.create_media_service();result=[]
            for profile in media.GetProfiles() or []:
                token=str(field(profile,"token",""));uri=media.GetStreamUri({"StreamSetup":{"Stream":"RTP-Unicast","Transport":{"Protocol":"RTSP"}},"ProfileToken":token})
                parsed=urlsplit(str(field(uri,"Uri","")))
                result.append(dict(token=token,name=str(field(profile,"Name",token)),rtsp_port=parsed.port or 554,rtsp_path=parsed.path+("?"+parsed.query if parsed.query else "")))
            return jsonify(success=True,profiles=result)
        except Exception:return jsonify(error="ONVIF-служба не предоставила профили. Проверьте адрес, порт и учётные данные."),502

