"""
Dedicated YouTube Automation Ranking Downloader.

Designed specifically for automated video ranking pipelines:
Downloads clean, unwatermarked videos from TikTok, Instagram, YouTube, etc.
directly as <number>.mp4 into target folder (default: E:\\YTAutomationFiles\\src).
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Optional

from ..core.state import STATE, DownloadJob, AppState
from ..core.config import DEFAULT_DOWNLOAD_DIR
from ..queue.manager import QueueManager
from ..extractors.url_detector import is_valid_media_url, extract_media_url, clean_url
from ..extractors.referer import auto_detect_referer
from ..extractors.no_watermark import resolve_no_watermark_media
from ..utils.clipboard import get_clipboard_text
from ..utils.notifications import play_sound
from ..utils.system import open_file_or_folder, set_console_title, reset_console_title
from .ui import Fore, Style, format_job_progress, format_linux_bar
from .commands import get_next_rank_number


DEFAULT_RANK_DIR = Path(r"E:\YTAutomationFiles\src")


def print_rank_banner(target_dir: Path):
    """Display dedicated ranking workstation banner."""
    target_dir.mkdir(parents=True, exist_ok=True)
    next_slot = get_next_rank_number(target_dir)
    files = sorted(
        [f for f in target_dir.iterdir() if f.is_file() and f.suffix.lower() in (".mp4", ".mov", ".mkv", ".webm")],
        key=lambda x: (int(x.stem) if x.stem.isdigit() else 999999, x.name)
    )

    print(f"""
{Fore.CYAN}╔═══════════════════════════════════════════════════════════════════════════╗
║  {Fore.LIGHTGREEN_EX}🎬 YT AUTOMATION RANKING DOWNLOADER (1-CLICK RUNNER){Fore.CYAN}                    ║
║  Auto-downloads clean unwatermarked MP4s as {Fore.WHITE}1.mp4, 2.mp4, 3.mp4...{Fore.CYAN}       ║
║  Destination: {Fore.LIGHTYELLOW_EX}{str(target_dir):<57}{Fore.CYAN} ║
╚═══════════════════════════════════════════════════════════════════════════╝{Style.RESET_ALL}
""")
    if files:
        names_preview = ", ".join(f"{f.name}" for f in files[:8])
        extra = f" (+{len(files) - 8} more)" if len(files) > 8 else ""
        print(f"  {Fore.WHITE}Current Clips in folder ({len(files)}):{Style.RESET_ALL} {Fore.LIGHTGREEN_EX}{names_preview}{extra}{Style.RESET_ALL}")
    else:
        print(f"  {Fore.LIGHTBLACK_EX}No video files in target folder yet.{Style.RESET_ALL}")
    print(f"  {Fore.GREEN}[⚡] Next Suggested Rank Slot:{Style.RESET_ALL} {Fore.LIGHTYELLOW_EX}#{next_slot}{Style.RESET_ALL}\n")


def run_rank_loop(target_dir: Optional[Path] = None):
    """Run interactive continuous ranking loop."""
    if target_dir is None:
        target_dir = Path(STATE.config.get("rank_download_dir", str(DEFAULT_RANK_DIR)))
    target_dir.mkdir(parents=True, exist_ok=True)

    set_console_title("YT Automation Ranking Downloader")
    queue_mgr = QueueManager(max_workers=2)

    def _on_job_progress(job: DownloadJob):
        sys.stdout.write(
            format_linux_bar(
                job.display_title or job.url,
                job.progress_pct,
                job.downloaded_str,
                job.total_str,
                job.speed_str,
                job.eta_str,
                job.fragment_str,
                status=job.status,
            )
        )
        sys.stdout.flush()

    def _on_job_finished(job: DownloadJob, success: bool):
        sys.stdout.write("\n")
        sys.stdout.flush()
        if success:
            play_sound("success", enabled=True)
            print(f"\n{Fore.GREEN}[✓] COMPLETED:{Style.RESET_ALL} {Fore.LIGHTGREEN_EX}{job.saved_filename or job.display_title}{Style.RESET_ALL} ({job.saved_filesize_str})")
            print(f"    {Fore.WHITE}Saved directly to:{Style.RESET_ALL} {target_dir}\n")
        else:
            play_sound("error", enabled=True)
            print(f"\n{Fore.RED}[X] FAILED:{Style.RESET_ALL} {job.error_message or 'Unknown error'}\n")

    queue_mgr.on_job_progress = _on_job_progress
    queue_mgr.on_job_finished = _on_job_finished

    print_rank_banner(target_dir)

    try:
        while not STATE.stop_requested:
            next_slot = get_next_rank_number(target_dir, queue_mgr=queue_mgr)
            prompt = (
                f"{Fore.CYAN}👉 Enter Rank #{next_slot} {Fore.WHITE}(Press {Fore.LIGHTYELLOW_EX}[Enter]{Fore.WHITE} for #{next_slot}, or type number, 'open', 'cls', 'q'): {Style.RESET_ALL}"
            )
            try:
                user_input = input(prompt).strip()
            except (KeyboardInterrupt, EOFError):
                break

            if not user_input:
                rank_num = next_slot
                url = None
            else:
                cmd_lower = user_input.lower()
                if cmd_lower in ("q", "quit", "exit"):
                    break
                if cmd_lower in ("cls", "clear"):
                    if os.name == "nt":
                        os.system("cls")
                    print_rank_banner(target_dir)
                    continue
                if cmd_lower in ("open", "dir", "o"):
                    if hasattr(os, "startfile"):
                        os.startfile(str(target_dir))
                    else:
                        open_file_or_folder(target_dir)
                    print(f"{Fore.GREEN}[✓] Opened folder in File Explorer.{Style.RESET_ALL}\n")
                    continue
                if cmd_lower in ("list", "ls", "files"):
                    files = sorted(
                        [f for f in target_dir.iterdir() if f.is_file() and f.suffix.lower() in (".mp4", ".mov", ".mkv", ".webm")],
                        key=lambda x: (int(x.stem) if x.stem.isdigit() else 999999, x.name)
                    )
                    print(f"\n{Fore.CYAN}Files in {target_dir}:{Style.RESET_ALL}")
                    for f in files:
                        sz_mb = f.stat().st_size / (1024 * 1024)
                        print(f"  • {Fore.LIGHTGREEN_EX}{f.name:<12}{Style.RESET_ALL} ({sz_mb:.1f} MB)")
                    print("")
                    continue

                parts = user_input.split(maxsplit=1)
                first_part = parts[0].lstrip("#")
                if first_part.isdigit():
                    rank_num = int(first_part)
                    url = extract_media_url(parts[1]) if len(parts) > 1 else None
                elif is_valid_media_url(user_input):
                    rank_num = next_slot
                    url = extract_media_url(user_input) or user_input
                else:
                    print(f"{Fore.RED}[!] Please enter a rank number (e.g. 6), press Enter, or type 'open' / 'q'.{Style.RESET_ALL}\n")
                    continue

            # Auto-detect URL from clipboard if not typed
            if not url:
                try:
                    clip_text = get_clipboard_text().strip()
                except Exception:
                    clip_text = ""
                if clip_text and is_valid_media_url(clip_text):
                    url = extract_media_url(clip_text) or clip_text
                    print(f"{Fore.GREEN}[⚡] Auto-detected URL from clipboard:{Style.RESET_ALL} {Fore.CYAN}{url}{Style.RESET_ALL}")
                else:
                    print(f"{Fore.YELLOW}[*] No video link currently on clipboard.{Style.RESET_ALL}")
                    try:
                        manual_url = input(f"{Fore.WHITE}Paste TikTok / Video URL >>> {Style.RESET_ALL}").strip()
                    except (KeyboardInterrupt, EOFError):
                        break
                    if not manual_url:
                        print(f"{Fore.YELLOW}[!] Cancelled.{Style.RESET_ALL}\n")
                        continue
                    url = extract_media_url(manual_url) or manual_url

            if not url or not is_valid_media_url(url):
                print(f"{Fore.RED}[!] Invalid media URL: {url}{Style.RESET_ALL}\n")
                continue

            target_output_file = target_dir / f"{rank_num}.mp4"
            print(f"{Fore.CYAN}[🔍] Resolving unwatermarked stream for Rank #{rank_num}...{Style.RESET_ALL}")

            try:
                media = resolve_no_watermark_media(url)
            except Exception:
                media = None

            if media and media.direct_url:
                direct_url = media.direct_url
                referer = media.referer or "https://www.tiktok.com/"
                display_title = f"Rank #{rank_num} ({media.title[:30]})" if media.title else f"Rank #{rank_num}"
                print(f"{Fore.GREEN}[✓] Extracted clean unwatermarked stream! ({media.platform}){Style.RESET_ALL}")
            else:
                direct_url = url
                referer = auto_detect_referer(url, default_referer="https://www.tiktok.com/")
                display_title = f"Rank #{rank_num}"

            out_tmpl = str(target_dir / f"{rank_num}.%(ext)s")

            job = DownloadJob(
                url=direct_url,
                referer=referer,
                display_title=display_title,
                target_dir=str(target_dir),
                custom_output_template=out_tmpl,
                preset_override=1,  # Best Available MP4
                force_video=True,
                needs_quality_prompt=False,
            )

            queue_mgr.enqueue(job)
            print(f"{Fore.GREEN}[+] Queued download for Rank #{rank_num} -> {target_output_file.name}{Style.RESET_ALL}")

            # Wait for this job to reach a terminal state (including STARTING and
            # FFmpeg PROCESSING) before prompting for the next slot.
            while job.status not in ("COMPLETED", "FAILED", "CANCELLED"):
                time.sleep(0.2)

    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        reset_console_title()
        queue_mgr.stop_requested = True
        print(f"\n{Fore.YELLOW}Exited YT Automation Ranking Downloader. Goodbye!{Style.RESET_ALL}\n")


def main():
    """CLI entrypoint."""
    run_rank_loop()


if __name__ == "__main__":
    main()
