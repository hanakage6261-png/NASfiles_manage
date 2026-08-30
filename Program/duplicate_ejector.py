"""Safely eject every present exact duplicate recorded by Phase 1."""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import sqlite3
import stat as stat_module
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from itertools import groupby
from pathlib import Path
from typing import Iterable, Iterator

from local_data_collector import (
    DEFAULT_DB_PATH,
    initialize_database,
    open_database,
    sha256_file,
)


COPY_CHUNK_SIZE = 4 * 1024 * 1024


@dataclass
class EjectionSummary:
    report_path: Path
    duplicate_groups: int = 0
    candidate_files: int = 0
    ejected_files: int = 0
    failed_files: int = 0
    dry_run_files: int = 0


def windows_downloads_directory() -> Path:
    """Resolve Downloads for the current user without embedding a username."""

    if os.name == "nt":
        try:
            import winreg

            key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
            downloads_guid = "{374DE290-123F-4565-9164-39C4925E467B}"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                value, _ = winreg.QueryValueEx(key, downloads_guid)
            return Path(os.path.expandvars(value)).resolve(strict=False)
        except (OSError, ImportError):
            pass
    return (Path.home() / "Downloads").resolve(strict=False)


def default_ejection_directory() -> Path:
    return windows_downloads_directory() / "重複ダウンロード"


