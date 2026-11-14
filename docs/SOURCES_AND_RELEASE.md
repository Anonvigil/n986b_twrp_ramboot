# Sources, dependency closure and release policy

## Upstream inputs

- [Team Win's official `c2s` downloads](https://dl.twrp.me/c2s/) supplied the `3.7.0_11-0` recovery image used as a local build input. Its SHA-256 in this run was `8a4dc7914d5ce0b6e2dae900433a853ad35a1606b5a94f3e9042ae85c6f2a771`. Team Win asks that its images not be mirrored; this repository contains no recovery image or extracted recovery binaries. [TWRP source](https://github.com/TeamWin/android_bootable_recovery) is available separately.
- The RAM transport research was based in part on [Osmium](https://git.froth.zone/max/osmium). The local upstream snapshot was commit `d0c50daa9e4284127803c990f8e1a49c01574f13`, licensed under the Unlicense. N986B's tested S-Boot Fastboot callback path is a device-specific extension; the older generic Download-mode path did not establish execution on this bootloader.
- The UEFI board/application work used EDK II and an Exynos990 board tree with separate BSD-style notices. Any copied source should carry its original headers and full applicable license texts. Proprietary device-tree/ECT material is excluded from this public candidate.
- Windows candidate ZIPs bundle the matching DLL from [libusb v1.0.30](https://github.com/libusb/libusb/releases/tag/v1.0.30), dynamically loaded at runtime. The archive SHA-256 is pinned in the build workflow; the LGPL-2.1-or-later license text is in [`third_party/libusb-COPYING`](../third_party/libusb-COPYING).

## Three different reproducibility levels

| Level | What it means | Current status |
| --- | --- | --- |
| Verify the recorded result | Check public JSON/photo hashes and compare local frozen FD/stream hashes | Available with `scripts/verify_public_evidence.py` |
| Replay the frozen UI10V bytes | Send the exact FD/stream on the exact tested profile and capture new Upload evidence | Requires local image files, validated sender, fresh profile receipt and WinUSB/libusb setup |
| Rebuild independently from source | Recreate the kernel, TWRP initramfs, DTB, UEFI FD and stream | Exact source revisions, configuration, patches, toolchain and redistributable inputs still need packaging |

The historical UI10V preparation script was a derivative build from pinned earlier UI10 binaries. The original sender imports prior diagnostic modules and demands earlier A/B gate JSON files. Those dependencies do not fit a clean checkout. The new `scripts/ramboot.py` is intended as a self-contained launcher candidate; it must pass offline negative tests and a new live N986B run before a tagged release describes it as tested. The frozen UI10V hashes identify the successful *old sender* run, not a new launcher validation.

## What this repository excludes

Generated `.fd`, `.efi`, `.dtb`, `.cpio.gz`, official recovery `.img`, ECT bytes, raw Upload RAM and unredacted ADB receipts are omitted. The source receipts contain a device-unique ADB serial, so only the filtered public manifest is included. These exclusions also prevent accidentally mirroring Team Win's image.

Original code and documentation use the repository's MIT license. The three evidence photographs are excluded from that license; third-party software and firmware remain under their own terms. Keep the upstream Unlicense and other required notices with any copied upstream source.

## Release gates

1. Freeze and verify the executable source and all original/frozen artifact SHA-256 values.
2. Run host-only plan, malformed-file, wrong-profile, stale-receipt and fake-USB transfer tests. Confirm no USB opens during a plan or rejected send.
3. Build a Windows executable in a clean environment; run its help, plan and negative tests on a machine without the research workspace.
4. Obtain a new live N986B send receipt, TWRP screen/touch observation, A/B Upload capture and post-run Android state using that exact executable hash.
5. Audit staged files for device serials, personal paths, firmware/ECT/TWRP blobs and license notices. Include only approved photographs and derived evidence.
6. Tag a release only after the live executable run passes. Document where users obtain the required image inputs and their hashes.
