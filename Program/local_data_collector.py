"""Phase 1 local media collector for NASfiles_manage.

The collector inventories supported media without modifying source files. It
stores paths relative to a configurable storage root and can therefore be used
with a temporary test directory, a future ``E:\\`` drive, or a NAS share.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sqlite3
import stat as stat_module
import sys
import uuid
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from excluded_folder_loader import load_excluded_folders, normalize_path


PROGRAM_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PROGRAM_DIR.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "LOCAL_database" / "local_files.db"
DEFAULT_LOG_PATH = PROGRAM_DIR / "logs" / "local_data_collector.log"
HASH_CHUNK_SIZE = 4 * 1024 * 1024
SYSTEM_EXCLUDED_DIRECTORY_NAMES = frozenset(
    {"$recycle.bin", "system volume information"}
)

INITIAL_FILE_TYPES: dict[str, str] = {
    # Images
    ".apng": "image",
    ".arw": "image",
    ".avif": "image",
    ".bmp": "image",
    ".cr2": "image",
    ".cr3": "image",
    ".dng": "image",
    ".gif": "image",
    ".heic": "image",
    ".heif": "image",
    ".ico": "image",
    ".jfif": "image",
    ".jpeg": "image",
    ".jpg": "image",
    ".jxl": "image",
    ".nef": "image",
    ".orf": "image",
    ".png": "image",
    ".raf": "image",
    ".raw": "image",
    ".rw2": "image",
    ".svg": "image",
    ".tif": "image",
    ".tiff": "image",
    ".webp": "image",
    # Video
    ".3gp": "video",
    ".asf": "video",
    ".avi": "video",
    ".divx": "video",
    ".f4v": "video",
    ".flv": "video",
    ".m2ts": "video",
    ".m2v": "video",
    ".m4v": "video",
    ".mkv": "video",
    ".mov": "video",
    ".mp4": "video",
    ".mpeg": "video",
    ".mpg": "video",
    ".mts": "video",
    ".ogv": "video",
    ".rm": "video",
    ".rmvb": "video",
    ".ts": "video",
    ".vob": "video",
    ".webm": "video",
    ".wmv": "video",
    # Audio
    ".aac": "audio",
    ".aif": "audio",
    ".aiff": "audio",
    ".alac": "audio",
    ".amr": "audio",
    ".ape": "audio",
    ".au": "audio",
    ".caf": "audio",
    ".flac": "audio",
    ".m4a": "audio",
    ".mka": "audio",
    ".mid": "audio",
    ".midi": "audio",
    ".mp3": "audio",
    ".oga": "audio",
    ".ogg": "audio",
    ".opus": "audio",
    ".wav": "audio",
    ".wma": "audio",
}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS files (
    file_id TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL,
    extension TEXT NOT NULL,
    storage_root_id INTEGER NOT NULL,
    relative_path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    modified_at TEXT,
    status TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS folder_units (
    folder_id TEXT PRIMARY KEY,
    storage_root_id INTEGER NOT NULL,
    relative_path TEXT NOT NULL,
    modified_at TEXT,
    status TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS file_types (
    extension TEXT PRIMARY KEY,
    file_type TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS storage_roots (
    storage_root_id INTEGER PRIMARY KEY,
    name TEXT,
    root_path TEXT NOT NULL UNIQUE,
    active INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS scan_runs (
    scan_id INTEGER PRIMARY KEY,
    storage_root_id INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    files_seen INTEGER,
    new_files INTEGER,
    missing_files INTEGER,
    duplicate_files INTEGER,
    folder_units_seen INTEGER,
    new_folder_units INTEGER,
    missing_folder_units INTEGER,
    error_count INTEGER
);

CREATE INDEX IF NOT EXISTS idx_files_root_path
    ON files(storage_root_id, relative_path);
CREATE INDEX IF NOT EXISTS idx_files_hash_status
    ON files(sha256, status);
CREATE INDEX IF NOT EXISTS idx_folder_units_root_path
    ON folder_units(storage_root_id, relative_path);
"""