def _duplicate_rows(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT f.file_id, f.sha256, f.relative_path, f.size_bytes,
               f.storage_root_id, r.root_path
        FROM files AS f
        JOIN storage_roots AS r ON r.storage_root_id = f.storage_root_id
        WHERE f.status = 'present'
          AND f.sha256 IN (
              SELECT sha256
              FROM files
              WHERE status = 'present'
              GROUP BY sha256
              HAVING COUNT(*) >= 2
          )
        ORDER BY f.sha256, f.storage_root_id, f.relative_path, f.file_id
        """
    ).fetchall()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path_key = os.path.normcase(os.path.normpath(os.fspath(path)))
        root_key = os.path.normcase(os.path.normpath(os.fspath(root)))
        return os.path.commonpath((path_key, root_key)) == root_key
    except ValueError:
        return False


def _is_reparse_or_symlink(path: Path) -> bool:
    path_stat = path.stat(follow_symlinks=False)
    attributes = getattr(path_stat, "st_file_attributes", 0)
    return path.is_symlink() or bool(
        attributes & getattr(stat_module, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _contains_reparse_component(path: Path, root: Path) -> bool:
    """Reject links/junctions introduced anywhere below the registered root."""

    relative = path.relative_to(root)
    current = root
    for component in relative.parts:
        current = current / component
        if _is_reparse_or_symlink(current):
            return True
    return False


def _next_available_path(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    source = Path(filename)
    suffix = source.suffix
    stem = source.name[: -len(suffix)] if suffix else source.name
    counter = 2
    while True:
        candidate = directory / f"{stem}__{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _new_report_path(directory: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = directory / f"duplicate_report_{timestamp}.csv"
    if not base.exists():
        return base
    counter = 2
    while True:
        candidate = directory / f"duplicate_report_{timestamp}_{counter:02d}.csv"
        if not candidate.exists():
            return candidate
        counter += 1


def _exclusive_copy(source: Path, destination: Path) -> None:
    """Copy without ever opening an existing destination for overwrite."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
    try:
        with open(source, "rb") as source_file, os.fdopen(descriptor, "wb") as target_file:
            descriptor = -1
            shutil.copyfileobj(source_file, target_file, length=COPY_CHUNK_SIZE)
            target_file.flush()
            os.fsync(target_file.fileno())
        shutil.copystat(source, destination, follow_symlinks=False)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _safe_remove_created_copy(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        # Preserve the original regardless; a partial copy can be reviewed and
        # removed manually if cleanup itself fails.
        pass


def _csv_row(
    group_name: str,
    row: sqlite3.Row,
    source: Path,
    destination: Path | None,
    result: str,
) -> dict[str, str | int]:
    return {
        "duplicate_group": group_name,
        "file_id": str(row["file_id"]),
        "sha256": str(row["sha256"]),
        "original_path": os.fspath(source),
        "ejected_path": os.fspath(destination) if destination is not None else "",
        "size_bytes": int(row["size_bytes"]),
        "result": result,
    }


def _process_one(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    group_name: str,
    sequence: int,
    ejection_directory: Path,
    dry_run: bool,
) -> tuple[dict[str, str | int], str]:
    # Use lexical absolute paths here. Resolving would follow a symlink before
    # the safety check and could turn a recorded path into a different target.
    root = Path(os.path.abspath(str(row["root_path"])))
    source = Path(os.path.abspath(os.path.join(root, str(row["relative_path"]))))
    destination: Path | None = None

    if not _is_within(source, root):
        return _csv_row(group_name, row, source, None, "unsafe_path"), "failed"
    if not source.exists() or not source.is_file():
        return _csv_row(group_name, row, source, None, "source_missing"), "failed"
    try:
        if _contains_reparse_component(source, root):
            return _csv_row(group_name, row, source, None, "reparse_point_refused"), "failed"
    except OSError:
        return _csv_row(group_name, row, source, None, "source_stat_failed"), "failed"

    target_name = f"{group_name}_{sequence:02d}__{source.name}"
    destination = _next_available_path(ejection_directory, target_name)
    if dry_run:
        return _csv_row(group_name, row, source, destination, "dry_run"), "dry_run"

    expected_size = int(row["size_bytes"])
    expected_hash = str(row["sha256"]).lower()
    try:
        if source.stat().st_size != expected_size or sha256_file(source) != expected_hash:
            return _csv_row(group_name, row, source, None, "source_changed"), "failed"

        _exclusive_copy(source, destination)
        if destination.stat().st_size != expected_size:
            _safe_remove_created_copy(destination)
            return _csv_row(group_name, row, source, destination, "copy_size_mismatch"), "failed"
        if sha256_file(destination) != expected_hash:
            _safe_remove_created_copy(destination)
            return _csv_row(group_name, row, source, destination, "copy_hash_mismatch"), "failed"

        # Recheck the source immediately before deletion so a file changed
        # concurrently after copying is never discarded.
        if source.stat().st_size != expected_size or sha256_file(source) != expected_hash:
            _safe_remove_created_copy(destination)
            return _csv_row(group_name, row, source, destination, "source_changed"), "failed"

        source.unlink()
    except FileExistsError:
        return _csv_row(group_name, row, source, destination, "destination_collision"), "failed"
    except OSError as error:
        _safe_remove_created_copy(destination)
        result = f"filesystem_error:{type(error).__name__}"
        return _csv_row(group_name, row, source, destination, result), "failed"

    try:
        cursor = connection.execute(
            "DELETE FROM files WHERE file_id = ? AND sha256 = ? AND status = 'present'",
            (row["file_id"], row["sha256"]),
        )
        if cursor.rowcount != 1:
            connection.rollback()
            return _csv_row(group_name, row, source, destination, "db_row_not_deleted"), "failed"
        connection.commit()
    except sqlite3.Error as error:
        connection.rollback()
        result = f"db_error:{type(error).__name__}"
        return _csv_row(group_name, row, source, destination, result), "failed"

    return _csv_row(group_name, row, source, destination, "ejected"), "ejected"


def eject_duplicates(
    db_path: str | os.PathLike[str] = DEFAULT_DB_PATH,
    ejection_directory: str | os.PathLike[str] | None = None,
    dry_run: bool = False,
) -> EjectionSummary:
    """Eject all files in every present duplicate group; no keeper is chosen."""

    destination_root = (
        Path(ejection_directory).resolve(strict=False)
        if ejection_directory is not None
        else default_ejection_directory()
    )
    destination_root.mkdir(parents=True, exist_ok=True)
    report_path = _new_report_path(destination_root)
    summary = EjectionSummary(report_path=report_path)
    fieldnames = [
        "duplicate_group",
        "file_id",
        "sha256",
        "original_path",
        "ejected_path",
        "size_bytes",
        "result",
    ]

    with closing(open_database(db_path)) as connection:
        initialize_database(connection)
        rows = _duplicate_rows(connection)
        with open(report_path, "x", encoding="utf-8-sig", newline="") as report_file:
            writer = csv.DictWriter(report_file, fieldnames=fieldnames)
            writer.writeheader()
            for group_index, (_, grouped_rows) in enumerate(
                groupby(rows, key=lambda item: item["sha256"]), start=1
            ):
                summary.duplicate_groups += 1
                group_name = f"DUP{group_index:06d}"
                for sequence, row in enumerate(grouped_rows, start=1):
                    summary.candidate_files += 1
                    report_row, outcome = _process_one(
                        connection,
                        row,
                        group_name,
                        sequence,
                        destination_root,
                        dry_run,
                    )
                    writer.writerow(report_row)
                    report_file.flush()
                    if outcome == "ejected":
                        summary.ejected_files += 1
                    elif outcome == "dry_run":
                        summary.dry_run_files += 1
                    else:
                        summary.failed_files += 1
    return summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Eject every present exact duplicate. No file is automatically kept in place."
        )
    )
    parser.add_argument("--db", default=os.fspath(DEFAULT_DB_PATH), help="SQLite database path")
    parser.add_argument(
        "--output",
        help="Override the default current-user Downloads/重複ダウンロード directory",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Write a report without copying or deleting files",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    summary = eject_duplicates(args.db, args.output, args.dry_run)
    print(f"Report: {summary.report_path}")
    print(f"Duplicate groups: {summary.duplicate_groups}")
    print(f"Candidate files: {summary.candidate_files}")
    print(f"Ejected files: {summary.ejected_files}")
    print(f"Failed files: {summary.failed_files}")
    if args.dry_run:
        print(f"Dry-run files: {summary.dry_run_files}")
    return 0 if summary.failed_files == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
