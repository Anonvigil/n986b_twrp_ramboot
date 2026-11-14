#!/usr/bin/env python3
"""Build a complete *local-use* ZIP from a launcher ZIP and frozen UI10V files.

This script deliberately does not download or publish third-party firmware or
TWRP. The caller must supply the exact files from their own authorized copy.
"""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import sys
import tempfile
import zipfile

import ramboot


ARTIFACT_HASHES = {
    ramboot.FD_NAME: ramboot.FD_SHA256,
    ramboot.STREAM_NAME: ramboot.STREAM_SHA256,
    ramboot.EFI_NAME: ramboot.EFI_SHA256,
    ramboot.FDT_NAME: ramboot.FDT_SHA256,
    ramboot.INITRD_NAME: ramboot.INITRD_SHA256,
}
PAYLOAD_SUMS = "SHA256SUMS-payload.txt"
REQUIRED_LAUNCHER_FILES = {
    "N986B-TWRP-RAMBOOT.exe", "libusb-1.0.dll",
    "scripts/ramboot.py", "SHA256SUMS.txt",
    "evidence/fbinput-analysis.json", "evidence/vts-off-analysis.json",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_artifacts(folder: Path) -> None:
    """Validate all bytes and the frozen stream layout before writing output."""
    for name, expected in ARTIFACT_HASHES.items():
        path = folder / name
        if not path.is_file():
            raise ValueError(f"missing frozen artifact: {name}")
        if sha256_file(path) != expected:
            raise ValueError(f"frozen artifact SHA-256 differs: {name}")
    ramboot.build_plan(folder)


def _safe_name(info: zipfile.ZipInfo) -> str | None:
    name = info.filename
    if (not name or "\\" in name or name.startswith("/") or
            any(part in ("", ".", "..") for part in name.rstrip("/").split("/"))):
        raise ValueError(f"unsafe launcher ZIP path: {name!r}")
    if PurePosixPath(name).is_absolute() or ":" in name.split("/", 1)[0]:
        raise ValueError(f"absolute launcher ZIP path: {name!r}")
    mode = info.external_attr >> 16
    if stat.S_IFMT(mode) == stat.S_IFLNK:
        raise ValueError(f"launcher ZIP symlink refused: {name!r}")
    if info.is_dir():
        return None
    folded = name.casefold()
    if (folded.startswith("artifacts/") or folded.startswith("private/") or
            folded == PAYLOAD_SUMS.casefold() or
            folded.endswith((".log", ".dump", ".raw", ".key", ".pem", ".pfx"))):
        raise ValueError(f"private or reserved launcher ZIP path: {name!r}")
    return name


def _candidate_entries(source: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    entries: dict[str, zipfile.ZipInfo] = {}
    seen: set[str] = set()
    for info in source.infolist():
        name = _safe_name(info)
        if name is None:
            continue
        folded = name.casefold()
        if folded in seen:
            raise ValueError(f"duplicate launcher ZIP path: {name!r}")
        seen.add(folded)
        entries[name] = info
    missing = REQUIRED_LAUNCHER_FILES - entries.keys()
    if missing:
        raise ValueError("launcher ZIP is incomplete: " + ", ".join(sorted(missing)))
    # The package must contain the launcher built from this exact source tree.
    current_script = Path(ramboot.__file__).read_bytes()
    if hashlib.sha256(source.read("scripts/ramboot.py")).digest() != hashlib.sha256(current_script).digest():
        raise ValueError("launcher ZIP was built from a different ramboot.py; rebuild the EXE first")
    sums = source.read("SHA256SUMS.txt").decode("ascii")
    expected_sums = {
        name: sha for sha, name in (line.split(None, 1) for line in sums.splitlines() if line.strip())
    }
    for name in ("N986B-TWRP-RAMBOOT.exe", "libusb-1.0.dll"):
        actual = hashlib.sha256(source.read(name)).hexdigest()
        if expected_sums.get(name, "").lower() != actual:
            raise ValueError(f"launcher ZIP checksum mismatch: {name}")
    return entries


def _launcher_directory_files(folder: Path) -> dict[str, Path]:
    root = Path(ramboot.__file__).resolve().parent.parent
    files = {
        "N986B-TWRP-RAMBOOT.exe": folder / "N986B-TWRP-RAMBOOT.exe",
        "libusb-1.0.dll": folder / "libusb-1.0.dll",
    }
    for name in ("README.md", "NOTICE.md", "LICENSE", "requirements-build.txt"):
        files[name] = root / name
    blocked_parts = {"__pycache__", "private", "artifacts", ".git"}
    blocked_names = {"N986BFreshFullEct.h"}
    blocked_suffixes = {".pyc", ".log", ".bin", ".fd", ".efi",
                        ".dtb", ".gz", ".img", ".raw", ".dump"}
    for subtree in ("docs", "evidence", "third_party", "sources"):
        for source in (root / subtree).rglob("*"):
            relative = source.relative_to(root)
            if (source.is_file() and not blocked_parts.intersection(relative.parts)
                    and source.name not in blocked_names
                    and source.suffix.lower() not in blocked_suffixes):
                files[source.relative_to(root).as_posix()] = source
    for pattern in ("*.py", "*.ps1"):
        for source in (root / "scripts").glob(pattern):
            files[source.relative_to(root).as_posix()] = source
    for name, source in files.items():
        if not source.is_file():
            raise ValueError(f"local launcher file missing: {name}")
        if name.casefold().startswith(("artifacts/", "private/")):
            raise ValueError(f"private launcher file refused: {name}")
    return files


def _write_artifacts(bundle: zipfile.ZipFile, artifacts: Path) -> None:
    for name in ARTIFACT_HASHES:
        info = zipfile.ZipInfo(f"artifacts/{name}")
        info.compress_type = zipfile.ZIP_STORED
        with (artifacts / name).open("rb") as src, bundle.open(info, "w") as dst:
            shutil.copyfileobj(src, dst, 1024 * 1024)
    lines = [f"{sha}  artifacts/{name}" for name, sha in ARTIFACT_HASHES.items()]
    bundle.writestr(PAYLOAD_SUMS, "\n".join(lines) + "\n")


def package_local_bundle(candidate: Path | None, launcher_dir: Path | None,
                         artifacts: Path, output: Path) -> None:
    if (candidate is None) == (launcher_dir is None):
        raise ValueError("provide exactly one of launcher ZIP or launcher directory")
    candidate = candidate.resolve() if candidate is not None else None
    launcher_dir = launcher_dir.resolve() if launcher_dir is not None else None
    artifacts, output = artifacts.resolve(), output.resolve()
    if candidate is not None and not candidate.is_file():
        raise ValueError(f"launcher ZIP missing: {candidate}")
    if output.exists():
        raise ValueError(f"output already exists: {output}")
    if output == candidate or output.is_relative_to(artifacts) or (
            launcher_dir is not None and output.is_relative_to(launcher_dir)):
        raise ValueError("output must not replace an input")
    verify_artifacts(artifacts)
    if candidate is not None:
        with zipfile.ZipFile(candidate, "r") as source:
            entries = _candidate_entries(source)
    else:
        files = _launcher_directory_files(launcher_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".n986b-bundle-", suffix=".tmp",
                                         dir=output.parent, delete=False) as temp:
            temporary = Path(temp.name)
        with zipfile.ZipFile(temporary, "w", allowZip64=True) as bundle:
            if candidate is not None:
                with zipfile.ZipFile(candidate, "r") as source:
                    for name, info in entries.items():
                        copy_info = zipfile.ZipInfo(name, date_time=info.date_time)
                        copy_info.compress_type = info.compress_type
                        copy_info.external_attr = info.external_attr
                        with source.open(info, "r") as src, bundle.open(copy_info, "w") as dst:
                            shutil.copyfileobj(src, dst, 1024 * 1024)
            else:
                for name, path in files.items():
                    info = zipfile.ZipInfo(name)
                    info.compress_type = zipfile.ZIP_DEFLATED
                    with path.open("rb") as src, bundle.open(info, "w") as dst:
                        shutil.copyfileobj(src, dst, 1024 * 1024)
                checksums = [
                    f"{sha256_file(files[name])}  {name}"
                    for name in ("N986B-TWRP-RAMBOOT.exe", "libusb-1.0.dll")
                ]
                bundle.writestr("SHA256SUMS.txt", "\n".join(checksums) + "\n")
            _write_artifacts(bundle, artifacts)
        os.replace(temporary, output)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    launcher = parser.add_mutually_exclusive_group(required=True)
    launcher.add_argument("--launcher-zip", type=Path)
    launcher.add_argument("--launcher-dir", type=Path)
    parser.add_argument("--artifacts", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        package_local_bundle(args.launcher_zip, args.launcher_dir,
                             args.artifacts, args.output)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print(f"bundle refused: {error}", file=sys.stderr)
        return 2
    print(f"local bundle: {args.output.resolve()}")
    print("Keep this ZIP local: its payload contains third-party recovery and device-derived bytes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
