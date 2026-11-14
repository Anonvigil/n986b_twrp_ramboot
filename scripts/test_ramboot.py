"""Offline tests for the pinned N986B RAM launcher. No USB/ADB device access."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace
import ctypes

import ramboot


class FakeFunction:
    def __init__(self, callback):
        self.callback = callback

    def __call__(self, *args):
        return self.callback(*args)


class FakeUsb:
    def __init__(self, terminal_disconnect=False, terminal_timeout=False,
                 short_first_bulk=False):
        self.controls = []
        self.bulks = []
        self.closed = False
        self.released = False
        self.exited = False
        self.vid_pid = None
        self.terminal_disconnect = terminal_disconnect
        self.terminal_timeout = terminal_timeout
        self.short_first_bulk = short_first_bulk
        self.libusb_init = FakeFunction(lambda context: 0)
        self.libusb_exit = FakeFunction(self._exit)
        self.libusb_open_device_with_vid_pid = FakeFunction(self._open)
        self.libusb_close = FakeFunction(self._close)
        self.libusb_claim_interface = FakeFunction(lambda handle, index: 0)
        self.libusb_release_interface = FakeFunction(self._release)
        self.libusb_control_transfer = FakeFunction(self._control)
        self.libusb_bulk_transfer = FakeFunction(self._bulk)
        self.libusb_error_name = FakeFunction(lambda code: b"FAKE_ERROR")

    def _open(self, context, vid, pid):
        self.vid_pid = (vid, pid)
        return 1

    def _close(self, handle):
        self.closed = True

    def _release(self, handle, interface):
        self.released = True
        return 0

    def _exit(self, context):
        self.exited = True

    def _control(self, handle, request_type, request, value, index,
                 buffer, length, timeout):
        self.controls.append((request_type, request,
                              struct.unpack_from("<Q", ctypes.string_at(buffer, length), 0x30)[0]))
        return length

    def _bulk(self, handle, endpoint, buffer, length, transferred, timeout):
        data = ctypes.string_at(buffer, length)
        self.bulks.append((endpoint, data))
        if self.short_first_bulk and len(self.bulks) == 1:
            transferred._obj.value = length - 1
            return 0
        if self.terminal_disconnect and data == ramboot.TERMINAL_PACKET:
            transferred._obj.value = 0
            return -4
        if self.terminal_timeout and data == ramboot.TERMINAL_PACKET:
            transferred._obj.value = 0
            return -7
        transferred._obj.value = length
        return 0


class HashingUsb(FakeUsb):
    """Model all OUT transfers without keeping the 83 MiB package in memory."""

    def __init__(self):
        self.bulk_count = 0
        self.payload_sha = hashlib.sha256()
        self.fd_last = None
        self.stream_first = None
        self.terminal = None
        super().__init__()

    def _bulk(self, handle, endpoint, buffer, length, transferred, timeout):
        self.bulk_count += 1
        data = ctypes.string_at(buffer, length)
        if 9 < self.bulk_count <= 9 + ramboot.PAYLOAD_PACKETS:
            self.payload_sha.update(data)
            if self.bulk_count == 9 + ramboot.FD_BYTES // ramboot.PACKET_BYTES:
                self.fd_last = data
            if self.bulk_count == 10 + ramboot.FD_BYTES // ramboot.PACKET_BYTES:
                self.stream_first = data
        if self.bulk_count == 10 + ramboot.PAYLOAD_PACKETS:
            self.terminal = data
        transferred._obj.value = length
        return 0


def receipt(now):
    return {"captured_utc": now.isoformat(), "serial": "TEST-DEVICE-1",
            "model": "SM-N986B", "bootloader": "N986BXXU0ATE3",
            "warranty_bit": "0", "verifiedbootstate": "green",
            "debug_level": "0x4948", "read_only_adb": True}


class RambootOfflineTests(unittest.TestCase):
    def test_callback_is_exact_frozen_80_bytes(self):
        stage = ramboot.build_stage()
        self.assertEqual(len(stage), 80)
        self.assertEqual(hashlib.sha256(stage).hexdigest(), ramboot.STAGE_SHA256)
        words = struct.unpack("<20I", stage)
        self.assertEqual(words[2], ramboot.b_cond(2, 12, 0))
        self.assertEqual(words[6], ramboot.b_cond(6, 8, 1))

    def test_dynamic_receipt_and_expiration(self):
        now = datetime(2026, 11, 8, 9, 0, tzinfo=timezone.utc)
        values = iter(["List of devices attached\nTEST-DEVICE-1 device usb:1-1",
                       "device", "SM-N986B", "N986BXXU0ATE3", "0", "green", "0x4948"])
        with mock.patch.object(ramboot, "_adb", side_effect=lambda *args: next(values)):
            captured = ramboot.capture_adb_receipt("adb", now)
        self.assertEqual(captured["serial"], "TEST-DEVICE-1")
        ramboot.validate_adb_receipt(captured, now + timedelta(minutes=14))
        with self.assertRaisesRegex(ValueError, "stale"):
            ramboot.validate_adb_receipt(captured, now + timedelta(minutes=16))
        captured["bootloader"] = "OTHER"
        with self.assertRaisesRegex(ValueError, "profile"):
            ramboot.validate_adb_receipt(captured, now)

    def test_prepare_refreshes_existing_private_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "private" / "adb.json"
            target.parent.mkdir()
            target.write_text('{"old": true}', encoding="utf-8")
            new_receipt = receipt(datetime.now(timezone.utc))
            with mock.patch.object(ramboot, "capture_adb_receipt", return_value=new_receipt), \
                 mock.patch("builtins.print"):
                self.assertEqual(ramboot.main(["prepare", "--receipt", str(target)]), 0)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), new_receipt)
            self.assertEqual(list(target.parent.glob(".adb-receipt-*.tmp")), [])

    def test_rejects_multiple_adb_devices(self):
        with mock.patch.object(ramboot, "_adb", return_value=(
            "List of devices attached\nONE device\nTWO device")):
            with self.assertRaisesRegex(ValueError, "expected one"):
                ramboot.capture_adb_receipt("adb")

    def test_bundled_prior_a_b_evidence(self):
        base = Path(__file__).resolve().parents[1] / "evidence"
        result = ramboot.validate_prior_evidence(
            base / "fbinput-analysis.json", base / "vts-off-analysis.json")
        self.assertEqual(result["fbinput_analysis_sha256"],
                         ramboot.FBINPUT_EVIDENCE_SHA256)
        self.assertEqual(result["vts_analysis_sha256"],
                         ramboot.VTS_EVIDENCE_SHA256)

    def test_no_device_io_for_plan_with_bad_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / ramboot.FD_NAME).write_bytes(b"tampered")
            (folder / ramboot.STREAM_NAME).write_bytes(b"tampered")
            with mock.patch.object(ramboot, "load_libusb", side_effect=AssertionError("USB called")), \
                 mock.patch.object(ramboot, "capture_adb_receipt", side_effect=AssertionError("ADB called")):
                self.assertEqual(ramboot.main(["plan", "--artifacts", directory]), 2)

    def test_missing_release_payload_has_actionable_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "missing RAM boot files.*artifacts folder"):
                ramboot.build_plan(Path(directory))

    def test_exact_usb_order_and_cleanup(self):
        usb = FakeUsb(terminal_disconnect=True)
        plan = SimpleNamespace(fd=b"A" * 1024, stream=b"", stage=ramboot.build_stage(),
                               payload_packets=2)
        with mock.patch("builtins.print"):
            self.assertFalse(ramboot.execute(plan, 5000, usb_loader=lambda: usb))
        self.assertEqual(usb.vid_pid, (ramboot.USB_VID, ramboot.USB_PID))
        self.assertEqual(len(usb.controls), 9)
        self.assertEqual([item[2] for item in usb.controls], [
            ramboot.FASTBOOT_STAGING, ramboot.CALLBACK_PA,
            ramboot.FASTBOOT_STAGING, ramboot.CALLBACK_PA,
            ramboot.FASTBOOT_STAGING, ramboot.CALLBACK_PA,
            ramboot.FASTBOOT_STAGING, ramboot.CALLBACK_PA, ramboot.PRETARGET])
        self.assertEqual(len(usb.bulks), 12)
        self.assertTrue(all(endpoint == ramboot.BULK_OUT for endpoint, _ in usb.bulks))
        self.assertEqual(usb.bulks[9], (ramboot.BULK_OUT, b"A" * 512))
        self.assertEqual(usb.bulks[10], (ramboot.BULK_OUT, b"A" * 512))
        self.assertEqual(usb.bulks[11], (ramboot.BULK_OUT, b"UEFITERM"))
        self.assertTrue(usb.closed and usb.released and usb.exited)

    def test_short_usb_write_refuses_and_closes(self):
        usb = FakeUsb(short_first_bulk=True)
        plan = SimpleNamespace(fd=b"A" * 512, stream=b"", stage=ramboot.build_stage(),
                               payload_packets=1)
        with self.assertRaisesRegex(ValueError, "prime"):
            ramboot.execute(plan, 5000, usb_loader=lambda: usb)
        self.assertTrue(usb.closed and usb.released and usb.exited)
        self.assertEqual(len(usb.bulks), 1)

    def test_terminal_timeout_is_not_claimed_as_ack(self):
        usb = FakeUsb(terminal_timeout=True)
        plan = SimpleNamespace(fd=b"A" * 512, stream=b"", stage=ramboot.build_stage(),
                               payload_packets=1)
        with mock.patch("builtins.print"):
            with self.assertRaisesRegex(ValueError, "UEFITERM terminal"):
                ramboot.execute(plan, 5000, usb_loader=lambda: usb)
        self.assertTrue(usb.closed and usb.released and usb.exited)

    def test_launch_requires_typed_confirmation_before_usb(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "private").mkdir()
            (base / "private" / "adb.json").write_text(json.dumps(
                receipt(datetime.now(timezone.utc))), encoding="utf-8")
            plan = SimpleNamespace(info={"manifest_sha256": "0" * 64},
                                   payload_packets=ramboot.PAYLOAD_PACKETS)
            with mock.patch.object(ramboot, "release_root", return_value=base), \
                 mock.patch.object(ramboot, "build_plan", return_value=plan), \
                 mock.patch.object(ramboot, "validate_prior_evidence", return_value={}), \
                 mock.patch("builtins.input", return_value="wrong"), \
                 mock.patch.object(ramboot, "execute", side_effect=AssertionError("USB called")):
                self.assertEqual(ramboot.main(["launch"]), 2)

    def test_fastboot_launch_without_adb_receipt_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            plan = SimpleNamespace(info={"manifest_sha256": "0" * 64},
                                   payload_packets=ramboot.PAYLOAD_PACKETS)
            with mock.patch.object(ramboot, "release_root", return_value=base), \
                 mock.patch.object(ramboot, "build_plan", return_value=plan), \
                 mock.patch.object(ramboot, "validate_prior_evidence", return_value={}), \
                 mock.patch("builtins.input", return_value="BOOT N986B"), \
                 mock.patch.object(ramboot, "_send_after_preflight") as send:
                self.assertEqual(ramboot.main(["launch"]), 0)
            self.assertEqual(send.call_args.args[1]["profile_check"],
                             "operator_confirmed_fastboot_only")

    @unittest.skipUnless(os.environ.get("N986B_UI10V_ARTIFACTS"),
                         "set N986B_UI10V_ARTIFACTS to the frozen local build directory")
    def test_real_frozen_artifacts_and_tamper(self):
        folder = Path(os.environ["N986B_UI10V_ARTIFACTS"])
        plan = ramboot.build_plan(folder)
        self.assertEqual(plan.payload_packets, 162_560)
        self.assertEqual(plan.info["fdt_sha256"], ramboot.FDT_SHA256)
        usb = HashingUsb()
        with mock.patch("builtins.print"):
            self.assertTrue(ramboot.execute(plan, 5000, usb_loader=lambda: usb))
        self.assertEqual(usb.bulk_count, 9 + 162_560 + 1)
        self.assertEqual(usb.payload_sha.hexdigest(), ramboot.COMBINED_SHA256)
        self.assertEqual(usb.terminal, b"UEFITERM")
        self.assertEqual(usb.fd_last, plan.fd[-512:])
        self.assertEqual(usb.stream_first, plan.stream[:512])
        with tempfile.TemporaryDirectory() as directory:
            tampered = Path(directory)
            payload = bytearray((folder / ramboot.FD_NAME).read_bytes())
            payload[12345] ^= 1
            (tampered / ramboot.FD_NAME).write_bytes(payload)
            (tampered / ramboot.STREAM_NAME).write_bytes(
                (folder / ramboot.STREAM_NAME).read_bytes())
            with self.assertRaisesRegex(ValueError, "FD size/SHA"):
                ramboot.build_plan(tampered)


if __name__ == "__main__":
    unittest.main()
