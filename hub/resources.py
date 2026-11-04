"""One authoritative set of resource presets and validation rules."""
from copy import deepcopy

BOUNDS = {
    "max_live_streams": (1, 128), "max_archive_streams": (1, 16),
    "archive_buffer_mb": (2, 128), "archive_idle_seconds": (30, 600),
    "ffmpeg_threads": (0, 32),
}
PRESETS = {
    "minimal": dict(zip(BOUNDS, (4, 1, 8, 90, 1))),
    "standard": dict(zip(BOUNDS, (16, 4, 16, 180, 2))),
    "maximum": dict(zip(BOUNDS, (128, 16, 128, 600, 32))),
}


def configure(current, requested, integer):
    if not isinstance(requested, dict):
        raise ValueError("Некорректные ограничения ресурсов")
    profile = requested.get("profile", current.get("profile", "standard"))
    if not isinstance(profile, str) or profile not in {*PRESETS, "custom"}:
        raise ValueError("Неизвестный профиль ресурсов")
    supplied = {key: integer(requested[key], key, *bounds)
                for key, bounds in BOUNDS.items() if key in requested}
    # A preset-only request explicitly applies that preset. Partial/manual edits
    # retain the other current values and never silently overwrite them.
    if not requested:
        return deepcopy(current)
    if "profile" in requested and profile != "custom" and not supplied:
        chosen = deepcopy(PRESETS[profile])
    elif "profile" in requested and profile != "custom" and all(value == PRESETS[profile][key] for key, value in supplied.items()):
        chosen = deepcopy(PRESETS[profile])
    else:
        chosen = {key: current.get(key, PRESETS["standard"][key]) for key in BOUNDS}
        chosen.update(supplied)
        profile = "custom"
    return {**chosen, "profile": profile}
