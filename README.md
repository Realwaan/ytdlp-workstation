# ⚡ YT-DLP Supercharged Downloader Workstation

[![Python](https://img.shields.io/badge/Python-3.8+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-0078D6?logo=windows)](https://microsoft.com)
[![yt-dlp](https://img.shields.io/badge/Powered%20By-yt--dlp-red?logo=youtube)](https://github.com/yt-dlp/yt-dlp)

An automated, cyber-styled terminal for **yt-dlp** that downloads videos and audio with **zero manual typing**, interactive **quality picker**, **browser cookie authentication**, **video trimming**, and **lossless audio**.

Whenever you copy a video link from YouTube, TikTok, Instagram, Twitter/X, Reddit, Kick, Rumble, etc., the terminal detects it from your clipboard and lets you pick quality or downloads automatically!

---

## 📦 Installation & Quick Start

### ⚡ Option 1: 1-Line PowerShell Web Installer (Fastest for Windows)
Open PowerShell and run this single command to install and set up your Desktop shortcut automatically:
```powershell
powershell -c "irm https://raw.githubusercontent.com/Realwaan/ytdlp-workstation/main/install.ps1 | iex"
```

---

### 🐍 Option 2: Install as a Python Package (`pip`)
You can install and run the workstation globally from any terminal using `pip`:
```bash
pip install git+https://github.com/Realwaan/ytdlp-workstation.git
```
*(Or via PyPI: `pip install ytdlp-workstation`)*

Once installed, launch it anytime from any directory:
```bash
ytdlp-workstation
```
*(Or: `python -m ytdlp_workstation`)*

---

### 💻 Option 3: Portable Clone & Run (Zero Installation)
If you prefer running it portably from a dedicated folder:
1. Clone or download this repo.
2. Double-click **`run.bat`** (or **`setup.bat`**).
   - Auto-checks and installs Python if needed
   - Downloads official `yt-dlp.exe` and `ffmpeg.exe`
   - Initializes local `downloads/` folder
3. Double-click **`create_desktop_shortcut.bat`** to pin a shortcut to your Desktop!

---

## 🚀 Quick Start

1. **Launch**:
   - Double-click **`YT-DLP Auto-Downloader`** on your **Desktop**, or
   - Double-click [run.bat](file:///f:/YTDLP/run.bat) in `f:\YTDLP`.
2. **Download & Pick Quality**:
   - Copy any video URL in your browser (`Ctrl+C`).
   - The terminal detects it and displays the **Video Quality Picker**:
     ```text
     ╔═══════════════════════════════════════════════════════════════╗
     ║ 🎥 PICK VIDEO QUALITY FOR THIS DOWNLOAD                       ║
     ║  [1] 4K / 2160p (Best Available) - Maximum possible resolution║
     ║  [2] 1440p (2K Quad HD)          - Ultra high quality         ║
     ║  [3] 1080p (Full HD)             - Recommended quality & size ║
     ║  [4] 720p  (HD)                  - Fast download, smaller size║
     ║  [5] 480p  (SD Standard)         - Low bandwidth              ║
     ║  [6] 360p  (Data Saver)          - Smallest video file size   ║
     ║  [7] Audio MP3 (320kbps)         - MP3 with artwork & tags    ║
     ║  [8] Audio M4A (Original AAC)    - Direct audio extraction    ║
     ║  [9] Audio FLAC (Lossless Studio)- Audiophile CD quality      ║
     ║  [a] Audio OPUS (Next-Gen)       - Ultra-efficient audio      ║
     ║  [b] Audio WAV (Raw PCM)         - Uncompressed audio for DAW ║
     ║  [0] Universal MKV (All Subs)    - Preserves all subtitles    ║
     ║  [f] Inspect All Formats (-F)    - Pick exact format ID table ║
     ║  [s] Skip / Cancel                                            ║
     ╚═══════════════════════════════════════════════════════════════╝
     ```
   - Press a **single key** (`1`-`9`, `a`, `b`, `0`) or press **`Enter`** to download in default best quality!

---

## 🎛️ Terminal Power Commands & Shortcuts

Type these commands directly at the `>>> ` prompt anytime:

| Command | Action |
|---|---|
| *(Copy in browser)* | Detects copied URL and triggers quality picker or auto-download |
| `<URL>` | Paste any URL directly to download |
| `play <song/artist>` | Search YouTube Music & instant download top track in **320kbps MP3** with cover art |
| `yt <query>` | Search YouTube and interactively pick from top 5 search results |
| `info <URL>` | Inspect video details, max resolution, audio codecs, and subtitles before downloading |
| `spotify <URL>` | Download Spotify track, album, or playlist in **320kbps MP3** with tags & art |
| `queue` / `qstatus` | View real-time concurrent queue status and parallel workers |
| `workers <1-5>` | Set number of concurrent parallel downloads *(e.g. `workers 3`)* |
| `pause` / `resume` | Pause or resume processing of the download queue |
| `cancel <ID>` | Cancel a pending queued download task |
| `codec <compat/quality>` | Force H.264/AAC for TV compatibility or AV1/VP9 for maximum quality |
| `archive [toggle/clear]` | Manage `--download-archive` duplicate blocker |
| `trim <start>-<end> <URL>` | Download only a specific time segment *(e.g. `trim 01:15-02:30 https://...`)* |
| `items <range> <URL>` | Download only specific playlist tracks *(e.g. `items 1-5 https://...`)* |
| `1080p <URL>` | Download immediately in **1080p Full HD** |
| `720p <URL>` | Download immediately in **720p HD** |
| `4k <URL>` / `1440p <URL>` | Download immediately in **4K** or **2K Quad HD** |
| `480p <URL>` / `360p <URL>` | Download in **480p** or **360p** Data Saver |
| `mp3 <URL>` | Download as **320kbps MP3** with album art & tags |
| `m4a <URL>` / `aac <URL>` | Download as **Original AAC Audio** (.m4a) without re-encoding |
| `flac <URL>` | Download as **Lossless Studio FLAC** |
| `opus <URL>` / `wav <URL>` | Download as **OPUS** or raw **WAV** |
| `subs <URL>` | Force download and embed subtitles |
| `subs <lang> <URL>` | Embed subtitles in specific language *(e.g. `subs es URL`, `subs ja URL`)* |
| `subs list <URL>` | List all available subtitle languages for a video |
| `sb [on/off]` | Toggle SponsorBlock (auto-skip sponsored segments & intros) |
| `ref <referer> <URL>` | Download from cloud streaming servers with Referer header *(e.g. `ref https://videasy.net/ <m3u8_url>`)* |
| `site <name/url>` | Switch active streaming detector site *(e.g. `site cinejoy` or `site movy`)* |
| `f <URL>` | Inspect all available formats with `yt-dlp -F` and pick custom format ID |
| `cookies <browser>` | Borrow browser login session *(e.g. `cookies chrome`, `cookies edge`, `cookies off`)* |
| `limit <rate>` | Cap download speed *(e.g. `limit 5M`, `limit 10M`, `limit off`)* |
| `↑` / `↓` *(Arrow Keys)* | Recall previously entered commands and URLs from interactive history |
| `qmode` | Toggle Quality Picker (**Prompt Each Time** vs **Auto Use Default**) |
| `p` or `preset` | Change default quality preset (1-12) |
| `c` or `clip` | Toggle Clipboard Monitor (**Auto-detect** ➔ **Ask First** ➔ **Off**) |
| `o` or `open` | Open `downloads` folder in Windows File Explorer |
| `d` or `dir` | Change downloads folder destination |
| `h` or `history` [clear] | View recent download history (or `h clear` to reset) |
| `nowm <URL>` | Download clean unwatermarked video directly (TikTok, Douyin, CapCut) |
| `sniff <URL>` | Sniff arbitrary webpage for embedded video streams (.m3u8/.mpd/.mp4) |
| `clean <1..N> [delogo/crop]` | Remove corner watermark (delogo) or crop banner from video |
| `norm [on/off/toggle]` | EBU R128 international broadcast audio loudness normalization (-16 LUFS) |
| `lyrics [on/off | song]` | Synchronized lyrics (.lrc) auto-downloading & LRCLIB search query |
| `dashboard` / `web [port]` | Launch modern glassmorphic web dashboard & local REST telemetry server |
| `sub <list/add/toggle/check>` | Automated channel subscriptions & background upload monitor |
| `webhook <list/add/test>` | Discord and HTTP JSON webhook completion notifications |
| `batch <file.txt>` | Import multi-line text file of URLs and enqueue downloads |
| `s` or `settings` | Full interactive settings menu |
| `u` or `update` | Run `yt-dlp -U` to update yt-dlp to latest version |
| `cls` or `clear` | Clear screen and reprint status dashboard |
| `q` or `exit` | Exit the terminal |

---

## 🍪 Browser Cookie Integration (Bypass Login & Age Walls)

To download age-restricted YouTube videos, Instagram posts, or Twitter/X sensitive clips:
1. In the terminal, type:
   ```text
   cookies chrome
   ```
   *(or `cookies edge`, `cookies firefox`, `cookies brave`)*
2. That's it! `yt-dlp` will automatically use your browser session to download login-restricted videos with no prompts or sign-in blocks.

---

## ✂️ Video Trimming & Clip Extractor

Download short clips directly without wasting bandwidth downloading full hours-long videos:
```text
trim 01:15-02:30 https://www.youtube.com/watch?v=...
clip 10:00-15:00 https://www.youtube.com/watch?v=...
```

---

## ☁️ Cloud Video Servers & Web Embeds (VidEasy, FileMoon, StreamTape, etc.)

Third-party movie/anime embed servers (like **VidEasy**, FileMoon, StreamTape, VidCloud, etc.) deliver standard **HLS (`.m3u8`)** or progressive `.mp4` chunks. They do not use commercial DRM encryption, but they **require an HTTP Referer header** to prevent hotlinking (which causes `403 Forbidden` if missing).

### How to Download from VidEasy or Cloud Servers:
1. Open the video page in your web browser (Chrome, Edge, or Firefox).
2. Press **`F12`** to open Developer Tools, then switch to the **Network** tab.
3. In the filter box, type **`m3u8`**.
4. Play the video for 2–3 seconds. A request ending in `.m3u8` (e.g., `playlist.m3u8` or `master.m3u8`) will appear in the list.
5. Right-click the `.m3u8` request ➔ **Copy** ➔ **Copy URL**.
6. In the terminal, run:
   ```text
   ref https://videasy.net/ <pasted_m3u8_url>
   ```
   *(Or replace `https://videasy.net/` with the domain of the website where you watched the video)*
7. The terminal passes `--referer` to `yt-dlp`, bypasses the 403 block, picks the highest resolution video stream, and compiles the full video with audio into your `downloads` folder!

> [!NOTE]
> **Commercial DRM Platforms (Netflix, Disney+, Prime Video, etc.)**: These services do not use open HLS or direct cloud files; they enforce proprietary Widevine/PlayReady hardware-level digital rights management (DRM) and license exchange handshakes. `yt-dlp` does not decrypt or bypass hardware DRM. Open cloud streaming servers and web embeds (VidEasy, etc.), however, use standard unencrypted streams and are fully supported.

---

## 🎵 Spotify Studio Engine (Tracks, Albums & Playlists)

The workstation features built-in Spotify media extraction:
- **Zero API Keys Required**: Uses public Spotify oEmbed and Web Embed JSON data directly.
- **Auto-Clipboard Detection**: Copy any `open.spotify.com/track/...`, `/album/...`, or `/playlist/...` link (or shortlink `spotify.link/...`), and the terminal immediately detects and queues it!
- **High-Fidelity 320kbps MP3**: Downloads the highest available studio master audio match.
- **Official Spotify Album Art & ID3 Tags**: Embeds the official high-resolution album cover and tags (`Artist`, `Title`, `Album`, `Track Number`).
- **Organized Album Subfolders**: Albums and playlists are automatically grouped into their own dedicated subfolder (`downloads/<Artist> - <Album>/01 - <Track>.mp3`).

---

## 🎧 Instant YouTube Audio Search (`play`) & Video Finder (`yt`)

Download music and videos without ever leaving the terminal or opening your browser:
- **Instant Audio (`play <song>`)**:
  ```text
  play hotel california eagles
  ```
  Searches YouTube, selects the top match, downloads the best audio stream, converts to 320kbps MP3, and embeds thumbnail cover art in one command.
- **Interactive Search (`yt <query>`)**:
  ```text
  yt synthwave radio
  ```
  Displays the top 5 YouTube results with video titles, channel names, and durations. Press `1`-`5` to download any item, `a` to download all 5, or `s` to cancel.

---

## 🔎 Media Inspector & Stream Inspector (`info`)

Inspect detailed video and stream properties before committing to a download:
```text
info https://www.youtube.com/watch?v=...
```
Displays:
- Video title, channel/uploader, view count, and upload date
- Exact duration and duration formatted in HH:MM:SS
- All available video resolutions (from 4K/2160p down to 360p) with container formats
- Available audio streams (M4A, OPUS, WebM) with sample rates and bitrates
- All available subtitle and closed-caption languages

---

## 🛡️ SponsorBlock Integration (`sb`)

Auto-skip YouTube sponsors, intro cards, self-promos, and channel subscribe reminders:
```text
sb on       # Enable SponsorBlock auto-skipping
sb off      # Disable SponsorBlock
sb          # Toggle on/off
```
When enabled, SponsorBlock segments are automatically trimmed directly during the stream merge process.

---

## ⌨️ Command History with Arrow Keys & History Management

- **Up & Down Arrow Navigation**: Press `↑` and `↓` at the `>>>` prompt to cycle through previously typed commands, URLs, and search queries.
- **History Reset**: View recent downloads with `history` (or `h`), and reset the log anytime with:
  ```text
  h clear
  ```

---

## 💾 Disk Space Safety Guard

The workstation actively monitors your target download drive:
- **Dashboard Badge**: Displays available free disk space directly in the status header (e.g. `156.8 GB Free`).
- **Low-Space Warning**: If free disk space drops below **1.0 GB**, the terminal proactively alerts you before initiating heavy video downloads to avoid incomplete files or corrupted system drives.

---

## 🛡️ 99.9% Download Success Rate & Antivirus Resilience

Windows antivirus real-time scanners (Windows Defender, Search Indexer) frequently lock temporary `.part` files as soon as download fragments finish writing, causing `[WinError 32] The process cannot access the file because it is being used by another process`.

The workstation applies 5 enterprise-grade hardening layers:
1. **Direct Fragment Writing (`--no-part`)**: Writes chunks directly without intermediate `.part` files, completely eliminating lock rename collisions.
2. **Byte-Range 416 Immunity (`--no-continue`)**: Cloud streaming CDNs reject partial resume byte-ranges on HLS fragments with `HTTP Error 416`. Re-fetching individual stalled 2MB chunks prevents stream corruption without restarting the entire download.
3. **25x File Access Retries (`--file-access-retries 25`)**: Retries file access with exponential backoff if an antivirus scanner briefly inspects a file.
4. **25x Fragment Retries (`--fragment-retries 25`)**: Automatically retries any transient connection drops or fragment stalls.
5. **Exponential Retry Sleep (`--retry-sleep fragment:exp=1:20`)**: Sleeps smoothly to give Windows Defender time to release file locks before writing.

---

## 🔔 Native Windows Desktop Notifications

Whenever a download completes, a native Windows 10/11 Toast notification pops up in the bottom-right corner of your screen showing the file title, duration, and download status—so you always know when your video is ready even if the terminal is minimized!

---

## 🌐 Supported Video Sites & Links (1,750+ Websites)

Powered by `yt-dlp`:
- **Social & Video Platforms**: YouTube, Shorts, TikTok, Instagram (Reels/Stories/Posts), Twitter/X, Facebook, Reddit, Twitch (Clips & VODs), Vimeo, Bilibili, Dailymotion, Pinterest, Threads, Snapchat, Tumblr, LinkedIn.
- **Livestreams & Hosts**: Kick, Rumble, Streamable, Loom, VK, OK.ru, Odysee, BitChute, Archive.org.
- **Audio & Podcasts**: SoundCloud, Bandcamp, Mixcloud, YouTube Music.
- **Direct Video Streams**: Any link ending in `.mp4`, `.m3u8`, `.webm`, `.mov`, `.mkv`, `.ts`, `.mpd`, etc.

---

## 📁 Repository Structure

| Path | Description |
|---|---|
| [run.bat](file:///f:/YTDLP/run.bat) | **1-Click Launcher** - Double-click to launch the workstation immediately |
| [bin/](file:///f:/YTDLP/bin/) | Bundled standalone executables (`yt-dlp.exe`, `ffmpeg.exe`, `ffprobe.exe`, `aria2c.exe`) |
| [data/](file:///f:/YTDLP/data/) | User configuration, history logs, and download archive (`config.json`, `history.json`, `archive.txt`) |
| [scripts/](file:///f:/YTDLP/scripts/) | Setup utilities, desktop shortcut creator, and installer scripts |
| [ytdlp_workstation/](file:///f:/YTDLP/ytdlp_workstation/) | Core modular package (`core/`, `engine/`, `extractors/`, `queue/`, `web/`, `utils/`, `cli/`) |
| [downloads/](file:///f:/YTDLP/downloads/) | Default folder where downloaded media and music are saved |
| [tests/](file:///f:/YTDLP/tests/) | Full Pytest automated test suite (172 unit & integration tests) |
| [pyproject.toml](file:///f:/YTDLP/pyproject.toml) | Modern PEP 621 Python package configuration (v2.0) |
| [requirements.txt](file:///f:/YTDLP/requirements.txt) | Python dependencies (`colorama`, `pyperclip`, `yt-dlp`) |
| [.gitignore](file:///f:/YTDLP/.gitignore) | Git ignore rules excluding binaries (>100MB), personal downloads, and user logs |
| [LICENSE](file:///f:/YTDLP/LICENSE) | Open source MIT License |

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).

