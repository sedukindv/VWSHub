"""Classify hardware failures without persisting credential-bearing exceptions."""
import socket


def failure_details(error=None, output=""):
    message = str(error or output).lower()
    if isinstance(error, (TimeoutError, socket.timeout)) or "timed out" in message:
        code, description = "timeout", "Истекло время ожидания устройства"
    elif any(term in message for term in ("401", "403", "unauthorized", "not authorized", "authentication", "wrong password", "авторизац")):
        code, description = "authentication", "Устройство отклонило авторизацию"
    elif any(term in message for term in ("unrecognized option", "option not found", "error setting option")):
        code, description = "ffmpeg_option", "Установленный FFmpeg не поддерживает параметр запуска"
    elif any(term in message for term in ("connection refused", "network is unreachable", "no route to host")) or isinstance(error, ConnectionError):
        code, description = "connection", "Нет соединения с сетевой службой устройства"
    elif any(term in message for term in ("codec", "invalid data", "could not find", "no video", "нет видеокадров")):
        code, description = "media_format", "Не удалось прочитать поддерживаемые медиаданные"
    else:
        code, description = "device_operation", "Операция устройства не завершена; причина не подтверждена"
    return {"error_code": code, "description": description,
            "error_type": type(error).__name__ if error else "FFmpegError"}
