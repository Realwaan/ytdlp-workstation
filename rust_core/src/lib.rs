mod archive;
mod hls;
mod merger;
mod mp4;
mod parser;
mod sniffer;

use pyo3::exceptions::PyIOError;
use pyo3::prelude::*;
use std::collections::{HashMap, HashSet};
use std::path::Path;

pub use archive::RustArchiveIndex;
pub use hls::{RustM3u8Manifest, RustM3u8Segment, RustM3u8Variant};
pub use sniffer::RustSniffedMedia;

/// Return crate version string for runtime telemetry and diagnostics.
#[pyfunction]
fn version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

/// Return list of active native Rust acceleration subsystems.
#[pyfunction]
fn capabilities() -> Vec<&'static str> {
    vec![
        "mp4_iso_bmff_scanner",
        "coalesced_fragment_merger",
        "tokio_hls_turbo_downloader",
        "dfa_media_url_engine",
        "zero_copy_progress_parser",
        "parallel_http2_sniffer",
        "buffered_archive_indexer",
    ]
}

/// Walk top-level ISO BMFF (MP4/MOV) boxes from byte 0.
/// Returns the byte offset of a concatenated second `ftyp` box if present, else `None`.
#[pyfunction]
fn find_embedded_second_ftyp_offset(py: Python<'_>, file_path: &str) -> Option<u64> {
    py.allow_threads(|| mp4::find_embedded_second_ftyp_offset_impl(Path::new(file_path)))
}

/// Inspect top-level ISO BMFF (MP4/MOV) boxes in `file_path`, returning `[(fourcc, offset, size), ...]`.
#[pyfunction]
fn inspect_mp4_boxes(py: Python<'_>, file_path: &str) -> PyResult<Vec<(String, u64, u64)>> {
    py.allow_threads(|| mp4::inspect_mp4_boxes_impl(Path::new(file_path))).map_err(|e| {
        PyIOError::new_err(format!(
            "Failed inspecting MP4 boxes in '{}': {}",
            file_path, e
        ))
    })
}

/// Scan `directory` for `*-Frag<N>` files, skipping `protected_bases`, and return sorted groups.
#[pyfunction]
#[pyo3(signature = (directory, protected_bases=Vec::new()))]
fn find_fragment_groups(
    py: Python<'_>,
    directory: &str,
    protected_bases: Vec<String>,
) -> HashMap<String, Vec<(u64, String)>> {
    py.allow_threads(|| {
        let protected: HashSet<String> = protected_bases.into_iter().collect();
        merger::find_fragment_groups_impl(Path::new(directory), &protected)
    })
}

/// Delete orphaned `*-Frag*` files in `directory` except those belonging to `protected_bases`.
#[pyfunction]
#[pyo3(signature = (directory, protected_bases=Vec::new()))]
fn cleanup_orphaned_fragments(
    py: Python<'_>,
    directory: &str,
    protected_bases: Vec<String>,
) -> u64 {
    py.allow_threads(|| {
        let protected: HashSet<String> = protected_bases.into_iter().collect();
        merger::cleanup_orphaned_fragments_impl(Path::new(directory), &protected)
    })
}

/// Extract bytes `[split_offset..EOF]` from `src_path` into `dst_path`, then truncate `src_path` to `split_offset`.
#[pyfunction]
fn split_appended_mp4_stream(
    py: Python<'_>,
    src_path: &str,
    dst_path: &str,
    split_offset: u64,
) -> PyResult<u64> {
    py.allow_threads(|| {
        merger::split_appended_mp4_stream_impl(
            Path::new(src_path),
            Path::new(dst_path),
            split_offset,
        )
    })
    .map_err(|e| PyIOError::new_err(format!("Failed splitting appended MP4 stream: {}", e)))
}

/// Stitch `frag_paths` sequentially onto `target_path` with a 16 MiB coalescing buffer outside the GIL.
/// Returns `(written_bytes, was_cancelled)`.
#[pyfunction]
#[pyo3(signature = (target_path, frag_paths, delete_frags=true, progress_interval_ms=100, check_cancelled=None, on_progress=None))]
fn stitch_fragments(
    py: Python<'_>,
    target_path: &str,
    frag_paths: Vec<String>,
    delete_frags: bool,
    progress_interval_ms: u64,
    check_cancelled: Option<Py<PyAny>>,
    on_progress: Option<Py<PyAny>>,
) -> PyResult<(u64, bool)> {
    merger::stitch_fragments_py(
        py,
        target_path,
        frag_paths,
        delete_frags,
        progress_interval_ms,
        check_cancelled,
        on_progress,
    )
}

