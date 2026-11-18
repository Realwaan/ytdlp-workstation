use std::fs::{File, OpenOptions};
use std::io::{BufReader, Read, Seek, SeekFrom};
use std::path::Path;

const MP4_READ_BUF: usize = 64 * 1024; // 64 KiB userspace buffer eliminates syscalls on adjacent small atoms

#[inline]
fn open_read_optimized(path: &Path) -> std::io::Result<File> {
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

/// Walk top-level ISO BMFF (MP4/MOV) boxes starting from byte 0.
/// If a second `ftyp` box is encountered after a media/movie box (`moov`, `mdat`, `moof`),
/// returns its exact byte offset. Used to recover files affected by `--no-part` collisions.
pub fn find_embedded_second_ftyp_offset_impl(path: &Path) -> Option<u64> {
    let raw_file = open_read_optimized(path).ok()?;
    let total_size = raw_file.metadata().ok()?.len();
    if total_size < 1024 {
        return None;
    }

    let mut reader = BufReader::with_capacity(MP4_READ_BUF, raw_file);
    let mut pos: u64 = 0;
    let mut seen_first_ftyp = false;
    let mut seen_media_box = false;
    let mut hdr = [0u8; 8];
    let mut ext = [0u8; 8];

    while pos.checked_add(8)? <= total_size {
        if reader.read_exact(&mut hdr).is_err() {
            break;
        }

        let sz32 = u32::from_be_bytes([hdr[0], hdr[1], hdr[2], hdr[3]]) as u64;
        let btype = &hdr[4..8];

        let (box_size, hdr_consumed) = if sz32 == 1 {
            if pos.checked_add(16)? > total_size {
                break;
            }
            if reader.read_exact(&mut ext).is_err() {
                break;
            }
            let sz64 = u64::from_be_bytes(ext);
            if sz64 < 16 {
                break;
            }
            (sz64, 16u64)
        } else if sz32 == 0 {
            break;
        } else if sz32 < 8 {
            break;
        } else {
            (sz32, 8u64)
        };

        if btype == b"ftyp" {
            if !seen_first_ftyp {
                seen_first_ftyp = true;
            } else if seen_media_box && pos > 0 {
                return Some(pos);
            }
        } else if btype == b"moov" || btype == b"mdat" || btype == b"moof" {
            seen_media_box = true;
        }

        let next_pos = pos.checked_add(box_size)?;
        if next_pos > total_size {
            break;
        }

        let payload_skip = box_size - hdr_consumed;
        if payload_skip <= i64::MAX as u64 {
            // Stays inside BufReader's 64 KiB buffer with zero kernel syscalls when nearby!
            if reader.seek_relative(payload_skip as i64).is_err() {
                break;
            }
        } else if reader.seek(SeekFrom::Start(next_pos)).is_err() {
            break;
        }

        pos = next_pos;
    }

    None
}

/// Inspect top-level ISO BMFF boxes in `path`, returning `(fourcc, byte_offset, byte_size)`.
pub fn inspect_mp4_boxes_impl(path: &Path) -> std::io::Result<Vec<(String, u64, u64)>> {
    let raw_file = open_read_optimized(path)?;
    let total_size = raw_file.metadata()?.len();
    let mut reader = BufReader::with_capacity(MP4_READ_BUF, raw_file);
    let mut boxes = Vec::new();

    let mut pos: u64 = 0;
    let mut hdr = [0u8; 8];
    let mut ext = [0u8; 8];

    while let Some(end_hdr) = pos.checked_add(8) {
        if end_hdr > total_size {
            break;
        }
        if reader.read_exact(&mut hdr).is_err() {
            break;
        }

        let sz32 = u32::from_be_bytes([hdr[0], hdr[1], hdr[2], hdr[3]]) as u64;
        let fourcc = String::from_utf8_lossy(&hdr[4..8]).into_owned();

        let (box_size, hdr_consumed) = if sz32 == 1 {
            if pos.checked_add(16).map_or(true, |e| e > total_size) {
                break;
            }
            if reader.read_exact(&mut ext).is_err() {
                break;
            }
            let sz64 = u64::from_be_bytes(ext);
            if sz64 < 16 {
                break;
            }
            (sz64, 16u64)
        } else if sz32 == 0 {
            (total_size - pos, 8u64)
        } else if sz32 < 8 {
            break;
        } else {
            (sz32, 8u64)
        };

        boxes.push((fourcc, pos, box_size));
        if sz32 == 0 {
            break;
        }

        let next_pos = match pos.checked_add(box_size) {
            Some(n) if n <= total_size => n,
            _ => break,
        };

        let payload_skip = box_size - hdr_consumed;
        if payload_skip <= i64::MAX as u64 {
            reader.seek_relative(payload_skip as i64)?;
        } else {
            reader.seek(SeekFrom::Start(next_pos))?;
        }
        pos = next_pos;
    }

    Ok(boxes)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::NamedTempFile;

    fn make_box(fourcc: &[u8; 4], payload_len: usize) -> Vec<u8> {
        let total = (8 + payload_len) as u32;
        let mut out = Vec::with_capacity(8 + payload_len);
        out.extend_from_slice(&total.to_be_bytes());
        out.extend_from_slice(fourcc);
        out.resize(8 + payload_len, 0xAA);
        out
    }

    #[test]
    fn detects_concatenated_second_ftyp_box() {
        let mut tmp = NamedTempFile::new().unwrap();
        let mut data = Vec::new();
        data.extend(make_box(b"ftyp", 24));
        data.extend(make_box(b"moov", 256));
        data.extend(make_box(b"mdat", 1024));
        let expected_offset = data.len() as u64;
        data.extend(make_box(b"ftyp", 24));
        data.extend(make_box(b"moof", 128));
        tmp.write_all(&data).unwrap();
        tmp.flush().unwrap();

        assert_eq!(
            find_embedded_second_ftyp_offset_impl(tmp.path()),
            Some(expected_offset)
        );
    }

    #[test]
    fn returns_none_for_clean_single_stream_mp4() {
        let mut tmp = NamedTempFile::new().unwrap();
        let mut data = Vec::new();
        data.extend(make_box(b"ftyp", 24));
        data.extend(make_box(b"moov", 512));
        data.extend(make_box(b"mdat", 1024));
        tmp.write_all(&data).unwrap();
        tmp.flush().unwrap();

        assert_eq!(find_embedded_second_ftyp_offset_impl(tmp.path()), None);
    }
}
