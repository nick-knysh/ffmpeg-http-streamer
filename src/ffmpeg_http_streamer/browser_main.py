"""Entry point for in-browser library browsing + HLS playback."""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

from . import constants, network, validation
from .browse_app import BrowserApp
from .browser_server import run_web_server


def parse_args():
    parser = argparse.ArgumentParser(
        description="FFmpeg HTTP browser (library UI + per-stream ports)",
    )
    parser.add_argument(
        "-p",
        "--web-port",
        type=int,
        required=True,
        help="Web UI port (49152-65535).",
    )
    parser.add_argument(
        "--library",
        type=str,
        required=True,
        help="Absolute path to the directory containing videos.",
    )
    parser.add_argument(
        "-d",
        "--cache-dir",
        type=str,
        default=str(Path.home() / ".cache" / "ffmpeg-http-browser"),
        help="Directory for HLS cache (created if missing).",
    )
    parser.add_argument(
        "-t",
        "--transcode",
        action="store_true",
        help="Transcode to H.264/AAC when needed (like ffmpeg-http-streamer).",
    )
    parser.add_argument(
        "--stream-port-min",
        type=int,
        default=constants.DEFAULT_STREAM_PORT_MIN,
        help="First port to try for HLS stream servers.",
    )
    parser.add_argument(
        "--stream-port-max",
        type=int,
        default=constants.DEFAULT_STREAM_PORT_MAX,
        help="Last port to try for HLS stream servers.",
    )
    parser.add_argument(
        "--max-streams",
        type=int,
        default=8,
        help="Maximum concurrent stream sessions.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        print(
            "Error: FFmpeg or FFprobe is not installed or not in PATH.",
            file=sys.stderr,
        )
        sys.exit(1)

    port = args.web_port
    if not constants.PORT_RANGE_START <= port <= constants.PORT_RANGE_END:
        print(
            f"Error: the port must be between "
            f"{constants.PORT_RANGE_START}-{constants.PORT_RANGE_END}.",
            file=sys.stderr,
        )
        sys.exit(1)
    if not network.is_port_free_any_host(port):
        print(f"Error: Port {port} is already in use.", file=sys.stderr)
        sys.exit(1)

    library = str(Path(args.library).resolve())
    if not Path(library).is_dir():
        print("Error: --library must be an existing directory.", file=sys.stderr)
        sys.exit(1)

    cache_dir = str(Path(args.cache_dir).resolve())
    if not validation.is_valid_directory(cache_dir):
        sys.exit(1)

    if args.stream_port_min > args.stream_port_max:
        print("Error: stream-port-min must be <= stream-port-max.", file=sys.stderr)
        sys.exit(1)

    app = BrowserApp(
        Path(library),
        Path(cache_dir),
        args.transcode,
        args.web_port,
        args.stream_port_min,
        args.stream_port_max,
        args.max_streams,
    )

    server, thread = run_web_server(app, "0.0.0.0", args.web_port)
    time.sleep(0.3)

    pip = network.get_private_ip()
    print("Web UI (library browse + player):")
    print(f"  http://127.0.0.1:{args.web_port}/")
    if pip:
        print(f"  http://{pip}:{args.web_port}/")
    print("Press Ctrl+C to stop.\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        app.shutdown_all_streams()
        app.terminate_all_encodes()
        try:
            server.shutdown()
        except OSError:
            pass
        thread.join(timeout=5)
        print("Stopped.")


if __name__ == "__main__":
    main()
