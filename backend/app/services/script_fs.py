"""Filesystem layer for the robot_scripts/ browser used by the Scripts page.

Everything here is confined to SCRIPTS_DIR: paths coming from the API are
relative and resolved through :func:`resolve`, which rejects escapes.
"""

from __future__ import annotations

import ast
import re
import shutil
from pathlib import Path
from typing import Any, Callable, Optional

from ..config_loader import SCRIPTS_DIR, load_script_manifest, save_json

MANIFEST_NAME = "manifest.json"
MAX_EDIT_BYTES = 1_000_000

TEXT_SUFFIXES = {
    ".py",
    ".json",
    ".txt",
    ".md",
    ".yaml",
    ".yml",
    ".cfg",
    ".ini",
    ".toml",
    ".csv",
    ".sh",
}

SKIP_NAMES = {
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    ".git",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    ".ipynb_checkpoints",
}

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# (mtime_ns, size) -> first docstring line, so tree polling stays cheap.
_doc_cache: dict[Path, tuple[tuple[int, int], str]] = {}


class ScriptFsError(Exception):
    """Rejected path or unsupported script filesystem operation."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def scripts_root() -> Path:
    return SCRIPTS_DIR.resolve()


def resolve(rel: str, *, must_exist: bool = True) -> Path:
    """Resolve a client-supplied relative path inside SCRIPTS_DIR."""
    raw = (rel or "").strip().replace("\\", "/")
    if raw.startswith("/"):
        raise ScriptFsError("Absolute paths are not allowed")
    raw = raw.strip("/")
    if not raw:
        raise ScriptFsError("Empty path")
    if "\x00" in raw:
        raise ScriptFsError("Invalid path")
    root = scripts_root()
    path = (root / raw).resolve()
    if path != root and root not in path.parents:
        raise ScriptFsError("Path escapes robot_scripts/")
    for part in Path(raw).parts:
        if part in {".", ".."}:
            raise ScriptFsError("Invalid path")
        if part in SKIP_NAMES:
            raise ScriptFsError(f"'{part}' is not editable")
    if must_exist and not path.exists():
        raise ScriptFsError(f"Not found: {raw}", status=404)
    return path


def relative(path: Path) -> str:
    return path.resolve().relative_to(scripts_root()).as_posix()


def validate_name(name: str) -> str:
    """Names are kept URL/import friendly so node ids and routes stay simple."""
    name = (name or "").strip()
    if not _NAME_RE.match(name):
        raise ScriptFsError(
            f"Invalid name '{name}': use letters, digits, dot, dash or underscore"
        )
    return name


def node_id_for(rel: str) -> str:
    stem = rel[:-3] if rel.endswith(".py") else rel
    return "script." + stem.replace("/", ".")


def is_python(path: Path) -> bool:
    return path.suffix == ".py"


def is_editable(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES


# --------------------------------------------------------------------------- #
# Metadata
# --------------------------------------------------------------------------- #


def manifest_scripts() -> dict[str, Any]:
    data = load_script_manifest().get("scripts", {})
    return data if isinstance(data, dict) else {}


def manifest_meta(rel: str, scripts: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Look up manifest metadata by relative path, falling back to bare filename."""
    table = manifest_scripts() if scripts is None else scripts
    meta = table.get(rel)
    if meta is None:
        meta = table.get(Path(rel).name)
    return meta if isinstance(meta, dict) else {}


def save_manifest(scripts: dict[str, Any]) -> None:
    data = load_script_manifest()
    data["scripts"] = scripts
    save_json(SCRIPTS_DIR / MANIFEST_NAME, data)


def set_manifest_entry(rel: str, entry: dict[str, Any]) -> None:
    entry = {k: v for k, v in entry.items() if v not in (None, "", [])}
    if not entry:
        return
    scripts = manifest_scripts()
    scripts[rel] = entry
    save_manifest(scripts)


