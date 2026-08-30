"""User-editable excluded-folder configuration for NASfiles_manage Phase 1.

An excluded folder is still managed as one ``folder_units`` record, but its
contents are never enumerated or hashed by the collector.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Callable, Iterable, Sequence


# =============================================================================
# USER SETTINGS - add absolute folder paths only inside this block.
# =============================================================================
EXCLUDED_FOLDERS: list[str] = [
    # r"E:\Games\GameA",
    # r"E:\Games\GameB",
]
# =============================================================================
# END USER SETTINGS - no changes below this line are normally necessary.
# =============================================================================


WarningHandler = Callable[[str], None]


def normalize_path(path: str | os.PathLike[str]) -> Path:
    """Return a normalized absolute path without requiring it to exist."""

    expanded = os.path.expandvars(os.path.expanduser(os.fspath(path)))
    return Path(os.path.abspath(expanded)).resolve(strict=False)


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.normpath(os.fspath(path)))


def _is_within(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath((_path_key(path), _path_key(root))) == _path_key(root)
    except ValueError:
        # Different Windows drives, for example.
        return False


def validate_excluded_folders(
    storage_root: str | os.PathLike[str],
    configured: Sequence[str | os.PathLike[str]] | None = None,
) -> tuple[list[Path], list[str]]:
    """Validate and normalize configured excluded folders.

    Missing paths remain valid so a temporarily disconnected or not-yet-created
    folder can stay in the user's settings. Invalid, duplicate, root-equal, and
    outside-root entries are ignored.
    """

    root = normalize_path(storage_root)
    entries = EXCLUDED_FOLDERS if configured is None else configured
    valid: list[Path] = []
    warnings: list[str] = []
    seen: set[str] = set()

    for index, raw_path in enumerate(entries, start=1):
        raw_text = os.fspath(raw_path).strip() if raw_path is not None else ""
        if not raw_text:
            warnings.append(f"Entry {index}: empty excluded-folder path was ignored.")
            continue

        path = normalize_path(raw_text)
        key = _path_key(path)
        if key in seen:
            warnings.append(f"Entry {index}: duplicate excluded-folder path was ignored: {path}")
            continue
        if key == _path_key(root):
            warnings.append(
                f"Entry {index}: the storage root itself cannot be an excluded folder and was ignored: {path}"
            )
            continue
        if not _is_within(path, root):
            warnings.append(
                f"Entry {index}: path is outside the storage root and was ignored: {path}"
            )
            continue

        seen.add(key)
        valid.append(path)
        if not path.exists():
            warnings.append(f"Entry {index}: excluded folder does not currently exist: {path}")
        elif not path.is_dir():
            warnings.append(f"Entry {index}: excluded-folder path is not a directory: {path}")

    for parent_index, parent in enumerate(valid):
        for child in valid[parent_index + 1 :]:
            if _is_within(child, parent) or _is_within(parent, child):
                ancestor, descendant = (
                    (parent, child) if _is_within(child, parent) else (child, parent)
                )
                warnings.append(
                    "Both a parent and its child are excluded; the child entry is redundant "
                    f"because traversal stops at the parent: {ancestor} -> {descendant}"
                )

    return valid, warnings


def load_excluded_folders(
    storage_root: str | os.PathLike[str],
    configured: Sequence[str | os.PathLike[str]] | None = None,
    warning_handler: WarningHandler | None = None,
) -> list[Path]:
    """Return validated paths and optionally emit every validation warning."""

    valid, warnings = validate_excluded_folders(storage_root, configured)
    if warning_handler is not None:
        for warning in warnings:
            warning_handler(warning)
    return valid


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate the EXCLUDED_FOLDERS settings for one storage root."
    )
    parser.add_argument("--root", required=True, help="Storage root, for example E:\\")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    valid, warnings = validate_excluded_folders(args.root)
    print(f"Storage root: {normalize_path(args.root)}")
    if valid:
        for path in valid:
            state = "exists" if path.is_dir() else "missing/not a directory"
            print(f"OK [{state}]: {path}")
    else:
        print("No valid excluded folders are configured.")
    for warning in warnings:
        print(f"WARNING: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
