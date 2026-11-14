#!/usr/bin/env python3
"""Rebuild the tested UI10V RAM stream from separately supplied inputs.

This is an offline file transformation. It never opens a USB device or writes
to a phone. The official recovery image and device-specific DTB are inputs,
not files distributed with this source tree.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import shutil
import stat
import struct
import subprocess
from pathlib import Path

IMAGE_SHA = "8a4dc7914d5ce0b6e2dae900433a853ad35a1606b5a94f3e9042ae85c6f2a771"
RAMDISK_SHA = "6e12e84f895763c63462abec2c96d127b2811f0e58d9a9a8cefcf74662fe2803"
RECOVERY_ELF_SHA = "99b3896dd26e265421bf22c7243283bad9f98367f1640efa2b132dc2a9bd49ce"
SOURCE_DTB_SHA = "78eae5000a548edca8e5ad80f73a1b28b2e443b9d26ddd10f7b0e84adac9f35c"
FIRST_DTB_SHA = "25d9031b8e4edd7a0a40b9fad435ec1083946d7fa671da5ffede6391282cdb7b"
FINAL_INITRD_SHA = "078814b1c8bf94153a1cdda1a076161eb9f5ab68cf58acd7691076dee811f436"
UI10_DTB_SHA = "bce69a6c17e2e1c7fc3174cb9f11153b5ef66d3111e90905c7c850ff1cc17837"
FINAL_DTB_SHA = "f055c5915815a705f196fd236ff24856859092fc88fcb4a2be3fd0e2de148769"
STREAM_SHA = "d1bfd029728be897f6bc5721e1c1abfcab41b0a84d5ca20591b8ea0911304f7b"
MARKER = b"N986B-TWRP-UI-EL0-20261108-48A921"
IMAGE_SIZE = 57_640_960
BASE = 0xA8000000
IMAGE_PA = 0xA8001000
DTB_PA = 0xAB6FA000
INITRD_PA = 0xAB77B000
END = 0xAC860000


def digest(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def check(blob: bytes, expected: str, label: str) -> None:
    actual = digest(blob)
    if actual != expected:
        raise ValueError(f"{label} SHA-256 mismatch: {actual}, expected {expected}")


def entries(cpio: bytes) -> list[tuple[str, list[int], bytes]]:
    result = []
    pos = 0
    while pos + 110 <= len(cpio):
        if cpio[pos:pos + 6] != b"070701":
            raise ValueError(f"bad newc header at {pos}")
        fields = [int(cpio[pos + 6 + i:pos + 14 + i], 16) for i in range(0, 104, 8)]
        size, namesize = fields[6], fields[11]
        pos += 110
        raw_name = cpio[pos:pos + namesize]
        if not raw_name.endswith(b"\0"):
            raise ValueError("unterminated newc name")
        name = raw_name[:-1].decode("utf-8")
        pos = (pos + namesize + 3) & ~3
        data = cpio[pos:pos + size]
        if len(data) != size:
            raise ValueError("truncated newc payload")
        pos = (pos + size + 3) & ~3
        if name == "TRAILER!!!":
            if cpio[pos:].strip(b"\0"):
                raise ValueError("data follows newc trailer")
            break
        result.append((name, fields, data))
    if len(result) != 3616 or len({name for name, _, _ in result}) != len(result):
        raise ValueError("unexpected recovery archive member set")
    return result


def newc_entry(out: bytearray, name: str, original: list[int], data: bytes) -> None:
    encoded = name.encode("utf-8") + b"\0"
    fields = original.copy()
    fields[6], fields[11] = len(data), len(encoded)
    out.extend(b"070701" + b"".join(f"{n:08x}".encode() for n in fields))
    out.extend(encoded)
    out.extend(b"\0" * (-len(out) % 4))
    out.extend(data)
    out.extend(b"\0" * (-len(out) % 4))


def repack(source: list[tuple[str, list[int], bytes]], changes: dict[str, bytes]) -> bytes:
    if not set(changes).issubset({name for name, _, _ in source}):
        raise ValueError("replacement target missing")
    cpio = bytearray()
    for name, fields, data in source:
        newc_entry(cpio, name, fields, changes.get(name, data))
    trailer = [len(source) + 1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 11, 0]
    newc_entry(cpio, "TRAILER!!!", trailer, b"")
    cpio.extend(b"\0" * (-len(cpio) % 512))
    bio = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=bio, mtime=0, compresslevel=9) as gz:
        gz.write(cpio)
    return bio.getvalue()


def make_initrd(official_ramdisk: bytes) -> bytes:
    check(official_ramdisk, RAMDISK_SHA, "official ramdisk")
    original = entries(gzip.decompress(official_ramdisk))
    payloads = {name: data for name, _, data in original}
    if digest(payloads["system/bin/recovery"]) != RECOVERY_ELF_SHA:
        raise ValueError("official recovery executable changed")
    init_name = "system/etc/init/hw/init.rc"
    init_rc = payloads[init_name]
    marker = b"service adbd /system/bin/adbd"
    if init_rc.count(marker) != 1:
        raise ValueError("unexpected init.rc service boundary")
    init_rc = init_rc[:init_rc.index(marker)]
    if b"class_start default" not in init_rc or b"start ueventd" not in init_rc:
        raise ValueError("recovery launch trigger missing")
    changes = {
        "system/etc/recovery.fstab": b"# Host-only UI candidate: no partition entries.\n",
        "system/etc/twrp.flags": b"",
        init_name: init_rc,
        "init.recovery.exynos990.rc": (
            b"on init\n    write /proc/sys/kernel/hung_task_timeout_secs 0\n"
            b"    mkdir /efs\n    mkdir /sec_efs\n\non fs\n"
            b"    export ANDROID_ROOT /system_root\n"
        ),
        "init.recovery.usb.rc": b"# Host-only UI candidate: USB gadget and pstore mounts disabled.\n",
        "system/etc/init/lpdumpd.rc": b"# Host-only UI candidate: lpdumpd disabled.\n",
        "system/bin/postrecoveryboot.sh": b"#!/sbin/bash\nexit 0\n",
    }
    first = repack(original, changes)
    # This standalone path verifies the final bytes rather than depending on
    # the historical intermediate archive's compressed representation.
    before = entries(gzip.decompress(first))
    payloads = {name: data for name, _, data in before}
    old = payloads[init_name]
    token = b"    class_start default\n"
    if old.count(token) != 1:
        raise ValueError("unexpected class_start trigger")
    new = old.replace(token, (
        b"    wait /dev/fb0 5\n"
        b"    mkdir /dev/graphics 0755 root graphics\n"
        b"    symlink /dev/fb0 /dev/graphics/fb0\n"
        b"    write /dev/kmsg " + MARKER + b" phase=before_recovery pid=1\n"
        b"    class_start default\n"
    ), 1)
    new += b"\non property:init.svc.recovery=running\n" + (
        b"    write /dev/kmsg " + MARKER + b" phase=recovery_running pid=1\n"
    )
    final = repack(before, {init_name: new})
    check(final, FINAL_INITRD_SHA, "UI10V initrd")
    check(dict((n, d) for n, _, d in entries(gzip.decompress(final)))["system/bin/recovery"],
          RECOVERY_ELF_SHA, "retained recovery executable")
    if any(stat.S_ISBLK(fields[1]) for _, fields, _ in entries(gzip.decompress(final))):
        raise ValueError("archive contains a block device node")
    return final


def run_fdtput(path: Path, kind: str, node: str, key: str, value: str) -> None:
    subprocess.run(["fdtput", "-t", kind, str(path), node, key, value], check=True)


def make_dtb(source: bytes, first_initrd_len: int, final_initrd_len: int,
             temporary: Path) -> bytes:
    check(source, SOURCE_DTB_SHA, "source storage-disabled DTB")
    if source[:4] != b"\xd0\x0d\xfe\xed":
        raise ValueError("not a flattened device tree")
    reserve_offset = struct.unpack_from(">I", source, 16)[0]
    expected = [(0xA0000000, 0x03000000), (0xA4000000, 0x00200000),
                (0xA6000000, 0x00200000)]
    actual = [struct.unpack_from(">QQ", source, reserve_offset + i * 16) for i in range(3)]
    if actual != expected:
        raise ValueError("source FDT reservation map changed")
    intermediate = bytearray(source)
    struct.pack_into(">QQ", intermediate, reserve_offset + 16, 0xA4000000, 0x02000000)
    temporary.write_bytes(intermediate)
    run_fdtput(temporary, "x", "/chosen", "linux,initrd-start", "a4000000")
    run_fdtput(temporary, "x", "/chosen", "linux,initrd-end",
               f"{0xA4000000 + first_initrd_len:x}")
    check(temporary.read_bytes(), FIRST_DTB_SHA, "first pass DTB")
    run_fdtput(temporary, "x", "/chosen", "linux,initrd-end",
               f"{0xA4000000 + final_initrd_len:x}")
    check(temporary.read_bytes(), UI10_DTB_SHA, "UI10 DTB")
    run_fdtput(temporary, "s", "/vts@0x15510000", "status", "disabled")
    final = temporary.read_bytes()
    check(final, FINAL_DTB_SHA, "UI10V DTB")
    return final


def make_stream(image: bytes, dtb: bytes, initrd: bytes) -> bytes:
    if len(image) != IMAGE_SIZE or len(dtb) != 528_004 or len(initrd) != 17_667_760:
        raise ValueError("unexpected component length")
    if DTB_PA + len(dtb) > INITRD_PA or INITRD_PA + len(initrd) > END:
        raise ValueError("RAM component overlap")
    manifest = bytearray(4096)
    manifest[:8] = b"N986BRCO"
    struct.pack_into("<IIQQ", manifest, 8, 2, 4096, IMAGE_PA, len(image))
    manifest[32:64] = bytes.fromhex(IMAGE_SHA)
    struct.pack_into("<QQ", manifest, 64, DTB_PA, len(dtb))
    manifest[80:112] = bytes.fromhex(FINAL_DTB_SHA)
    struct.pack_into("<QII", manifest, 112, END, 4, 2)
    struct.pack_into("<QQ", manifest, 128, INITRD_PA, len(initrd))
    manifest[144:176] = bytes.fromhex(FINAL_INITRD_SHA)
    stream = bytearray(END - BASE)
    stream[:4096] = manifest
    for address, blob in ((IMAGE_PA, image), (DTB_PA, dtb), (INITRD_PA, initrd)):
        stream[address - BASE:address - BASE + len(blob)] = blob
    result = bytes(stream)
    check(result, STREAM_SHA, "UI10V RAM stream")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--official-image", type=Path, required=True)
    parser.add_argument("--base-dtb", type=Path, required=True,
                        help="Locally supplied storage-disabled DTB, SHA-256 78eae500...")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if shutil.which("fdtput") is None:
        parser.error("fdtput from device-tree-compiler must be on PATH")
    image = args.official_image.read_bytes()
    check(image, IMAGE_SHA, "official Team Win c2s image")
    if len(image) != IMAGE_SIZE or image[:8] != b"ANDROID!" or \
            struct.unpack_from("<I", image, 40)[0] != 2:
        raise ValueError("unexpected Android recovery image header")
    ramdisk = image[37_367_808:37_367_808 + 17_747_664]
    initrd = make_initrd(ramdisk)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    temporary = args.output_dir / "_working.dtb"
    try:
        dtb = make_dtb(args.base_dtb.read_bytes(), 17_661_778, len(initrd), temporary)
    finally:
        temporary.unlink(missing_ok=True)
    stream = make_stream(image, dtb, initrd)
    outputs = {
        "n986b-twrp-ui10v-ramdisk.cpio.gz": initrd,
        "n986b-twrp-ui10v-vts-disabled.dtb": dtb,
        "recovery-ui10v-ram-stream.bin": stream,
    }
    for name, blob in outputs.items():
        (args.output_dir / name).write_bytes(blob)
    print(json.dumps({name: {"bytes": len(blob), "sha256": digest(blob)}
                      for name, blob in outputs.items()}, indent=2))


if __name__ == "__main__":
    main()
