use crate::sniffer::{http_client_with_headers, resolve_relative_url_impl, tokio_runtime};
use bytes::Bytes;
use futures_util::{stream, StreamExt};
use pyo3::exceptions::PyIOError;
use pyo3::prelude::*;
use std::collections::HashMap;
use std::fs::{self, File};
use std::io::{BufWriter, Write};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

const HLS_WRITE_BUF_SIZE: usize = 16 * 1024 * 1024; // 16 MiB sequential coalescing buffer

#[pyclass(frozen, get_all)]
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RustM3u8Variant {
    pub url: String,
    pub bandwidth: u64,
    pub width: u32,
    pub height: u32,
    pub codecs: String,
}

#[pyclass(frozen, get_all)]
#[derive(Clone, Debug, PartialEq)]
pub struct RustM3u8Segment {
    pub index: usize,
    pub url: String,
    pub duration: f64,
    pub byte_offset: Option<u64>,
    pub byte_length: Option<u64>,
}

#[pyclass(frozen, get_all)]
#[derive(Clone, Debug, PartialEq)]
pub struct RustM3u8Manifest {
    pub is_master: bool,
    pub is_encrypted: bool,
    pub is_live: bool,
    pub has_separate_audio: bool,
    pub init_segment_url: Option<String>,
    pub init_byte_offset: Option<u64>,
    pub init_byte_length: Option<u64>,
    pub variants: Vec<RustM3u8Variant>,
    pub segments: Vec<RustM3u8Segment>,
    pub total_duration: f64,
}

/// Extract the value of `KEY=VALUE` or `KEY="VALUE"` from an M3U8 attribute list.
fn extract_m3u8_attr<'a>(attrs: &'a str, key: &str) -> Option<&'a str> {
    let mut rest = attrs;
    while !rest.is_empty() {
        rest = rest.trim_start_matches(|c: char| c == ',' || c.is_ascii_whitespace());
        if rest.is_empty() {
            break;
        }
        let eq_pos = rest.find('=')?;
        let k = rest[..eq_pos].trim();
        let after_eq = &rest[eq_pos + 1..];

        let (val, next_rest) = if let Some(stripped) = after_eq.strip_prefix('"') {
            let end_q = stripped.find('"')?;
            (&stripped[..end_q], &stripped[end_q + 1..])
        } else {
            match after_eq.find(',') {
                Some(comma) => (after_eq[..comma].trim(), &after_eq[comma + 1..]),
                None => (after_eq.trim(), ""),
            }
        };

        if k.eq_ignore_ascii_case(key) {
            return Some(val);
        }
        rest = next_rest;
    }
    None
}

fn parse_byterange_spec(spec: &str, running_offset: &mut u64) -> Option<(u64, u64)> {
    let spec = spec.trim().trim_matches('"');
    let (len_str, off_opt) = match spec.split_once('@') {
        Some((l, o)) => (l.trim(), Some(o.trim())),
        None => (spec, None),
    };
    let length = len_str.parse::<u64>().ok()?;
    let offset = match off_opt {
        Some(o) => o.parse::<u64>().ok()?,
        None => *running_offset,
    };
    *running_offset = offset.saturating_add(length);
    Some((offset, length))
}