/// Parse an HLS Master or Media `.m3u8` playlist into a `RustM3u8Manifest`.
#[pyfunction]
fn parse_m3u8_playlist(
    py: Python<'_>,
    content: &str,
    base_url: &str,
) -> Option<RustM3u8Manifest> {
    py.allow_threads(|| hls::parse_m3u8_playlist_impl(content, base_url))
}

/// Download an unencrypted VOD HLS `.m3u8` stream directly into `output_path` with sliding-window
/// HTTP/2 segment concurrency and zero temporary fragment files on disk.
#[pyfunction]
#[pyo3(signature = (manifest_url, output_path, headers=HashMap::new(), max_height=None, concurrency=16, max_retries=8, timeout_secs=25.0, progress_interval_ms=100, check_cancelled=None, on_progress=None))]
#[allow(clippy::too_many_arguments)]
fn download_hls_stream(
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
    hls::download_hls_stream_py(
        py,
        manifest_url,
        output_path,
        headers,
        max_height,
        concurrency,
        max_retries,
        timeout_secs,
        progress_interval_ms,
        check_cancelled,
        on_progress,
    )
}

/// Resolve a relative URL (`link`) against `base_url`.
#[pyfunction]
fn resolve_relative_url(base_url: &str, link: &str) -> String {
    sniffer::resolve_relative_url_impl(base_url, link)
}

/// Extract highest-priority embedded media stream from raw HTML.
#[pyfunction]
fn extract_media_from_html(
    py: Python<'_>,
    html: &str,
    page_url: &str,
) -> Option<RustSniffedMedia> {
    py.allow_threads(|| sniffer::extract_media_from_html_impl(html, page_url))
}

/// Extract all unique embedded media streams from raw HTML in priority order.
#[pyfunction]
fn extract_all_media_from_html(
    py: Python<'_>,
    html: &str,
    page_url: &str,
) -> Vec<RustSniffedMedia> {
    py.allow_threads(|| sniffer::extract_all_media_from_html_impl(html, page_url))
}

/// Fetch a single webpage asynchronously and extract its highest-priority media stream.
#[pyfunction]
#[pyo3(signature = (page_url, timeout=8.0))]
fn sniff_webpage(py: Python<'_>, page_url: &str, timeout: f64) -> Option<RustSniffedMedia> {
    py.allow_threads(|| sniffer::sniff_webpage_impl(page_url, timeout))
}

/// Fetch multiple webpages concurrently on Tokio's async HTTP pool and extract media streams.
#[pyfunction]
#[pyo3(signature = (page_urls, timeout=8.0, max_concurrency=16))]
fn sniff_webpages_batch(
    py: Python<'_>,
    page_urls: Vec<String>,
    timeout: f64,
    max_concurrency: usize,
) -> Vec<Option<RustSniffedMedia>> {
    py.allow_threads(|| sniffer::sniff_webpages_batch_impl(page_urls, timeout, max_concurrency))
}

/// Follow HTTP shortlink redirects (`HEAD` with `Range: bytes=0-0` fallback) on the pooled HTTP/2 client.
#[pyfunction]
#[pyo3(signature = (url, timeout=5.0))]
fn follow_redirects(py: Python<'_>, url: &str, timeout: f64) -> String {
    py.allow_threads(|| sniffer::follow_redirects_impl(url, timeout))
}

/// Fetch multiple `(url, custom_headers)` pairs concurrently on Tokio's pooled HTTP/2 client.
#[pyfunction]
#[pyo3(signature = (requests, timeout=8.0))]
fn fetch_urls_parallel(
    py: Python<'_>,
    requests: Vec<(String, HashMap<String, String>)>,
    timeout: f64,
) -> Vec<Option<(u16, String, String)>> {
    py.allow_threads(|| sniffer::fetch_urls_parallel_impl(requests, timeout))
}

/// Strip marketing tracking parameters (`utm_*`, `si`, `fbclid`, etc.) from a single URL.
#[pyfunction]
fn clean_url(url: &str) -> String {
    sniffer::clean_url_impl(url)
}

/// Strip marketing tracking parameters from a batch of URLs outside the GIL.
#[pyfunction]
fn clean_urls_batch(py: Python<'_>, urls: Vec<String>) -> Vec<String> {
    py.allow_threads(|| urls.iter().map(|u| sniffer::clean_url_impl(u)).collect())
}

/// Validate if `text` is a downloadable media URL using linear-time DFA matching.
#[pyfunction]
#[pyo3(signature = (text, media_filter_only=true))]
fn is_valid_media_url(text: &str, media_filter_only: bool) -> bool {
    parser::is_valid_media_url_impl(text, media_filter_only)
}

