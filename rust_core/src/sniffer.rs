use futures_util::StreamExt;
use pyo3::prelude::*;
use regex::Regex;
use serde_json::Value;
use std::collections::{HashMap, HashSet};
use std::sync::{Arc, OnceLock};
use std::time::Duration;
use tokio::runtime::{Builder, Runtime};
use tokio::sync::Semaphore;
use url::Url;

const USER_AGENT_DESKTOP: &str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36";
const MAX_SNIFF_HTML_BYTES: usize = 2 * 1024 * 1024; // Cap HTML body read at 2 MiB per page

#[pyclass(frozen, get_all)]
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RustSniffedMedia {
    pub media_url: String,
    pub title: String,
    pub referer: String,
    pub source_type: String,
    pub is_m3u8: bool,
}

#[pymethods]
impl RustSniffedMedia {
    #[new]
    #[pyo3(signature = (media_url, title, referer, source_type="html5".to_string(), is_m3u8=false))]
    pub fn new(
        media_url: String,
        title: String,
        referer: String,
        source_type: String,
        is_m3u8: bool,
    ) -> Self {
        Self {
            media_url,
            title,
            referer,
            source_type,
            is_m3u8,
        }
    }

    #[getter]
    pub fn url(&self) -> &str {
        &self.media_url
    }

    #[getter]
    pub fn stream_type(&self) -> &str {
        &self.source_type
    }
}

struct SnifferRegexes {
    html_title: Regex,
    ws_ctl: Regex,
    title_split: Regex,
    og_video: Regex,
    og_video_alt: Regex,
    ld_json: Regex,
    video_src: Regex,
    player_script: Regex,
}

fn regexes() -> &'static SnifferRegexes {
    static REGEXES: OnceLock<SnifferRegexes> = OnceLock::new();
    REGEXES.get_or_init(|| SnifferRegexes {
        html_title: Regex::new(r"(?i)<title[^>]*>([^<]+)</title>").expect("valid html_title regex"),
        ws_ctl: Regex::new(r"[\r\n\t]+").expect("valid ws_ctl regex"),
        title_split: Regex::new(r"\s+[|\-–—]\s+").expect("valid title_split regex"),
        og_video: Regex::new(
            r#"(?i)<meta\s+[^>]*?(?:property|name)=["'](?:og:video|og:video:url|og:video:secure_url|twitter:player:stream)["']\s+[^>]*?content=["']([^"']+)["']"#,
        )
        .expect("valid og_video regex"),
        og_video_alt: Regex::new(
            r#"(?i)<meta\s+[^>]*?content=["']([^"']+)["']\s+[^>]*?(?:property|name)=["'](?:og:video|og:video:url|og:video:secure_url|twitter:player:stream)["']"#,
        )
        .expect("valid og_video_alt regex"),
        ld_json: Regex::new(
            r#"(?is)<script[^>]*type=["']application/ld\+json["'][^>]*>(.*?)</script>"#,
        )
        .expect("valid ld_json regex"),
        video_src: Regex::new(
            r#"(?i)<(?:video|source)\s+[^>]*?src=["']([^"']+\.(?:mp4|m3u8|webm|mov|mkv|mpd)(?:\?[^"']*)?)["']"#,
        )
        .expect("valid video_src regex"),
        player_script: Regex::new(
            r#"(?i)(?:file|source|src|url)\s*:\s*["'](https?://[^"']+\.(?:mp4|m3u8|webm|mpd)(?:\?[^"']*)?)["']"#,
        )
        .expect("valid player_script regex"),
    })
}

/// Resolve a relative or protocol-relative URL against `base_url`.
pub fn resolve_relative_url_impl(base_url: &str, link: &str) -> String {
    let link = link.trim();
    if link.is_empty() {
        return String::new();
    }
    if link.starts_with("http://") || link.starts_with("https://") {
        return link.to_string();
    }
    if link.starts_with("//") {
        if let Some(colon_idx) = base_url.find(':') {
            let scheme = &base_url[..colon_idx];
            if !scheme.is_empty() {
                return format!("{}:{}", scheme, link);
            }
        }
        return format!("https:{}", link);
    }
    if let Ok(base) = Url::parse(base_url) {
        if let Ok(joined) = base.join(link) {
            return joined.into();
        }
    }
    link.to_string()
}

