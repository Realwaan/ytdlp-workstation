use crate::sniffer::clean_url_impl;
use regex::Regex;
use std::sync::OnceLock;

const COMMON_MEDIA_DOMAINS: &[&str] = &[
    // Music & Podcasts
    r"(?:open\.)?spotify\.com",
    r"spotify\.link",
    r"(?:www\.)?soundcloud\.com",
    r"(?:www\.)?bandcamp\.com",
    r"(?:www\.)?mixcloud\.com",
    // Major Video Platforms
    r"(?:www\.)?youtube\.com",
    r"youtu\.be",
    r"(?:www\.)?vimeo\.com",
    r"(?:www\.)?dailymotion\.com",
    r"dai\.ly",
    r"(?:www\.)?bilibili\.com",
    r"b23\.tv",
    r"(?:www\.)?twitch\.tv",
    r"(?:www\.)?kick\.com",
    r"(?:www\.)?rumble\.com",
    r"(?:www\.)?streamable\.com",
    r"(?:www\.)?loom\.com",
    r"(?:www\.)?odysee\.com",
    r"(?:www\.)?bitchute\.com",
    r"(?:www\.)?crunchyroll\.com",
    r"(?:www\.)?ted\.com",
    r"(?:www\.)?archive\.org",
    // Social & Short-Form Video
    r"(?:www\.)?tiktok\.com",
    r"vt\.tiktok\.com",
    r"vm\.tiktok\.com",
    r"(?:www\.)?douyin\.com",
    r"v\.douyin\.com",
    r"iesdouyin\.com",
    r"(?:www\.)?capcut\.com",
    r"(?:www\.)?kuaishou\.com",
    r"kwai\.com",
    r"(?:www\.)?xiaohongshu\.com",
    r"xhslink\.com",
    r"(?:www\.)?instagram\.com",
    r"(?:www\.)?threads\.net",
    r"(?:www\.)?snapchat\.com",
    r"(?:www\.)?pinterest\.com",
    r"pin\.it",
    r"(?:www\.)?twitter\.com",
    r"(?:www\.)?x\.com",
    r"t\.co",
    r"(?:www\.)?reddit\.com",
    r"v\.redd\.it",
    r"(?:www\.)?facebook\.com",
    r"fb\.watch",
    r"(?:www\.)?weibo\.com",
    r"weibo\.cn",
    r"(?:www\.)?linkedin\.com",
    r"(?:www\.)?tumblr\.com",
    r"(?:www\.)?vk\.com",
    r"(?:www\.)?ok\.ru",
    r"(?:www\.)?imgur\.com",
    r"(?:www\.)?giphy\.com",
    r"(?:www\.)?redgifs\.com",
    // Streaming hosts & cloud embeds
    r"(?:www\.)?streamtape\.com",
    r"doodstream\.com",
    r"dood\.to",
    r"dood\.watch",
    r"dood\.so",
    r"filemoon\.sx",
    r"filemoon\.to",
    r"voe\.sx",
    r"voe-network\.net",
    r"mixdrop\.co",
    r"mixdrop\.to",
    r"mp4upload\.com",
    r"vidhide\.com",
    r"vidhidepro\.com",
    r"streamsb\.net",
    r"sbembed\.com",
    r"watchsb\.com",
    r"streamwish\.to",
    r"streamwish\.com",
    r"vidmoly\.me",
    r"upstream\.to",
];

struct ParserRegexes {
    media_domain: Regex,
    media_ext: Regex,
    generic_url: Regex,
    douyin_wm: Regex,
    aria2: Regex,
    merger: Regex,
    extract_audio: Regex,
    already_dl: Regex,
}

