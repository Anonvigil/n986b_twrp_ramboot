# Sources, dependency closure and release policy

## Upstream inputs

- [Team Win's official `c2s` downloads](https://dl.twrp.me/c2s/) supplied the `3.7.0_11-0` recovery image used as a local build input. Its SHA-256 in this run was `8a4dc7914d5ce0b6e2dae900433a853ad35a1606b5a94f3e9042ae85c6f2a771`. Team Win asks that its images not be mirrored; this repository contains no recovery image or extracted recovery binaries. [TWRP source](https://github.com/TeamWin/android_bootable_recovery) is available separately.
- The RAM transport research was based in part on [Osmium](https://git.froth.zone/max/osmium). The local upstream snapshot was commit `d0c50daa9e4284127803c990f8e1a49c01574f13`, licensed under the Unlicense. N986B's tested S-Boot Fastboot callback path is a device-specific extension; the older generic Download-mode path did not establish execution on this bootloader.
- The UEFI board/application work used EDK II and an Exynos990 board tree with separate BSD-style notices. The tested overlay and a pinned preparation/build recipe are in [`sources/efi`](../sources/efi/README.md); its extracted stock ECT is excluded. The stream reconstruction is in [`sources/twrp`](../sources/twrp/README.md). The tested device DTB and official TWRP image are supplied only locally.
- Windows candidate ZIPs bundle the matching DLL from [libusb v1.0.30](https://github.com/libusb/libusb/releases/tag/v1.0.30), dynamically loaded at runtime. The archive SHA-256 is pinned in the build workflow; the LGPL-2.1-or-later license text is in [`third_party/libusb-COPYING`](../third_party/libusb-COPYING).

## Three different reproducibility levels

| Level | What it means | Current status |
| --- | --- | --- |
| Verify the recorded result | Check public JSON/photo hashes and compare local frozen FD/stream hashes | Available with `scripts/verify_public_evidence.py` |
| Replay the frozen UI10V bytes | Send the exact FD/stream on the exact tested profile and capture new Upload evidence | Requires local image files, the launcher, operator profile confirmation and WinUSB/libusb setup; the new EXE still needs a live phone run |
| Reconstruct tested FD/stream | Use the pinned EFI overlay and stream recipe with external hash-checked inputs | The stream, initrd and FDT have been reconstructed byte-for-byte from the official TWRP image and the tested live N986B FDT. The EFI overlay builds an untested variant, but its FD/EFI hashes differ from the successful bytes; stock ECT and other binary inputs are not publicly bundled |
| Rebuild every component from source | Compile the Linux kernel and TWRP userspace, then make DTB, UEFI FD and stream | Exact upstream kernel/TWRP source revisions and a source-only component build remain unverified |

The historical UI10V preparation script was a derivative build from pinned earlier UI10 binaries. The original sender imports prior diagnostic modules and demands earlier A/B gate JSON files. Those dependencies do not fit a clean checkout. The new `scripts/ramboot.py` is a self-contained launcher candidate when its exact payload is provided locally; it must pass a new live N986B run before a tagged release describes it as tested. The frozen UI10V hashes identify the successful *old sender* run, not a new launcher validation.

## What this repository excludes

Generated `.fd`, `.efi`, `.dtb`, `.cpio.gz`, official recovery `.img`, ECT bytes, raw Upload RAM and unredacted ADB receipts are omitted from this public repository and release. The source receipts contain a device-unique ADB serial, so only the filtered public manifest is included. The exact stream embeds the complete official TWRP image; [Team Win's download page](https://dl.twrp.me/c2s/) prohibits mirroring without written permission. The successful EFI/FD also embeds an N986B stock ECT whose public redistribution rights have not been established. `scripts/package_local_bundle.py` verifies and bundles a user's locally held bytes for private use; it does not publish or download them.

Original code and documentation use the repository's MIT license. The three evidence photographs are excluded from that license; third-party software and firmware remain under their own terms. Keep the upstream Unlicense and other required notices with any copied upstream source.

## Release gates

1. Freeze and verify the executable source and all original/frozen artifact SHA-256 values.
2. Run host-only plan, malformed-file, wrong-profile, stale-receipt and fake-USB transfer tests. Confirm no USB opens during a plan or rejected send.
3. Build a Windows executable in a clean environment; run its help, plan and negative tests on a machine without the research workspace.
4. Obtain a new live N986B send receipt, TWRP screen/touch observation, A/B Upload capture and post-run Android state using that exact executable hash.
5. Audit staged files for device serials, personal paths, firmware/ECT/TWRP blobs and license notices. Include only approved photographs and derived evidence.
6. Label host-tested executable assets as prerelease candidates with their missing inputs and live-validation status. Promote to a stable release only after the exact executable passes a live N986B run and A/B Upload check. Do not publicly mirror the frozen payload without the relevant distribution rights; document where users obtain inputs and their hashes.
