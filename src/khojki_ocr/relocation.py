"""Explicit read-only relocation of historical provenance paths; never fall back."""

from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

_mapping = ContextVar("provenance_mapping", default=None)


@contextmanager
def relocated_sources(original_root, project_root, *, allowed_roots=()):
    old, new = Path(original_root), Path(project_root).resolve()
    if not old.is_absolute():
        raise ValueError("Original root must be absolute")
    token = _mapping.set((old, new, tuple(Path(p).resolve() for p in allowed_roots)))
    try:
        yield
    finally:
        _mapping.reset(token)


def source_path(name):
    path = Path(name)
    mapping = _mapping.get()
    if mapping is None:
        return path
    old, new, extra = mapping
    if path.is_absolute() and path.is_relative_to(old):
        candidate = new / path.relative_to(old)
    else:
        candidate = path if path.is_absolute() else new / path
    candidate = candidate.resolve()
    if not any(candidate.is_relative_to(root) for root in (new, *extra)):
        raise ValueError("Relocated source escapes the allowed project root")
    # Existence is checked here: never retry the original absolute path.
    if not candidate.is_file():
        raise ValueError("Relocated source is missing")
    return candidate
