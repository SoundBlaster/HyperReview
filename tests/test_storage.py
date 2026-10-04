import tempfile
import unittest
from pathlib import Path

from hyperreview.storage import StorageError, read_json, write_bundle


class StorageTests(unittest.TestCase):
    def test_bounded_and_strict_json(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "input.json"
            for body in (b'{"id":1,"id":2}', b'{"metric":NaN}', b'x' * 11):
                path.write_bytes(body)
                with self.assertRaises(StorageError):
                    read_json(path, max_bytes=10)
            path.write_bytes(b'{"id":1}')
            self.assertEqual(read_json(path), {"id": 1})

    def test_duplicate_and_nonfinite_json(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "input.json"
            for body in (b'{"id":1,"id":2}', b'{"metric":NaN}'):
                path.write_bytes(body)
                with self.assertRaises(StorageError):
                    read_json(path)

    def test_private_artifacts_and_names(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            destination = write_bundle({"request.json": b"{}"}, root / "requests")
            self.assertEqual(destination.stat().st_mode & 0o777, 0o700)
            self.assertEqual((destination / "request.json").stat().st_mode & 0o777, 0o600)
            with self.assertRaises(StorageError):
                write_bundle({"../escape": b"{}"}, root)
            (root / "link").symlink_to(root / "requests", target_is_directory=True)
            with self.assertRaises(StorageError):
                write_bundle({"request.json": b"{}"}, root / "link")
