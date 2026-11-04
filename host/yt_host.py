#!/usr/bin/env python3
"""Native messaging host for the YT History Downloader extension.

The browser launches this process (through the manifest written by install.py)
and talks to it over stdin/stdout: a 4-byte length prefix in native byte order,
followed by UTF-8 JSON. NEVER print to stdout here, it is the message channel.

Requires: Python 3.8+. yt-dlp is looked up in ./bin, then PATH, then `python -m yt_dlp`.
"""
import itertools
import json
import os
import queue
import re
import shutil
import signal
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
BIN_DIR = APP_DIR / "bin"
IS_WIN = os.name == "nt"
LOG_FILE = APP_DIR / "host.log"
STAMP = APP_DIR / ".last_update_check"
UPDATE_EVERY = 24 * 3600  # seconds between yt-dlp self-updates

ID_RE = re.compile(r"^[\w-]{11}$")
QUALITY_RE = re.compile(r"^(best|\d{3,4})$")
PROGRESS_RE = re.compile(r"\[download\]\s+(\d+(?:\.\d+)?)%")


def log(msg):
    try:
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > 500_000:
            LOG_FILE.write_text("")
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:  # noqa: BLE001
        pass


def load_config():
    """Optional config.json next to this file: {"outDir": "...", "workers": 2}."""
    try:
        return json.loads((APP_DIR / "config.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


CONFIG = load_config()
OUT_DIR = Path(CONFIG.get("outDir") or Path.home() / "Downloads" / "YT-Downloads").expanduser()
try:
    WORKERS = max(1, min(int(CONFIG.get("workers", 2)), 8))
except (TypeError, ValueError):
    WORKERS = 2

jobs = {}  # video id -> {title, status, progress, error}
lock = threading.Lock()
work = queue.Queue()
procs = {}  # video id -> running yt-dlp process
gen_counter = itertools.count(1)  # tells a re-queued job apart from its stale queue entry
ready = threading.Event()  # set once the optional yt-dlp self-update finished


# ---------- tools ----------
def bundled_ytdlp():
    p = BIN_DIR / ("yt-dlp.exe" if IS_WIN else "yt-dlp")
    return p if p.exists() else None


def ytdlp_cmd():
    b = bundled_ytdlp()
    if b:
        return [str(b)]
    found = shutil.which("yt-dlp")
    if found:
        return [found]
    return [sys.executable, "-m", "yt_dlp"]


def ffmpeg_info():
    """Returns (extra yt-dlp args, ffmpeg available?)."""
    local = BIN_DIR / ("ffmpeg.exe" if IS_WIN else "ffmpeg")
    if local.exists():
        return ["--ffmpeg-location", str(BIN_DIR)], True
    return [], shutil.which("ffmpeg") is not None


def maintenance():
    """Update the bundled yt-dlp binary at most once a day, then release the workers."""
    try:
        if bundled_ytdlp():
            age = time.time() - STAMP.stat().st_mtime if STAMP.exists() else UPDATE_EVERY + 1
            if age > UPDATE_EVERY:
                subprocess.run(
                    ytdlp_cmd() + ["-U"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=120, creationflags=0x08000000 if IS_WIN else 0,
                )
                STAMP.touch()
    except Exception as e:  # noqa: BLE001
        log(f"update check failed: {e}")
    finally:
        ready.set()


# ---------- downloads ----------
def kill_tree(p):
    """Stop yt-dlp and anything it started (ffmpeg, or the PyInstaller child)."""
    try:
        if IS_WIN:
            subprocess.run(
                ["taskkill", "/PID", str(p.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=0x08000000,
            )
        else:
            os.killpg(os.getpgid(p.pid), signal.SIGTERM)
    except Exception:  # noqa: BLE001
        try:
            p.terminate()
        except Exception:  # noqa: BLE001
            pass


def remove_partials(vid):
    """Delete the half-downloaded files of a cancelled video (finished files are never touched)."""
    tag = f"[{vid}]"
    try:
        for f in OUT_DIR.iterdir():
            n = f.name
            if tag in n and (n.endswith((".part", ".ytdl")) or ".part-Frag" in n):
                f.unlink()
    except Exception as e:  # noqa: BLE001
        log(f"cleanup for {vid} failed: {e}")


def set_job(vid, **kw):
    with lock:
        jobs.setdefault(vid, {}).update(kw)


def build_cmd(vid, fmt, quality):
    cmd = ytdlp_cmd() + [
        "--newline", "--no-playlist",
        "-o", str(OUT_DIR / "%(title).150B [%(id)s].%(ext)s"),
    ]
    if IS_WIN:
        cmd.append("--windows-filenames")
    cmd += ffmpeg_info()[0]
    if fmt == "video":
        h = "" if quality == "best" else f"[height<={quality}]"
        cmd += [
            "-f", f"bv*{h}[ext=mp4]+ba[ext=m4a]/bv*{h}+ba/b{h}",
            "--merge-output-format", "mp4",
        ]
    elif fmt == "mp3":
        cmd += ["-x", "--audio-format", "mp3", "--audio-quality", f"{quality}K"]
    else:  # m4a
        cmd += ["-f", "ba[ext=m4a]/ba", "-x", "--audio-format", "m4a"]
    cmd.append(f"https://www.youtube.com/watch?v={vid}")
    return cmd


def run_job(vid, fmt, quality):
    # the worker already moved this job to "downloading" under the lock
    last = ""
    tail = []
    try:
        p = subprocess.Popen(
            build_cmd(vid, fmt, quality),
            # stdin must NOT be inherited: it is the browser's message channel.
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, errors="replace",
            creationflags=0x08000000 if IS_WIN else 0,  # no console window on Windows
            start_new_session=not IS_WIN,  # own process group, so a cancel can stop the whole tree
        )
        with lock:
            procs[vid] = p
            cancelled = jobs.get(vid, {}).get("status") == "cancelled"
        if cancelled:  # cancelled in the instant between starting and registering
            kill_tree(p)
        for line in p.stdout:
            line = line.strip()
            if line:
                last = line
                tail = (tail + [line])[-15:]
            m = PROGRESS_RE.search(line)
            if m:
                set_job(vid, progress=float(m.group(1)))
        p.wait()
        with lock:
            procs.pop(vid, None)
            cancelled = jobs.get(vid, {}).get("status") == "cancelled"
        if cancelled:
            remove_partials(vid)
        elif p.returncode == 0:
            set_job(vid, status="done", progress=100)
        else:
            log(f"job {vid} failed (exit {p.returncode}):\n  " + "\n  ".join(tail))
            set_job(vid, status="error", error=last[:300])
    except Exception as e:  # noqa: BLE001
        log(f"job {vid} crashed: {e}")
        with lock:
            procs.pop(vid, None)
        if jobs.get(vid, {}).get("status") != "cancelled":
            set_job(vid, status="error", error=str(e))


def worker():
    ready.wait()
    while True:
        vid, fmt, quality, gen = work.get()
        try:
            with lock:
                j = jobs.get(vid)
                # skip stale entries: cancelled while queued, or replaced by a newer queue entry
                go = bool(j) and j.get("gen") == gen and j.get("status") == "queued"
                if go:
                    j.update(status="downloading", progress=0, error="")
            if go:
                run_job(vid, fmt, quality)
        finally:
            work.task_done()


def start_downloads(req):
    fmt, quality, items = req.get("format"), str(req.get("quality")), req.get("items")
    if fmt not in ("video", "mp3", "m4a") or not QUALITY_RE.match(quality):
        raise ValueError("Invalid format or quality")
    if not isinstance(items, list):
        raise ValueError("Bad request")
    if not ffmpeg_info()[1]:
        raise ValueError("ffmpeg not found. Install ffmpeg (it must be on your PATH) and try again.")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    queued = 0
    with lock:
        # a new batch clears the finished jobs of the previous one
        for v in [v for v, j in jobs.items() if j.get("status") in ("done", "error", "cancelled")]:
            del jobs[v]
        for it in items:
            vid = str(it.get("id", "")) if isinstance(it, dict) else ""
            if not ID_RE.match(vid) or vid in jobs:  # invalid, or already queued/running
                continue
            gen = next(gen_counter)
            jobs[vid] = {"title": str(it.get("title", ""))[:200], "status": "queued", "progress": 0, "error": "", "gen": gen}
            work.put((vid, fmt, quality, gen))
            queued += 1
    return {"queued": queued}


def cancel_jobs(req):
    """Cancel the given video ids, or every queued/running job when no ids are given."""
    ids = req.get("ids")
    if ids is not None and not isinstance(ids, list):
        raise ValueError("Bad request")
    n = 0
    with lock:
        targets = list(jobs) if ids is None else [str(i) for i in ids]
        for vid in targets:
            j = jobs.get(vid)
            if not j or j.get("status") not in ("queued", "downloading"):
                continue
            j.update(status="cancelled", error="")
            n += 1
            p = procs.get(vid)
            if p:
                kill_tree(p)
    return {"cancelled": n}


def status():
    with lock:
        snap = {v: {k: j.get(k) for k in ("status", "progress", "error")} for v, j in jobs.items()}
    return {"outDir": str(OUT_DIR), "jobs": snap}


def handle(msg):
    kind = msg.get("type")
    if kind == "download":
        return start_downloads(msg.get("payload") or {})
    if kind == "cancel":
        return cancel_jobs(msg.get("payload") or {})
    if kind == "status":
        return status()
    if kind == "ping":
        return {"ok": True}
    raise ValueError("Unknown request")


# ---------- native messaging framing ----------
out_lock = threading.Lock()


def read_msg():
    raw = sys.stdin.buffer.read(4)
    if len(raw) < 4:
        return None  # browser closed the pipe
    (n,) = struct.unpack("=I", raw)
    return json.loads(sys.stdin.buffer.read(n).decode("utf-8"))


def write_msg(obj):
    data = json.dumps(obj).encode("utf-8")
    with out_lock:
        sys.stdout.buffer.write(struct.pack("=I", len(data)) + data)
        sys.stdout.buffer.flush()


def main():
    if IS_WIN:
        import msvcrt
        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)

    threading.Thread(target=maintenance, daemon=True).start()
    for _ in range(WORKERS):
        threading.Thread(target=worker, daemon=True).start()

    try:
        while True:
            msg = read_msg()
            if msg is None:
                break
            reply = {"id": msg.get("id")}
            try:
                reply.update(ok=True, data=handle(msg))
            except Exception as e:  # noqa: BLE001
                reply.update(ok=False, error=str(e))
            write_msg(reply)
    finally:
        # Browser went away: stop children (partial .part files resume next time).
        with lock:
            for p in list(procs.values()):
                kill_tree(p)


if __name__ == "__main__":
    main()
