#!/usr/bin/env python3
"""T1-T7 共用底座：无依赖 CDP 客户端、浏览器拉起、静态文件服务、统计、证据包。

只依赖标准库（numpy / PIL 仅在 t2 里按需导入）。

设计取舍：
- 不用 websocket-client / websockets，自己实现最小 WebSocket 客户端（约 110 行）。
  理由：这些脚本要在「别人刚装好的机器」上跑得起来，少一个 pip 依赖就少一次失败。
- 自己拉起 Chrome 并读 DevToolsActivePort 取端口，而不是要求先手工启动浏览器。
  理由：这样每次测量都是干净会话，符合 docs/08 里「≥3 个独立批次」的要求。
"""

from __future__ import annotations

import base64
import functools
import hashlib
import json
import os
import pathlib
import platform
import shutil
import socket
import statistics
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

# ---------------------------------------------------------------- 统计


def summarize(values: list[float]) -> dict[str, float | int]:
    """给出一组测量值的分布。只报均值会被质疑，所以全都给。"""
    if not values:
        return {"n": 0}
    ordered = sorted(values)
    n = len(ordered)
    p95_index = min(n - 1, max(0, round(0.95 * (n - 1))))
    return {
        "n": n,
        "min": ordered[0],
        "median": statistics.median(ordered),
        "p95": ordered[p95_index],
        "max": ordered[-1],
        "mean": statistics.fmean(ordered),
        "stdev": statistics.stdev(ordered) if n > 1 else 0.0,
    }


def drop_warmup(values: list[float], count: int) -> list[float]:
    """丢掉前 count 个值。第一帧通常包含管线预热，留着会拉高均值。"""
    return values[count:]


# ---------------------------------------------------------------- 环境


def env_info() -> dict[str, str]:
    """六项环境。docs/08 §1.1 要求每条数据都必须带这些。"""

    def run(cmd: list[str]) -> str:
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            return (out.stdout or out.stderr).strip().splitlines()[0]
        except (OSError, subprocess.SubprocessError, IndexError):
            return "n/a"

    kernel = platform.release()
    proc_version = ""
    try:
        proc_version = pathlib.Path("/proc/version").read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass

    glx = run(["sh", "-c", "glxinfo -B 2>/dev/null | grep -i 'OpenGL renderer' || true"])
    return {
        "os": f"{platform.system()} {platform.release()}",
        "distro": run(["sh", "-c", "lsb_release -ds 2>/dev/null || cat /etc/os-release | grep PRETTY | cut -d= -f2"]),
        "kernel": kernel,
        "is_wsl": "yes" if "microsoft" in proc_version.lower() else "no",
        "cpu": run(["sh", "-c", "lscpu 2>/dev/null | grep -m1 'Model name' | cut -d: -f2 | xargs"]),
        "gl_renderer": glx or "n/a (mesa-utils 未安装，请用 chrome://gpu 抄录)",
        "python": sys.version.split()[0],
        "chrome": run(["sh", "-c", "google-chrome --version 2>/dev/null || chromium --version 2>/dev/null || chromium-browser --version 2>/dev/null"]),
        "sway": run(["sh", "-c", "sway --version 2>/dev/null | head -1"]),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }


# ---------------------------------------------------------------- 证据包


@dataclass
class Evidence:
    """一次测量的证据目录。任何人拿这个目录 + commit sha 就应该能重跑。"""

    topic: str
    root: pathlib.Path
    meta: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.dir = self.root / f"{self.topic}-{stamp}"
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "env.txt").write_text(
            "\n".join(f"{k}: {v}" for k, v in env_info().items()) + "\n", encoding="utf-8"
        )
        (self.dir / "command.sh").write_text(" ".join(sys.argv) + "\n", encoding="utf-8")

    def write_json(self, name: str, payload: object) -> pathlib.Path:
        path = self.dir / name
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def write_text(self, name: str, text: str) -> pathlib.Path:
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def path(self) -> str:
        return str(self.dir)


# ---------------------------------------------------------------- 最小 WebSocket 客户端


class WebSocketError(RuntimeError):
    pass


class WebSocket:
    """够用的最小实现：文本帧、掩码发送、处理 ping/close。

    CDP 只用文本帧，不需要二进制、分片、扩展协商。
    """

    def __init__(self, url: str, timeout: float = 30.0) -> None:
        if not url.startswith("ws://"):
            raise WebSocketError(f"only ws:// supported, got {url}")
        rest = url[len("ws://") :]
        authority, _, path = rest.partition("/")
        host, _, port_text = authority.partition(":")
        self._sock = socket.create_connection((host, int(port_text or "80")), timeout=timeout)
        self._sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET /{path} HTTP/1.1\r\n"
            f"Host: {authority}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self._sock.sendall(request.encode())
        header = self._read_until(b"\r\n\r\n")
        if b"101" not in header.split(b"\r\n")[0]:
            raise WebSocketError(f"handshake failed: {header[:120]!r}")

    def _read_until(self, marker: bytes) -> bytes:
        buf = b""
        while marker not in buf:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise WebSocketError("connection closed during handshake")
            buf += chunk
        return buf

    def _recv_exact(self, count: int) -> bytes:
        buf = b""
        while len(buf) < count:
            chunk = self._sock.recv(count - len(buf))
            if not chunk:
                raise WebSocketError("connection closed")
            buf += chunk
        return buf

    def send(self, text: str) -> None:
        payload = text.encode()
        header = bytearray([0x81])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", length)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", length)
        mask = os.urandom(4)
        header += mask
        masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
        self._sock.sendall(bytes(header) + masked)

    def recv(self) -> str:
        while True:
            first, second = self._recv_exact(2)
            opcode = first & 0x0F
            length = second & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._recv_exact(8))[0]
            payload = self._recv_exact(length) if length else b""
            if opcode == 0x8:
                raise WebSocketError("server closed")
            if opcode == 0x9:
                self._sock.sendall(b"\x8a" + bytes([0x80]) + os.urandom(4))
                continue
            if opcode in (0x1, 0x2):
                return payload.decode("utf-8", errors="replace")

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass


