use pyo3::prelude::*;
use std::collections::{HashMap, HashSet};
use std::fs;
use std::hash::{BuildHasherDefault, Hasher};
use std::io::{BufWriter, Write};
use std::path::Path;
use std::sync::RwLock;

/// Fast non-cryptographic 64-bit FxHasher (used by rustc internally for symbol tables).
#[derive(Default)]
struct IdentityU64Hasher(u64);

impl Hasher for IdentityU64Hasher {
    #[inline]
    fn finish(&self) -> u64 {
        self.0
    }

    #[inline]
    fn write(&mut self, bytes: &[u8]) {
        self.0 = fx_hash_bytes(bytes);
    }

    #[inline]
    fn write_u64(&mut self, i: u64) {
        self.0 = i;
    }
}

type FastU64Map<V> = HashMap<u64, V, BuildHasherDefault<IdentityU64Hasher>>;

#[inline]
fn fx_hash_bytes(bytes: &[u8]) -> u64 {
    const K: u64 = 0x517cc1b727220a95;
    let mut hash: u64 = 0xcbf29ce484222325;
    let mut chunks = bytes.chunks_exact(8);
    for chunk in &mut chunks {
        let word = u64::from_le_bytes([
            chunk[0], chunk[1], chunk[2], chunk[3], chunk[4], chunk[5], chunk[6], chunk[7],
        ]);
        hash = (hash.rotate_left(5) ^ word).wrapping_mul(K);
    }
    for &b in chunks.remainder() {
        hash = (hash.rotate_left(5) ^ (b as u64)).wrapping_mul(K);
    }
    hash
}

#[derive(Clone)]
enum SpanBucket {
    One(u32, u32),
    Many(Box<Vec<(u32, u32)>>),
}

impl SpanBucket {
    #[inline]
    fn matches(&self, arena: &[u8], needle: &[u8]) -> bool {
        match self {
            SpanBucket::One(s, e) => &arena[*s as usize..*e as usize] == needle,
            SpanBucket::Many(list) => list
                .iter()
                .any(|(s, e)| &arena[*s as usize..*e as usize] == needle),
        }
    }

    #[inline]
    fn insert(&mut self, arena: &[u8], start: u32, end: u32) -> bool {
        let needle = &arena[start as usize..end as usize];
        if self.matches(arena, needle) {
            return false;
        }
        match self {
            SpanBucket::One(s, e) => {
                let prev = (*s, *e);
                *self = SpanBucket::Many(Box::new(vec![prev, (start, end)]));
            }
            SpanBucket::Many(list) => list.push((start, end)),
        }
        true
    }
}

struct ArchiveInner {
    arena: Vec<u8>,
    entry_spans: Vec<(u32, u32)>,
    entry_map: FastU64Map<SpanBucket>,
    id_map: FastU64Map<SpanBucket>,
}

impl ArchiveInner {
    fn with_capacity(arena_bytes: Vec<u8>, est_items: usize) -> Self {
        Self {
            arena: arena_bytes,
            entry_spans: Vec::with_capacity(est_items),
            entry_map: HashMap::with_capacity_and_hasher(est_items, BuildHasherDefault::default()),
            id_map: HashMap::with_capacity_and_hasher(est_items, BuildHasherDefault::default()),
        }
    }

    #[inline]
    fn insert_span_known_slices(
        entry_spans: &mut Vec<(u32, u32)>,
        entry_map: &mut FastU64Map<SpanBucket>,
        id_map: &mut FastU64Map<SpanBucket>,
        arena: &[u8],
        entry_start: u32,
        entry_end: u32,
        id_start: u32,
        id_end: u32,
    ) -> bool {
        let entry_slice = &arena[entry_start as usize..entry_end as usize];
        let eh = fx_hash_bytes(entry_slice);
        let is_new = match entry_map.get_mut(&eh) {
            None => {
                entry_map.insert(eh, SpanBucket::One(entry_start, entry_end));
                true
            }
            Some(bucket) => bucket.insert(arena, entry_start, entry_end),
        };
        if !is_new {
            return false;
        }

        entry_spans.push((entry_start, entry_end));
        let id_slice = &arena[id_start as usize..id_end as usize];
        let ih = fx_hash_bytes(id_slice);
        match id_map.get_mut(&ih) {
            None => {
                id_map.insert(ih, SpanBucket::One(id_start, id_end));
            }
            Some(bucket) => {
                let _ = bucket.insert(arena, id_start, id_end);
            }
        }
        true
    }

    #[inline]
    fn insert_span(&mut self, entry_start: u32, entry_end: u32, id_start: u32, id_end: u32) -> bool {
        Self::insert_span_known_slices(
            &mut self.entry_spans,
            &mut self.entry_map,
            &mut self.id_map,
            &self.arena,
            entry_start,
            entry_end,
            id_start,
            id_end,
        )
    }