/// Extract first matching media or HTTP(S) URL from `text`.
#[pyfunction]
fn extract_media_url(text: &str) -> Option<String> {
    parser::extract_media_url_impl(text)
}

/// Clean, strip comments, and validate a batch of raw lines into ready-to-enqueue URLs outside the GIL.
#[pyfunction]
#[pyo3(signature = (lines, media_filter_only=false))]
fn filter_valid_media_urls_batch(
    py: Python<'_>,
    lines: Vec<String>,
    media_filter_only: bool,
) -> Vec<String> {
    py.allow_threads(|| parser::filter_valid_media_urls_batch_impl(&lines, media_filter_only))
}

/// Strip Douyin `/playwm/` and `watermark=` query parameter from CDN URLs.
#[pyfunction]
fn clean_douyin_watermark_url(url: &str) -> String {
    parser::clean_douyin_watermark_url_impl(url)
}

/// Parse a `yt-dlp` or `aria2c` stdout line into a compact 7-tuple
/// `(kind, pct, downloaded, total, speed, eta, extra)` with zero intermediate Rust String allocations,
/// or `None` for non-telemetry lines.
#[pyfunction]
fn parse_progress_line<'py>(py: Python<'py>, line: &str) -> PyResult<Option<Bound<'py, pyo3::types::PyTuple>>> {
    match parser::parse_progress_line_borrowed(line) {
        None => Ok(None),
        Some(ev) => {
            let tup = (
                ev.kind,
                ev.pct,
                ev.downloaded,
                ev.total,
                ev.speed(),
                ev.eta,
                ev.extra_str(),
            )
                .into_pyobject(py)?;
            Ok(Some(tup))
        }
    }
}

/// Load `archive.txt` in a single buffered pass outside the GIL, returning `(cache_set, id_index_map, had_generic)`.
#[pyfunction]
#[pyo3(signature = (file_path, rewrite_if_generic=true))]
fn load_archive_file(
    py: Python<'_>,
    file_path: &str,
    rewrite_if_generic: bool,
) -> (HashSet<String>, HashMap<String, String>, bool) {
    py.allow_threads(|| archive::load_archive_file_impl(Path::new(file_path), rewrite_if_generic))
}

#[pymodule]
fn ytdlp_rust_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    m.add_class::<RustSniffedMedia>()?;
    m.add_class::<RustM3u8Variant>()?;
    m.add_class::<RustM3u8Segment>()?;
    m.add_class::<RustM3u8Manifest>()?;
    m.add_class::<RustArchiveIndex>()?;

    m.add_function(wrap_pyfunction!(version, m)?)?;
    m.add_function(wrap_pyfunction!(capabilities, m)?)?;
    m.add_function(wrap_pyfunction!(find_embedded_second_ftyp_offset, m)?)?;
    m.add_function(wrap_pyfunction!(inspect_mp4_boxes, m)?)?;
    m.add_function(wrap_pyfunction!(find_fragment_groups, m)?)?;
    m.add_function(wrap_pyfunction!(cleanup_orphaned_fragments, m)?)?;
    m.add_function(wrap_pyfunction!(split_appended_mp4_stream, m)?)?;
    m.add_function(wrap_pyfunction!(stitch_fragments, m)?)?;
    m.add_function(wrap_pyfunction!(parse_m3u8_playlist, m)?)?;
    m.add_function(wrap_pyfunction!(download_hls_stream, m)?)?;
    m.add_function(wrap_pyfunction!(resolve_relative_url, m)?)?;
    m.add_function(wrap_pyfunction!(extract_media_from_html, m)?)?;
    m.add_function(wrap_pyfunction!(extract_all_media_from_html, m)?)?;
    m.add_function(wrap_pyfunction!(sniff_webpage, m)?)?;
    m.add_function(wrap_pyfunction!(sniff_webpages_batch, m)?)?;
    m.add_function(wrap_pyfunction!(follow_redirects, m)?)?;
    m.add_function(wrap_pyfunction!(fetch_urls_parallel, m)?)?;
    m.add_function(wrap_pyfunction!(clean_url, m)?)?;
    m.add_function(wrap_pyfunction!(clean_urls_batch, m)?)?;
    m.add_function(wrap_pyfunction!(is_valid_media_url, m)?)?;
    m.add_function(wrap_pyfunction!(extract_media_url, m)?)?;
    m.add_function(wrap_pyfunction!(filter_valid_media_urls_batch, m)?)?;
    m.add_function(wrap_pyfunction!(clean_douyin_watermark_url, m)?)?;
    m.add_function(wrap_pyfunction!(parse_progress_line, m)?)?;
    m.add_function(wrap_pyfunction!(load_archive_file, m)?)?;
    Ok(())
}