/// Parse an HLS Master or Media `.m3u8` playlist per RFC 8216.
pub fn parse_m3u8_playlist_impl(content: &str, base_url: &str) -> Option<RustM3u8Manifest> {
    let trimmed = content.trim_start_matches('\u{feff}').trim();
    if !trimmed.starts_with("#EXTM3U") {
        return None;
    }

    let mut is_master = false;
    let mut is_encrypted = false;
    let mut has_endlist = false;
    let mut is_vod_type = false;
    let mut has_separate_audio = false;

    let mut init_segment_url: Option<String> = None;
    let mut init_byte_offset: Option<u64> = None;
    let mut init_byte_length: Option<u64> = None;

    let mut variants: Vec<RustM3u8Variant> = Vec::new();
    let mut segments: Vec<RustM3u8Segment> = Vec::new();

    let mut pending_stream_inf: Option<(u64, u32, u32, String)> = None;
    let mut pending_duration: Option<f64> = None;
    let mut pending_byterange: Option<(u64, u64)> = None;
    let mut running_byterange_offset: u64 = 0;

    for raw_line in trimmed.lines() {
        let line = raw_line.trim();
        if line.is_empty() {
            continue;
        }

        if let Some(attrs) = line.strip_prefix("#EXT-X-STREAM-INF:") {
            is_master = true;
            let bw = extract_m3u8_attr(attrs, "BANDWIDTH")
                .or_else(|| extract_m3u8_attr(attrs, "AVERAGE-BANDWIDTH"))
                .and_then(|s| s.parse::<u64>().ok())
                .unwrap_or(0);

            let (w, h) = extract_m3u8_attr(attrs, "RESOLUTION")
                .and_then(|res| res.split_once('x').or_else(|| res.split_once('X')))
                .map(|(ws, hs)| {
                    (
                        ws.trim().parse::<u32>().unwrap_or(0),
                        hs.trim().parse::<u32>().unwrap_or(0),
                    )
                })
                .unwrap_or((0, 0));

            let codecs = extract_m3u8_attr(attrs, "CODECS")
                .unwrap_or("")
                .to_string();

            pending_stream_inf = Some((bw, w, h, codecs));
            continue;
        }

        if let Some(attrs) = line.strip_prefix("#EXT-X-MEDIA:") {
            let mtype = extract_m3u8_attr(attrs, "TYPE").unwrap_or("");
            let uri = extract_m3u8_attr(attrs, "URI").unwrap_or("");
            if mtype.eq_ignore_ascii_case("AUDIO") && !uri.is_empty() {
                has_separate_audio = true;
            }
            continue;
        }

        if let Some(attrs) = line.strip_prefix("#EXT-X-KEY:") {
            let method = extract_m3u8_attr(attrs, "METHOD").unwrap_or("NONE");
            if !method.eq_ignore_ascii_case("NONE") {
                is_encrypted = true;
            }
            continue;
        }

        if let Some(attrs) = line.strip_prefix("#EXT-X-MAP:") {
            if let Some(uri) = extract_m3u8_attr(attrs, "URI") {
                let resolved = resolve_relative_url_impl(base_url, uri);
                if !resolved.is_empty() {
                    init_segment_url = Some(resolved);
                    if let Some(br_str) = extract_m3u8_attr(attrs, "BYTERANGE") {
                        let mut dummy_off = 0u64;
                        if let Some((off, len)) = parse_byterange_spec(br_str, &mut dummy_off) {
                            init_byte_offset = Some(off);
                            init_byte_length = Some(len);
                        }
                    }
                }
            }
            continue;
        }

        if let Some(rest) = line.strip_prefix("#EXTINF:") {
            let dur_str = rest.split(',').next().unwrap_or("0").trim();
            let dur = dur_str.parse::<f64>().unwrap_or(0.0).max(0.0);
            pending_duration = Some(dur);
            continue;
        }

        if let Some(br_spec) = line.strip_prefix("#EXT-X-BYTERANGE:") {
            pending_byterange = parse_byterange_spec(br_spec, &mut running_byterange_offset);
            continue;
        }

        if let Some(ptype) = line.strip_prefix("#EXT-X-PLAYLIST-TYPE:") {
            if ptype.trim().eq_ignore_ascii_case("VOD") {
                is_vod_type = true;
            }
            continue;
        }

        if line.starts_with("#EXT-X-ENDLIST") {
            has_endlist = true;
            continue;
        }

        if line.starts_with('#') {
            continue;
        }

        // Non-comment URI line
        let resolved_uri = resolve_relative_url_impl(base_url, line);
        if resolved_uri.is_empty() {
            continue;
        }

        if let Some((bw, w, h, codecs)) = pending_stream_inf.take() {
            variants.push(RustM3u8Variant {
                url: resolved_uri,
                bandwidth: bw,
                width: w,
                height: h,
                codecs,
            });
        } else if pending_duration.is_some() || !is_master {
            let dur = pending_duration.take().unwrap_or(0.0);
            let (byte_offset, byte_length) = match pending_byterange.take() {
                Some((o, l)) => (Some(o), Some(l)),
                None => (None, None),
            };
            let idx = segments.len();
            segments.push(RustM3u8Segment {
                index: idx,
                url: resolved_uri,
                duration: dur,
                byte_offset,
                byte_length,
            });
        }
    }

    variants.sort_by(|a, b| b.height.cmp(&a.height).then_with(|| b.bandwidth.cmp(&a.bandwidth)));

    let total_duration: f64 = segments.iter().map(|s| s.duration).sum();
    let is_live = !is_master && !segments.is_empty() && !has_endlist && !is_vod_type;

    Some(RustM3u8Manifest {
        is_master,
        is_encrypted,
        is_live,
        has_separate_audio,
        init_segment_url,
        init_byte_offset,
        init_byte_length,
        variants,
        segments,
        total_duration,
    })
}

