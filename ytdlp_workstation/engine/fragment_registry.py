"""
Fragment ownership registry.

With several download workers sharing one target folder, a whole-directory scan
for ``*-Frag<N>`` files (post-download auto-merge, failure cleanup) would also
pick up fragments that ANOTHER worker is still writing -- stitching them early
under the wrong title, or deleting them mid-download.

Each engine "claims" the destination filenames it is writing (fragments are
named ``<destination>-Frag<N>``). Scans then skip bases claimed by other jobs.
Dependency-free so it can be imported from utils without cycles.
"""

__all__ = ["claim", "release", "claimed_by_others", "fragment_base"]

import threading
from pathlib import Path
from typing import Dict, Optional, Set

_lock = threading.Lock()
_claims: Dict[str, Set[str]] = {}


def fragment_base(filename: str) -> str:
    """Return the destination name a ``<name>-Frag<N>`` file belongs to."""
    return filename.rsplit("-Frag", 1)[0] if "-Frag" in filename else filename


def claim(job_id: str, destination: str) -> None:
    """Record that ``job_id`` is writing ``destination`` (path or bare name)."""
    if not job_id or not destination:
        return
    name = Path(destination.strip().strip('"')).name
    if not name:
        return
    with _lock:
        _claims.setdefault(job_id, set()).add(name)


def release(job_id: str) -> None:
    """Drop all claims of a finished/cancelled job."""
    with _lock:
        _claims.pop(job_id, None)


def claimed_by_others(job_id: Optional[str] = None) -> Set[str]:
    """Destination names currently claimed by jobs other than ``job_id``."""
    with _lock:
        out: Set[str] = set()
        for jid, names in _claims.items():
            if jid != job_id:
                out |= names
        return out
