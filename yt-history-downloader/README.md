# YT History Downloader

Select videos on your YouTube history page and download them as MP4, MP3 or M4A.

Two parts:
- **`extension/`**: a Chromium extension that adds checkboxes and a download panel to YouTube's history page.
- **`host/`**: a small Python helper that runs [yt-dlp](https://github.com/yt-dlp/yt-dlp). The browser starts it automatically (Native Messaging), so there is no server to run and no open port.

Works with Chrome, Chromium, Brave, Edge, Opera and Vivaldi. Firefox is not supported yet.

## Install

Requirements: Python 3.8+ and [ffmpeg](https://ffmpeg.org/) on your PATH.

1. Download or clone this repo.
2. Run the installer from the repo folder:
   ```
   python3 install.py
   ```
   It copies the helper to a per-user folder, downloads the standalone yt-dlp binary, and registers the helper with the browsers it finds.
   Use `python3 install.py --system-ytdlp` to skip the download and use a yt-dlp you installed yourself (e.g. `sudo dnf install yt-dlp`).
3. Load the extension: open `chrome://extensions` (or `opera://extensions`, `brave://extensions`, ...), enable **Developer mode**, click **Load unpacked**, and pick the `extension` folder.
4. Restart the browser if it was already open when you ran the installer.

## Use

1. Open https://www.youtube.com/feed/history while logged in.
2. Tick the videos you want (or **Select all**; scroll first to load more).
3. Pick a format and quality, press **Download**.

Files go to `~/Downloads/YT-Downloads`. The helper only runs while the browser is open; closing it stops running downloads, and unfinished files resume next time.

To change the folder or number of parallel downloads, create `config.json` in the helper's data folder:
```json
{ "outDir": "~/Videos/YouTube", "workers": 3 }
```
Data folder: `~/.local/share/yt-history-downloader` (Linux), `~/Library/Application Support/YT History Downloader` (macOS), `%LOCALAPPDATA%\YT History Downloader` (Windows). `host.log` there helps with debugging.

## Updating and uninstalling

- yt-dlp updates itself at most once a day (the bundled binary only).
- To update the helper, pull the repo and run `python3 install.py` again.
- Uninstall: `python3 install.py --uninstall`, then remove the extension in your browser.

## Troubleshooting

- **"Helper not installed"**: run `install.py`, then restart the browser.
- **MP3 fails or video/audio stay as separate files**: your system ffmpeg is broken or missing. Run `python3 install.py --bundled-ffmpeg` to download a known-good ffmpeg (yt-dlp's own build, ~150 MB) that the helper then uses instead. Failed jobs are also logged in `host.log`.
- **"ffmpeg not found"**: install ffmpeg. On Fedora, MP3 needs the full build: enable RPM Fusion, then `sudo dnf swap ffmpeg-free ffmpeg --allowerasing`.
- **Download errors about a JavaScript runtime**: recent yt-dlp versions use one (deno recommended) for some YouTube formats. Install deno or node.
- **Flatpak/Snap browsers** can't launch the helper out of the box. Use a regular package of the browser.
- **Checkboxes don't appear**: YouTube changed its layout. The selectors are at the top of `extension/content.js`.
- **Age-restricted/private videos**: add `--cookies-from-browser <browser>` in `build_cmd` in `host/yt_host.py`.

## Notes

- The extension ID is fixed by the `key` in `extension/manifest.json`; the installer derives it from there so the browser accepts the helper. If you generate your own key, re-run `install.py`.
- Windows support is written but untested.
- Downloading may conflict with YouTube's Terms of Service. Use it for personal copies of content you have the right to save.
