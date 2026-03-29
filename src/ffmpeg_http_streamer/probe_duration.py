"""ffprobe helpers for browser mode."""

from __future__ import annotations

import json
import subprocess
from typing import Optional


def probe_duration_seconds(path: str) -> Optional[float]:
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        path,
    ]
    try:
        out = subprocess.check_output(cmd, text=True, timeout=120)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return None
    try:
        data = json.loads(out)
        dur = data.get("format", {}).get("duration")
        if dur is None:
            return None
        return float(dur)
    except (TypeError, ValueError):
        return None