@dataclass
class ScanResult:
    scan_id: int
    storage_root_id: int
    status: str = "running"
    files_seen: int = 0
    new_files: int = 0
    missing_files: int = 0
    duplicate_files: int = 0
    folder_units_seen: int = 0
    new_folder_units: int = 0
    missing_folder_units: int = 0
    error_count: int = 0


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def timestamp_from_ns(timestamp_ns: int) -> str:
    seconds, nanoseconds = divmod(timestamp_ns, 1_000_000_000)
    base = datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    return f"{base}.{nanoseconds:09d}+00:00"


def sha256_file(path: str | os.PathLike[str], chunk_size: int = HASH_CHUNK_SIZE) -> str:
    """Hash a file in bounded chunks so large media is not loaded into memory."""

    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def open_database(db_path: str | os.PathLike[str] = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA_SQL)
    connection.executemany(
        "INSERT INTO file_types(extension, file_type) VALUES (?, ?) "
        "ON CONFLICT(extension) DO NOTHING",
        sorted(INITIAL_FILE_TYPES.items()),
    )
    connection.commit()


def register_storage_root(
    connection: sqlite3.Connection,
    root: Path,
    name: str | None,
) -> int:
    root_text = os.fspath(root)
    row = connection.execute(
        "SELECT storage_root_id FROM storage_roots WHERE root_path = ?", (root_text,)
    ).fetchone()
    if row is not None:
        connection.execute(
            "UPDATE storage_roots SET name = COALESCE(?, name), active = 1 "
            "WHERE storage_root_id = ?",
            (name, row["storage_root_id"]),
        )
        connection.commit()
        return int(row["storage_root_id"])

    cursor = connection.execute(
        "INSERT INTO storage_roots(name, root_path, active) VALUES (?, ?, 1)",
        (name, root_text),
    )
    connection.commit()
    return int(cursor.lastrowid)


def _start_scan(connection: sqlite3.Connection, storage_root_id: int) -> int:
    cursor = connection.execute(
        "INSERT INTO scan_runs(storage_root_id, started_at, status, error_count) "
        "VALUES (?, ?, 'running', 0)",
        (storage_root_id, utc_now()),
    )
    connection.commit()
    return int(cursor.lastrowid)


def _finish_scan(connection: sqlite3.Connection, result: ScanResult) -> None:
    connection.execute(
        """
        UPDATE scan_runs
        SET finished_at = ?, status = ?, files_seen = ?, new_files = ?,
            missing_files = ?, duplicate_files = ?, folder_units_seen = ?,
            new_folder_units = ?, missing_folder_units = ?, error_count = ?
        WHERE scan_id = ?
        """,
        (
            utc_now(),
            result.status,
            result.files_seen,
            result.new_files,
            result.missing_files,
            result.duplicate_files,
            result.folder_units_seen,
            result.new_folder_units,
            result.missing_folder_units,
            result.error_count,
            result.scan_id,
        ),
    )
    connection.commit()


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.normpath(os.fspath(path)))


def _relative_path(path: Path, root: Path) -> str:
    return os.path.normpath(os.path.relpath(path, root))


