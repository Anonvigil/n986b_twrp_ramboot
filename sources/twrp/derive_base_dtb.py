#!/usr/bin/env python3
"""Derive the tested storage-disabled base DTB from local image + live FDT.

The live N986B FDT is a separately supplied device capture. This offline tool
extracts revision-19 overlay 4 from the official recovery image, merges the
live memory map, adds loader reservations, and disables storage controllers.
Every stage is checked against the recorded successful build's SHA-256.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import subprocess
from pathlib import Path

IMAGE_SHA = "8a4dc7914d5ce0b6e2dae900433a853ad35a1606b5a94f3e9042ae85c6f2a771"
LIVE_SHA = "b0e8715a9dcfb55c393a7f1e6cb984e200b2b568ac1b152c1a8b40aae25009d1"
BASE_ENTRY_SHA = "65170c81837d7a82428c98ef2b0307526661e7bc3f3e729605e300b9b2ac4eb6"
OVERLAY_SHA = "8c7e2507d99bd91c52f03e8dc6c4a8eae00af5bb4a68e73fbc54a511b632998b"
MERGED_SHA = "97e69e5e935f014e6babc80ec9225de1c8bd1bfe91ed27565def56add1a513b0"
LIVE_MERGE_SHA = "ecf1c0b32ea0f0eb292d61f383dd964e7c95d01a68ef9b3e2211065811e26e64"
RESERVED_SHA = "3db4de9113ea0261176c84f1636057994ef12a50288d0169ad03733d70d88388"
FINAL_SHA = "78eae5000a548edca8e5ad80f73a1b28b2e443b9d26ddd10f7b0e84adac9f35c"
EXPECTED_MODEL = b"Samsung C2S EUR OPENX 19 based on EXYNOS990\0"
EXTRA_RESERVED = {"kaslr", "el2_earlymem", "el2_code", "fb", "sboot", "harxlog_mem"}
STORAGE_NODES = ("/ufs@0x13100000", "/ufs-srpmb", "/dwmmc2@132E0000")
RESERVATIONS = ((0xA0000000, 0x03000000), (0xA4000000, 0x00200000),
                (0xA6000000, 0x00200000))


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check(data: bytes, expected: str, label: str) -> None:
    got = digest(data)
    if got != expected:
        raise ValueError(f"{label} SHA-256 mismatch: {got}, expected {expected}")


def table_entry(image: bytes, offset: int, size: int, index: int) -> bytes:
    table = image[offset:offset + size]
    if len(table) != size or size < 32:
        raise ValueError("truncated Android DT table")
    magic, total, header, entry_size, count, entries_offset, _, _ = struct.unpack_from(">8I", table)
    if magic != 0xD7B7AB1E or total != size or header != 32 or entry_size != 32 or index >= count:
        raise ValueError("unexpected Android DT table layout")
    length, start, _, _, *_ = struct.unpack_from(">8I", table, entries_offset + index * entry_size)
    data = table[start:start + length]
    if len(data) != length or data[:4] != b"\xd0\x0d\xfe\xed":
        raise ValueError("truncated DT table entry")
    return data


def output(command: list[str]) -> str:
    return subprocess.check_output(command, text=True).strip()


def children(blob: Path, node: str) -> list[str]:
    return output(["fdtget", "-l", str(blob), node]).splitlines()


def properties(blob: Path, node: str) -> list[str]:
    return output(["fdtget", "-p", str(blob), node]).splitlines()


def raw_property(blob: Path, node: str, key: str) -> bytes:
    return bytes(int(x, 16) for x in output(["fdtget", "-t", "bx", str(blob), node, key]).split())


def cell(blob: Path, node: str, key: str) -> int:
    raw = raw_property(blob, node, key)
    if len(raw) != 4:
        raise ValueError(f"unexpected cell width: {node}/{key}")
    return struct.unpack(">I", raw)[0]


def copy_leaf(source: Path, target: Path, node: str) -> None:
    if children(source, node):
        raise ValueError(f"refusing nested node: {node}")
    subprocess.run(["fdtput", "-c", str(target), node], check=True)
    for key in properties(source, node):
        values = [f"{x:x}" for x in raw_property(source, node, key)]
        subprocess.run(["fdtput", "-t", "bx", str(target), node, key, *values], check=True)
        if raw_property(source, node, key) != raw_property(target, node, key):
            raise ValueError(f"copied property mismatch: {node}/{key}")


def reserve_map(data: bytes) -> tuple[int, list[tuple[int, int]]]:
    if data[:4] != b"\xd0\x0d\xfe\xed":
        raise ValueError("bad FDT magic")
    words = struct.unpack_from(">10I", data)
    total, struct_offset, string_offset, map_offset = words[1:5]
    if total != len(data) or map_offset % 8 or not 40 <= map_offset < struct_offset < string_offset:
        raise ValueError("bad FDT header offsets")
    ranges = []
    pos = map_offset
    while pos + 16 <= struct_offset:
        address, length = struct.unpack_from(">QQ", data, pos)
        pos += 16
        if address == 0 and length == 0:
            return map_offset, ranges
        ranges.append((address, length))
    raise ValueError("unterminated FDT reservation map")


def add_reservations(source: bytes) -> bytes:
    map_offset, ranges = reserve_map(source)
    if ranges:
        raise ValueError("expected empty FDT reservation map")
    words = list(struct.unpack_from(">10I", source))
    extra = b"".join(struct.pack(">QQ", a, n) for a, n in RESERVATIONS)
    result = bytearray(source[:map_offset] + extra + source[map_offset:])
    for index in (1, 2, 3):
        words[index] += len(extra)
    struct.pack_into(">10I", result, 0, *words)
    if reserve_map(result)[1] != list(RESERVATIONS):
        raise ValueError("reservation map readback failed")
    return bytes(result)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--official-image", type=Path, required=True)
    parser.add_argument("--live-dtb", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    for command in ("fdtoverlay", "fdtget", "fdtput", "dtc"):
        if shutil.which(command) is None:
            parser.error(f"{command} from device-tree-compiler must be on PATH")
    image = args.official_image.read_bytes()
    check(image, IMAGE_SHA, "official Team Win c2s image")
    if len(image) != 57_640_960 or image[:8] != b"ANDROID!" or \
            struct.unpack_from("<I", image, 40)[0] != 2:
        raise ValueError("unexpected Android image header")
    dtbo_offset = struct.unpack_from("<Q", image, 1636)[0]
    dtbo_size = struct.unpack_from("<I", image, 1632)[0]
    dtb_size = struct.unpack_from("<I", image, 1648)[0]
    dtb_offset = (dtbo_offset + dtbo_size + 2047) & ~2047
    if (dtbo_offset, dtbo_size, dtb_offset, dtb_size) != \
            (55_115_776, 2_181_436, 57_298_944, 340_908):
        raise ValueError("unexpected Android DT placement")
    base_entry = table_entry(image, dtb_offset, dtb_size, 0)
    overlay = table_entry(image, dtbo_offset, dtbo_size, 4)
    check(base_entry, BASE_ENTRY_SHA, "official DTB entry 0")
    check(overlay, OVERLAY_SHA, "official DTBO entry 4")
    live = args.live_dtb.read_bytes()
    check(live, LIVE_SHA, "locally supplied live N986B FDT")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    base_path = args.output_dir / "_base-entry.dtb"
    overlay_path = args.output_dir / "_overlay-4.dtb"
    merged_path = args.output_dir / "_merged.dtb"
    copied_path = args.output_dir / "_live-memory.dtb"
    reserved_path = args.output_dir / "_reserved.dtb"
    final_path = args.output_dir / "n986b-storage-disabled-base.dtb"
    base_path.write_bytes(base_entry)
    overlay_path.write_bytes(overlay)
    subprocess.run(["fdtoverlay", "-i", str(base_path), "-o", str(merged_path),
                    str(overlay_path)], check=True)
    check(merged_path.read_bytes(), MERGED_SHA, "revision-19 overlay merge")
    if raw_property(merged_path, "/", "model") != EXPECTED_MODEL or \
            raw_property(args.live_dtb, "/", "model") != EXPECTED_MODEL:
        raise ValueError("N986B model mismatch")
    if (cell(merged_path, "/", "#address-cells"),
        cell(merged_path, "/", "#size-cells"),
        cell(args.live_dtb, "/", "#address-cells"),
        cell(args.live_dtb, "/", "#size-cells")) != (2, 1, 2, 1):
        raise ValueError("unexpected FDT root cell widths")
    memory_nodes = [x for x in children(args.live_dtb, "/") if x.startswith("memory@")]
    if len(memory_nodes) != 16 or any(x.startswith("memory@") for x in children(merged_path, "/")):
        raise ValueError("unexpected memory node inventory")
    added_reserved = sorted(set(children(args.live_dtb, "/reserved-memory")) -
                            set(children(merged_path, "/reserved-memory")))
    if set(added_reserved) != EXTRA_RESERVED:
        raise ValueError("unexpected extra reserved-memory nodes")
    shutil.copyfile(merged_path, copied_path)
    for name in memory_nodes:
        copy_leaf(args.live_dtb, copied_path, "/" + name)
    for name in added_reserved:
        copy_leaf(args.live_dtb, copied_path, "/reserved-memory/" + name)
    check(copied_path.read_bytes(), LIVE_MERGE_SHA, "live memory merge")
    for key in properties(merged_path, "/mali@18500000"):
        if raw_property(merged_path, "/mali@18500000", key) != \
                raw_property(copied_path, "/mali@18500000", key):
            raise ValueError(f"GPU property changed: {key}")
    reserved_path.write_bytes(add_reservations(copied_path.read_bytes()))
    check(reserved_path.read_bytes(), RESERVED_SHA, "loader reservations")
    shutil.copyfile(reserved_path, final_path)
    for node in STORAGE_NODES:
        subprocess.run(["fdtput", "-t", "s", str(final_path), node, "status", "disabled"], check=True)
        if raw_property(final_path, node, "status") != b"disabled\0":
            raise ValueError(f"storage disable failed: {node}")
    final = final_path.read_bytes()
    check(final, FINAL_SHA, "storage-disabled base DTB")
    if reserve_map(final)[1] != list(RESERVATIONS):
        raise ValueError("reservations changed")
    subprocess.run(["dtc", "-I", "dtb", "-O", "dtb", "-o", "/dev/null",
                    str(final_path)], check=True, stderr=subprocess.DEVNULL)
    print(json.dumps({"output": str(final_path), "bytes": len(final),
                      "sha256": digest(final), "live_input_sha256": digest(live),
                      "memory_nodes": len(memory_nodes),
                      "disabled_storage_nodes": list(STORAGE_NODES)}, indent=2))


if __name__ == "__main__":
    main()
