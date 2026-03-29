import socket
import subprocess
import sys
import threading
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from . import constants


def delete_stream_files(streaming_directory):
    target_extensions = (".ts", ".m3u", ".m3u8")
    deleted_count = 0
    undeleted_count = 0

    try:
        for filename in Path(streaming_directory).iterdir():
            if str(filename).lower().endswith(target_extensions):
                file_path = Path(streaming_directory) / filename
                try:
                    if Path(file_path).is_file():
                        Path(file_path).unlink()
                        deleted_count += 1
                except Exception as e:
                    print(
                        f"⚠️  Notice: Impossible to delete the file '{file_path}'. Reason: {e}.",
                        file=sys.stderr,
                    )
                    undeleted_count += 1

    except PermissionError:
        print(
            f"Error: insufficient permissions to read from the directory '{streaming_directory}'.",
            file=sys.stderr,
        )
        return False

    if undeleted_count > 0:
        print(f"{deleted_count} deleted stream files.")
        print(f"Error: {undeleted_count} undeleted stream files.", file=sys.stderr)
        return False

    if deleted_count > 0:
        print(f"{deleted_count} deleted stream files.")
    else:
        print("No stream files to delete found.")
    return True


def has_codec(stream_type, address, target_codec):
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-select_streams",
        stream_type,
        "-show_entries",
        "stream=codec_name",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        address,
    ]

    output = subprocess.check_output(cmd, text=True, timeout=60).strip()
    if not output:
        return (False, 0)

    codecs = output.lower().splitlines()

    if target_codec.lower() in codecs:
        return (True, len(codecs))
    return (False, len(codecs))


def transcode_maps_for_input(address):
    try:
        has_codec_video, num_codec_video = has_codec("v", address, "h264")
        if has_codec_video is False and num_codec_video == 0:
            raise ValueError("the input doesn't have a codec video.")
        elif has_codec_video is False and num_codec_video > 0:
            print("Adding video track: h264.")
    except Exception as e:
        raise ValueError(
            f"it isn't possible to check the input codec video: {e}",
        ) from e

    try:
        has_codec_audio, num_codec_audio = has_codec("a", address, "aac")
        if has_codec_audio is False and num_codec_audio == 0:
            print("The input doesn't have a codec audio.")
        elif has_codec_audio is False and num_codec_audio > 0:
            print("Adding audio track: aac.")
    except Exception as e:
        raise ValueError(
            f"it isn't possible to check the input codec audio: {e}",
        ) from e

    codecs = []
    if has_codec_video and has_codec_audio:
        codecs = ["-map", "0", "-c", "copy"]
    elif has_codec_video and (has_codec_audio is False and num_codec_audio):
        codecs = [
            "-map",
            "0:v?",
            "-map",
            "0:a?",
            "-map",
            "0:a:0?",
            "-map",
            "0:s?",
            "-map",
            "0:d?",
            "-map",
            "0:t?",
            "-c:v",
            "copy",
            "-c:a",
            "copy",
            f"-c:a:{num_codec_audio}",
            "aac",
            f"-ac:a:{num_codec_audio}",
            "2",
            f"-b:a:{num_codec_audio}",
            "192k",
            "-c:s",
            "copy",
            "-c:d",
            "copy",
            "-c:t",
            "copy",
        ]
    elif has_codec_video and (has_codec_audio is False and num_codec_audio == 0):
        codecs = ["-map", "0", "-c", "copy"]
    elif (has_codec_video is False and num_codec_video) and has_codec_audio:
        codecs = [
            "-map",
            "0:v?",
            "-map",
            "0:v:0?",
            "-map",
            "0:a?",
            "-map",
            "0:s?",
            "-map",
            "0:d?",
            "-map",
            "0:t?",
            "-c:v",
            "copy",
            f"-c:v:{num_codec_video}",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "23",
            "-c:a",
            "copy",
            "-c:s",
            "copy",
            "-c:d",
            "copy",
            "-c:t",
            "copy",
        ]
    elif (has_codec_video is False and num_codec_video) and (
        has_codec_audio is False and num_codec_audio
    ):
        codecs = [
            "-map",
            "0:v?",
            "-map",
            "0:v:0?",
            "-map",
            "0:a?",
            "-map",
            "0:a:0?",
            "-map",
            "0:s?",
            "-map",
            "0:d?",
            "-map",
            "0:t?",
            "-c:v",
            "copy",
            f"-c:v:{num_codec_video}",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "23",
            "-c:a",
            "copy",
            f"-c:a:{num_codec_audio}",
            "aac",
            f"-ac:a:{num_codec_audio}",
            "2",
            f"-b:a:{num_codec_audio}",
            "192k",
            "-c:s",
            "copy",
            "-c:d",
            "copy",
            "-c:t",
            "copy",
        ]

    elif (has_codec_video is False and num_codec_video) and (
        has_codec_audio is False and num_codec_audio == 0
    ):
        codecs = [
            "-map",
            "0:v?",
            "-map",
            "0:v:0?",
            "-map",
            "0:s?",
            "-map",
            "0:d?",
            "-map",
            "0:t?",
            "-c:v",
            "copy",
            f"-c:v:{num_codec_video}",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "23",
            "-an",
            "-c:s",
            "copy",
            "-c:d",
            "copy",
            "-c:t",
            "copy",
        ]

    return codecs




