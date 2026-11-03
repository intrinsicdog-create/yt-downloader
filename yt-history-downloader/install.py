#!/usr/bin/env python3
"""Installer for the YT History Downloader helper (Linux, macOS, Windows).

What it does:
  1. Copies host/yt_host.py into a per-user data folder.
  2. Downloads the standalone yt-dlp binary from GitHub (skip with --system-ytdlp).
  3. Registers the native messaging host with every Chromium-based browser it finds.

Usage:  python3 install.py            install / update
        python3 install.py --uninstall
"""
import argparse
import base64
import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

HOST_NAME = "com.ythd.helper"
ROOT = Path(__file__).resolve().parent
SYSTEM = platform.system()  # Linux / Darwin / Windows
YTDLP_BASE = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/"
FFMPEG_BASE = "https://github.com/yt-dlp/FFmpeg-Builds/releases/latest/download/"


def data_dir():
    if SYSTEM == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "YT History Downloader"
    if SYSTEM == "Darwin":
        return Path.home() / "Library" / "Application Support" / "YT History Downloader"
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "yt-history-downloader"


def extension_id():
    """Chrome derives the ID from the public key pinned in extension/manifest.json."""
    key = json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))["key"]
    digest = hashlib.sha256(base64.b64decode(key)).hexdigest()[:32]
    return "".join(chr(ord("a") + int(c, 16)) for c in digest)


def browser_dirs():
    h = Path.home()
    if SYSTEM == "Linux":
        c = h / ".config"
        return {
            "Chrome": c / "google-chrome", "Chromium": c / "chromium",
            "Brave": c / "BraveSoftware" / "Brave-Browser", "Edge": c / "microsoft-edge",
            "Opera": c / "opera", "Vivaldi": c / "vivaldi",
        }
    if SYSTEM == "Darwin":
        a = h / "Library" / "Application Support"
        return {
            "Chrome": a / "Google" / "Chrome", "Chromium": a / "Chromium",
            "Brave": a / "BraveSoftware" / "Brave-Browser", "Edge": a / "Microsoft Edge",
            "Opera": a / "com.operasoftware.Opera", "Vivaldi": a / "Vivaldi",
        }
    return {}


WIN_KEYS = {
    "Chrome": r"Software\Google\Chrome\NativeMessagingHosts",
    "Chromium": r"Software\Chromium\NativeMessagingHosts",
    "Edge": r"Software\Microsoft\Edge\NativeMessagingHosts",
    "Brave": r"Software\BraveSoftware\Brave-Browser\NativeMessagingHosts",
}


def ytdlp_asset():
    machine = platform.machine().lower()
    if SYSTEM == "Windows":
        return "yt-dlp.exe"
    if SYSTEM == "Darwin":
        return "yt-dlp_macos"
    if machine in ("x86_64", "amd64"):
        return "yt-dlp_linux"
    if machine in ("aarch64", "arm64"):
        return "yt-dlp_linux_aarch64"
    return "yt-dlp"  # python zipapp, works anywhere with python3


