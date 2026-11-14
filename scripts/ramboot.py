#!/usr/bin/env python3
"""Pinned SM-N986B UI10V TWRP RAM launcher.

`plan` is offline. `prepare` makes a read-only Android ADB receipt. Only an
explicit `send` opens the Fastboot USB device and transfers data. This launcher
has no flash, erase, partition, Odin, unlock or persistent-write command.

The callback encoding and USB sequence were adapted from Osmium and the N986B
research sender. Osmium's upstream LICENSE is the Unlicense; see NOTICE.md.
"""

from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace


PROFILE = "SM-N986B/N986BXXU0ATE3"
SBOOT_SHA256 = "d0f631d6320977c5b7509ff1457ee8c22878ca6b39619653c8361389c2fa3080"
FD_NAME = "N986B-TWRP-UI10V-VTS-OFF-RAM.fd"
STREAM_NAME = "recovery-ui10v-ram-stream.bin"
EFI_NAME = "N986BUi10V.efi"
FDT_NAME = "n986b-twrp-ui10v-vts-disabled.dtb"
INITRD_NAME = "n986b-twrp-ui10v-ramdisk.cpio.gz"
FD_SHA256 = "0ac10b5ae7ed996102d4ff74ee8f0d2002d57088fa804c93a1d2b271ebb06c01"
STREAM_SHA256 = "d1bfd029728be897f6bc5721e1c1abfcab41b0a84d5ca20591b8ea0911304f7b"
COMBINED_SHA256 = "4affaa0cf66ba86538204699a7d5daed34a84f05052e8fac67b4791c0e45e82d"
EFI_SHA256 = "a274548662f9c88167facf96e1bbe3aa0a7bedf2e2e0c7f589364af2abcd1fa5"
FDT_SHA256 = "f055c5915815a705f196fd236ff24856859092fc88fcb4a2be3fd0e2de148769"
INITRD_SHA256 = "078814b1c8bf94153a1cdda1a076161eb9f5ab68cf58acd7691076dee811f436"
IMAGE_SHA256 = "8a4dc7914d5ce0b6e2dae900433a853ad35a1606b5a94f3e9042ae85c6f2a771"
STAGE_SHA256 = "f52d3c42df1585c486fd46776292297f38b6aa60045d71719df92766dcffc16d"
FBINPUT_EVIDENCE_SHA256 = "17c9a99c9b4a307e2e4416cf9b9592db131b76655da8b4a1ea29a4b8b756e51b"
VTS_EVIDENCE_SHA256 = "44742ae10997dcd10f45af873afe741f9c1c596a8f9ac8465034cb72376a396f"
PRIOR_FB_STREAM_SHA256 = "46cbff933e3c5b003ee10ffee96c1764d24f154ad6d18d7073aee0070a09a084"
PRIOR_VTS_STREAM_SHA256 = "c5a780ba3ea7ee616825c29043ec22360591be111c864180db6134c1910b335f"

MANIFEST = struct.Struct("<8sIIQQ32sQQ32sQIIQQ32s")
FD_PA, FD_BYTES, FD_END = 0x90000000, 0x700000, 0x90700000
STREAM_PA, STREAM_END, STREAM_BYTES = 0xA8000000, 0xAC860000, 75_890_688
IMAGE_PA, IMAGE_BYTES = 0xA8001000, 57_640_960
FDT_PA, FDT_BYTES = 0xAB6FA000, 528_004
INITRD_PA, INITRD_BYTES = 0xAB77B000, 17_667_760
RUNTIME_INITRD_PA, RUNTIME_INITRD_END = 0xA4000000, 0xA50D96B0
STORAGE_NODES = ("/ufs@0x13100000", "/ufs-srpmb", "/dwmmc2@132E0000")
VTS_NODE = "/vts@0x15510000"
CALLBACK_PA, FASTBOOT_STAGING = 0xE81EC280, 0x8B000000
FASTBOOT_NEXT_POINTER, SBOOT_FDT = 0xE83483F8, 0x8A000000
PRETARGET = FD_PA - 8
ARCH_INVALIDATE_CACHE_RANGE = 0xE8016638
ARCH_SYNC_CACHE_RANGE = 0xE8016658
MMU_DISABLE = 0xE80AC798
TERMINAL_PACKET = b"UEFITERM"
PACKET_BYTES, PAYLOAD_PACKETS = 512, 162_560
USB_VID, USB_PID, BULK_OUT = 0x18D1, 0x0002, 0x02
RECEIPT_MAX_AGE_SECONDS = 15 * 60


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require(condition: bool, detail: str) -> None:
    if not condition:
        raise ValueError(detail)


