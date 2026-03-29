
"""Orchestration: library paths, HLS cache, encode jobs, stream sessions."""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from . import constants, network, streaming
from .probe_duration import probe_duration_seconds


def safe_resolve_under_root(root: Path, rel: str) -> Path:
    root = root.resolve()
    rel = rel.replace("\\", "/").strip("/")
    if rel == "" or rel == ".":
        return root
    if rel.startswith("..") or "/../" in f"/{rel}/":
        raise PermissionError("invalid path")
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as e:
        raise PermissionError("path outside library") from e
    return candidate


def cache_key_for_file(video_path: Path, transcode: bool) -> str:
    st = video_path.stat()
    mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))
    material = "\0".join(
        [
            str(video_path.resolve()),
            str(mtime_ns),
            str(st.st_size),
            "1" if transcode else "0",
            constants.CACHE_PROFILE_VERSION,
        ],
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def is_cache_complete(cache_dir: Path) -> bool:
    m3u8 = cache_dir / "stream.m3u8"
    if not m3u8.is_file():
        return False
    text = m3u8.read_text(encoding="utf-8", errors="replace")
    if "#EXT-X-ENDLIST" not in text:
        return False
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith(".ts"):
            seg = cache_dir / line
            if not seg.is_file():
                return False
    return True


class BrowserApp:
    def __init__(
        self,
        library_root: Path,
        cache_root: Path,
        transcode: bool,
        web_port: int,
        stream_port_min: int,
        stream_port_max: int,
        max_streams: int,
    ) -> None:
        self.library_root = library_root.resolve()
        self.cache_root = cache_root.resolve()
        self.transcode = transcode
        self.web_port = web_port
        self.stream_port_min = stream_port_min
        self.stream_port_max = stream_port_max
        self.max_streams = max_streams
        self._global_lock = threading.Lock()
        self._key_locks: Dict[str, threading.Lock] = {}
        self._encode_procs: Dict[str, Any] = {}
        self._sessions: Dict[str, Dict[str, Any]] = {}

    def _lock_for_key(self, key: str) -> threading.Lock:
        with self._global_lock:
            if key not in self._key_locks:
                self._key_locks[key] = threading.Lock()
            return self._key_locks[key]

    def list_browse(self, rel_path: str) -> Dict[str, Any]:
        base = safe_resolve_under_root(self.library_root, rel_path)
        if not base.is_dir():
            return {"error": "not a directory"}
        dirs = []
        videos = []
        for child in sorted(base.iterdir(), key=lambda p: p.name.lower()):
            if child.name.startswith("."):
                continue
            if child.is_dir():
                dirs.append(child.name)
            elif child.is_file():
                if child.suffix.lower() in constants.VIDEO_EXTENSIONS:
                    rel = str(child.relative_to(self.library_root)).replace("\\", "/")
                    videos.append(rel)
        return {"directories": dirs, "videos": videos, "path": rel_path}

    def _find_stream_port(self) -> Optional[int]:
        for port in range(self.stream_port_min, self.stream_port_max + 1):
            if port == self.web_port:
                continue
            if network.is_port_free_any_host(port):
                return port
        return None

    def _finalize_encode(self, key: str, cache_dir: Path, proc: Any, source: Path) -> None:
        code = proc.wait()
        with self._lock_for_key(key):
            cur = self._encode_procs.get(key)
            if cur is proc:
                self._encode_procs.pop(key, None)
        if code != 0:
            return
        if not is_cache_complete(cache_dir):
            return
        meta = {
            "duration": probe_duration_seconds(str(source)),
            "source": str(source.resolve()),
        }
        try:
            (cache_dir / constants.READY_MARKER_NAME).write_text(
                json.dumps(meta),
                encoding="utf-8",
            )
        except OSError:
            pass

    def ensure_encoding(self, video_path: Path, cache_dir: Path, key: str) -> Any:
        if is_cache_complete(cache_dir):
            return None
        lock = self._lock_for_key(key)
        with lock:
            proc = self._encode_procs.get(key)
            if proc is not None and proc.poll() is None:
                return proc
            m3u8 = cache_dir / "stream.m3u8"
            if m3u8.is_file():
                text = m3u8.read_text(encoding="utf-8", errors="replace")
                if "#EXT-X-ENDLIST" not in text:
                    streaming.clear_partial_hls_output(str(cache_dir))
            cache_dir.mkdir(parents=True, exist_ok=True)
            proc = streaming.run_ffmpeg_progressive_cache_process(
                str(cache_dir),
                self.transcode,
                str(video_path),
            )
            if proc is None:
                return None
            self._encode_procs[key] = proc
            t = threading.Thread(
                target=self._finalize_encode,
                args=(key, cache_dir, proc, video_path),
                daemon=True,
            )
            t.start()
            return proc

    def play(
        self,
        rel_video: str,
        host_header: Optional[str],
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        if len(self._sessions) >= self.max_streams:
            return None, "max concurrent streams reached"
        try:
            video_path = safe_resolve_under_root(self.library_root, rel_video)
        except PermissionError as e:
            return None, str(e)
        if not video_path.is_file():
            return None, "not a file"
        ext = video_path.suffix.lower()
        if ext not in constants.VIDEO_EXTENSIONS:
            return None, "not a supported video type"
        duration = probe_duration_seconds(str(video_path))
        key = cache_key_for_file(video_path, self.transcode)
        cache_dir = self.cache_root / key
        cache_dir.mkdir(parents=True, exist_ok=True)
        proc = self.ensure_encoding(video_path, cache_dir, key)
        if not is_cache_complete(cache_dir):
            if proc is None:
                return None, "failed to start transcoder"
            ok = streaming.wait_first_playable_segment(str(cache_dir), proc, timeout_s=300)
            if not ok:
                return None, "timeout waiting for first HLS segment"
        stream_port = self._find_stream_port()
        if stream_port is None:
            return None, "no free stream port in range"
        server, thread = streaming.run_cors_http_server_process(
            "0.0.0.0",
            stream_port,
            str(cache_dir),
        )
        if server is None:
            return None, "failed to start stream HTTP server"
        sid = str(uuid.uuid4())
        self._sessions[sid] = {
            "server": server,
            "thread": thread,
            "port": stream_port,
            "cache_key": key,
        }
        host = host_header or network.get_private_ip() or "127.0.0.1"
        if ":" in host:
            host = host.split("[", 1)[-1].split("]", 1)[0]
        playlist_url = f"http://{host}:{stream_port}/stream.m3u8"
        return {
            "streamId": sid,
            "playlistUrl": playlist_url,
            "durationSec": duration,
            "cacheKey": key,
        }, None

    def stop_stream(self, stream_id: str) -> Tuple[bool, Optional[str]]:
        with self._global_lock:
            sess = self._sessions.pop(stream_id, None)
        if not sess:
            return False, "unknown stream"
        server = sess["server"]
        thread = sess["thread"]
        try:
            server.shutdown()
        except OSError:
            pass
        if thread.is_alive():
            thread.join(timeout=5)
        return True, None


    def shutdown_all_streams(self) -> None:
        with self._global_lock:
            ids = list(self._sessions.keys())
        for sid in ids:
            self.stop_stream(sid)

    def terminate_all_encodes(self) -> None:
        with self._global_lock:
            procs = list(self._encode_procs.items())
        for _key, proc in procs:
            if proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                except OSError:
                    pass