def drop_manifest_entries(prefixes: list[str]) -> None:
    """Remove manifest entries for deleted files (or everything under a folder)."""
    scripts = manifest_scripts()
    keys = [
        key for key in scripts if any(key == p or key.startswith(f"{p}/") for p in prefixes)
    ]
    if not keys:
        return
    for key in keys:
        scripts.pop(key, None)
    save_manifest(scripts)


def move_manifest_entry(src_rel: str, dst_rel: str, is_dir: bool = False) -> None:
    """Re-key manifest metadata after a rename or move."""
    scripts = manifest_scripts()
    changed = False
    if is_dir:
        prefix = f"{src_rel}/"
        for key in [k for k in scripts if k.startswith(prefix)]:
            scripts[f"{dst_rel}/{key[len(prefix):]}"] = scripts.pop(key)
            changed = True
    else:
        for key in (src_rel, Path(src_rel).name):
            if key in scripts:
                scripts[dst_rel] = scripts.pop(key)
                changed = True
                break
    if changed:
        save_manifest(scripts)


def docstring_summary(path: Path) -> str:
    """First line of the module docstring, so undocumented trees self-describe."""
    if not is_python(path):
        return ""
    try:
        stat = path.stat()
    except OSError:
        return ""
    key = (stat.st_mtime_ns, stat.st_size)
    cached = _doc_cache.get(path)
    if cached and cached[0] == key:
        return cached[1]
    summary = ""
    if stat.st_size <= MAX_EDIT_BYTES:
        try:
            doc = ast.get_docstring(ast.parse(path.read_text(errors="replace")))
            if doc:
                summary = doc.strip().splitlines()[0].strip()
        except (OSError, SyntaxError, ValueError):
            summary = ""
    _doc_cache[path] = (key, summary)
    return summary


# --------------------------------------------------------------------------- #
# Tree
# --------------------------------------------------------------------------- #


def build_tree(state_of: Callable[[str], Optional[str]]) -> dict[str, Any]:
    """Nested tree of robot_scripts/, with node state for each Python file."""
    root = scripts_root()
    scripts = manifest_scripts()

    def entry_for(path: Path) -> dict[str, Any]:
        rel = relative(path)
        if path.is_dir():
            return {
                "type": "dir",
                "name": path.name,
                "path": rel,
                "children": walk(path),
            }
        meta = manifest_meta(rel, scripts)
        item: dict[str, Any] = {
            "type": "file",
            "name": path.name,
            "path": rel,
            "size": path.stat().st_size if path.exists() else 0,
            "editable": is_editable(path),
            "python": is_python(path),
        }
        if is_python(path):
            node_id = node_id_for(rel)
            item.update(
                {
                    "node_id": node_id,
                    "display_name": meta.get("display_name") or path.name,
                    "description": meta.get("description") or docstring_summary(path),
                    "resources": meta.get("resources", []),
                    "registered": rel in scripts or path.name in scripts,
                    "state": state_of(node_id) or "created",
                }
            )
        return item

    def walk(directory: Path) -> list[dict[str, Any]]:
        try:
            children = list(directory.iterdir())
        except OSError:
            return []
        visible = [c for c in children if c.name not in SKIP_NAMES and not c.name.startswith(".")]
        dirs = sorted((c for c in visible if c.is_dir()), key=lambda p: p.name.lower())
        files = sorted((c for c in visible if c.is_file()), key=lambda p: p.name.lower())
        return [entry_for(c) for c in (*dirs, *files)]

    return {
        "type": "dir",
        "name": root.name,
        "path": "",
        "children": walk(root) if root.exists() else [],
    }


def list_python_files() -> list[str]:
    root = scripts_root()
    if not root.exists():
        return []
    out = []
    for path in root.rglob("*.py"):
        parts = path.relative_to(root).parts
        if any(p in SKIP_NAMES or p.startswith(".") for p in parts):
            continue
        out.append(relative(path))
    return sorted(out)


# --------------------------------------------------------------------------- #
# File operations
# --------------------------------------------------------------------------- #