def parse_fdt(blob: bytes) -> tuple[dict[str, dict[str, bytes]], list[tuple[int, int]]]:
    """Read bounded FDT properties and memreserve entries without libfdt."""
    require(len(blob) >= 40, "FDT header truncated")
    (magic, total, off_struct, off_strings, off_reserve, version,
     last_compatible, _cpu, strings_len, struct_len) = struct.unpack_from(">10I", blob)
    require(magic == 0xD00DFEED and 17 <= version <= 20 and
            last_compatible <= version and 40 <= total <= len(blob) and
            40 <= off_reserve < off_struct and
            off_struct + struct_len <= total and
            off_strings >= off_struct + struct_len and
            off_strings + strings_len <= total, "FDT header/bounds invalid")
    reservations: list[tuple[int, int]] = []
    position = off_reserve
    while True:
        require(position + 16 <= off_struct, "FDT memreserve terminator missing")
        address, size = struct.unpack_from(">QQ", blob, position)
        position += 16
        if address == size == 0:
            break
        require(size > 0 and address + size <= (1 << 64) and
                len(reservations) < 64, "FDT memreserve malformed")
        reservations.append((address, size))
    props: dict[str, dict[str, bytes]] = {}
    strings = blob[off_strings:off_strings + strings_len]
    position, end = off_struct, off_struct + struct_len
    stack: list[str] = []
    ended = False
    while position + 4 <= end:
        token = struct.unpack_from(">I", blob, position)[0]
        position += 4
        if token == 1:
            name_end = blob.find(b"\0", position, end)
            require(name_end >= 0, "FDT node name unterminated")
            stack.append(blob[position:name_end].decode("ascii"))
            position = (name_end + 4) & ~3
            props.setdefault("/" + "/".join(stack[1:]), {})
        elif token == 2:
            require(bool(stack), "FDT node underflow")
            stack.pop()
        elif token == 3:
            require(bool(stack) and position + 8 <= end, "FDT property header truncated")
            length, nameoff = struct.unpack_from(">II", blob, position)
            position += 8
            require(position + length <= end and nameoff < len(strings),
                    "FDT property bounds invalid")
            name_end = strings.find(b"\0", nameoff)
            require(name_end >= 0, "FDT property name unterminated")
            name = strings[nameoff:name_end].decode("ascii")
            path = "/" + "/".join(stack[1:])
            require(name not in props[path], "duplicate FDT property")
            props[path][name] = blob[position:position + length]
            position = (position + length + 3) & ~3
        elif token == 4:
            continue
        elif token == 9:
            ended = True
            break
        else:
            raise ValueError("unexpected FDT token")
    require(ended and not stack, "FDT structure unterminated")
    return props, reservations


