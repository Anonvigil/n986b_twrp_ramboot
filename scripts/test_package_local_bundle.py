"""Host-only checks for assembling a private, complete RAM-boot ZIP."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

import package_local_bundle as pack
import ramboot


class PackageLocalBundleTests(unittest.TestCase):
    def _fake_artifacts(self, base: Path) -> Path:
        folder = base / "artifacts-input"
        folder.mkdir()
        for name in pack.ARTIFACT_HASHES:
            (folder / name).write_bytes(name.encode("ascii"))
        return folder

    def _candidate(self, base: Path, script_bytes: bytes | None = None,
                   extra_name: str | None = None) -> Path:
        path = base / "candidate.zip"
        exe, dll = b"fake executable", b"fake native library"
        sums = (f"{hashlib.sha256(exe).hexdigest()}  N986B-TWRP-RAMBOOT.exe\n"
                f"{hashlib.sha256(dll).hexdigest()}  libusb-1.0.dll\n")
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("N986B-TWRP-RAMBOOT.exe", exe)
            archive.writestr("libusb-1.0.dll", dll)
            archive.writestr("SHA256SUMS.txt", sums)
            archive.writestr("scripts/ramboot.py", script_bytes or
                             Path(ramboot.__file__).read_bytes())
            archive.writestr("evidence/fbinput-analysis.json", "{}")
            archive.writestr("evidence/vts-off-analysis.json", "{}")
            if extra_name is not None:
                archive.writestr(extra_name, b"bad")
        return path

    def test_candidate_zip_gets_exact_artifact_names_and_no_private_files(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            candidate = self._candidate(base)
            artifacts = self._fake_artifacts(base)
            output = base / "complete.zip"
            with mock.patch.object(pack, "verify_artifacts"):
                pack.package_local_bundle(candidate, None, artifacts, output)
            with zipfile.ZipFile(output) as archive:
                names = set(archive.namelist())
                self.assertTrue(pack.REQUIRED_LAUNCHER_FILES <= names)
                self.assertTrue({f"artifacts/{name}" for name in pack.ARTIFACT_HASHES} <= names)
                self.assertIn(pack.PAYLOAD_SUMS, names)
                self.assertFalse(any(name.startswith("private/") for name in names))
                self.assertEqual(archive.read("artifacts/" + ramboot.FD_NAME),
                                 ramboot.FD_NAME.encode("ascii"))

    def test_build_directory_gets_current_source_and_checksum(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            launcher = base / "built"
            launcher.mkdir()
            (launcher / "N986B-TWRP-RAMBOOT.exe").write_bytes(b"source built exe")
            (launcher / "libusb-1.0.dll").write_bytes(b"matching dll")
            artifacts = self._fake_artifacts(base)
            output = base / "complete.zip"
            with mock.patch.object(pack, "verify_artifacts"):
                pack.package_local_bundle(None, launcher, artifacts, output)
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(archive.read("scripts/ramboot.py"),
                                 Path(ramboot.__file__).read_bytes())
                self.assertIn(hashlib.sha256(b"source built exe").hexdigest(),
                              archive.read("SHA256SUMS.txt").decode("ascii"))
                self.assertEqual(archive.read("artifacts/" + ramboot.STREAM_NAME),
                                 ramboot.STREAM_NAME.encode("ascii"))

    def test_rejects_stale_launcher_source_before_output(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            candidate = self._candidate(base, b"old source")
            artifacts = self._fake_artifacts(base)
            output = base / "complete.zip"
            with mock.patch.object(pack, "verify_artifacts"):
                with self.assertRaisesRegex(ValueError, "different ramboot.py"):
                    pack.package_local_bundle(candidate, None, artifacts, output)
            self.assertFalse(output.exists())

    def test_rejects_unsafe_or_private_candidate_paths(self):
        for unsafe in ("../escape.txt", "private/adb.json", "C:/host/file", "artifacts/old.fd"):
            with self.subTest(unsafe=unsafe), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                candidate = self._candidate(base, extra_name=unsafe)
                artifacts = self._fake_artifacts(base)
                output = base / "complete.zip"
                with mock.patch.object(pack, "verify_artifacts"):
                    with self.assertRaisesRegex(ValueError, "path"):
                        pack.package_local_bundle(candidate, None, artifacts, output)
                self.assertFalse(output.exists())

    def test_real_artifacts_validate_when_supplied(self):
        source = os.environ.get("N986B_UI10V_ARTIFACTS")
        if not source:
            self.skipTest("set N986B_UI10V_ARTIFACTS to frozen local build directory")
        pack.verify_artifacts(Path(source))


if __name__ == "__main__":
    unittest.main()
