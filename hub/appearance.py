"""Validate semantic theme colors without allowing arbitrary CSS values."""
import copy
import re

COLOR_KEYS = {"background", "surface", "surface_alt", "text", "text_soft", "muted", "line",
              "accent", "icon_color", "success", "warning", "danger", "info", "button_text"}


def theme_colors(value):
    if not isinstance(value, dict) or set(value) - {"light", "dark"}:
        raise ValueError("Оформление: ожидаются светлая и тёмная темы")
    for mode, colors in value.items():
        if not isinstance(colors, dict) or set(colors) - COLOR_KEYS:
            raise ValueError("Неизвестный параметр цвета темы")
        if any(not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color) for color in colors.values()):
            raise ValueError("Цвет: #RRGGBB")
    return copy.deepcopy(value)