def movz(register: int, immediate: int, shift: int = 0) -> int:
    require(0 <= register <= 31 and 0 <= immediate <= 0xFFFF and
            shift in (0, 16), "invalid MOVZ operand")
    return 0xD2800000 | ((shift // 16) << 21) | (immediate << 5) | register


def movk(register: int, immediate: int, shift: int = 0) -> int:
    require(0 <= register <= 31 and 0 <= immediate <= 0xFFFF and
            shift in (0, 16), "invalid MOVK operand")
    return 0xF2800000 | ((shift // 16) << 21) | (immediate << 5) | register


def set_u32(register: int, value: int) -> list[int]:
    require(0 <= value <= 0xFFFFFFFF, "stage value out of range")
    low, high = value & 0xFFFF, value >> 16
    if low:
        return [movz(register, low)] + ([movk(register, high, 16)] if high else [])
    return [movz(register, high, 16)]


def b_cond(source: int, target: int, condition: int) -> int:
    delta = target - source
    require(-(1 << 18) <= delta < (1 << 18), "conditional branch out of range")
    return 0x54000000 | ((delta & 0x7FFFF) << 5) | condition


def build_stage() -> bytes:
    """Encode the proven 80-byte AArch64 callback, with pinned branch edges."""
    words: list[int] = []
    words += set_u32(4, STREAM_END)
    words.append(0xEB04001F)  # cmp x0,x4: terminal at exact stream end
    terminal_branch = len(words)
    words.append(0)
    words.append(0x8B010002)  # add x2,x0,x1
    words += set_u32(5, FD_END)
    words.append(0xEB05005F)  # cmp x2,x5
    skip_branch = len(words)
    words.append(0)
    words += set_u32(2, STREAM_PA)
    store = len(words)
    words += set_u32(3, FASTBOOT_NEXT_POINTER)
    words.append(0xF9000062)  # str x2,[x3]
    words.append(0xD65F03C0)  # ret
    handoff = len(words)
    words += set_u32(0, SBOOT_FDT)
    words += [0xD5034FDF, 0xD5033F9F, 0xD508751F, 0xD5033F9F, 0xD5033FDF]
    words += set_u32(7, FD_PA)
    words.append(0xD61F00E0)  # br x7
    words[terminal_branch] = b_cond(terminal_branch, handoff, 0)
    words[skip_branch] = b_cond(skip_branch, store, 1)
    require(len(words) == 20 and handoff == 12, "stage instruction layout changed")
    stage = struct.pack("<20I", *words)
    require(digest(stage) == STAGE_SHA256, "stage SHA-256 differs")
    return stage


def check_stream(stream: bytes) -> dict:
    require(len(stream) == STREAM_BYTES and digest(stream) == STREAM_SHA256,
            "stream size/SHA-256 differs from UI10V")
    fields = MANIFEST.unpack_from(stream)
    (magic, version, header_size, image_pa, image_size, image_sha,
     fdt_pa, fdt_size, fdt_sha, end, overlay, flags,
     initrd_pa, initrd_size, initrd_sha) = fields
    require(magic == b"N986BRCO" and version == 2 and header_size == 4096 and
            image_pa == IMAGE_PA and image_size == IMAGE_BYTES and
            image_sha.hex() == IMAGE_SHA256 and fdt_pa == FDT_PA and
            fdt_size == FDT_BYTES and fdt_sha.hex() == FDT_SHA256 and
            initrd_pa == INITRD_PA and initrd_size == INITRD_BYTES and
            initrd_sha.hex() == INITRD_SHA256 and end == STREAM_END and
            end == STREAM_PA + len(stream) and overlay == 4 and flags == 2 and
            not any(stream[MANIFEST.size:header_size]) and
            image_pa + image_size <= fdt_pa and
            fdt_pa + fdt_size <= initrd_pa and
            initrd_pa + initrd_size <= end,
            "stream manifest or component bounds differ")
    image = stream[image_pa - STREAM_PA:image_pa - STREAM_PA + image_size]
    fdt = stream[fdt_pa - STREAM_PA:fdt_pa - STREAM_PA + fdt_size]
    initrd = stream[initrd_pa - STREAM_PA:initrd_pa - STREAM_PA + initrd_size]
    require(digest(image) == IMAGE_SHA256 and image[:8] == b"ANDROID!" and
            digest(fdt) == FDT_SHA256 and fdt[:4] == bytes.fromhex("d00dfeed") and
            digest(initrd) == INITRD_SHA256 and initrd[:2] == b"\x1f\x8b",
            "stream component bytes differ")
    props, reservations = parse_fdt(fdt)
    for node in STORAGE_NODES + (VTS_NODE,):
        require(props.get(node, {}).get("status") == b"disabled\0",
                f"storage/VTS isolation differs: {node}")
    # The source FDT retains stock boot arguments. The pinned UEFI app appends
    # recovery arguments at runtime; its exact behavior is frozen by FD SHA.
    bootargs = props.get("/chosen", {}).get("bootargs", b"")
    require(b"androidboot.hardware=exynos990" in bootargs,
            "N986B source FDT boot arguments absent")
    require((0xA0000000, 0x3000000) in reservations and
            (0xA4000000, 0x2000000) in reservations and
            (0xA6000000, 0x200000) in reservations,
            "runtime destination memreserve entries absent")
    return {"manifest_sha256": digest(stream[:4096]),
            "image_sha256": digest(image), "fdt_sha256": digest(fdt),
            "initrd_sha256": digest(initrd), "bootargs": bootargs.rstrip(b"\0").decode("ascii")}


def _read_optional(folder: Path, filename: str, expected_sha: str,
                   expected_embedded: bytes | None = None) -> None:
    path = folder / filename
    if not path.exists():
        return
    data = path.read_bytes()
    require(digest(data) == expected_sha, f"optional {filename} SHA-256 differs")
    if expected_embedded is not None:
        require(data == expected_embedded, f"optional {filename} differs from stream")


def build_plan(folder: Path) -> SimpleNamespace:
    fd = (folder / FD_NAME).read_bytes()
    stream = (folder / STREAM_NAME).read_bytes()
    require(len(fd) == FD_BYTES and digest(fd) == FD_SHA256,
            "FD size/SHA-256 differs from UI10V")
    info = check_stream(stream)
    require(digest(fd + stream) == COMBINED_SHA256 and
            (len(fd) + len(stream)) // PACKET_BYTES == PAYLOAD_PACKETS and
            (len(fd) + len(stream)) % PACKET_BYTES == 0,
            "combined FD/stream identity or packet count differs")
    stage = build_stage()
    fdt = stream[FDT_PA - STREAM_PA:FDT_PA - STREAM_PA + FDT_BYTES]
    initrd = stream[INITRD_PA - STREAM_PA:INITRD_PA - STREAM_PA + INITRD_BYTES]
    _read_optional(folder, EFI_NAME, EFI_SHA256)
    _read_optional(folder, FDT_NAME, FDT_SHA256, fdt)
    _read_optional(folder, INITRD_NAME, INITRD_SHA256, initrd)
    return SimpleNamespace(fd=fd, stream=stream, stage=stage, info=info,
                           payload_packets=PAYLOAD_PACKETS)


def _adb(adb: str, serial: str | None, *arguments: str) -> str:
    command = [adb]
    if serial is not None:
        command += ["-s", serial]
    command += list(arguments)
    result = subprocess.run(command, capture_output=True, text=True,
                            timeout=15, check=True)
    return result.stdout.strip()


def capture_adb_receipt(adb: str, now: datetime | None = None) -> dict:
    lines = _adb(adb, None, "devices", "-l").splitlines()[1:]
    devices = [line.split()[0] for line in lines if len(line.split()) >= 2 and
               line.split()[1] == "device"]
    require(len(devices) == 1, f"expected one authorized Android ADB device; found {len(devices)}")
    serial = devices[0]
    require(_adb(adb, serial, "get-state") == "device", "Android ADB state changed")
    props = {key: _adb(adb, serial, "shell", "getprop", key) for key in (
        "ro.product.model", "ro.bootloader", "ro.boot.warranty_bit",
        "ro.boot.verifiedbootstate", "ro.boot.debug_level")}
    if not props["ro.boot.debug_level"]:
        cmdline = _adb(adb, serial, "shell", "cat", "/proc/cmdline")
        match = re.search(r"(?:^|\s)androidboot\.debug_level=(\S+)", cmdline)
        props["ro.boot.debug_level"] = match.group(1) if match else ""
    receipt = {
        "captured_utc": (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(),
        "serial": serial,
        "model": props["ro.product.model"],
        "bootloader": props["ro.bootloader"],
        "warranty_bit": props["ro.boot.warranty_bit"],
        "verifiedbootstate": props["ro.boot.verifiedbootstate"],
        "debug_level": props["ro.boot.debug_level"],
        "read_only_adb": True,
    }
    validate_adb_receipt(receipt, now)
    return receipt


def validate_adb_receipt(receipt: dict, now: datetime | None = None) -> None:
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    captured = datetime.fromisoformat(receipt["captured_utc"])
    require(captured.tzinfo is not None, "ADB receipt timezone absent")
    age = (moment - captured.astimezone(timezone.utc)).total_seconds()
    require(-30 <= age <= RECEIPT_MAX_AGE_SECONDS, "ADB receipt is stale or from future")
    require(isinstance(receipt.get("serial"), str) and bool(receipt["serial"]) and
            receipt.get("model") == "SM-N986B" and
            receipt.get("bootloader") == "N986BXXU0ATE3" and
            receipt.get("warranty_bit") == "0" and
            receipt.get("verifiedbootstate") == "green" and
            receipt.get("debug_level") == "0x4948" and
            receipt.get("read_only_adb") is True,
            "ADB model/bootloader/boot state differs from tested profile")


def validate_prior_evidence(fbinput_path: Path, vts_path: Path) -> dict:
    fbraw, vtsraw = fbinput_path.read_bytes(), vts_path.read_bytes()
    require(digest(fbraw) == FBINPUT_EVIDENCE_SHA256,
            "FB/input A/B evidence file hash differs")
    require(digest(vtsraw) == VTS_EVIDENCE_SHA256,
            "VTS-off A/B evidence file hash differs")
    fb, vts = json.loads(fbraw), json.loads(vtsraw)
    require(fb.get("capture_integrity") == "pass" and
            fb.get("source_stream_sha256") == PRIOR_FB_STREAM_SHA256 and
            fb.get("fbinput_el0_kmsg_proof") is True,
            "FB/input A/B evidence does not pass")
    delta = vts.get("vts_off_runtime_delta", {})
    require(vts.get("capture_integrity") == "pass" and
            vts.get("strict_fdt_gate") == "pass" and
            vts.get("source_stream_sha256") == PRIOR_VTS_STREAM_SHA256 and
            vts.get("stream_source_exact_full") is True and
            vts.get("fbioctl_el0_kmsg_proof") is True and
            delta.get("only_runtime_property_delta") ==
            "/vts@0x15510000/status:okay->disabled" and
            delta.get("nodes_all_other_properties_exact") is True,
            "VTS-off A/B evidence does not pass")
    return {"fbinput_analysis_sha256": digest(fbraw),
            "vts_analysis_sha256": digest(vtsraw)}


def _libusb_candidates() -> list[Path]:
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve().parent
        bundled = Path(getattr(sys, "_MEIPASS", executable))
        return [executable / "libusb-1.0.dll", bundled / "libusb-1.0.dll"]
    return [Path(__file__).resolve().parent / "libusb-1.0.dll"]


def load_libusb() -> ctypes.CDLL:
    for candidate in _libusb_candidates():
        if candidate.is_file():
            # libusb's Windows ABI is WINAPI/stdcall. CDLL uses cdecl on x86.
            loader = ctypes.WinDLL if sys.platform == "win32" else ctypes.CDLL
            return loader(str(candidate))
    raise FileNotFoundError("libusb-1.0.dll is required beside ramboot.exe/ramboot.py")


def configure_libusb(usb: ctypes.CDLL) -> None:
    usb.libusb_init.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
    usb.libusb_init.restype = ctypes.c_int
    usb.libusb_exit.argtypes = [ctypes.c_void_p]
    usb.libusb_open_device_with_vid_pid.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_uint16]
    usb.libusb_open_device_with_vid_pid.restype = ctypes.c_void_p
    usb.libusb_close.argtypes = [ctypes.c_void_p]
    usb.libusb_claim_interface.argtypes = [ctypes.c_void_p, ctypes.c_int]
    usb.libusb_claim_interface.restype = ctypes.c_int
    usb.libusb_release_interface.argtypes = [ctypes.c_void_p, ctypes.c_int]
    usb.libusb_release_interface.restype = ctypes.c_int
    usb.libusb_control_transfer.argtypes = [ctypes.c_void_p, ctypes.c_uint8,
        ctypes.c_uint8, ctypes.c_uint16, ctypes.c_uint16,
        ctypes.POINTER(ctypes.c_ubyte), ctypes.c_uint16, ctypes.c_uint]
    usb.libusb_control_transfer.restype = ctypes.c_int
    usb.libusb_bulk_transfer.argtypes = [ctypes.c_void_p, ctypes.c_ubyte,
        ctypes.POINTER(ctypes.c_ubyte), ctypes.c_int,
        ctypes.POINTER(ctypes.c_int), ctypes.c_uint]
    usb.libusb_bulk_transfer.restype = ctypes.c_int
    usb.libusb_error_name.argtypes = [ctypes.c_int]
    usb.libusb_error_name.restype = ctypes.c_char_p


def probe_libusb() -> None:
    """Check native DLL load and calling convention without opening a phone."""
    usb = load_libusb()
    configure_libusb(usb)
    context = ctypes.c_void_p()
    result = usb.libusb_init(ctypes.byref(context))
    require(result == 0, f"libusb_init: {usb_error_name(usb, result)}")
    usb.libusb_exit(context)
    print(json.dumps({"libusb_loaded": True,
                      "process_pointer_bits": struct.calcsize("P") * 8,
                      "device_transfer": False}))


def usb_error_name(usb: ctypes.CDLL, code: int) -> str:
    raw = usb.libusb_error_name(code)
    return raw.decode("ascii", errors="replace") if raw else f"error {code}"


def set_sel_payload(pointer: int) -> bytes:
    payload = bytearray(64)
    struct.pack_into("<Q", payload, 0x20, 1)
    struct.pack_into("<Q", payload, 0x30, pointer)
    struct.pack_into("<Q", payload, 0x38, 1)
    return bytes(payload)


def control_set_sel(usb: ctypes.CDLL, handle: int, pointer: int,
                    timeout_ms: int) -> None:
    data = set_sel_payload(pointer)
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    result = usb.libusb_control_transfer(handle, 0, 0x30, 0, 0, buffer,
                                          len(data), timeout_ms)
    require(result == len(data), f"SET_SEL pointer 0x{pointer:x}: {result}/{len(data)}")


def exact_bulk(usb: ctypes.CDLL, handle: int, data: bytes, timeout_ms: int,
               label: str, allow_disconnect: bool = False) -> bool:
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    transferred = ctypes.c_int(0)
    result = usb.libusb_bulk_transfer(handle, BULK_OUT, buffer, len(data),
                                      ctypes.byref(transferred), timeout_ms)
    if allow_disconnect and result == -4 and transferred.value == 0:
        return False
    require(result == 0 and transferred.value == len(data),
            f"{label}: USB OUT {usb_error_name(usb, result)}; {transferred.value}/{len(data)}")
    return True


def execute(plan: SimpleNamespace, timeout_ms: int,
            usb_loader=load_libusb) -> bool:
    """The sole Fastboot device I/O path. Caller must finish all gates first."""
    usb = usb_loader()
    configure_libusb(usb)
    context = ctypes.c_void_p()
    result = usb.libusb_init(ctypes.byref(context))
    require(result == 0, f"libusb_init: {usb_error_name(usb, result)}")
    handle, claimed = None, False
    try:
        handle = usb.libusb_open_device_with_vid_pid(context, USB_VID, USB_PID)
        require(bool(handle), f"Fastboot USB {USB_VID:04x}:{USB_PID:04x} not found")
        result = usb.libusb_claim_interface(handle, 0)
        require(result == 0, f"claim interface 0: {usb_error_name(usb, result)}")
        claimed = True
        setup = [
            (FASTBOOT_STAGING, b"getvar:product", "prime"),
            (CALLBACK_PA, plan.stage, "install callback"),
            (FASTBOOT_STAGING, struct.pack("<Q", ARCH_INVALIDATE_CACHE_RANGE), "invalidate stage"),
            (CALLBACK_PA, plan.stage, "restore callback after invalidate"),
            (FASTBOOT_STAGING, struct.pack("<Q", ARCH_SYNC_CACHE_RANGE), "sync stage"),
            (CALLBACK_PA, plan.stage, "restore callback after sync"),
            (FASTBOOT_STAGING, struct.pack("<Q", MMU_DISABLE), "disable MMU"),
            (CALLBACK_PA, plan.stage, "restore callback after MMU disable"),
            (PRETARGET, struct.pack("<Q", FASTBOOT_STAGING), "install auto-advance"),
        ]
        for pointer, data, label in setup:
            control_set_sel(usb, handle, pointer, timeout_ms)
            exact_bulk(usb, handle, data, timeout_ms, label)
        for index in range(plan.payload_packets):
            offset = index * PACKET_BYTES
            if offset < FD_BYTES:
                data = plan.fd[offset:offset + PACKET_BYTES]
            else:
                stream_offset = offset - FD_BYTES
                data = plan.stream[stream_offset:stream_offset + PACKET_BYTES]
            require(len(data) == PACKET_BYTES, "payload packet split changed")
            exact_bulk(usb, handle, data, timeout_ms, f"payload packet {index}")
            if (index + 1) % 4096 == 0 or index + 1 == plan.payload_packets:
                print(f"packets_acked={index + 1}/{plan.payload_packets}", flush=True)
        return exact_bulk(usb, handle, TERMINAL_PACKET, timeout_ms,
                          "UEFITERM terminal", allow_disconnect=True)
    finally:
        if handle:
            if claimed:
                usb.libusb_release_interface(handle, 0)
            usb.libusb_close(handle)
        usb.libusb_exit(context)


def plan_record(plan: SimpleNamespace) -> dict:
    return {"mode": "n986b_twrp_ui10v_vts_off_ram_volatile",
            "profile": PROFILE, "resident_sboot_sha256_assumed": SBOOT_SHA256,
            "fd_sha256": FD_SHA256, "stream_sha256": STREAM_SHA256,
            "combined_sha256": COMBINED_SHA256, "fdt_sha256": FDT_SHA256,
            "initrd_sha256": INITRD_SHA256, "stage_sha256": STAGE_SHA256,
            "manifest_sha256": plan.info["manifest_sha256"],
            "fd_pa": hex(FD_PA), "stream_pa": hex(STREAM_PA),
            "stream_end": hex(STREAM_END), "packet_bytes": PACKET_BYTES,
            "payload_packets": plan.payload_packets,
            "setup_outs": 9, "terminal_outs": 1,
            "storage_and_vts_disabled": True}


def release_root() -> Path:
    """Folder containing the released EXE, or repository root in source mode."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _send_after_preflight(plan: SimpleNamespace, evidence: dict,
                          send_receipt: Path, timeout_ms: int) -> None:
    report = plan_record(plan)
    print(json.dumps({**report, **evidence,
                      "device_io": "starting_fastboot_ram_send"}, indent=2), flush=True)
    terminal_acked = execute(plan, timeout_ms)
    result = {**report, **evidence, "send_requested": True,
              "sent_utc": datetime.now(timezone.utc).isoformat(),
              "payload_outs": plan.payload_packets,
              "out_acked": 9 + plan.payload_packets + int(terminal_acked),
              "terminal_status": "acked" if terminal_acked else "usb_disconnected_unconfirmed"}
    send_receipt.parent.mkdir(parents=True, exist_ok=True)
    with send_receipt.open("x", encoding="utf-8") as output:
        json.dump(result, output, indent=2)
        output.write("\n")
    print(f"ram_send_payload_complete=true terminal_acked={terminal_acked}", flush=True)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        argv = ["launch"]
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="read-only Android ADB receipt")
    prepare.add_argument("--adb", default="adb")
    prepare.add_argument("--receipt", type=Path,
                         default=release_root() / "private" / "adb.json")
    commands.add_parser("probe-usb", help="load libusb DLL without opening a phone")
    preview = commands.add_parser("plan", help="offline image validation only")
    preview.add_argument("--artifacts", type=Path,
                         default=release_root() / "artifacts")
    launch = commands.add_parser("launch", help="interactive Fastboot send using local files")
    launch.add_argument("--timeout-ms", type=int, default=5000)
    send = commands.add_parser("send", help="explicit volatile Fastboot RAM send")
    send.add_argument("--artifacts", type=Path, required=True)
    send.add_argument("--adb-receipt", type=Path, required=True)
    send.add_argument("--fbinput-evidence", type=Path, required=True)
    send.add_argument("--vts-evidence", type=Path, required=True)
    send.add_argument("--send-receipt", type=Path, required=True)
    send.add_argument("--confirm-combined-sha256", required=True)
    send.add_argument("--confirm-device-profile", required=True)
    send.add_argument("--confirm-resident-sboot-sha256", required=True)
    send.add_argument("--confirm-warranty-bit-zero", action="store_true")
    send.add_argument("--confirm-debug-high", action="store_true")
    send.add_argument("--timeout-ms", type=int, default=5000)
    args = parser.parse_args(argv)
    try:
        if args.command == "probe-usb":
            probe_libusb()
            return 0
        if args.command == "prepare":
            receipt = capture_adb_receipt(args.adb)
            args.receipt.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=args.receipt.parent,
                    prefix=".adb-receipt-", suffix=".tmp", delete=False
                ) as output:
                    temporary = Path(output.name)
                    json.dump(receipt, output, indent=2)
                    output.write("\n")
                os.replace(temporary, args.receipt)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            print(json.dumps({"receipt": str(args.receipt), "profile": PROFILE,
                              "captured_utc": receipt["captured_utc"],
                              "device_io": "read_only_adb"}, indent=2))
            return 0
        artifact_dir = (release_root() / "artifacts") if args.command == "launch" else args.artifacts
        plan = build_plan(artifact_dir)
        report = plan_record(plan)
        if args.command == "plan":
            print(json.dumps({**report, "device_io": False}, indent=2))
            return 0
        if args.command == "launch":
            require(args.timeout_ms > 0, "timeout must be positive")
            private = release_root() / "private"
            receipt_path = private / "adb.json"
            fbinput_path = release_root() / "evidence" / "fbinput-analysis.json"
            vts_path = release_root() / "evidence" / "vts-off-analysis.json"
            validate_adb_receipt(json.loads(receipt_path.read_text(encoding="utf-8")))
            proof = validate_prior_evidence(fbinput_path, vts_path)
            send_receipt = private / ("send-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json")
            require(not send_receipt.exists(), "send receipt path already exists")
            print(json.dumps({**report, **proof, "device_io": False}, indent=2), flush=True)
            print("This checks a prior Android receipt; the current S-Boot SHA cannot be read live here.")
            typed = input("Type BOOT N986B to transfer the pinned RAM image: ").strip()
            require(typed == "BOOT N986B", "typed Fastboot RAM send confirmation absent")
            _send_after_preflight(plan, proof, send_receipt, args.timeout_ms)
            return 0
        require(args.timeout_ms > 0, "timeout must be positive")
        require(not args.send_receipt.exists(), "send receipt path already exists")
        validate_adb_receipt(json.loads(args.adb_receipt.read_text(encoding="utf-8")))
        proof = validate_prior_evidence(args.fbinput_evidence, args.vts_evidence)
        require(args.confirm_combined_sha256.lower() == COMBINED_SHA256 and
                args.confirm_device_profile == PROFILE and
                args.confirm_resident_sboot_sha256.lower() == SBOOT_SHA256 and
                args.confirm_warranty_bit_zero and args.confirm_debug_high,
                "exact image/profile/S-Boot/boot-state confirmations absent")
        _send_after_preflight(plan, proof, args.send_receipt, args.timeout_ms)
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, EOFError,
            subprocess.SubprocessError) as error:
        print(f"refused={error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