fn parser_regexes() -> &'static ParserRegexes {
    static RX: OnceLock<ParserRegexes> = OnceLock::new();
    RX.get_or_init(|| {
        let domain_union = COMMON_MEDIA_DOMAINS.join("|");
        let media_pat = format!(
            r"(?i)https?://(?:[a-zA-Z0-9_\-]+\.)*(?:{})(?::[0-9]+)?(?:/[^\s]*)?",
            domain_union
        );
        ParserRegexes {
            media_domain: Regex::new(&media_pat).expect("valid media_domain DFA"),
            media_ext: Regex::new(
                r"(?i)https?://[^\s]+\.(?:mp4|m3u8|webm|mov|mkv|flv|avi|ts|mpd|mp3|m4a|aac|wav|opus|ogg|flac)(?:\?[^\s]*)?",
            )
            .expect("valid media_ext DFA"),
            generic_url: Regex::new(r"(?i)^https?://[a-zA-Z0-9\-.]+(?::[0-9]+)?(?:/[^\s]*)?$")
                .expect("valid generic_url DFA"),
            douyin_wm: Regex::new(r"([?&])watermark=[0-9]+").expect("valid douyin_wm DFA"),
            aria2: Regex::new(
                r"\[#[0-9a-fA-F]+\s+([^\s/]+)/([^\s(]+)\((\d+(?:\.\d+)?)%\).*?DL:([^\s\]]+)(?:\s+ETA:([^\s\]]+))?",
            )
            .expect("valid aria2 DFA"),
            merger: Regex::new(r#"\[Merger\] Merging formats into "(.+)""#)
                .expect("valid merger DFA"),
            extract_audio: Regex::new(r"\[ExtractAudio\] Destination: (.+)")
                .expect("valid extract_audio DFA"),
            already_dl: Regex::new(r"\[download\] (.+) has already been downloaded")
                .expect("valid already_dl DFA"),
        }
    })
}

/// Validate if `text` contains or is a downloadable media URL (linear-time DFA).
pub fn is_valid_media_url_impl(text: &str, media_filter_only: bool) -> bool {
    let trimmed = text.trim();
    if trimmed.is_empty() {
        return false;
    }
    let rx = parser_regexes();
    if media_filter_only {
        rx.media_domain.is_match(trimmed) || rx.media_ext.is_match(trimmed)
    } else {
        rx.generic_url.is_match(trimmed)
            || trimmed.starts_with("http://")
            || trimmed.starts_with("https://")
    }
}

/// Extract first matching media or HTTP(S) URL from `text`.
pub fn extract_media_url_impl(text: &str) -> Option<String> {
    if text.is_empty() {
        return None;
    }
    let rx = parser_regexes();
    if let Some(m) = rx.media_domain.find(text) {
        return Some(m.as_str().to_string());
    }
    if let Some(m) = rx.media_ext.find(text) {
        return Some(m.as_str().to_string());
    }
    let trimmed = text.trim();
    if let Some(m) = rx.generic_url.find(trimmed) {
        return Some(m.as_str().to_string());
    }
    if trimmed.starts_with("http://") || trimmed.starts_with("https://") {
        Some(trimmed.to_string())
    } else {
        None
    }
}

/// Clean, filter comments, and validate a batch of raw lines into ready-to-enqueue URLs.
pub fn filter_valid_media_urls_batch_impl(
    lines: &[String],
    media_filter_only: bool,
) -> Vec<String> {
    let mut out = Vec::with_capacity(lines.len());
    for raw in lines {
        let trimmed = raw.trim();
        if trimmed.is_empty() || trimmed.starts_with('#') {
            continue;
        }
        let cleaned = clean_url_impl(trimmed);
        if is_valid_media_url_impl(&cleaned, media_filter_only) {
            out.push(cleaned);
        }
    }
    out
}

/// Strip `/playwm/` and `watermark=` query parameter from Douyin CDN URLs.
pub fn clean_douyin_watermark_url_impl(url: &str) -> String {
    if url.is_empty() {
        return String::new();
    }
    let replaced = url.replace("/playwm/", "/play/");
    parser_regexes()
        .douyin_wm
        .replace_all(&replaced, "")
        .into_owned()
}

