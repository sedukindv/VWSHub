"""Bounded, credential-free diagnostics for hardware integration reports."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone

from .store import protected

SENSITIVE = re.compile(r"password|passwd|secret|credential|token|authorization|cookie|camkey", re.I)


def scrub(value):
    if isinstance(value, dict):
        return {str(k): scrub(v) for k, v in value.items() if not SENSITIVE.search(str(k))}
    if isinstance(value, (list, tuple)):
        return [scrub(v) for v in value[:100]]
    if isinstance(value, str):
        value = re.sub(r"(\w+://)[^\s/@]+(?::[^\s/@]*)?@", r"\1[redacted]@", value)
        value = re.sub(r"([?&](?:password|token|auth|key)=)[^&\s]+", r"\1[redacted]", value, flags=re.I)
        return value.replace("\r", " ").replace("\n", " ")[:600]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return type(value).__name__


class HardwareJournal:
    def __init__(self, store):
        self.store = store
        self.path = store.base_dir / "hardware.jsonl"

    def record(self, event, camera=None, level="info", **details):
        """Never pass raw protocol packets, configuration objects or exceptions."""
        try:
            if not self.store.get_settings().get("diagnostics", {}).get("enabled", True):
                return
            device = {k: camera[k] for k in ("id", "recorder_id", "protocol", "ip", "port", "channel") if camera and k in camera}
            entry = {
                "time": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "level": level if level in {"info", "warning", "error"} else "info",
                "event": str(event)[:100], "device": scrub(device), "detail": scrub(details),
            }
            with self.store.lock:
                if self.path.exists() and self.path.stat().st_size >= 2_000_000:
                    for i in (2, 1):
                        old = self.path.with_name(self.path.name + f".{i}")
                        if old.exists(): os.replace(old, self.path.with_name(self.path.name + f".{i + 1}"))
                    os.replace(self.path, self.path.with_name(self.path.name + ".1"))
                with self.path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(entry, ensure_ascii=False, allow_nan=False) + "\n")
                protected(self.path)
        except (OSError, ValueError):
            # A full/read-only diagnostics disk must not interrupt a video stream.
            return

    def entries(self, limit=300):
        result = []
        with self.store.lock:
            for path in [self.path] + [self.path.with_name(self.path.name + f".{i}") for i in (1, 2, 3)]:
                if not path.exists(): continue
                for line in reversed(path.read_text(encoding="utf-8").splitlines()):
                    try:
                        entry=json.loads(line)
                        if isinstance(entry,dict):result.append(entry)
                    except ValueError: continue
                    if len(result) >= limit: return result
        return result

    def clear(self):
        with self.store.lock:
            for path in [self.path] + [self.path.with_name(self.path.name + f".{i}") for i in (1, 2, 3)]:
                if path.exists(): path.unlink()
