"""Native yt-dlp execution engine, options builder, Rust acceleration bridge, and progress hook bindings."""

from .auto_clipper import create_vertical_short, generate_anti_spam_variants, get_sfx_path
from .rust_accel import (
    HAS_RUST_CORE,
    RUST_CORE_VERSION,
    is_rust_enabled,
    set_rust_enabled,
    get_rust_capabilities,
    force_python_fallback,
)

__all__ = [
    "create_vertical_short",
    "generate_anti_spam_variants",
    "get_sfx_path",
    "HAS_RUST_CORE",
    "RUST_CORE_VERSION",
    "is_rust_enabled",
    "set_rust_enabled",
    "get_rust_capabilities",
    "force_python_fallback",
]