def transcode_input(address):
    try:
        return transcode_maps_for_input(address)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def run_python_http_server_process(bind_host, port, streaming_directory):
    class CustomHTTPRequestHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=streaming_directory, **kwargs)

    try:
        server = HTTPServer((bind_host, port), CustomHTTPRequestHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()

        connect_host = "127.0.0.1" if bind_host in ("0.0.0.0", "") else bind_host
        start_time = time.time()
        while time.time() - start_time < constants.PROCESS_STARTUP_TIMEOUT_S:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(1)
                result = sock.connect_ex((connect_host, port))
                if result == 0:
                    print(f"HTTP Server started (port: {port})")
                    return server, server_thread

            time.sleep(0.5)

    except OSError as e:
        if e.errno == constants.EADDRINUSE:
            print(f"Error: Port {port} already in use.", file=sys.stderr)
        else:
            print(
                f"Error: HTTP Server stops during the starting with error: {e}",
                file=sys.stderr,
            )
        return None, None
    except Exception as e:
        print(
            f"Error: HTTP Server stops during the starting with error: {e}",
            file=sys.stderr,
        )
        return None, None

    else:
        return None, None


def run_ffmpeg_process(private_ip, port, streaming_directory, transcode, address):
    codecs = ["-map", "0", "-c", "copy"]
    if transcode:
        codecs = transcode_input(address)

    base_url = f"http://{private_ip}:{port}/"
    output_m3u8 = Path(streaming_directory) / "stream.m3u8"

    output_m3u = Path(streaming_directory) / "stream.m3u"
    m3u8_url = f"{base_url}stream.m3u8"
    with output_m3u.open("w") as f:
        f.write("#EXTM3U\n")
        f.write("#EXTINF:-1,Stream Video\n")
        f.write(f"{m3u8_url}\n")

    command = [
        "ffmpeg",
        "-re",
        "-i",
        address,
        "-sn",
        *codecs,
        "-f",
        "hls",
        "-hls_time",
        "10",
        "-hls_list_size",
        "24",
        "-hls_flags",
        "delete_segments+independent_segments",
        "-hls_base_url",
        base_url,
        "-hls_allow_cache",
        "1",
        "-hls_segment_type",
        "mpegts",
        "-loglevel",
        "info",
        output_m3u8,
    ]

    try:
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL)
    except OSError as e:
        if isinstance(e, FileNotFoundError):
            print("Error: The FFmpeg command wasn't found.", file=sys.stderr)
            return None
        print(
            f"Error: a problem during FFmpeg command startup: {e}.",
            file=sys.stderr,
        )
        return None

    print(f"FFmpeg process starts with PID: {process.pid}.\n")

    start_time = time.time()
    while time.time() - start_time < constants.PROCESS_STARTUP_TIMEOUT_S:
        return_code = process.poll()
        if return_code is not None:
            print(f"\nReturn code FFmpeg: {process.returncode}", file=sys.stderr)

            if process.returncode != 0:
                print(
                    f"Error: FFmpeg stops prematurely due to a generic error (code={process.returncode}). Check the stderr traceback.",
                    file=sys.stderr,
                )
            else:
                print(
                    "Error: FFmpeg stops prematurely without any error.",
                    file=sys.stderr,
                )
            return None
        time.sleep(0.5)

    return process