def download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "yt-history-downloader-installer"})
    tmp = dest.with_name(dest.name + ".part")
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done, last_pct = 0, -1
        tty = sys.stdout.isatty()
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total:
                pct = done * 100 // total
                if tty:
                    bar = "#" * (pct // 4) + "-" * (25 - pct // 4)
                    print(f"\r  [{bar}] {pct:3d}%  {done / 1e6:6.1f} / {total / 1e6:.1f} MB", end="", flush=True)
                elif pct // 10 != last_pct // 10:  # piped output: one line per 10%
                    print(f"  {pct}%", flush=True)
                last_pct = pct
        if tty and total:
            print()
    tmp.replace(dest)
    if SYSTEM != "Windows":
        dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def works(cmd):
    """Returns the first line of `cmd --version` output if the binary runs, else None."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        out = (r.stdout or r.stderr).strip().splitlines()
        return out[0] if r.returncode == 0 and out else None
    except Exception:  # noqa: BLE001
        return None


def install_ytdlp(dd, force=False):
    bin_dir = dd / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    dest = bin_dir / ("yt-dlp.exe" if SYSTEM == "Windows" else "yt-dlp")
    if dest.exists() and not force:
        v = works([str(dest), "--version"])
        if v:
            print(f"yt-dlp already installed ({v}), skipping. It updates itself daily; use --force to reinstall.")
            return
    asset = ytdlp_asset()
    print(f"Downloading yt-dlp ({asset}) ...")
    download(YTDLP_BASE + asset, dest)
    try:
        v = subprocess.run([str(dest), "--version"], capture_output=True, text=True, timeout=60)
        print("  yt-dlp version:", v.stdout.strip() or v.stderr.strip())
    except Exception as e:  # noqa: BLE001
        print("  WARNING: the downloaded yt-dlp did not run:", e)


def ffmpeg_asset():
    machine = platform.machine().lower()
    if SYSTEM == "Windows":
        return "ffmpeg-master-latest-win64-gpl.zip"
    if SYSTEM == "Linux" and machine in ("x86_64", "amd64"):
        return "ffmpeg-master-latest-linux64-gpl.tar.xz"
    if SYSTEM == "Linux" and machine in ("aarch64", "arm64"):
        return "ffmpeg-master-latest-linuxarm64-gpl.tar.xz"
    return None  # no prebuilt for macOS here: use `brew install ffmpeg`


def install_ffmpeg(dd, force=False):
    """Download yt-dlp's own ffmpeg build and keep only ffmpeg + ffprobe in bin/."""
    asset = ffmpeg_asset()
    if not asset:
        print("No prebuilt ffmpeg for this platform; install ffmpeg yourself (e.g. `brew install ffmpeg`).")
        return
    bin_dir = dd / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    exe = ".exe" if SYSTEM == "Windows" else ""
    wanted = {f"ffmpeg{exe}", f"ffprobe{exe}"}
    if not force and all((bin_dir / n).exists() for n in wanted):
        v = works([str(bin_dir / f"ffmpeg{exe}"), "-version"])
        if v:
            print(f"ffmpeg already installed ({v[:40]}), skipping. Use --force to reinstall.")
            return
    print(f"Downloading ffmpeg ({asset}, ~150 MB) ...")
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / asset
        download(FFMPEG_BASE + asset, archive)
        found = set()
        if asset.endswith(".zip"):
            with zipfile.ZipFile(archive) as z:
                for name in z.namelist():
                    base = name.rsplit("/", 1)[-1]
                    if "/bin/" in name and base in wanted:
                        (bin_dir / base).write_bytes(z.read(name))
                        found.add(base)
        else:
            with tarfile.open(archive, "r:xz") as t:
                for m in t:
                    base = m.name.rsplit("/", 1)[-1]
                    if "/bin/" in m.name and m.isfile() and base in wanted:
                        (bin_dir / base).write_bytes(t.extractfile(m).read())
                        (bin_dir / base).chmod(0o755)
                        found.add(base)
    if found != wanted:
        print("  WARNING: ffmpeg archive didn't contain the expected files:", wanted - found)
        return
    r = subprocess.run([str(bin_dir / f"ffmpeg{exe}"), "-version"], capture_output=True, text=True, timeout=60)
    print("  ffmpeg:", (r.stdout.splitlines() or [r.stderr.strip()])[0])


def install_host(dd):
    dd.mkdir(parents=True, exist_ok=True)
    host = dd / "yt_host.py"
    text = (ROOT / "host" / "yt_host.py").read_text(encoding="utf-8").splitlines()
    if SYSTEM != "Windows":
        # Pin the interpreter so the browser doesn't depend on its own PATH.
        text[0] = f"#!{sys.executable}"
    host.write_text("\n".join(text) + "\n", encoding="utf-8")
    if SYSTEM == "Windows":
        bat = dd / "yt_host.bat"
        bat.write_text(f'@echo off\r\n"{sys.executable}" "{host}" %*\r\n')
        return bat
    host.chmod(0o755)
    return host


def manifest_for(path, ext_id):
    return {
        "name": HOST_NAME,
        "description": "YT History Downloader helper (runs yt-dlp)",
        "path": str(path),
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{ext_id}/"],
    }


def register(entry, dd, ext_id):
    registered = []
    if SYSTEM == "Windows":
        import winreg
        manifest = dd / f"{HOST_NAME}.json"
        manifest.write_text(json.dumps(manifest_for(entry, ext_id), indent=2))
        for name, key in WIN_KEYS.items():
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, f"{key}\\{HOST_NAME}") as k:
                winreg.SetValueEx(k, "", 0, winreg.REG_SZ, str(manifest))
            registered.append(name)
        return registered
    for name, d in browser_dirs().items():
        if d.exists():
            target = d / "NativeMessagingHosts"
            target.mkdir(exist_ok=True)
            (target / f"{HOST_NAME}.json").write_text(json.dumps(manifest_for(entry, ext_id), indent=2))
            registered.append(name)
    return registered


