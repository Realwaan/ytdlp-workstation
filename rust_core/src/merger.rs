use pyo3::exceptions::PyIOError;
use pyo3::prelude::*;
use std::collections::{HashMap, HashSet};
use std::fs::{self, File, OpenOptions};
use std::io::{BufWriter, Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

const IO_BUF_SIZE: usize = 4 * 1024 * 1024; // 4 MiB read buffer + 16 MiB coalescing BufWriter
const OUT_WRITE_BUF_SIZE: usize = 16 * 1024 * 1024;

#[inline]
fn open_sequential_read(path: &Path) -> std::io::Result<File> {
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;
        const FILE_FLAG_SEQUENTIAL_SCAN: u32 = 0x0800_0000;
        OpenOptions::new()
            .read(true)
            .custom_flags(FILE_FLAG_SEQUENTIAL_SCAN)
            .open(path)
    }
    #[cfg(not(windows))]
    {
        File::open(path)
    }
}

/// Parse a `*-Frag<N>` filename into `(base_filename, fragment_number)`.
#[inline]
pub fn parse_fragment_filename(name: &str) -> Option<(&str, u64)> {
    let idx = name.rfind("-Frag")?;
    let base = &name[..idx];
    let num_str = &name[idx + 5..];
    if base.is_empty() || num_str.is_empty() || !num_str.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    let num = num_str.parse::<u64>().ok()?;
    Some((base, num))
}

/// Scan `directory` for `*-Frag<N>` files, skipping bases in `protected`, and sort each group by `frag_num`.
pub fn find_fragment_groups_impl(
    directory: &Path,
    protected: &HashSet<String>,
) -> HashMap<String, Vec<(u64, String)>> {
    let mut groups: HashMap<String, Vec<(u64, String)>> = HashMap::new();
    let entries = match fs::read_dir(directory) {
        Ok(rd) => rd,
        Err(_) => return groups,
    };

    for entry_res in entries {
        let entry = match entry_res {
            Ok(e) => e,
            Err(_) => continue,
        };

        let file_name_os = entry.file_name();
        let file_name = match file_name_os.to_str() {
            Some(s) => s,
            None => continue,
        };

        let (base, frag_num) = match parse_fragment_filename(file_name) {
            Some(pair) => pair,
            None => continue,
        };

        if protected.contains(base) {
            continue;
        }

        // Uses OS directory entry metadata directly on Windows without an extra stat syscall when not a symlink.
        let is_file = match entry.file_type() {
            Ok(ft) if ft.is_symlink() => entry.path().is_file(),
            Ok(ft) => ft.is_file(),
            Err(_) => false,
        };
        if !is_file {
            continue;
        }

        let full_path = entry.path().to_string_lossy().into_owned();
        groups
            .entry(base.to_owned())
            .or_default()
            .push((frag_num, full_path));
    }

    for list in groups.values_mut() {
        list.sort_unstable_by_key(|(num, _)| *num);
    }

    groups
}

/// Delete all orphaned `*-Frag*` files in `directory` whose base name (`rsplit("-Frag", 1)[0]`)
/// is not claimed by another active job in `protected`. Returns the count of deleted files.
pub fn cleanup_orphaned_fragments_impl(directory: &Path, protected: &HashSet<String>) -> u64 {
    let entries = match fs::read_dir(directory) {
        Ok(rd) => rd,
        Err(_) => return 0,
    };

    let mut deleted: u64 = 0;
    for entry_res in entries {
        let entry = match entry_res {
            Ok(e) => e,
            Err(_) => continue,
        };
        let fname_os = entry.file_name();
        let fname = match fname_os.to_str() {
            Some(s) => s,
            None => continue,
        };
        let frag_idx = match fname.rfind("-Frag") {
            Some(idx) => idx,
            None => continue,
        };
        let base = &fname[..frag_idx];
        if !protected.is_empty() && protected.contains(base) {
            continue;
        }
        let is_file = match entry.file_type() {
            Ok(ft) if ft.is_symlink() => entry.path().is_file(),
            Ok(ft) => ft.is_file(),
            Err(_) => false,
        };
        if is_file && fs::remove_file(entry.path()).is_ok() {
            deleted += 1;
        }
    }
    deleted
}

/// Extract bytes `[split_offset..EOF]` from `src_path` into `dst_path`, then truncate `src_path` to `split_offset`.
pub fn split_appended_mp4_stream_impl(
    src_path: &Path,
    dst_path: &Path,
    split_offset: u64,
) -> std::io::Result<u64> {
    let mut copied: u64 = 0;
    {
        let mut src = File::open(src_path)?;
        let mut dst = File::create(dst_path)?;
        src.seek(SeekFrom::Start(split_offset))?;

        let mut buf = vec![0u8; IO_BUF_SIZE];
        loop {
            let n = src.read(&mut buf)?;
            if n == 0 {
                break;
            }
            dst.write_all(&buf[..n])?;
            copied += n as u64;
        }
        dst.flush()?;
    }

    let src_trunc = OpenOptions::new().write(true).open(src_path)?;
    src_trunc.set_len(split_offset)?;
    Ok(copied)
}