def read_file(rel: str) -> dict[str, Any]:
    path = resolve(rel)
    if path.is_dir():
        raise ScriptFsError("Path is a folder")
    if not is_editable(path):
        raise ScriptFsError(f"{path.suffix or 'This file type'} is not editable")
    if path.stat().st_size > MAX_EDIT_BYTES:
        raise ScriptFsError("File is too large to edit (>1 MB)")
    return {
        "path": relative(path),
        "content": path.read_text(errors="replace"),
        "python": is_python(path),
    }


def write_file(rel: str, content: str) -> Path:
    path = resolve(rel, must_exist=False)
    if path.exists() and path.is_dir():
        raise ScriptFsError("Path is a folder")
    if not is_editable(path):
        raise ScriptFsError(f"{path.suffix or 'This file type'} is not editable")
    if len(content.encode()) > MAX_EDIT_BYTES:
        raise ScriptFsError("Content is too large (>1 MB)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def create_file(rel: str, content: str) -> Path:
    path = resolve(rel, must_exist=False)
    validate_name(path.name)
    if path.exists():
        raise ScriptFsError(f"{relative(path)} already exists", status=409)
    return write_file(rel, content)


def create_folder(rel: str) -> Path:
    path = resolve(rel, must_exist=False)
    validate_name(path.name)
    if path.exists():
        raise ScriptFsError(f"{relative(path)} already exists", status=409)
    path.mkdir(parents=True)
    return path


def rename(src_rel: str, dst_rel: str) -> tuple[Path, Path]:
    src = resolve(src_rel)
    dst = resolve(dst_rel, must_exist=False)
    validate_name(dst.name)
    if dst.exists():
        raise ScriptFsError(f"{relative(dst)} already exists", status=409)
    if src == scripts_root():
        raise ScriptFsError("Cannot rename robot_scripts/")
    if src.is_dir() and src in dst.parents:
        raise ScriptFsError("Cannot move a folder into itself")
    if src.suffix != dst.suffix:
        raise ScriptFsError("Keep the file extension when renaming")
    was_dir = src.is_dir()
    src_norm, dst_norm = relative(src), relative(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    move_manifest_entry(src_norm, dst_norm, is_dir=was_dir)
    return src, dst


def delete(rel: str) -> Path:
    path = resolve(rel)
    if path == scripts_root():
        raise ScriptFsError("Cannot delete robot_scripts/")
    if path.name == MANIFEST_NAME and path.parent == scripts_root():
        raise ScriptFsError("manifest.json is required by DCS")
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    return path


def python_files_under(path: Path) -> list[str]:
    """Relative paths of Python files affected by an operation on ``path``."""
    if path.is_dir():
        return [relative(p) for p in sorted(path.rglob("*.py"))]
    return [relative(path)] if is_python(path) else []


def source_roots() -> list[str]:
    """Checkout folders under robot_scripts/ that hold an importable package.

    A cloned repo such as robot_scripts/mini_bdx_runtime/ contains the real
    mini_bdx_runtime/ package one level down, which is what scripts import.
    """
    root = scripts_root()
    if not root.exists():
        return []
    roots = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name in SKIP_NAMES or child.name.startswith("."):
            continue
        try:
            subdirs = [sub for sub in child.iterdir() if sub.is_dir()]
        except OSError:
            continue
        if any((sub / "__init__.py").exists() for sub in subdirs):
            roots.append(str(child.resolve()))
    return roots


def script_python_path(script_path: Path) -> list[str]:
    """sys.path entries for a spawned script, in priority order.

    Source roots come first so a repo's real package wins over a stray
    __init__.py in the folder above it, then the script's own folder, then
    robot_scripts/ itself (for dcs_sdk and top-level sibling modules).
    """
    entries = [*source_roots(), str(script_path.parent.resolve()), str(scripts_root())]
    seen: list[str] = []
    for entry in entries:
        if entry not in seen:
            seen.append(entry)
    return seen