fn extract_clean_page_title(html: &str, rx: &SnifferRegexes) -> String {
    let raw_title = rx
        .html_title
        .captures(html)
        .and_then(|c| c.get(1))
        .map(|m| m.as_str().trim())
        .unwrap_or("Web Video");

    let collapsed = rx.ws_ctl.replace_all(raw_title, " ");
    let first_part = rx
        .title_split
        .split(&collapsed)
        .next()
        .map(str::trim)
        .unwrap_or("");

    if first_part.is_empty() {
        "Web Video".to_string()
    } else {
        first_part.to_string()
    }
}

fn collect_video_objects<'a>(val: &'a Value, out: &mut Vec<&'a serde_json::Map<String, Value>>) {
    match val {
        Value::Object(map) => {
            let is_video_obj = match map.get("@type") {
                Some(Value::String(t)) => t == "VideoObject",
                Some(Value::Array(arr)) => arr.iter().any(|v| v.as_str() == Some("VideoObject")),
                _ => false,
            };
            if is_video_obj {
                out.push(map);
            }
            if let Some(graph) = map.get("@graph") {
                collect_video_objects(graph, out);
            }
        }
        Value::Array(arr) => {
            for item in arr {
                collect_video_objects(item, out);
            }
        }
        _ => {}
    }
}

#[inline]
fn is_m3u8_url(url: &str) -> bool {
    url.to_ascii_lowercase().contains(".m3u8")
}

#[inline]
fn is_webpage_extension(url: &str) -> bool {
    let lower = url.to_ascii_lowercase();
    lower.ends_with(".html") || lower.ends_with(".htm") || lower.ends_with(".php")
}

/// Extract all unique embedded media streams from raw HTML in priority order.
pub fn extract_all_media_from_html_impl(html: &str, page_url: &str) -> Vec<RustSniffedMedia> {
    if html.is_empty() {
        return Vec::new();
    }

    let rx = regexes();
    let clean_title = extract_clean_page_title(html, rx);
    let mut results: Vec<RustSniffedMedia> = Vec::new();
    let mut seen: HashSet<String> = HashSet::new();

    let mut push_unique = |cand: String, title: String, source_type: &str| {
        if !cand.is_empty() && seen.insert(cand.clone()) {
            let m3u8 = is_m3u8_url(&cand);
            results.push(RustSniffedMedia {
                media_url: cand,
                title,
                referer: page_url.to_string(),
                source_type: source_type.to_string(),
                is_m3u8: m3u8,
            });
        }
    };

    // 1. OpenGraph / Twitter player meta tags
    for re in [&rx.og_video, &rx.og_video_alt] {
        for caps in re.captures_iter(html) {
            if let Some(m) = caps.get(1) {
                let cand = resolve_relative_url_impl(page_url, m.as_str());
                if cand.starts_with("http") && !is_webpage_extension(&cand) {
                    push_unique(cand, clean_title.clone(), "og:video");
                }
            }
        }
    }

    // 2. JSON-LD VideoObject structured data
    for caps in rx.ld_json.captures_iter(html) {
        if let Some(m) = caps.get(1) {
            if let Ok(parsed) = serde_json::from_str::<Value>(m.as_str().trim()) {
                let mut v_objs = Vec::new();
                collect_video_objects(&parsed, &mut v_objs);
                for map in v_objs {
                    let content_url = map
                        .get("contentUrl")
                        .and_then(Value::as_str)
                        .or_else(|| map.get("embedUrl").and_then(Value::as_str));
                    if let Some(raw_u) = content_url {
                        let cand = resolve_relative_url_impl(page_url, raw_u);
                        let v_name = map
                            .get("name")
                            .and_then(Value::as_str)
                            .map(str::trim)
                            .filter(|s| !s.is_empty())
                            .map(str::to_string)
                            .unwrap_or_else(|| clean_title.clone());
                        push_unique(cand, v_name, "json-ld");
                    }
                }
            }
        }
    }

    // 3. HTML5 <video> / <source> elements
    for caps in rx.video_src.captures_iter(html) {
        if let Some(m) = caps.get(1) {
            let cand = resolve_relative_url_impl(page_url, m.as_str());
            push_unique(cand, clean_title.clone(), "html5");
        }
    }

    // 4. Inline player configs (JWPlayer, VideoJS, Hls.js)
    for caps in rx.player_script.captures_iter(html) {
        if let Some(m) = caps.get(1) {
            let cand = resolve_relative_url_impl(page_url, m.as_str());
            push_unique(cand, clean_title.clone(), "player-config");
        }
    }

    results
}

