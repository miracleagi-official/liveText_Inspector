"""Dual-port raw receiver for liveTextApp + liveSpeaker testing.

Listens on:
- HOST/PORT: subtitle protocol (header + size + payload + ACK)
- EVENT_SERVER_HOST/EVENT_SERVER_PORT: liveSpeaker JSON-line stream

Payload is printed as received string. JSON parsing is intentionally omitted.
"""

from __future__ import annotations

import atexit
import os
import signal
import socket
import struct
import sys
import threading
import time
import traceback
from pathlib import Path

try:
    from dotenv import load_dotenv as _load_dotenv
except Exception:
    _load_dotenv = None

from etc import get_base_dir

_LOG_LOCK = threading.Lock()
_LOG_PATH = Path(get_base_dir()) / "test_recv_debug.log"
_SIGNAL_STOP = threading.Event()


def _log(message: str) -> None:
    line = f"[test_recv] {message}"
    print(line, flush=True)
    try:
        with _LOG_LOCK:
            _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with _LOG_PATH.open("a", encoding="utf-8", errors="replace") as fp:
                fp.write(line + "\n")
    except Exception:
        pass


def _log_exception(prefix: str, exc: BaseException) -> None:
    _log(f"{prefix}: {exc}")
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    try:
        with _LOG_LOCK:
            with _LOG_PATH.open("a", encoding="utf-8", errors="replace") as fp:
                fp.write(tb + "\n")
    except Exception:
        pass


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _load_env() -> None:
    base_dir = Path(get_base_dir())
    env_path = base_dir / ".env"
    if _load_dotenv is not None:
        if env_path.is_file():
            _load_dotenv(env_path, override=False)
        else:
            _load_dotenv(override=False)
        return

    if not env_path.is_file():
        return

    # Fallback parser when python-dotenv is unavailable.
    for raw_line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip('"').strip("'")


def _print_payload(raw: bytes) -> None:
    text = raw.decode("utf-8", errors="replace")
    if text.strip():
        print(text, flush=True)
        try:
            with _LOG_LOCK:
                with _LOG_PATH.open("a", encoding="utf-8", errors="replace") as fp:
                    fp.write(text + "\n")
        except Exception:
            pass


def _recv_exact(
    conn: socket.socket,
    size: int,
    stop_event: threading.Event,
) -> bytes | None:
    buf = bytearray()
    while len(buf) < size and not stop_event.is_set():
        try:
            chunk = conn.recv(size - len(buf))
        except socket.timeout:
            continue
        if not chunk:
            return None
        buf.extend(chunk)
    if len(buf) < size:
        return None
    return bytes(buf)


def _handle_subtitle_client(
    conn: socket.socket,
    addr: tuple[str, int],
    stop_event: threading.Event,
    resp_checkcode: int,
) -> None:
    _log(f"[subtitle] client connected: {addr}")
    conn.settimeout(1.0)
    try:
        while not stop_event.is_set():
            header = _recv_exact(conn, 8, stop_event)
            if not header:
                break
            _, req_code = struct.unpack("<ii", header)

            size_raw = _recv_exact(conn, 4, stop_event)
            if not size_raw:
                break
            (size,) = struct.unpack("<i", size_raw)
            if size < 0:
                break

            payload = _recv_exact(conn, size, stop_event)
            if payload is None:
                break

            _print_payload(payload)

            try:
                conn.sendall(struct.pack("<iiB", resp_checkcode, req_code, 0))
            except OSError:
                break
    except OSError as exc:
        _log(f"[subtitle] socket warning: {addr} -> {exc}")
    except Exception as exc:
        _log_exception(f"[subtitle] handler error for {addr}", exc)
    finally:
        _log(f"[subtitle] client disconnected: {addr}")


