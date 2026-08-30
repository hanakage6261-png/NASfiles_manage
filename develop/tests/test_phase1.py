from __future__ import annotations

import csv
import hashlib
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid
from contextlib import closing
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROGRAM_DIR = PROJECT_ROOT / "Program"
sys.path.insert(0, os.fspath(PROGRAM_DIR))

from duplicate_ejector import eject_duplicates  # noqa: E402
from excluded_folder_loader import validate_excluded_folders  # noqa: E402
from local_data_collector import (  # noqa: E402
    initialize_database,
    open_database,
    scan_storage,
)


class Phase1Tests(unittest.TestCase):
    def setUp(self) -> None:
        # Keep test data under the workspace. Some managed Windows environments
        # intentionally deny child creation in the process-wide TEMP folder.
        self.temporary = tempfile.TemporaryDirectory(
            prefix="nasfiles_phase1_", dir=Path(__file__).resolve().parent
        )
        self.base = Path(self.temporary.name)
        self.root = self.base / "storage"
        self.root.mkdir()
        self.db_path = self.base / "database" / "local_files.db"
        self.logger = logging.getLogger(f"phase1-test-{id(self)}")
        self.logger.handlers.clear()
        self.logger.addHandler(logging.NullHandler())
        self.logger.propagate = False

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_file(self, relative: str, content: bytes) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def rows(self, sql: str, parameters: tuple[object, ...] = ()) -> list[sqlite3.Row]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            return connection.execute(sql, parameters).fetchall()
        finally:
            connection.close()

    def scan(self, excluded: list[Path | str] | None = None):
        return scan_storage(
            self.root,
            self.db_path,
            root_name="test_storage",
            excluded_folders=[] if excluded is None else excluded,
            logger=self.logger,
        )

    def test_inventory_schema_and_excluded_folder_lifecycle(self) -> None:
        expected_media = {
            "photo.JPG": b"small image payload",
            "clips/movie.mp4": b"small video payload",
            "music/song.MP3": b"small audio payload",
        }
        for relative, content in expected_media.items():
            self.write_file(relative, content)
        self.write_file("tool.exe", b"not media")
        self.write_file("notes.md", b"not media")

        game = self.root / "Games" / "GameA"
        for relative in ("logo.png", "BGM/title.ogg", "movies/intro.mp4"):
            path = game / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"excluded payload")

        self.write_file("$RECYCLE.BIN/recycled.jpg", b"system excluded")
        self.write_file("System Volume Information/index.mp3", b"system excluded")

        before = (self.root / "photo.JPG").read_bytes()
        first = self.scan([game])
        self.assertEqual("success", first.status)
        self.assertEqual(3, first.files_seen)
        self.assertEqual(3, first.new_files)
        self.assertEqual(1, first.folder_units_seen)
        self.assertEqual(1, first.new_folder_units)

        files = self.rows("SELECT * FROM files ORDER BY relative_path")
        self.assertEqual(
            {os.path.normpath(path) for path in expected_media},
            {row["relative_path"] for row in files},
        )
        self.assertEqual({".jpg", ".mp4", ".mp3"}, {row["extension"] for row in files})
        self.assertEqual(before, (self.root / "photo.JPG").read_bytes())
        for row in files:
            self.assertEqual(4, uuid.UUID(row["file_id"]).version)
            self.assertEqual(64, len(row["sha256"]))
            self.assertEqual(row["sha256"], row["sha256"].lower())

        columns = {
            row["name"] for row in self.rows("PRAGMA table_info(files)")
        }
        self.assertNotIn("media_type", columns)
        self.assertNotIn("filename", columns)
        self.assertNotIn("source_url", columns)
        self.assertEqual(
            {"files", "folder_units", "file_types", "storage_roots", "scan_runs"},
            {
                row["name"]
                for row in self.rows(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                )
            },
        )

        unit = self.rows("SELECT * FROM folder_units")[0]
        original_folder_id = unit["folder_id"]
        self.assertEqual(os.path.normpath("Games/GameA"), unit["relative_path"])
        self.assertEqual("present", unit["status"])

        # An unchanged rescan must use path/size/mtime and avoid rehashing.
        with patch("local_data_collector.sha256_file", side_effect=AssertionError("rehash")):
            second = self.scan([game])
        self.assertEqual(0, second.new_files)
        self.assertEqual(
            original_folder_id,
            self.rows("SELECT folder_id FROM folder_units")[0]["folder_id"],
        )

        shutil.rmtree(game)
        third = self.scan([game])
        self.assertEqual(1, third.missing_folder_units)
        missing_unit = self.rows("SELECT * FROM folder_units")[0]
        self.assertEqual(original_folder_id, missing_unit["folder_id"])
        self.assertEqual("missing", missing_unit["status"])

    def test_excluded_settings_warn_for_invalid_duplicate_missing_and_nesting(self) -> None:
        parent = self.root / "Packages"
        child = parent / "Child"
        child.mkdir(parents=True)
        missing = self.root / "NotCreated"
        outside = self.base / "outside"
        outside.mkdir()
        valid, warnings = validate_excluded_folders(
            self.root,
            ["", self.root, parent, child, parent, missing, outside],
        )
        self.assertEqual([parent.resolve(), child.resolve(), missing.resolve()], valid)
        warning_text = "\n".join(warnings)
        self.assertIn("empty", warning_text)
        self.assertIn("storage root itself", warning_text)
        self.assertIn("duplicate", warning_text)
        self.assertIn("does not currently exist", warning_text)
        self.assertIn("outside", warning_text)
        self.assertIn("parent and its child", warning_text)

    def test_file_move_keeps_uuid_and_missing_is_retained(self) -> None:
        old_path = self.write_file("old-name.jpg", b"move me")
        self.scan()
        original = self.rows("SELECT file_id, sha256 FROM files")[0]

        new_path = self.root / "renamed" / "new-name.jpg"
        new_path.parent.mkdir()
        old_path.replace(new_path)
        moved = self.scan()
        self.assertEqual("success", moved.status)
        self.assertEqual(0, moved.new_files)
        record = self.rows("SELECT * FROM files")[0]
        self.assertEqual(original["file_id"], record["file_id"])
        self.assertEqual(os.path.normpath("renamed/new-name.jpg"), record["relative_path"])
        self.assertEqual("present", record["status"])

        new_path.unlink()
        missing = self.scan()
        self.assertEqual(1, missing.missing_files)
        record = self.rows("SELECT * FROM files")[0]
        self.assertEqual(original["file_id"], record["file_id"])
        self.assertEqual("missing", record["status"])

    def test_unavailable_root_fails_without_marking_everything_missing(self) -> None:
        self.write_file("keep-status.jpg", b"present before disconnect")
        self.scan()
        moved_root = self.base / "temporarily-disconnected"
        self.root.replace(moved_root)
        try:
            result = scan_storage(
                self.root,
                self.db_path,
                excluded_folders=[],
                logger=self.logger,
            )
            self.assertEqual("failed", result.status)
            self.assertEqual("present", self.rows("SELECT status FROM files")[0]["status"])
            self.assertEqual(
                "failed",
                self.rows("SELECT status FROM scan_runs ORDER BY scan_id DESC LIMIT 1")[0]["status"],
            )
        finally:
            moved_root.replace(self.root)

    def test_ambiguous_move_does_not_guess_between_identical_missing_records(self) -> None:
        payload = b"same bytes"
        first = self.write_file("first.jpg", payload)
        second = self.write_file("second.jpg", payload)
        self.scan()
        old_ids = {row["file_id"] for row in self.rows("SELECT file_id FROM files")}
        first.unlink()
        second.unlink()
        self.write_file("unknown.jpg", payload)

        result = self.scan()
        self.assertEqual(1, result.new_files)
        rows = self.rows("SELECT file_id, relative_path, status FROM files")
        new_row = next(row for row in rows if row["relative_path"] == "unknown.jpg")
        self.assertNotIn(new_row["file_id"], old_ids)
        self.assertEqual("present", new_row["status"])
        self.assertEqual(
            2,
            sum(1 for row in rows if row["file_id"] in old_ids and row["status"] == "missing"),
        )

    def test_file_types_table_can_enable_an_extension_without_code_change(self) -> None:
        with closing(open_database(self.db_path)) as connection:
            initialize_database(connection)
            connection.execute(
                "INSERT INTO file_types(extension, file_type) VALUES ('.custommedia', 'image')"
            )
            connection.commit()
        self.write_file("added.custommedia", b"table-driven")
        self.scan()
        self.assertEqual(
            [".custommedia"],
            [row["extension"] for row in self.rows("SELECT extension FROM files")],
        )

    def test_duplicate_ejector_moves_all_verified_copies_and_ignores_folder_units(self) -> None:
        payload = b"an exact duplicate payload"
        first = self.write_file("duplicates/a.jpg", payload)
        second = self.write_file("duplicates/nested/a.jpg", payload)
        game = self.root / "GameA"
        game.mkdir()
        (game / "same.jpg").write_bytes(payload)
        scan = self.scan([game])
        self.assertEqual(2, scan.duplicate_files)

        output = self.base / "Downloads" / "重複ダウンロード"
        preview = eject_duplicates(self.db_path, output, dry_run=True)
        self.assertEqual(2, preview.dry_run_files)
        self.assertTrue(first.exists())
        self.assertTrue(second.exists())
        self.assertEqual(2, len(self.rows("SELECT file_id FROM files")))

        summary = eject_duplicates(self.db_path, output)
        self.assertEqual(1, summary.duplicate_groups)
        self.assertEqual(2, summary.candidate_files)
        self.assertEqual(2, summary.ejected_files)
        self.assertEqual(0, summary.failed_files)
        self.assertFalse(first.exists())
        self.assertFalse(second.exists())
        self.assertEqual([], self.rows("SELECT file_id FROM files"))
        self.assertEqual(1, len(self.rows("SELECT folder_id FROM folder_units")))
        self.assertTrue((game / "same.jpg").exists())

        with summary.report_path.open("r", encoding="utf-8-sig", newline="") as report_file:
            report = list(csv.DictReader(report_file))
        self.assertEqual(2, len(report))
        self.assertEqual({"ejected"}, {row["result"] for row in report})
        ejected_paths = [Path(row["ejected_path"]) for row in report]
        self.assertEqual(2, len(set(ejected_paths)))
        for ejected in ejected_paths:
            self.assertTrue(ejected.exists())
            self.assertEqual(len(payload), ejected.stat().st_size)
            self.assertEqual(hashlib.sha256(payload).hexdigest(), hashlib.sha256(ejected.read_bytes()).hexdigest())

    def test_duplicate_ejector_refuses_a_source_changed_after_scan(self) -> None:
        first = self.write_file("a.jpg", b"original-A")
        second = self.write_file("b.jpg", b"original-A")
        self.scan()
        first.write_bytes(b"modified-B")  # Same byte length, different SHA-256.
        summary = eject_duplicates(self.db_path, self.base / "ejected")
        self.assertEqual(1, summary.failed_files)
        self.assertEqual(1, summary.ejected_files)
        self.assertTrue(first.exists())
        self.assertFalse(second.exists())
        remaining = self.rows("SELECT relative_path FROM files")
        self.assertEqual(["a.jpg"], [row["relative_path"] for row in remaining])

    def test_directory_symlink_is_not_followed_when_supported(self) -> None:
        self.write_file("ordinary.jpg", b"ordinary")
        loop = self.root / "loop"
        try:
            os.symlink(self.root, loop, target_is_directory=True)
        except (OSError, NotImplementedError):
            if os.name != "nt":
                self.skipTest("Directory symlink creation is unavailable on this system")
            junction = subprocess.run(
                ["cmd", "/c", "mklink", "/J", os.fspath(loop), os.fspath(self.root)],
                capture_output=True,
                text=True,
            )
            if junction.returncode != 0:
                self.skipTest("Directory junction creation is unavailable on this system")
        try:
            result = self.scan()
            self.assertEqual("success", result.status)
            self.assertEqual(1, result.files_seen)
            self.assertEqual(
                ["ordinary.jpg"],
                [row["relative_path"] for row in self.rows("SELECT * FROM files")],
            )
        finally:
            if loop.exists() or loop.is_symlink():
                os.rmdir(loop)


if __name__ == "__main__":
    unittest.main()
