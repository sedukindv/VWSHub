"""Public locale metadata and persisted preference validation."""
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

LOCALES = (
    ("ru", "Русский"), ("en", "English"), ("ar", "العربية"),
    ("be", "Беларуская"), ("bn", "বাংলা"), ("cs", "Čeština"),
    ("da", "Dansk"), ("nl", "Nederlands"), ("fa", "فارسی"),
    ("fi", "Suomi"), ("fr", "Français"), ("de", "Deutsch"),
    ("hi", "हिन्दी"), ("hu", "Magyar"), ("id", "Bahasa Indonesia"),
    ("it", "Italiano"), ("ja", "日本語"), ("ko", "한국어"),
    ("zh-CN", "简体中文"), ("nb-NO", "Norsk bokmål"), ("pl", "Polski"),
    ("pt-BR", "Português (Brasil)"), ("es", "Español"), ("sv", "Svenska"),
    ("zh-TW", "繁體中文"), ("tr", "Türkçe"), ("uk", "Українська"),
    ("vi", "Tiếng Việt"),
)
SUPPORTED_LOCALES = tuple(code for code, _ in LOCALES)
PUBLIC_LOCALES = [{"code": code, "name": name, "direction": "rtl" if code in ("ar", "fa") else "ltr"}
                  for code, name in LOCALES]


def timezone_preference(value):
    if value == "":
        return ""
    if not isinstance(value, str) or len(value) > 100:
        raise ValueError("Неизвестный часовой пояс IANA")
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("Неизвестный часовой пояс IANA") from None
    return value