pub fn select_best_variant<'a>(
    variants: &'a [RustM3u8Variant],
    max_height: Option<u32>,
) -> Option<&'a RustM3u8Variant> {
    if variants.is_empty() {
        return None;
    }
    if let Some(target_h) = max_height {
        if target_h > 0 {
            if let Some(matched) = variants.iter().find(|v| v.height > 0 && v.height <= target_h) {
                return Some(matched);
            }
            // If all variants have explicit height > target_h, pick the smallest available above target_h
            if variants.iter().all(|v| v.height > target_h) {
                return variants.last();
            }
        }
    }
    variants.first()
}

async fn fetch_bytes_with_retry(
    client: &reqwest::Client,
    url: &str,
    headers: &reqwest::header::HeaderMap,
    byte_range: Option<(u64, u64)>,
    timeout: Duration,
    max_retries: u32,
    cancelled: &AtomicBool,
) -> Result<(Bytes, String), String> {
    let mut attempt = 0u32;
    loop {
        if cancelled.load(Ordering::Relaxed) {
            return Err("cancelled".to_string());
        }

        let mut req = client.get(url).headers(headers.clone()).timeout(timeout);
        if let Some((offset, length)) = byte_range {
            if length > 0 {
                let end_inclusive = offset.saturating_add(length - 1);
                req = req.header(
                    reqwest::header::RANGE,
                    format!("bytes={}-{}", offset, end_inclusive),
                );
            }
        }

        match req.send().await {
            Ok(resp) => {
                let status = resp.status();
                if status.is_success() {
                    let final_url = resp.url().to_string();
                    match resp.bytes().await {
                        Ok(b) => return Ok((b, final_url)),
                        Err(e) if attempt < max_retries => {
                            let delay_ms = (200u64.saturating_mul(1u64 << attempt.min(5))).min(5000);
                            tokio::time::sleep(Duration::from_millis(delay_ms)).await;
                            attempt += 1;
                            let _ = e;
                            continue;
                        }
                        Err(e) => return Err(format!("segment body error: {}", e)),
                    }
                } else if (status.is_server_error() || status.as_u16() == 429) && attempt < max_retries {
                    let delay_ms = (250u64.saturating_mul(1u64 << attempt.min(5))).min(5000);
                    tokio::time::sleep(Duration::from_millis(delay_ms)).await;
                    attempt += 1;
                    continue;
                } else {
                    return Err(format!("HTTP {}", status.as_u16()));
                }
            }
            Err(e) => {
                if attempt < max_retries && !cancelled.load(Ordering::Relaxed) {
                    let delay_ms = (200u64.saturating_mul(1u64 << attempt.min(5))).min(5000);
                    tokio::time::sleep(Duration::from_millis(delay_ms)).await;
                    attempt += 1;
                    continue;
                }
                return Err(format!("request failed: {}", e));
            }
        }
    }
}