def _handle_event_client(
    conn: socket.socket,
    addr: tuple[str, int],
    stop_event: threading.Event,
) -> None:
    _log(f"[event] client connected: {addr}")
    buffer = b""
    conn.settimeout(1.0)
    try:
        while not stop_event.is_set():
            try:
                chunk = conn.recv(4096)
            except socket.timeout:
                continue
            except OSError as exc:
                _log(f"[event] socket warning: {addr} -> {exc}")
                break
            if not chunk:
                break

            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                _print_payload(line)

        if buffer.strip():
            _print_payload(buffer)
    except Exception as exc:
        _log_exception(f"[event] handler error for {addr}", exc)
    finally:
        _log(f"[event] client disconnected: {addr}")


def _run_server(
    name: str,
    host: str,
    port: int,
    stop_event: threading.Event,
    handler,
) -> None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((host, port))
            server.listen(5)
            server.settimeout(1.0)

            _log(f"[{name}] listening {host}:{port}")

            while not stop_event.is_set():
                try:
                    conn, addr = server.accept()
                except socket.timeout:
                    continue
                except OSError as exc:
                    if stop_event.is_set():
                        break
                    _log(f"[{name}] accept warning: {exc}")
                    time.sleep(0.2)
                    continue
                t = threading.Thread(
                    target=handler,
                    args=(conn, addr),
                    daemon=True,
                )
                t.start()
    except Exception as exc:
        _log_exception(f"[{name}] server fatal", exc)


def _install_exception_hooks() -> None:
    def _thread_hook(args):
        _log_exception(
            f"[thread-exception] name={args.thread.name}",
            args.exc_value,
        )

    def _main_hook(exc_type, exc_value, exc_traceback):
        if exc_value is None:
            return
        _log_exception("[main-exception]", exc_value)

    threading.excepthook = _thread_hook
    sys.excepthook = _main_hook


def _install_signal_handlers() -> None:
    def _handler(signum, _frame):
        _log(f"[signal] received signum={signum}")
        _SIGNAL_STOP.set()

    for sig_name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, sig_name, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, _handler)
        except Exception:
            pass


def main() -> int:
    _install_exception_hooks()
    _install_signal_handlers()
    _load_env()
    _log(f"python={sys.version}")
    _log(f"pid={os.getpid()}")

    host = os.getenv("HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.getenv("PORT", "26071"))
    resp_checkcode = int(os.getenv("RESP_CHECKCODE", "20250918"), 0)

    event_enabled = _env_bool("ENABLE_EVENT_SERVER", True)
    event_host = os.getenv("EVENT_SERVER_HOST", "127.0.0.1").strip() or "127.0.0.1"
    event_port = int(os.getenv("EVENT_SERVER_PORT", "26075"))

    stop_event = threading.Event()
    threads: list[threading.Thread] = []

    subtitle_thread = threading.Thread(
        target=_run_server,
        args=(
            "subtitle",
            host,
            port,
            stop_event,
            lambda conn, addr: _handle_subtitle_client(
                conn, addr, stop_event, resp_checkcode
            ),
        ),
        daemon=False,
    )
    subtitle_thread.start()
    threads.append(subtitle_thread)

    if event_enabled:
        event_thread = threading.Thread(
            target=_run_server,
            args=(
                "event",
                event_host,
                event_port,
                stop_event,
                lambda conn, addr: _handle_event_client(conn, addr, stop_event),
            ),
            daemon=False,
        )
        event_thread.start()
        threads.append(event_thread)
    else:
        _log("[event] disabled by ENABLE_EVENT_SERVER=false")

    _log("waiting for liveTextApp/liveSpeaker...")

    try:
        heartbeat_at = time.monotonic()
        while not _SIGNAL_STOP.is_set():
            time.sleep(0.3)
            if time.monotonic() - heartbeat_at >= 10.0:
                _log("heartbeat alive")
                heartbeat_at = time.monotonic()
    except KeyboardInterrupt:
        _log("stop requested (KeyboardInterrupt)")
    finally:
        _log("shutdown begin")
        stop_event.set()
        for t in threads:
            t.join(timeout=2.0)
        _log("shutdown end")

    return 0


if __name__ == "__main__":
    atexit.register(lambda: _log("process exiting"))
    sys.exit(main())