def unregister():
    if SYSTEM == "Windows":
        import winreg
        for key in WIN_KEYS.values():
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, f"{key}\\{HOST_NAME}")
            except OSError:
                pass
        return
    for d in browser_dirs().values():
        (d / "NativeMessagingHosts" / f"{HOST_NAME}.json").unlink(missing_ok=True)


def sandbox_warning():
    h = Path.home()
    hits = []
    for app in ("com.google.Chrome", "org.chromium.Chromium", "com.brave.Browser",
                "com.opera.Opera", "com.microsoft.Edge", "com.vivaldi.Vivaldi"):
        if (h / ".var" / "app" / app).exists():
            hits.append(app + " (Flatpak)")
    if (h / "snap" / "chromium").exists():
        hits.append("chromium (Snap)")
    if hits:
        print("\nNOTE: sandboxed browsers found: " + ", ".join(hits))
        print("  Flatpak/Snap browsers can't launch the helper out of the box.")
        print("  Use a native (non-sandboxed) package of the browser, or grant it access manually.")


def check_tools(dd):
    print()
    bundled = (dd / "bin" / ("ffmpeg.exe" if SYSTEM == "Windows" else "ffmpeg")).exists()
    if not bundled and not shutil.which("ffmpeg"):
        hint = {
            "Linux": "Fedora: enable RPM Fusion, then `sudo dnf swap ffmpeg-free ffmpeg --allowerasing`.\n"
                     "       Debian/Ubuntu: `sudo apt install ffmpeg`.",
            "Darwin": "`brew install ffmpeg`",
            "Windows": "`winget install Gyan.FFmpeg`",
        }.get(SYSTEM, "")
        print("WARNING: ffmpeg not found on PATH. Merging video/audio and MP3 conversion need it.")
        print("  " + hint)
    if not any(shutil.which(x) for x in ("deno", "node", "bun", "qjs")):
        print("NOTE: no JavaScript runtime found (deno, node, bun). Recent yt-dlp versions use one")
        print("  for some YouTube formats; if downloads fail with a JS-runtime warning, install deno.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--uninstall", action="store_true", help="remove the helper and its browser registrations")
    ap.add_argument("--system-ytdlp", action="store_true",
                    help="don't download yt-dlp; use the one on PATH (e.g. `sudo dnf install yt-dlp`)")
    ap.add_argument("--bundled-ffmpeg", action="store_true",
                    help="also download a known-good ffmpeg into the helper folder (used instead of the system one)")
    ap.add_argument("--force", action="store_true", help="re-download yt-dlp/ffmpeg even if already installed")
    ap.add_argument("--extension-id", help="override the extension ID (only if you re-keyed the extension)")
    args = ap.parse_args()

    dd = data_dir()
    if args.uninstall:
        unregister()
        shutil.rmtree(dd, ignore_errors=True)
        print("Removed the helper. Remove the extension itself from your browser's extensions page.")
        return

    ext_id = args.extension_id or extension_id()
    entry = install_host(dd)
    if not args.system_ytdlp:
        try:
            install_ytdlp(dd, args.force)
        except Exception as e:  # noqa: BLE001
            print(f"WARNING: couldn't download yt-dlp ({e}). Re-run later, or install it yourself and use --system-ytdlp.")
    if args.bundled_ffmpeg:
        try:
            install_ffmpeg(dd, args.force)
        except Exception as e:  # noqa: BLE001
            print(f"WARNING: couldn't set up ffmpeg ({e}).")
    browsers = register(entry, dd, ext_id)

    print(f"\nHelper installed in: {dd}")
    print(f"Extension ID: {ext_id}")
    print("Registered for: " + (", ".join(browsers) if browsers else "NO browsers found (is one installed and run once?)"))
    sandbox_warning()
    check_tools(dd)
    print("\nNext: load the `extension` folder via your browser's extensions page (Developer mode > Load unpacked).")


if __name__ == "__main__":
    main()
