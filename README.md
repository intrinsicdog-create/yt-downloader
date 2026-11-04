# YT History Downloader

Select videos on your YouTube history page and download them as MP4, MP3 or M4A.

Two parts:
- **`extension/`**: a Chromium extension that adds checkboxes and a download panel to YouTube's history page.
- **`host/`**: a small Python helper that runs [yt-dlp](https://github.com/yt-dlp/yt-dlp). The browser starts it automatically (Native Messaging), so there is no server to run and no open port.

Works with Chrome, Chromium, Brave, Edge, Opera and Vivaldi. Firefox is not supported yet.

## Features

- Checkboxes on every video in your history, plus **Select all** / **Clear**
- MP4 (up to best available), MP3 or M4A, with a quality choice
- Live progress: a bar on each video, a status badge, and an overall progress bar in the panel
- **Cancel** a single download with the ✕ on its badge, or everything with **Cancel all**; partial files of cancelled downloads are cleaned up
- Smooth animations that follow your OS "reduce motion" setting

## Install

You need **Python 3.8+** and **ffmpeg**. The installer can download yt-dlp and a known-good ffmpeg for you.

### Windows (PowerShell)

1. Install Python (skip if `python --version` already works), then **close and reopen PowerShell**:
   ```powershell
   winget install Python.Python.3.12
   ```
2. Get the project, either with git:
   ```powershell
   git clone https://github.com/<your-username>/yt-history-downloader.git
   cd yt-history-downloader
   ```
   or click **Code > Download ZIP** on GitHub, extract it, and `cd` into the extracted folder.
3. Run the installer. `--bundled-ffmpeg` downloads ffmpeg (~200 MB) so you don't have to install it yourself:
   ```powershell
   python install.py --bundled-ffmpeg
   ```
   (If `python` isn't found, try `py install.py --bundled-ffmpeg`.)
4. Load the extension (see [Load the extension](#load-the-extension)), then restart the browser.

Optional: `winget install DenoLand.Deno` installs a JavaScript runtime that recent yt-dlp versions use for some YouTube formats. Install it if downloads fail with a JS-runtime warning.

Windows notes:
- The helper is registered in the current user's registry for Chrome, Chromium, Edge and Brave. No admin rights needed.
- Keep Python installed: the helper runs through the Python that ran the installer. If you move or reinstall Python, run the installer again.
- Windows support is new and lightly tested. If something fails, check `host.log` (see below) and open an issue.

### Linux

```bash
git clone https://github.com/<your-username>/yt-history-downloader.git
cd yt-history-downloader
python3 install.py --bundled-ffmpeg
```
`--bundled-ffmpeg` is optional but recommended. On Fedora, the system ffmpeg may lack the MP3 encoder or crash; the bundled build avoids that. Alternatively, install ffmpeg yourself: on Fedora enable RPM Fusion, then `sudo dnf swap ffmpeg-free ffmpeg --allowerasing`; on Debian/Ubuntu `sudo apt install ffmpeg`.

To use a yt-dlp you installed yourself (e.g. `sudo dnf install yt-dlp`) instead of downloading one, add `--system-ytdlp`.

### macOS

```bash
brew install ffmpeg
git clone https://github.com/<your-username>/yt-history-downloader.git
cd yt-history-downloader
python3 install.py
```
There is no bundled ffmpeg on macOS, so install it with Homebrew first.

### Load the extension

Open `chrome://extensions` (or `opera://extensions`, `brave://extensions`, `edge://extensions`), enable **Developer mode**, click **Load unpacked**, and pick the `extension` folder. Restart the browser if it was already open when you ran the installer.

### Installer options

| Option | What it does |
| --- | --- |
| `--bundled-ffmpeg` | Download a known-good ffmpeg into the helper folder (Windows and Linux) |
| `--system-ytdlp` | Don't download yt-dlp; use the one on your PATH |
| `--force` | Re-download yt-dlp/ffmpeg even if already installed |
| `--uninstall` | Remove the helper and its browser registrations |

Re-running the installer is safe: it skips yt-dlp and ffmpeg if they are already installed and working.

## Use

1. Open https://www.youtube.com/feed/history while logged in.
2. Tick the videos you want (or **Select all**; scroll first to load more).
3. Pick a format and quality, press **Download**.
4. Changed your mind? Click the ✕ on a video's badge to cancel it, or **Cancel all** in the panel.

Files go to `Downloads/YT-Downloads` in your home folder. The helper only runs while the browser is open; closing it stops running downloads, and unfinished files resume next time.

To change the folder or number of parallel downloads, create `config.json` in the helper's data folder:
```json
{ "outDir": "~/Videos/YouTube", "workers": 3 }
```
On Windows use forward slashes or doubled backslashes in paths, e.g. `"D:/Videos/YouTube"`.

Helper data folder:
- Windows: `%LOCALAPPDATA%\YT History Downloader`
- Linux: `~/.local/share/yt-history-downloader`
- macOS: `~/Library/Application Support/YT History Downloader`

`host.log` in that folder shows why a download failed.

## Updating and uninstalling

- yt-dlp updates itself at most once a day (the bundled binary only).
- To update: get the latest version of the repo, run the installer again (`python install.py` on Windows, `python3 install.py` elsewhere; it only refreshes the helper and skips yt-dlp/ffmpeg if they're already installed), then click the reload icon for the extension on your browser's extensions page.
- Uninstall: run the installer with `--uninstall`, then remove the extension in your browser.

## Troubleshooting

- **"Helper not installed"**: run the installer, then restart the browser.
- **MP3 fails or video and audio stay as separate files**: your system ffmpeg is broken or missing. Run the installer with `--bundled-ffmpeg --force`.
- **"ffmpeg not found"**: install ffmpeg or use `--bundled-ffmpeg` (see above).
- **Download errors about a JavaScript runtime**: install deno (`winget install DenoLand.Deno` on Windows) or node.
- **Flatpak/Snap browsers** (Linux) can't launch the helper out of the box. Use a regular package of the browser.
- **Checkboxes don't appear**: YouTube changed its layout. The selectors are at the top of `extension/content.js`.
- **Age-restricted/private videos**: add `--cookies-from-browser <browser>` in `build_cmd` in `host/yt_host.py`, then re-run the installer.

## Notes

- The extension ID is fixed by the `key` in `extension/manifest.json`; the installer derives it from there so the browser accepts the helper. If you generate your own key, re-run the installer.
- Downloading may conflict with YouTube's Terms of Service. Use it for personal copies of content you have the right to save.