def build_progressive_cache_hls_command(address, streaming_directory, transcode):
    codecs = ["-map", "0", "-c", "copy"]
    if transcode:
        codecs = transcode_maps_for_input(address)
    output_m3u8 = Path(streaming_directory) / "stream.m3u8"
    return [
        "ffmpeg",
        "-i",
        address,
        "-sn",
        *codecs,
        "-f",
        "hls",
        "-hls_time",
        "10",
        "-hls_list_size",
        "0",
        "-hls_playlist_type",
        "event",
        "-hls_flags",
        "independent_segments",
        "-hls_segment_type",
        "mpegts",
        "-loglevel",
        "info",
        str(output_m3u8),
    ]


def clear_partial_hls_output(streaming_directory):
    d = Path(streaming_directory)
    for p in d.glob("*.ts"):
        try:
            p.unlink()
        except OSError:
            pass
    for name in ("stream.m3u8", "stream.m3u"):
        p = d / name
        if p.is_file():
            try:
                p.unlink()
            except OSError:
                pass
    ready = d / constants.READY_MARKER_NAME
    if ready.is_file():
        try:
            ready.unlink()
        except OSError:
            pass


def run_ffmpeg_progressive_cache_process(streaming_directory, transcode, address):
    command = build_progressive_cache_hls_command(
        address,
        streaming_directory,
        transcode,
    )
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as e:
        if isinstance(e, FileNotFoundError):
            print("Error: The FFmpeg command wasn't found.", file=sys.stderr)
            return None
        print(
            f"Error: a problem during FFmpeg command startup: {e}.",
            file=sys.stderr,
        )
        return None

    print(f"FFmpeg (progressive cache) PID: {process.pid}.")

    start_time = time.time()
    while time.time() - start_time < constants.PROCESS_STARTUP_TIMEOUT_S:
        return_code = process.poll()
        if return_code is not None:
            print(f"\nReturn code FFmpeg: {process.returncode}", file=sys.stderr)
            if process.returncode != 0:
                print(
                    "Error: FFmpeg stopped during startup.",
                    file=sys.stderr,
                )
            else:
                print(
                    "Error: FFmpeg stopped prematurely without error.",
                    file=sys.stderr,
                )
            return None
        time.sleep(0.5)

    return process


def wait_first_playable_segment(streaming_directory, process, timeout_s=300):
    d = Path(streaming_directory)
    m3u8 = d / "stream.m3u8"
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if process.poll() is not None:
            return False
        if m3u8.is_file():
            text = m3u8.read_text(encoding="utf-8", errors="replace")
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.endswith(".ts"):
                    seg = d / line
                    if seg.is_file() and seg.stat().st_size > 0:
                        return True
        time.sleep(0.2)
    return False


def wait_ffmpeg_finish(process, timeout_s=None):
    if timeout_s is None:
        return process.wait()
    # Python 3.3+ wait with timeout via polling
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        code = process.poll()
        if code is not None:
            return code
        time.sleep(0.2)
    return None


def run_cors_http_server_process(bind_host, port, streaming_directory):
    class CORSRequestHandler(SimpleHTTPRequestHandler):
        def end_headers(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            super().end_headers()

        def log_message(self, format, *args):
            return

        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=streaming_directory, **kwargs)

    try:
        server = HTTPServer((bind_host, port), CORSRequestHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()

        connect_host = "127.0.0.1" if bind_host in ("0.0.0.0", "") else bind_host
        start_time = time.time()
        while time.time() - start_time < constants.PROCESS_STARTUP_TIMEOUT_S:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(1)
                result = sock.connect_ex((connect_host, port))
                if result == 0:
                    print(f"CORS HTTP Server started (port: {port})")
                    return server, server_thread

            time.sleep(0.5)

    except OSError as e:
        if e.errno == constants.EADDRINUSE:
            print(f"Error: Port {port} already in use.", file=sys.stderr)
        else:
            print(
                f"Error: HTTP Server stops during the starting with error: {e}",
                file=sys.stderr,
            )
        return None, None
    except Exception as e:
        print(
            f"Error: HTTP Server stops during the starting with error: {e}",
            file=sys.stderr,
        )
        return None, None

    else:
        return None, None