/// Download a VOD unencrypted HLS `.m3u8` stream directly into `output_path` with sliding-window
/// HTTP/2 segment concurrency and zero temporary fragment files on disk.
///
/// Returns `(status, written_bytes, completed_segments, total_segments)` where `status` is:
/// - `"ok"`: stream downloaded completely into `output_path`
/// - `"cancelled"`: user cancelled mid-flight (partial file cleaned up)
/// - `"fallback:<reason>"`: manifest requires `yt-dlp` (encrypted, live, separate audio, or non-m3u8)
#[allow(clippy::too_many_arguments)]
pub fn download_hls_stream_py(
    py: Python<'_>,
    manifest_url: &str,
    output_path: &str,
    headers: HashMap<String, String>,
    max_height: Option<u32>,
    concurrency: usize,
    max_retries: u32,
    timeout_secs: f64,
    progress_interval_ms: u64,
    check_cancelled: Option<Py<PyAny>>,
    on_progress: Option<Py<PyAny>>,
) -> PyResult<(String, u64, usize, usize)> {
    let client = http_client_with_headers();
    let mut header_map = reqwest::header::HeaderMap::new();
    for (k, v) in &headers {
        if let (Ok(hname), Ok(hval)) = (
            reqwest::header::HeaderName::from_bytes(k.as_bytes()),
            reqwest::header::HeaderValue::from_str(v),
        ) {
            header_map.insert(hname, hval);
        }
    }

    let timeout = Duration::from_secs_f64(timeout_secs.clamp(2.0, 120.0));
    let cancelled = Arc::new(AtomicBool::new(false));

    // Step 1 & 2: Fetch and resolve Master -> Media manifest outside the GIL
    let resolved_manifest = py.allow_threads(|| {
        tokio_runtime().block_on(async {
            let (raw_bytes, final_url) = fetch_bytes_with_retry(
                client,
                manifest_url,
                &header_map,
                None,
                timeout,
                3,
                &cancelled,
            )
            .await
            .map_err(|e| format!("manifest-fetch:{}", e))?;

            let text = String::from_utf8_lossy(&raw_bytes);
            let parsed = parse_m3u8_playlist_impl(&text, &final_url)
                .ok_or_else(|| "not-m3u8".to_string())?;

            if parsed.is_master {
                if parsed.has_separate_audio {
                    return Err("separate-audio-rendition".to_string());
                }
                let variant = select_best_variant(&parsed.variants, max_height)
                    .ok_or_else(|| "empty-master-variants".to_string())?;
                let (media_bytes, media_final_url) = fetch_bytes_with_retry(
                    client,
                    &variant.url,
                    &header_map,
                    None,
                    timeout,
                    3,
                    &cancelled,
                )
                .await
                .map_err(|e| format!("variant-fetch:{}", e))?;
                let media_text = String::from_utf8_lossy(&media_bytes);
                parse_m3u8_playlist_impl(&media_text, &media_final_url)
                    .ok_or_else(|| "invalid-media-m3u8".to_string())
            } else {
                Ok(parsed)
            }
        })
    });

    let media = match resolved_manifest {
        Ok(m) => m,
        Err(reason) => return Ok((format!("fallback:{}", reason), 0, 0, 0)),
    };

    if media.is_encrypted {
        return Ok(("fallback:encrypted-hls".to_string(), 0, 0, 0));
    }
    if media.is_live {
        return Ok(("fallback:live-hls".to_string(), 0, 0, 0));
    }
    if media.is_master || media.segments.is_empty() {
        return Ok(("fallback:no-segments".to_string(), 0, 0, 0));
    }

    let total_segments = media.segments.len();
    let out_path = PathBuf::from(output_path);
    if let Some(parent) = out_path.parent() {
        let _ = fs::create_dir_all(parent);
    }

    let raw_file = File::create(&out_path)
        .map_err(|e| PyIOError::new_err(format!("Failed creating '{}': {}", output_path, e)))?;
    let mut writer = BufWriter::with_capacity(HLS_WRITE_BUF_SIZE, raw_file);
    let mut written_bytes: u64 = 0;

    // Optional fMP4 `#EXT-X-MAP` initialization segment
    if let Some(ref init_url) = media.init_segment_url {
        let init_range = match (media.init_byte_offset, media.init_byte_length) {
            (Some(o), Some(l)) => Some((o, l)),
            _ => None,
        };
        let init_res = py.allow_threads(|| {
            tokio_runtime().block_on(fetch_bytes_with_retry(
                client,
                init_url,
                &header_map,
                init_range,
                timeout,
                max_retries,
                &cancelled,
            ))
        });
        match init_res {
            Ok((init_bytes, _)) => {
                writer
                    .write_all(&init_bytes)
                    .map_err(|e| PyIOError::new_err(format!("Init write error: {}", e)))?;
                written_bytes += init_bytes.len() as u64;
            }
            Err(reason) => {
                drop(writer);
                let _ = fs::remove_file(&out_path);
                return Ok((format!("fallback:init-failed:{}", reason), 0, 0, total_segments));
            }
        }
    }

    // Step 3: Process segments in sliding-window batches so GIL hooks run cleanly without holding Tokio locks
    let window = concurrency.clamp(1, 32);
    let start_instant = Instant::now();
    let mut last_ui_instant: Option<Instant> = None;
    let min_interval = Duration::from_millis(progress_interval_ms);
    let mut completed_segments: usize = 0;

    // Process in chunks of `window` (or streaming pipeline via channel) so Tokio keeps full concurrency!
    // Using a bounded Tokio mpsc channel of ordered segment batches keeps the HTTP pipeline 100% saturated
    // continuously across the entire movie without pausing between windows!
    let (tx, mut rx) = tokio::sync::mpsc::channel::<Result<Bytes, String>>(window * 2);
    let segments_owned = media.segments;
    let headers_arc = Arc::new(header_map);
    let cancelled_worker = Arc::clone(&cancelled);

    tokio_runtime().spawn(async move {
        let mut ordered_stream = stream::iter(segments_owned.into_iter().map(|seg| {
            let hdrs = Arc::clone(&headers_arc);
            let cancel_tok = Arc::clone(&cancelled_worker);
            let br = match (seg.byte_offset, seg.byte_length) {
                (Some(o), Some(l)) => Some((o, l)),
                _ => None,
            };
            async move {
                fetch_bytes_with_retry(
                    client,
                    &seg.url,
                    &hdrs,
                    br,
                    timeout,
                    max_retries,
                    &cancel_tok,
                )
                .await
                .map(|(b, _)| b)
            }
        }))
        .buffered(window);

        while let Some(seg_res) = ordered_stream.next().await {
            if cancelled_worker.load(Ordering::Relaxed) {
                break;
            }
            let is_err = seg_res.is_err();
            if tx.send(seg_res).await.is_err() || is_err {
                break;
            }
        }
    });

    let mut failed_err: Option<String> = None;

    loop {
        if let Some(ref cancel_cb) = check_cancelled {
            let is_cancelled: bool = cancel_cb.bind(py).call0()?.extract()?;
            if is_cancelled {
                cancelled.store(true, Ordering::Relaxed);
                break;
            }
        }

        let next_item = py.allow_threads(|| {
            tokio_runtime().block_on(async {
                tokio::time::timeout(Duration::from_millis(250), rx.recv()).await
            })
        });

        let seg_bytes = match next_item {
            Err(_elapsed) => continue, // Re-check Python cancellation every 250ms even if network is slow
            Ok(None) => break,         // Stream completed
            Ok(Some(Ok(b))) => b,
            Ok(Some(Err(err_msg))) => {
                cancelled.store(true, Ordering::Relaxed);
                failed_err = Some(err_msg);
                break;
            }
        };

        py.allow_threads(|| writer.write_all(&seg_bytes))
            .map_err(|e| PyIOError::new_err(format!("Failed writing HLS segment: {}", e)))?;

        written_bytes = written_bytes.saturating_add(seg_bytes.len() as u64);
        completed_segments += 1;

        let should_emit = completed_segments == 1
            || completed_segments == total_segments
            || last_ui_instant.map_or(true, |t| t.elapsed() >= min_interval);

        if should_emit {
            last_ui_instant = Some(Instant::now());
            if let Some(ref prog_cb) = on_progress {
                let elapsed = start_instant.elapsed().as_secs_f64().max(0.001);
                let speed_bps = (written_bytes as f64) / elapsed;
                let est_total = if completed_segments > 0 {
                    ((written_bytes as f64) * (total_segments as f64 / completed_segments as f64))
                        as u64
                } else {
                    written_bytes
                };
                let rem_bytes = est_total.saturating_sub(written_bytes);
                let eta_secs = if speed_bps > 1.0 {
                    (rem_bytes as f64 / speed_bps) as u64
                } else {
                    0
                };
                prog_cb.bind(py).call1((
                    written_bytes,
                    est_total,
                    speed_bps,
                    eta_secs,
                    completed_segments,
                    total_segments,
                ))?;
            }
        }
    }

    if cancelled.load(Ordering::Relaxed) && failed_err.is_none() {
        drop(writer);
        let _ = fs::remove_file(&out_path);
        return Ok(("cancelled".to_string(), written_bytes, completed_segments, total_segments));
    }

    if let Some(err) = failed_err {
        drop(writer);
        let _ = fs::remove_file(&out_path);
        return Ok((
            format!("fallback:segment-error:{}", err),
            written_bytes,
            completed_segments,
            total_segments,
        ));
    }

    py.allow_threads(|| writer.flush())
        .map_err(|e| PyIOError::new_err(format!("Failed flushing HLS file: {}", e)))?;

    Ok(("ok".to_string(), written_bytes, completed_segments, total_segments))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_master_playlist_and_ranks_variants() {
        let m3u8 = r#"#EXTM3U
#EXT-X-VERSION:3
#EXT-X-STREAM-INF:BANDWIDTH=1500000,RESOLUTION=1280x720,CODECS="avc1.4d401f,mp4a.40.2"
720p/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=5500000,RESOLUTION=1920x1080,CODECS="avc1.640028,mp4a.40.2"
https://cdn.example.com/1080p/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360
/hls/360p.m3u8
"#;
        let parsed = parse_m3u8_playlist_impl(m3u8, "https://stream.example.com/movies/master.m3u8").unwrap();
        assert!(parsed.is_master);
        assert!(!parsed.has_separate_audio);
        assert_eq!(parsed.variants.len(), 3);
        assert_eq!(parsed.variants[0].height, 1080);
        assert_eq!(parsed.variants[1].url, "https://stream.example.com/movies/720p/index.m3u8");
        assert_eq!(parsed.variants[2].url, "https://stream.example.com/hls/360p.m3u8");

        let v720 = select_best_variant(&parsed.variants, Some(720)).unwrap();
        assert_eq!(v720.height, 720);
    }

    #[test]
    fn parses_media_playlist_with_fmp4_map_and_byterange() {
        let m3u8 = r#"#EXTM3U
#EXT-X-TARGETDURATION:6
#EXT-X-PLAYLIST-TYPE:VOD
#EXT-X-MAP:URI="init.mp4",BYTERANGE="720@0"
#EXTINF:6.006,
#EXT-X-BYTERANGE:1000@720
main.m4s
#EXTINF:5.500,
#EXT-X-BYTERANGE:2000
main.m4s
#EXT-X-ENDLIST
"#;
        let parsed = parse_m3u8_playlist_impl(m3u8, "https://cdn.example.com/vod/stream.m3u8").unwrap();
        assert!(!parsed.is_master);
        assert!(!parsed.is_encrypted);
        assert!(!parsed.is_live);
        assert_eq!(
            parsed.init_segment_url.as_deref(),
            Some("https://cdn.example.com/vod/init.mp4")
        );
        assert_eq!(parsed.init_byte_offset, Some(0));
        assert_eq!(parsed.init_byte_length, Some(720));
        assert_eq!(parsed.segments.len(), 2);
        assert_eq!(parsed.segments[0].byte_offset, Some(720));
        assert_eq!(parsed.segments[0].byte_length, Some(1000));
        // Second segment omits `@offset`, so RFC 8216 continues at 720 + 1000 = 1720
        assert_eq!(parsed.segments[1].byte_offset, Some(1720));
        assert_eq!(parsed.segments[1].byte_length, Some(2000));
        assert!((parsed.total_duration - 11.506).abs() < 1e-6);
    }

    #[test]
    fn detects_encryption_and_separate_audio() {
        let enc_m3u8 = r#"#EXTM3U
#EXT-X-KEY:METHOD=AES-128,URI="https://keys.example/k.bin"
#EXTINF:4.0,
seg1.ts
#EXT-X-ENDLIST
"#;
        let p1 = parse_m3u8_playlist_impl(enc_m3u8, "https://cdn.example/a.m3u8").unwrap();
        assert!(p1.is_encrypted);

        let sep_audio = r#"#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",NAME="English",URI="audio/en.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=3000000,RESOLUTION=1920x1080,AUDIO="aud"
video/1080p.m3u8
"#;
        let p2 = parse_m3u8_playlist_impl(sep_audio, "https://cdn.example/master.m3u8").unwrap();
        assert!(p2.is_master);
        assert!(p2.has_separate_audio);
    }
}