/// Extract the highest-priority embedded media stream from raw HTML.
pub fn extract_media_from_html_impl(html: &str, page_url: &str) -> Option<RustSniffedMedia> {
    extract_all_media_from_html_impl(html, page_url)
        .into_iter()
        .next()
}

pub(crate) fn tokio_runtime() -> &'static Runtime {
    static RT: OnceLock<Runtime> = OnceLock::new();
    RT.get_or_init(|| {
        Builder::new_multi_thread()
            .worker_threads(4)
            .enable_all()
            .thread_name("ytdlp-rust-worker")
            .build()
            .expect("Failed to initialize Tokio runtime")
    })
}

pub(crate) fn http_client_with_headers() -> &'static reqwest::Client {
    static CLIENT: OnceLock<reqwest::Client> = OnceLock::new();
    CLIENT.get_or_init(|| {
        reqwest::Client::builder()
            .user_agent(USER_AGENT_DESKTOP)
            .pool_max_idle_per_host(24)
            .tcp_nodelay(true)
            .redirect(reqwest::redirect::Policy::limited(8))
            .build()
            .expect("Failed to build reqwest HTTP client")
    })
}

fn http_client() -> &'static reqwest::Client {
    http_client_with_headers()
}

async fn sniff_single_async(page_url: String, timeout: Duration) -> Option<RustSniffedMedia> {
    if !page_url.starts_with("http://") && !page_url.starts_with("https://") {
        return None;
    }

    let resp = http_client()
        .get(&page_url)
        .header(
            reqwest::header::ACCEPT,
            "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        )
        .header(reqwest::header::ACCEPT_LANGUAGE, "en-US,en;q=0.9")
        .timeout(timeout)
        .send()
        .await
        .ok()?;

    if !resp.status().is_success() {
        return None;
    }

    let final_url = resp.url().to_string();
    let content_type = resp
        .headers()
        .get(reqwest::header::CONTENT_TYPE)
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .to_ascii_lowercase();

    if content_type.contains("video/")
        || content_type.contains("audio/")
        || content_type.contains("application/vnd.apple.mpegurl")
        || content_type.contains("application/x-mpegurl")
    {
        let m3u8 = content_type.contains("mpegurl") || is_m3u8_url(&final_url);
        return Some(RustSniffedMedia {
            media_url: final_url,
            title: "Direct Video Stream".to_string(),
            referer: page_url,
            source_type: "direct-header".to_string(),
            is_m3u8: m3u8,
        });
    }

    // Stream response chunks up to MAX_SNIFF_HTML_BYTES so huge non-HTML bodies never exhaust memory
    let mut body_bytes = Vec::with_capacity(64 * 1024);
    let mut stream = resp.bytes_stream();
    while let Some(chunk_res) = stream.next().await {
        let chunk = match chunk_res {
            Ok(c) => c,
            Err(_) => break,
        };
        let remaining = MAX_SNIFF_HTML_BYTES.saturating_sub(body_bytes.len());
        if remaining == 0 {
            break;
        }
        let take_len = chunk.len().min(remaining);
        body_bytes.extend_from_slice(&chunk[..take_len]);
        if body_bytes.len() >= MAX_SNIFF_HTML_BYTES {
            break;
        }
    }

    let html = String::from_utf8_lossy(&body_bytes);
    extract_media_from_html_impl(&html, &page_url)
}

/// Fetch a single webpage and sniff embedded media outside the GIL.
pub fn sniff_webpage_impl(page_url: &str, timeout_secs: f64) -> Option<RustSniffedMedia> {
    let timeout = Duration::from_secs_f64(timeout_secs.clamp(0.5, 120.0));
    let url_owned = page_url.trim().to_string();
    tokio_runtime().block_on(sniff_single_async(url_owned, timeout))
}

/// Fetch multiple webpages concurrently on Tokio's async HTTP pool, preserving input order.
pub fn sniff_webpages_batch_impl(
    urls: Vec<String>,
    timeout_secs: f64,
    max_concurrency: usize,
) -> Vec<Option<RustSniffedMedia>> {
    if urls.is_empty() {
        return Vec::new();
    }
    let timeout = Duration::from_secs_f64(timeout_secs.clamp(0.5, 120.0));
    let concurrency = max_concurrency.clamp(1, 64);

    tokio_runtime().block_on(async move {
        let sem = Arc::new(Semaphore::new(concurrency));
        let mut handles = Vec::with_capacity(urls.len());

        for raw_url in urls {
            let sem_clone = Arc::clone(&sem);
            let u = raw_url.trim().to_string();
            handles.push(tokio::spawn(async move {
                let _permit = sem_clone.acquire_owned().await.ok()?;
                sniff_single_async(u, timeout).await
            }));
        }

        let mut out = Vec::with_capacity(handles.len());
        for h in handles {
            out.push(h.await.ok().flatten());
        }
        out
    })
}

/// Follow HTTP redirects (`HEAD` with `Range: bytes=0-0` GET fallback) on the pooled HTTP/2 client.
pub fn follow_redirects_impl(url: &str, timeout_secs: f64) -> String {
    let trimmed = url.trim();
    if trimmed.is_empty() {
        return String::new();
    }
    let timeout = Duration::from_secs_f64(timeout_secs.clamp(0.5, 60.0));
    let target = trimmed.to_string();

    tokio_runtime().block_on(async move {
        let client = http_client();
        if let Ok(resp) = client.head(&target).timeout(timeout).send().await {
            if resp.status().is_success() || resp.status().is_redirection() {
                return resp.url().to_string();
            }
        }
        if let Ok(resp) = client
            .get(&target)
            .header(reqwest::header::RANGE, "bytes=0-0")
            .timeout(timeout)
            .send()
            .await
        {
            return resp.url().to_string();
        }
        target
    })
}

/// Fetch multiple `(url, custom_headers)` pairs concurrently on Tokio's pooled HTTP/2 client.
/// Returns `Option<(status_code, final_url, body_text)>` in input order (capped at 4 MiB per response).
pub fn fetch_urls_parallel_impl(
    requests: Vec<(String, HashMap<String, String>)>,
    timeout_secs: f64,
) -> Vec<Option<(u16, String, String)>> {
    if requests.is_empty() {
        return Vec::new();
    }
    let timeout = Duration::from_secs_f64(timeout_secs.clamp(0.5, 60.0));
    const MAX_BODY: usize = 4 * 1024 * 1024;

    tokio_runtime().block_on(async move {
        let mut handles = Vec::with_capacity(requests.len());
        for (raw_url, hdrs) in requests {
            handles.push(tokio::spawn(async move {
                let mut req = http_client().get(raw_url.trim()).timeout(timeout);
                for (k, v) in hdrs {
                    if let (Ok(hn), Ok(hv)) = (
                        reqwest::header::HeaderName::from_bytes(k.as_bytes()),
                        reqwest::header::HeaderValue::from_str(&v),
                    ) {
                        req = req.header(hn, hv);
                    }
                }
                let resp = req.send().await.ok()?;
                let status = resp.status().as_u16();
                let final_url = resp.url().to_string();
                let mut body_bytes = Vec::with_capacity(16 * 1024);
                let mut stream = resp.bytes_stream();
                while let Some(chunk_res) = stream.next().await {
                    let chunk = match chunk_res {
                        Ok(c) => c,
                        Err(_) => break,
                    };
                    let rem = MAX_BODY.saturating_sub(body_bytes.len());
                    if rem == 0 {
                        break;
                    }
                    let take_len = chunk.len().min(rem);
                    body_bytes.extend_from_slice(&chunk[..take_len]);
                    if body_bytes.len() >= MAX_BODY {
                        break;
                    }
                }
                let text = String::from_utf8_lossy(&body_bytes).into_owned();
                Some((status, final_url, text))
            }));
        }

        let mut out = Vec::with_capacity(handles.len());
        for h in handles {
            out.push(h.await.ok().flatten());
        }
        out
    })
}

#[inline]
fn is_tracking_param(key: &str) -> bool {
    if key.len() >= 4 && key.as_bytes()[..4].eq_ignore_ascii_case(b"utm_") {
        return true;
    }
    const DROP_EXACT: [&str; 10] = [
        "si",
        "feature",
        "fbclid",
        "gclid",
        "igshid",
        "share_token",
        "share_app_name",
        "share_id",
        "ref_src",
        "ref_url",
    ];
    DROP_EXACT.iter().any(|k| key.eq_ignore_ascii_case(k))
}

/// Strip marketing tracking parameters (`utm_*`, `si`, `fbclid`, etc.) while preserving
/// exact signed query encodings and fragments.
pub fn clean_url_impl(url: &str) -> String {
    let trimmed = url.trim();
    if trimmed.is_empty() {
        return String::new();
    }

    let (before_frag, frag_opt) = match trimmed.find('#') {
        Some(idx) => (&trimmed[..idx], Some(&trimmed[idx + 1..])),
        None => (trimmed, None),
    };

    let (base, query) = match before_frag.find('?') {
        Some(idx) => (&before_frag[..idx], &before_frag[idx + 1..]),
        None => return trimmed.to_string(),
    };

    if query.is_empty() {
        let mut out = base.to_string();
        if let Some(frag) = frag_opt {
            if !frag.is_empty() {
                out.push('#');
                out.push_str(frag);
            }
        }
        return out;
    }

    let mut kept: Vec<&str> = Vec::new();
    let mut dropped_any = false;

    for pair in query.split('&') {
        if pair.is_empty() {
            continue;
        }
        let raw_key = pair.split('=').next().unwrap_or("");
        if is_tracking_param(raw_key) {
            dropped_any = true;
        } else {
            kept.push(pair);
        }
    }

    if !dropped_any {
        return trimmed.to_string();
    }

    let mut out = String::with_capacity(trimmed.len());
    out.push_str(base);
    if !kept.is_empty() {
        out.push('?');
        out.push_str(&kept.join("&"));
    }
    if let Some(frag) = frag_opt {
        if !frag.is_empty() {
            out.push('#');
            out.push_str(frag);
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resolves_relative_urls() {
        let base = "https://example.com/articles/news.html";
        assert_eq!(
            resolve_relative_url_impl(base, "/media/video.mp4"),
            "https://example.com/media/video.mp4"
        );
        assert_eq!(
            resolve_relative_url_impl(base, "//cdn.example.com/video.mp4"),
            "https://cdn.example.com/video.mp4"
        );
        assert_eq!(
            resolve_relative_url_impl(base, "https://cdn.other.com/v.mp4"),
            "https://cdn.other.com/v.mp4"
        );
    }

    #[test]
    fn extracts_og_jsonld_html5_and_player_config() {
        let html = r#"
        <html>
          <head>
            <title>Exclusive Interview - Tech News</title>
            <meta property="og:video" content="https://cdn.example.com/videos/interview.mp4" />
            <script type="application/ld+json">
            {"@type": "VideoObject", "name": "LD Stream", "contentUrl": "https://cdn.example.com/ld.m3u8"}
            </script>
          </head>
          <body>
            <video><source src="/local/clip.mp4" /></video>
          </body>
        </html>
        "#;

        let all = extract_all_media_from_html_impl(html, "https://technews.com/post/1");
        assert_eq!(all.len(), 3);
        assert_eq!(all[0].source_type, "og:video");
        assert_eq!(all[0].title, "Exclusive Interview");
        assert_eq!(all[1].source_type, "json-ld");
        assert!(all[1].is_m3u8);
        assert_eq!(all[2].media_url, "https://technews.com/local/clip.mp4");
    }

    #[test]
    fn cleans_tracking_parameters_accurately() {
        assert_eq!(
            clean_url_impl("https://www.youtube.com/watch?v=dQw4w9WgXcQ&si=12345&utm_source=twitter"),
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        );
        assert_eq!(
            clean_url_impl("https://www.youtube.com/watch?si=12345&v=dQw4w9WgXcQ"),
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        );
        assert_eq!(
            clean_url_impl("https://youtu.be/dQw4w9WgXcQ?si=abcdef123"),
            "https://youtu.be/dQw4w9WgXcQ"
        );
    }
}