def _is_reparse_point(entry: os.DirEntry[str]) -> bool:
    try:
        if entry.is_symlink():
            return True
        entry_stat = entry.stat(follow_symlinks=False)
        attributes = getattr(entry_stat, "st_file_attributes", 0)
        return bool(attributes & getattr(stat_module, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    except OSError:
        raise


def _directory_identity(path: Path) -> tuple[int, int] | tuple[str, str]:
    path_stat = path.stat(follow_symlinks=False)
    if path_stat.st_ino:
        return path_stat.st_dev, path_stat.st_ino
    return "path", _path_key(path)


def _under_prefix(relative_path: str, prefix: str) -> bool:
    if prefix == os.curdir:
        return True
    path_key = os.path.normcase(os.path.normpath(relative_path))
    prefix_key = os.path.normcase(os.path.normpath(prefix))
    return path_key == prefix_key or path_key.startswith(prefix_key + os.sep)


def _active_extensions(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row["extension"]).lower()
        for row in connection.execute("SELECT extension FROM file_types")
    }


def _record_folder_unit(
    connection: sqlite3.Connection,
    storage_root_id: int,
    root: Path,
    folder: Path,
    seen_folder_ids: set[str],
) -> bool:
    relative = _relative_path(folder, root)
    folder_stat = folder.stat(follow_symlinks=False)
    modified_at = timestamp_from_ns(folder_stat.st_mtime_ns)
    now = utc_now()
    row = connection.execute(
        "SELECT folder_id FROM folder_units "
        "WHERE storage_root_id = ? AND relative_path = ? ORDER BY first_seen_at LIMIT 1",
        (storage_root_id, relative),
    ).fetchone()
    is_new = row is None
    if is_new:
        folder_id = str(uuid.uuid4())
        connection.execute(
            """
            INSERT INTO folder_units(
                folder_id, storage_root_id, relative_path, modified_at,
                status, first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, 'present', ?, ?)
            """,
            (folder_id, storage_root_id, relative, modified_at, now, now),
        )
    else:
        folder_id = str(row["folder_id"])
        connection.execute(
            "UPDATE folder_units SET modified_at = ?, status = 'present', last_seen_at = ? "
            "WHERE folder_id = ?",
            (modified_at, now, folder_id),
        )
    connection.commit()
    seen_folder_ids.add(folder_id)
    return is_new


def _missing_move_candidates(
    connection: sqlite3.Connection,
    storage_root_id: int,
    root: Path,
    sha256: str,
    size_bytes: int,
    seen_file_ids: set[str],
) -> list[sqlite3.Row]:
    rows = connection.execute(
        "SELECT file_id, relative_path FROM files "
        "WHERE storage_root_id = ? AND sha256 = ? AND size_bytes = ?",
        (storage_root_id, sha256, size_bytes),
    ).fetchall()
    candidates: list[sqlite3.Row] = []
    for row in rows:
        if row["file_id"] in seen_file_ids:
            continue
        old_path = root / str(row["relative_path"])
        if not old_path.exists():
            candidates.append(row)
    return candidates


def _record_file(
    connection: sqlite3.Connection,
    storage_root_id: int,
    root: Path,
    path: Path,
    extension: str,
    seen_file_ids: set[str],
) -> bool:
    relative = _relative_path(path, root)
    before = path.stat(follow_symlinks=False)
    size_bytes = before.st_size
    modified_at = timestamp_from_ns(before.st_mtime_ns)
    now = utc_now()
    existing = connection.execute(
        "SELECT * FROM files WHERE storage_root_id = ? AND relative_path = ? "
        "ORDER BY first_seen_at LIMIT 1",
        (storage_root_id, relative),
    ).fetchone()

    if (
        existing is not None
        and int(existing["size_bytes"]) == size_bytes
        and existing["modified_at"] == modified_at
    ):
        file_id = str(existing["file_id"])
        connection.execute(
            "UPDATE files SET extension = ?, status = 'present', last_seen_at = ? "
            "WHERE file_id = ?",
            (extension, now, file_id),
        )
        connection.commit()
        seen_file_ids.add(file_id)
        return False

    digest = sha256_file(path)
    after = path.stat(follow_symlinks=False)
    if after.st_size != size_bytes or after.st_mtime_ns != before.st_mtime_ns:
        raise OSError(f"File changed while it was being hashed: {path}")

    if existing is not None:
        file_id = str(existing["file_id"])
        connection.execute(
            """
            UPDATE files
            SET sha256 = ?, extension = ?, size_bytes = ?, modified_at = ?,
                status = 'present', last_seen_at = ?
            WHERE file_id = ?
            """,
            (digest, extension, size_bytes, modified_at, now, file_id),
        )
        connection.commit()
        seen_file_ids.add(file_id)
        return False

    candidates = _missing_move_candidates(
        connection, storage_root_id, root, digest, size_bytes, seen_file_ids
    )
    if len(candidates) == 1:
        file_id = str(candidates[0]["file_id"])
        connection.execute(
            """
            UPDATE files
            SET relative_path = ?, extension = ?, size_bytes = ?, modified_at = ?,
                status = 'present', last_seen_at = ?
            WHERE file_id = ?
            """,
            (relative, extension, size_bytes, modified_at, now, file_id),
        )
        connection.commit()
        seen_file_ids.add(file_id)
        return False

    file_id = str(uuid.uuid4())
    connection.execute(
        """
        INSERT INTO files(
            file_id, sha256, extension, storage_root_id, relative_path,
            size_bytes, modified_at, status, first_seen_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'present', ?, ?)
        """,
        (
            file_id,
            digest,
            extension,
            storage_root_id,
            relative,
            size_bytes,
            modified_at,
            now,
            now,
        ),
    )
    connection.commit()
    seen_file_ids.add(file_id)
    return True


def _mark_missing(
    connection: sqlite3.Connection,
    table: str,
    id_column: str,
    storage_root_id: int,
    seen_ids: set[str],
    protected_prefixes: Sequence[str],
    protected_paths: set[str],
) -> int:
    rows = connection.execute(
        f"SELECT {id_column}, relative_path FROM {table} "
        "WHERE storage_root_id = ? AND status = 'present'",
        (storage_root_id,),
    ).fetchall()
    missing_count = 0
    for row in rows:
        record_id = str(row[id_column])
        relative = str(row["relative_path"])
        if record_id in seen_ids:
            continue
        if relative in protected_paths:
            continue
        if any(_under_prefix(relative, prefix) for prefix in protected_prefixes):
            continue
        connection.execute(
            f"UPDATE {table} SET status = 'missing' WHERE {id_column} = ?",
            (record_id,),
        )
        connection.commit()
        missing_count += 1
    return missing_count


def _count_duplicate_files(connection: sqlite3.Connection, storage_root_id: int) -> int:
    row = connection.execute(
        """
        SELECT COALESCE(SUM(group_count), 0) AS duplicate_count
        FROM (
            SELECT COUNT(*) AS group_count
            FROM files
            WHERE storage_root_id = ? AND status = 'present'
            GROUP BY sha256
            HAVING COUNT(*) >= 2
        )
        """,
        (storage_root_id,),
    ).fetchone()
    return int(row["duplicate_count"])


def scan_storage(
    storage_root: str | os.PathLike[str],
    db_path: str | os.PathLike[str] = DEFAULT_DB_PATH,
    root_name: str | None = None,
    excluded_folders: Sequence[str | os.PathLike[str]] | None = None,
    logger: logging.Logger | None = None,
) -> ScanResult:
    """Scan one storage root and return its persisted scan summary."""

    log = logger or logging.getLogger("nasfiles_manage.collector")
    root = normalize_path(storage_root)
    with closing(open_database(db_path)) as connection:
        initialize_database(connection)
        storage_root_id = register_storage_root(connection, root, root_name)
        scan_id = _start_scan(connection, storage_root_id)
        result = ScanResult(scan_id=scan_id, storage_root_id=storage_root_id)

        if not root.exists() or not root.is_dir():
            result.status = "failed"
            result.error_count = 1
            log.error("Storage root is unavailable or is not a directory: %s", root)
            _finish_scan(connection, result)
            return result

        excluded_paths = load_excluded_folders(
            root,
            configured=excluded_folders,
            warning_handler=lambda message: log.warning("Excluded-folder setting: %s", message),
        )
        excluded_keys = {_path_key(path) for path in excluded_paths}
        extensions = _active_extensions(connection)
        seen_file_ids: set[str] = set()
        seen_folder_ids: set[str] = set()
        inaccessible_prefixes: list[str] = []
        unreadable_file_paths: set[str] = set()
        visited_directories: set[tuple[int, int] | tuple[str, str]] = set()
        root_enumeration_failed = False

        try:
            stack = [root]
            while stack:
                directory = stack.pop()
                relative_directory = _relative_path(directory, root)
                try:
                    identity = _directory_identity(directory)
                    if identity in visited_directories:
                        log.warning("Directory loop/revisit skipped: %s", directory)
                        continue
                    visited_directories.add(identity)
                    with os.scandir(directory) as iterator:
                        entries = sorted(iterator, key=lambda item: item.name.casefold())
                except OSError as error:
                    result.error_count += 1
                    inaccessible_prefixes.append(relative_directory)
                    log.error("Cannot enumerate directory %s: %s", directory, error)
                    if directory == root:
                        root_enumeration_failed = True
                    continue

                for entry in entries:
                    path = Path(entry.path)
                    relative = _relative_path(path, root)
                    try:
                        is_reparse = _is_reparse_point(entry)
                        is_directory = entry.is_dir(follow_symlinks=False)

                        if is_directory and entry.name.casefold() in SYSTEM_EXCLUDED_DIRECTORY_NAMES:
                            log.info("System directory skipped: %s", path)
                            continue

                        # Explicit exclusions are registered before reparse-point
                        # handling because their contents are never followed.
                        if _path_key(path) in excluded_keys and (
                            is_directory or entry.is_dir(follow_symlinks=True)
                        ):
                            if _record_folder_unit(
                                connection,
                                storage_root_id,
                                root,
                                path,
                                seen_folder_ids,
                            ):
                                result.new_folder_units += 1
                            result.folder_units_seen += 1
                            continue

                        if is_reparse:
                            log.warning("Symbolic link/reparse point skipped: %s", path)
                            continue

                        if is_directory:
                            stack.append(path)
                            continue

                        if not entry.is_file(follow_symlinks=False):
                            continue
                        extension = path.suffix.lower()
                        if extension not in extensions:
                            continue
                        if _record_file(
                            connection,
                            storage_root_id,
                            root,
                            path,
                            extension,
                            seen_file_ids,
                        ):
                            result.new_files += 1
                        result.files_seen += 1
                    except OSError as error:
                        result.error_count += 1
                        unreadable_file_paths.add(relative)
                        # Conservatively protect both this path and any records
                        # below it in case the failed entry was a directory.
                        inaccessible_prefixes.append(relative)
                        log.error("Cannot process %s: %s", path, error)
                    except sqlite3.Error:
                        # A database failure is not safely recoverable as a
                        # per-file filesystem error.
                        raise

            result.missing_files = _mark_missing(
                connection,
                "files",
                "file_id",
                storage_root_id,
                seen_file_ids,
                inaccessible_prefixes,
                unreadable_file_paths,
            )
            result.missing_folder_units = _mark_missing(
                connection,
                "folder_units",
                "folder_id",
                storage_root_id,
                seen_folder_ids,
                inaccessible_prefixes,
                set(),
            )
            result.duplicate_files = _count_duplicate_files(connection, storage_root_id)
            result.status = "failed" if root_enumeration_failed else "success"
        except KeyboardInterrupt:
            result.status = "interrupted"
            result.error_count += 1
            log.warning("Scan interrupted by user")
            _finish_scan(connection, result)
            raise
        except Exception as error:
            result.status = "failed"
            result.error_count += 1
            log.exception("Scan failed: %s", error)

        _finish_scan(connection, result)
        return result


def configure_logging(log_path: str | os.PathLike[str] = DEFAULT_LOG_PATH) -> logging.Logger:
    logger = logging.getLogger("nasfiles_manage.collector")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    logger.addHandler(stream)
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect a Phase 1 local media inventory.")
    parser.add_argument("--root", required=True, help=r"Storage root, e.g. E:\\ or \\server\share")
    parser.add_argument("--name", help="Friendly storage-root name, e.g. external_hdd")
    parser.add_argument("--db", default=os.fspath(DEFAULT_DB_PATH), help="SQLite database path")
    parser.add_argument("--log", default=os.fspath(DEFAULT_LOG_PATH), help="Log file path")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logger = configure_logging(args.log)
    result = scan_storage(
        storage_root=args.root,
        db_path=args.db,
        root_name=args.name,
        logger=logger,
    )
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    return 0 if result.status == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