class Cdp:
    """CDP 会话。call() 同步等结果，事件丢弃（本套脚本不需要事件）。"""

    def __init__(self, ws_url: str, timeout: float = 60.0) -> None:
        self._ws = WebSocket(ws_url, timeout=timeout)
        self._next_id = 0

    def call(self, method: str, **params: object) -> dict[str, object]:
        self._next_id += 1
        message_id = self._next_id
        self._ws.send(json.dumps({"id": message_id, "method": method, "params": params}))
        while True:
            message = json.loads(self._ws.recv())
            if message.get("id") != message_id:
                continue
            if "error" in message:
                raise WebSocketError(f"{method}: {message['error']}")
            return message.get("result", {})

    def eval_json(self, expression: str) -> object | None:
        """在页面里求值并把结果当 JSON 取回。"""
        result = self.call(
            "Runtime.evaluate",
            expression=expression,
            returnByValue=True,
            awaitPromise=True,
        )
        return result.get("result", {}).get("value")

    def close(self) -> None:
        self._ws.close()


# ---------------------------------------------------------------- 浏览器


def chrome_binary() -> str:
    for name in ("google-chrome", "chromium", "chromium-browser", "google-chrome-stable"):
        found = shutil.which(name)
        if found:
            return found
    raise SystemExit("找不到 Chrome / Chromium，请先安装或以 --chrome 指定路径")


def launch_chrome(
    url: str,
    *,
    headless: bool = True,
    width: int = 1280,
    height: int = 720,
    extra_flags: list[str] | None = None,
    binary: str | None = None,
) -> tuple[subprocess.Popen[bytes], int, pathlib.Path]:
    """拉起一个干净会话的 Chrome，返回 (进程, 调试端口, 用户数据目录)。"""
    binary = binary or chrome_binary()
    data_dir = pathlib.Path(tempfile.mkdtemp(prefix="probe-profile-"))
    flags = [
        binary,
        "--remote-debugging-port=0",
        f"--user-data-dir={data_dir}",
        f"--window-size={width},{height}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--force-device-scale-factor=1",
    ]
    if headless:
        flags.append("--headless=new")
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        # root 下 Chrome 直接拒绝启动；WSL 的 /dev/shm 默认只有 64MB
        flags += ["--no-sandbox", "--disable-dev-shm-usage"]
    flags += extra_flags or []
    flags.append(url)
    proc = subprocess.Popen(flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    port_file = data_dir / "DevToolsActivePort"
    for _ in range(200):
        if port_file.exists() and port_file.stat().st_size > 0:
            return proc, int(port_file.read_text(encoding="utf-8").splitlines()[0]), data_dir
        if proc.poll() is not None:
            raise SystemExit("Chrome 启动后立刻退出，检查 --chrome 路径与权限")
        time.sleep(0.05)
    proc.kill()
    raise SystemExit("等不到 DevToolsActivePort（20s）")


def page_target(port: int, url_prefix: str = "") -> str:
    """取页面目标的 ws 调试地址。"""
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=10) as response:
        targets = json.load(response)
    pages = [t for t in targets if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
    if url_prefix:
        pages = [t for t in pages if url_prefix in t.get("url", "")] or pages
    if not pages:
        raise SystemExit("没有可用的页面目标")
    return pages[0]["webSocketDebuggerUrl"]


def wait_for(cdp: Cdp, expression: str, timeout: float = 20.0, interval: float = 0.1) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cdp.eval_json(expression):
            return
        time.sleep(interval)
    raise SystemExit(f"等待超时：{expression}")


# ---------------------------------------------------------------- 静态服务


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:  # 静默，避免污染 stdout 报告
        del fmt, args


def serve_directory(path: pathlib.Path) -> tuple[ThreadingHTTPServer, int]:
    handler = functools.partial(_QuietHandler, directory=str(path))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


# ---------------------------------------------------------------- 杂项


def png_bytes_to_digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()[:16]


def decode_data_url(data_url: str) -> bytes:
    _, _, encoded = data_url.partition(",")
    return base64.b64decode(encoded)


def print_table(rows: list[list[str]], headers: list[str]) -> None:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    print(line)
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print("  ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row)))
