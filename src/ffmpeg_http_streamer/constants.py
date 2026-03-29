import errno

VIDEO_EXTENSIONS = {
    ".mp4",
    ".mkv",
    ".avi",
    ".mov",
    ".flv",
    ".wmv",
    ".webm",
    ".mpeg",
    ".mpg",
    ".3gp",
    ".m4v",
    ".divx",
}


PORT_RANGE_START = 49152
PORT_RANGE_END = 65535


PROCESS_STARTUP_TIMEOUT_S = 20


EADDRINUSE = errno.EADDRINUSE

# Bumped when browser cache FFmpeg args change (invalidates cache dirs).
CACHE_PROFILE_VERSION = "1"

DEFAULT_STREAM_PORT_MIN = 49200
DEFAULT_STREAM_PORT_MAX = 65535

READY_MARKER_NAME = ".ready"