/// Stitch `frag_paths` sequentially onto `target_path` using a single reusable 16 MiB buffer,
/// releasing Python's GIL during all file I/O and invoking `check_cancelled` / `on_progress` hooks.
/// Returns `(written_bytes, was_cancelled)`.
pub fn stitch_fragments_py(
    py: Python<'_>,
    target_path: &str,
    frag_paths: Vec<String>,
    delete_frags: bool,
    progress_interval_ms: u64,
    check_cancelled: Option<Py<PyAny>>,
    on_progress: Option<Py<PyAny>>,
) -> PyResult<(u64, bool)> {
    let target = PathBuf::from(target_path);
    let total_frags = frag_paths.len();
    if total_frags == 0 {
        let existing_len = fs::metadata(&target).map(|m| m.len()).unwrap_or(0);
        return Ok((existing_len, false));
    }

    // Compute byte totals outside the GIL
    let (prefix_bytes, remaining_bytes) = py.allow_threads(|| {
        let p_bytes = fs::metadata(&target).map(|m| m.len()).unwrap_or(0);
        let r_bytes: u64 = frag_paths
            .iter()
            .filter_map(|p| fs::metadata(p).ok().map(|m| m.len()))
            .sum();
        (p_bytes, r_bytes)
    });

    let grand_total_bytes = prefix_bytes.saturating_add(remaining_bytes);
    let mut written_bytes = prefix_bytes;

    let raw_out_file = py
        .allow_threads(|| OpenOptions::new().create(true).append(true).open(&target))
        .map_err(|e| PyIOError::new_err(format!("Failed opening target '{}': {}", target_path, e)))?;
    let mut out_file = BufWriter::with_capacity(OUT_WRITE_BUF_SIZE, raw_out_file);

    let mut buf = vec![0u8; IO_BUF_SIZE];
    let start_instant = Instant::now();
    let mut last_ui_instant: Option<Instant> = None;
    let min_interval = Duration::from_millis(progress_interval_ms);

    for (idx_zero, frag_path_str) in frag_paths.iter().enumerate() {
        let idx = idx_zero + 1;

        if let Some(ref cancel_cb) = check_cancelled {
            let is_cancelled: bool = cancel_cb.bind(py).call0()?.extract()?;
            if is_cancelled {
                return Ok((written_bytes, true));
            }
        }

        let frag_result: std::io::Result<(u64, bool)> = py.allow_threads(|| {
            let fpath = Path::new(frag_path_str);
            if !fpath.exists() {
                return Ok((0, false));
            }

            let mut delta: u64 = 0;
            {
                let mut in_f = open_sequential_read(fpath)?;
                loop {
                    let n = in_f.read(&mut buf)?;
                    if n == 0 {
                        break;
                    }
                    out_file.write_all(&buf[..n])?;
                    delta += n as u64;
                }
            }

            if delete_frags {
                let _ = fs::remove_file(fpath);
            }
            Ok((delta, true))
        });

        let (delta, existed) = frag_result
            .map_err(|e| PyIOError::new_err(format!("Fragment stitch I/O error on '{}': {}", frag_path_str, e)))?;

        if !existed {
            continue;
        }
        written_bytes = written_bytes.saturating_add(delta);

        let should_emit = idx == 1
            || idx == total_frags
            || last_ui_instant.map_or(true, |last| last.elapsed() >= min_interval);

        if should_emit {
            last_ui_instant = Some(Instant::now());
            if let Some(ref prog_cb) = on_progress {
                let elapsed_secs = start_instant.elapsed().as_secs_f64().max(0.001);
                prog_cb.bind(py).call1((
                    written_bytes,
                    grand_total_bytes,
                    prefix_bytes,
                    elapsed_secs,
                    idx,
                    total_frags,
                ))?;
            }
        }
    }

    py.allow_threads(|| out_file.flush())
        .map_err(|e| PyIOError::new_err(format!("Failed flushing '{}': {}", target_path, e)))?;

    Ok((written_bytes, false))
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn parses_valid_and_invalid_fragment_names() {
        assert_eq!(
            parse_fragment_filename("movie [2160p].mp4-Frag1"),
            Some(("movie [2160p].mp4", 1))
        );
        assert_eq!(
            parse_fragment_filename("stream-Frag0042"),
            Some(("stream", 42))
        );
        assert_eq!(parse_fragment_filename("-Frag1"), None);
        assert_eq!(parse_fragment_filename("movie-Frag"), None);
        assert_eq!(parse_fragment_filename("movie-Frag1.part"), None);
        assert_eq!(parse_fragment_filename("regular.mp4"), None);
    }

    #[test]
    fn groups_and_sorts_fragments_respecting_protected() {
        let dir = tempdir().unwrap();
        fs::write(dir.path().join("a.mp4-Frag10"), b"10").unwrap();
        fs::write(dir.path().join("a.mp4-Frag2"), b"2").unwrap();
        fs::write(dir.path().join("b.mp4-Frag1"), b"b1").unwrap();

        let mut protected = HashSet::new();
        protected.insert("b.mp4".to_string());

        let groups = find_fragment_groups_impl(dir.path(), &protected);
        assert!(groups.contains_key("a.mp4"));
        assert!(!groups.contains_key("b.mp4"));
        let a_frags = &groups["a.mp4"];
        assert_eq!(a_frags.len(), 2);
        assert_eq!(a_frags[0].0, 2);
        assert_eq!(a_frags[1].0, 10);
    }

    #[test]
    fn splits_and_truncates_appended_stream() {
        let dir = tempdir().unwrap();
        let src = dir.path().join("orig.mp4");
        let dst = dir.path().join("split.mp4");
        fs::write(&src, b"FIRST_MOVIE_DATA|SECOND_STREAM").unwrap();

        let copied = split_appended_mp4_stream_impl(&src, &dst, 17).unwrap();
        assert_eq!(copied, 13);
        assert_eq!(fs::read(&src).unwrap(), b"FIRST_MOVIE_DATA|");
        assert_eq!(fs::read(&dst).unwrap(), b"SECOND_STREAM");
    }
}