    #[inline]
    fn contains_id(&self, vid: &[u8]) -> bool {
        let ih = fx_hash_bytes(vid);
        self.id_map
            .get(&ih)
            .is_some_and(|b| b.matches(&self.arena, vid))
    }

    #[inline]
    fn contains_entry(&self, entry: &[u8]) -> bool {
        let eh = fx_hash_bytes(entry);
        self.entry_map
            .get(&eh)
            .is_some_and(|b| b.matches(&self.arena, entry))
    }
}

/// Arena-backed, zero-per-line-allocation native Rust archive index (`O(1)` duplicate blocker).
/// Loads `archive.txt` into a single contiguous byte arena and indexes `(start, end)` spans via 64-bit FxHash.
#[pyclass]
pub struct RustArchiveIndex {
    inner: RwLock<ArchiveInner>,
    pub had_generic: bool,
}

#[pymethods]
impl RustArchiveIndex {
    #[new]
    #[pyo3(signature = (file_path, rewrite_if_generic=true))]
    pub fn new(py: Python<'_>, file_path: &str, rewrite_if_generic: bool) -> Self {
        py.allow_threads(|| Self::load_native(Path::new(file_path), rewrite_if_generic))
    }

    /// Check if `video_id` exists in the archive (`O(1)` exact match).
    pub fn is_archived(&self, video_id: &str) -> bool {
        let vid = video_id.trim();
        if vid.is_empty() {
            return false;
        }
        self.inner
            .read()
            .map(|g| g.contains_id(vid.as_bytes()))
            .unwrap_or(false)
    }

    /// Insert `(extractor, video_id)`. Returns `Some(entry_line)` if newly added, else `None`.
    pub fn add_entry(&self, extractor: &str, video_id: &str) -> Option<String> {
        let entry = format!("{} {}", extractor, video_id).trim().to_string();
        if entry.is_empty() {
            return None;
        }
        let mut guard = self.inner.write().ok()?;
        if guard.contains_entry(entry.as_bytes()) {
            return None;
        }

        let entry_start = guard.arena.len() as u32;
        guard.arena.extend_from_slice(entry.as_bytes());
        let entry_end = guard.arena.len() as u32;

        let vid_trimmed = video_id.trim();
        let (id_start, id_end) = if !vid_trimmed.is_empty() && entry.ends_with(vid_trimmed) {
            (entry_end - vid_trimmed.len() as u32, entry_end)
        } else {
            (entry_start, entry_end)
        };

        guard.insert_span(entry_start, entry_end, id_start, id_end);
        Some(entry)
    }

    /// Clear all in-memory archive entries and indexed IDs (`O(1)`).
    pub fn clear(&self) {
        if let Ok(mut guard) = self.inner.write() {
            guard.arena.clear();
            guard.entry_spans.clear();
            guard.entry_map.clear();
            guard.id_map.clear();
        }
    }

    /// Return snapshot list of full archive lines (used only for one-time SQLite seeding).
    pub fn entries(&self) -> Vec<String> {
        let guard = match self.inner.read() {
            Ok(g) => g,
            Err(_) => return Vec::new(),
        };
        guard
            .entry_spans
            .iter()
            .map(|&(s, e)| String::from_utf8_lossy(&guard.arena[s as usize..e as usize]).into_owned())
            .collect()
    }

    pub fn __len__(&self) -> usize {
        self.inner.read().map(|g| g.entry_spans.len()).unwrap_or(0)
    }

    pub fn __contains__(&self, item: &str) -> bool {
        self.inner
            .read()
            .map(|g| g.contains_entry(item.as_bytes()))
            .unwrap_or(false)
    }
}

#[inline]
fn trim_ascii_range(buf: &[u8], mut start: usize, mut end: usize) -> (usize, usize) {
    while start < end && buf[start].is_ascii_whitespace() {
        start += 1;
    }
    while end > start && buf[end - 1].is_ascii_whitespace() {
        end -= 1;
    }
    (start, end)
}

