#!/usr/bin/env python3
"""Verify published UI10V evidence and optional private build inputs.

This tool reads local files only. It never queries or writes a phone.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "evidence" / "ui10v-public.json"


def digest_file(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def check_file(path: Path, expected_hash: str, expected_size: int | None = None) -> None:
    if not path.is_file():
        raise ValueError(f"missing: {path}")
    if expected_size is not None and path.stat().st_size != expected_size:
        raise ValueError(f"size mismatch: {path}")
    actual = digest_file(path)
    if actual != expected_hash:
        raise ValueError(f"SHA-256 mismatch: {path}\nexpected {expected_hash}\nactual   {actual}")
    print(f"PASS {path.name} {actual}")


def combined_hash(fd_path: Path, stream_path: Path) -> str:
    sha = hashlib.sha256()
    for path in (fd_path, stream_path):
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                sha.update(chunk)
    return sha.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path,
                        help="directory with private frozen FD, stream, EFI, DTB and initramfs")
    args = parser.parse_args()
    try:
        evidence = json.loads(MANIFEST.read_text(encoding="utf-8"))
        if evidence.get("schema") != 1:
            raise ValueError("unknown public evidence schema")
        for name, expected in evidence["photos"].items():
            check_file(ROOT / "evidence" / "photos" / name, expected)
        if args.artifacts is not None:
            artifacts = args.artifacts.resolve(strict=True)
            for name, record in evidence["artifacts"].items():
                check_file(artifacts / name, record["sha256"], record["size"])
            fd = artifacts / "N986B-TWRP-UI10V-VTS-OFF-RAM.fd"
            stream = artifacts / "recovery-ui10v-ram-stream.bin"
            if combined_hash(fd, stream) != evidence["combined_fd_stream_sha256"]:
                raise ValueError("combined FD+stream SHA-256 mismatch")
            print("PASS combined FD+stream SHA-256")
        print("evidence_integrity=pass")
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"evidence_integrity=fail: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
