"""
Native Rust extension (`ytdlp_rust_core`) runtime bridge and fallback controller.

Provides zero-cost detection of the compiled PyO3 extension module and allows
toggling or forcing pure-Python fallback via `set_rust_enabled(False)`,
`YTDLP_WS_DISABLE_RUST=1`, or `force_python_fallback()` for deterministic
parity testing and benchmarking.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator, List, Optional

__all__ = [
    "HAS_RUST_CORE",
    "RUST_CORE_VERSION",
    "rust_core",
    "is_rust_enabled",
    "set_rust_enabled",
    "get_rust_capabilities",
    "force_python_fallback",
]

try:
    import ytdlp_rust_core as _rust_core  # type: ignore[import-not-found]
    HAS_RUST_CORE: bool = True
    RUST_CORE_VERSION: Optional[str] = getattr(_rust_core, "__version__", "0.2.0")
    rust_core: Optional[Any] = _rust_core
except ImportError:
    HAS_RUST_CORE = False
    RUST_CORE_VERSION = None
    rust_core = None

_FORCE_PYTHON: bool = os.environ.get("YTDLP_WS_DISABLE_RUST", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)


def is_rust_enabled() -> bool:
    """Return True when `ytdlp_rust_core` is compiled, importable, and not disabled."""
    return HAS_RUST_CORE and not _FORCE_PYTHON


def set_rust_enabled(enabled: bool) -> bool:
    """Enable or disable Rust acceleration at runtime. Returns the new active state."""
    global _FORCE_PYTHON
    _FORCE_PYTHON = not bool(enabled)
    return is_rust_enabled()


def get_rust_capabilities() -> List[str]:
    """Return the list of compiled Rust acceleration subsystems."""
    if HAS_RUST_CORE and rust_core is not None and hasattr(rust_core, "capabilities"):
        try:
            return list(rust_core.capabilities())
        except Exception:
            return []
    return []


@contextmanager
def force_python_fallback() -> Iterator[None]:
    """Context manager that temporarily disables Rust acceleration (for tests & benchmarks)."""
    global _FORCE_PYTHON
    prev = _FORCE_PYTHON
    _FORCE_PYTHON = True
    try:
        yield
    finally:
        _FORCE_PYTHON = prev