impl RustArchiveIndex {
    pub fn load_native(path: &Path, rewrite_if_generic: bool) -> Self {
        let raw_bytes = match fs::read(path) {
            Ok(b) => b,
            Err(_) => {
                return Self {
                    inner: RwLock::new(ArchiveInner::with_capacity(Vec::new(), 0)),
                    had_generic: false,
                }
            }
        };

        let est_cap = (raw_bytes.len() / 20).max(16);
        let mut entry_spans: Vec<(u32, u32)> = Vec::with_capacity(est_cap);
        let mut entry_map: FastU64Map<SpanBucket> =
            HashMap::with_capacity_and_hasher(est_cap, BuildHasherDefault::default());
        let mut id_map: FastU64Map<SpanBucket> =
            HashMap::with_capacity_and_hasher(est_cap, BuildHasherDefault::default());
        let mut had_generic = false;

        let len = raw_bytes.len();
        let mut line_start = 0usize;

        while line_start < len {
            let line_end = match memchr::memchr(b'\n', &raw_bytes[line_start..]) {
                Some(off) => line_start + off,
                None => len,
            };

            let (s, e) = trim_ascii_range(&raw_bytes, line_start, line_end);
            line_start = line_end + 1;

            if s >= e || raw_bytes[s] == b'#' {
                continue;
            }
            if e - s >= 8 && &raw_bytes[s..s + 8] == b"generic " {
                had_generic = true;
                continue;
            }

            let (id_s, id_e) = match memchr::memchr2(b' ', b'\t', &raw_bytes[s..e]) {
                Some(ws_off) => {
                    let mut p = s + ws_off + 1;
                    while p < e && raw_bytes[p].is_ascii_whitespace() {
                        p += 1;
                    }
                    if p < e { (p, e) } else { (s, e) }
                }
                None => (s, e),
            };

            ArchiveInner::insert_span_known_slices(
                &mut entry_spans,
                &mut entry_map,
                &mut id_map,
                &raw_bytes,
                s as u32,
                e as u32,
                id_s as u32,
                id_e as u32,
            );
        }

        if had_generic && rewrite_if_generic {
            let mut sorted_slices: Vec<&[u8]> = entry_spans
                .iter()
                .map(|&(s, e)| &raw_bytes[s as usize..e as usize])
                .collect();
            sorted_slices.sort_unstable();
            if let Ok(f) = fs::File::create(path) {
                let mut w = BufWriter::new(f);
                for slice in sorted_slices {
                    let _ = w.write_all(slice);
                    let _ = w.write_all(b"\n");
                }
                let _ = w.flush();
            }
        }

        Self {
            inner: RwLock::new(ArchiveInner {
                arena: raw_bytes,
                entry_spans,
                entry_map,
                id_map,
            }),
            had_generic,
        }
    }
}

/// Tuple loader retained for callers needing owned Python set + dict copies.
pub fn load_archive_file_impl(
    path: &Path,
    rewrite_if_generic: bool,
) -> (HashSet<String>, HashMap<String, String>, bool) {
    let mut cache = HashSet::new();
    let mut index = HashMap::new();
    let mut had_generic = false;

    let raw_bytes = match fs::read(path) {
        Ok(b) => b,
        Err(_) => return (cache, index, false),
    };

    let text = String::from_utf8_lossy(&raw_bytes);
    for raw_line in text.lines() {
        let line = raw_line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        if line.starts_with("generic ") {
            had_generic = true;
            continue;
        }
        let video_id = match line.split_once(char::is_whitespace) {
            Some((_, rest)) => rest.trim_start(),
            None => line,
        };
        index.insert(video_id.to_string(), line.to_string());
        cache.insert(line.to_string());
    }

    if had_generic && rewrite_if_generic {
        let mut sorted: Vec<&String> = cache.iter().collect();
        sorted.sort_unstable();
        if let Ok(f) = fs::File::create(path) {
            let mut w = BufWriter::new(f);
            for entry in sorted {
                let _ = writeln!(w, "{}", entry);
            }
            let _ = w.flush();
        }
    }

    (cache, index, had_generic)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::NamedTempFile;

    #[test]
    fn loads_and_cleans_generic_archive_entries() {
        let tmp = NamedTempFile::new().unwrap();
        fs::write(
            tmp.path(),
            "# comment\nyoutube dQw4w9WgXcQ\ngeneric index-v1-a1\ntiktok 7319999\nlegacy_single_id\n",
        )
        .unwrap();

        let idx = RustArchiveIndex::load_native(tmp.path(), true);
        assert!(idx.had_generic);
        assert_eq!(idx.__len__(), 3);
        assert!(idx.is_archived("dQw4w9WgXcQ"));
        assert!(idx.is_archived("7319999"));
        assert!(idx.is_archived("legacy_single_id"));
        assert!(!idx.is_archived("index-v1-a1"));

        let added = idx.add_entry("vimeo", "55555");
        assert_eq!(added.as_deref(), Some("vimeo 55555"));
        assert!(idx.is_archived("55555"));
        assert!(idx.add_entry("vimeo", "55555").is_none());

        let rewritten = fs::read_to_string(tmp.path()).unwrap();
        assert!(!rewritten.contains("generic "));
        assert!(rewritten.contains("youtube dQw4w9WgXcQ"));
    }
}