/// Borrowed zero-copy telemetry event slices pointing directly into the input `raw_line`.
#[derive(Clone, Debug, PartialEq)]
pub struct BorrowedProgressEvent<'a> {
    pub kind: &'static str,
    pub pct: f64,
    pub downloaded: &'a str,
    pub total: &'a str,
    pub speed_borrowed: &'a str,
    pub speed_owned: Option<String>,
    pub eta: &'a str,
    pub extra: &'a str,
    pub extra_owned: Option<String>,
}

impl<'a> BorrowedProgressEvent<'a> {
    #[inline]
    pub fn speed(&self) -> &str {
        self.speed_owned.as_deref().unwrap_or(self.speed_borrowed)
    }

    #[inline]
    pub fn extra_str(&self) -> &str {
        self.extra_owned.as_deref().unwrap_or(self.extra)
    }
}

/// Fast zero-allocation slice parser for `yt-dlp` and `aria2c` stdout lines.
pub fn parse_progress_line_borrowed<'a>(raw_line: &'a str) -> Option<BorrowedProgressEvent<'a>> {
    let line = raw_line.trim();
    if line.is_empty() {
        return None;
    }

    // Fast first-byte / length rejection for ordinary log lines
    let b0 = line.as_bytes()[0];
    if b0 != b'P' && b0 != b'[' && !line.contains("PROGRESS|") && !line.contains("ERROR:") && !line.contains("already been") {
        return None;
    }

    // 1. Custom yt-dlp `--progress-template` line (100% zero-allocation `&str` slices)
    if line.contains("PROGRESS|P=")
        || (line.contains("P=") && line.contains("|D=") && line.contains("|S="))
    {
        let payload = match line.rsplit_once("PROGRESS|") {
            Some((_, after)) => after,
            None => line,
        };

        let mut pct = 0.0f64;
        let mut downloaded = "";
        let mut total = "";
        let mut speed = "--";
        let mut eta = "--:--";
        let mut fragment = "";

        for seg in payload.split('|') {
            if let Some((k, v)) = seg.split_once('=') {
                let key = k.trim();
                let val = v.trim();
                match key {
                    "P" => {
                        pct = val.trim_end_matches('%').trim().parse::<f64>().unwrap_or(0.0);
                    }
                    "D" => downloaded = val,
                    "T" => total = val,
                    "S" => speed = val,
                    "E" => eta = val,
                    "F" => fragment = val,
                    _ => {}
                }
            }
        }

        return Some(BorrowedProgressEvent {
            kind: "progress",
            pct,
            downloaded,
            total,
            speed_borrowed: speed,
            speed_owned: None,
            eta,
            extra: fragment,
            extra_owned: None,
        });
    }

    // 2. aria2c progress summary line
    if line.starts_with("[#") || (line.contains("[#") && line.contains('%') && line.contains("DL:")) {
        if line.contains('%') && line.contains("DL:") {
            let rx = parser_regexes();
            if let Some(caps) = rx.aria2.captures(line) {
                let downloaded = caps.get(1).map_or("", |m| m.as_str());
                let total = caps.get(2).map_or("", |m| m.as_str());
                let pct = caps
                    .get(3)
                    .and_then(|m| m.as_str().parse::<f64>().ok())
                    .unwrap_or(0.0);
                let dl_rate = caps.get(4).map_or("", |m| m.as_str());
                let eta = caps.get(5).map_or("--:--", |m| m.as_str());
                return Some(BorrowedProgressEvent {
                    kind: "aria2c",
                    pct,
                    downloaded,
                    total,
                    speed_borrowed: "",
                    speed_owned: Some(format!("{}/s", dl_rate)),
                    eta,
                    extra: "",
                    extra_owned: None,
                });
            }
        }
    }

    // 3. FFmpeg Merger / ExtractAudio post-processing lines
    if line.contains("[Merger]") || line.contains("[ExtractAudio]") {
        let rx = parser_regexes();
        let filepath = rx
            .merger
            .captures(line)
            .or_else(|| rx.extract_audio.captures(line))
            .and_then(|c| c.get(1))
            .map_or("", |m| m.as_str().trim().trim_matches('"'));

        return Some(BorrowedProgressEvent {
            kind: "postprocess",
            pct: 100.0,
            downloaded: "",
            total: "",
            speed_borrowed: "",
            speed_owned: None,
            eta: "",
            extra: filepath,
            extra_owned: None,
        });
    }

    // 4. Download destination notice
    if let Some((_, after)) = line.split_once("[download] Destination:") {
        return Some(BorrowedProgressEvent {
            kind: "destination",
            pct: 0.0,
            downloaded: "",
            total: "",
            speed_borrowed: "",
            speed_owned: None,
            eta: "",
            extra: after.trim().trim_matches('"'),
            extra_owned: None,
        });
    }

    // 5. Already downloaded / archive skip notice
    if line.contains("has already been downloaded")
        || line.contains("has already been recorded in the archive")
    {
        let rx = parser_regexes();
        let filepath = rx
            .already_dl
            .captures(line)
            .and_then(|c| c.get(1))
            .map_or("", |m| m.as_str().trim().trim_matches('"'));
        return Some(BorrowedProgressEvent {
            kind: "archive_skip",
            pct: 0.0,
            downloaded: "",
            total: "",
            speed_borrowed: "",
            speed_owned: None,
            eta: "",
            extra: filepath,
            extra_owned: None,
        });
    }

    // 6. Error diagnostic line
    if line.contains("ERROR:") {
        let detail = line.replace("ERROR:", "").trim().to_string();
        if !detail.is_empty() {
            return Some(BorrowedProgressEvent {
                kind: "error",
                pct: 0.0,
                downloaded: "",
                total: "",
                speed_borrowed: "",
                speed_owned: None,
                eta: "",
                extra: "",
                extra_owned: Some(detail),
            });
        }
    }

    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn validates_and_extracts_media_urls() {
        assert!(is_valid_media_url_impl(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            true
        ));
        assert!(is_valid_media_url_impl(
            "https://vt.tiktok.com/ZSjR1234/",
            true
        ));
        assert!(is_valid_media_url_impl(
            "https://cdn.example.com/videos/stream.m3u8?token=abc",
            true
        ));
        assert!(!is_valid_media_url_impl(
            "https://example.com/article/read-me",
            true
        ));
        assert!(is_valid_media_url_impl(
            "https://example.com/article/read-me",
            false
        ));

        assert_eq!(
            extract_media_url_impl("Check this https://youtu.be/dQw4w9WgXcQ right now!").as_deref(),
            Some("https://youtu.be/dQw4w9WgXcQ")
        );
    }

    #[test]
    fn parses_ytdlp_and_aria2_progress_lines() {
        let p = parse_progress_line_borrowed(
            "PROGRESS|P= 50.5% |D=50MiB|T=100MiB|S=12.4MiB/s|E=00:04|F=5/10",
        )
        .unwrap();
        assert_eq!(p.kind, "progress");
        assert!((p.pct - 50.5).abs() < 1e-6);
        assert_eq!(p.extra_str(), "5/10");

        let a = parse_progress_line_borrowed("[#408b72 15MiB/42MiB(35%) CN:16 DL:12MiB ETA:2s]")
            .unwrap();
        assert_eq!(a.kind, "aria2c");
        assert!((a.pct - 35.0).abs() < 1e-6);
        assert_eq!(a.speed(), "12MiB/s");
        assert_eq!(a.eta, "2s");

        let m = parse_progress_line_borrowed(r#"[Merger] Merging formats into "My Video [abc].mkv""#)
            .unwrap();
        assert_eq!(m.kind, "postprocess");
        assert_eq!(m.extra_str(), "My Video [abc].mkv");

        assert!(parse_progress_line_borrowed("[youtube] Extracting URL: https://...").is_none());
    }

    #[test]
    fn cleans_douyin_watermark_urls() {
        assert_eq!(
            clean_douyin_watermark_url_impl("https://aweme.snssdk.com/aweme/v1/playwm/?video_id=123&watermark=1"),
            "https://aweme.snssdk.com/aweme/v1/play/?video_id=123"
        );
    }
}
