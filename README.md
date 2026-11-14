# SM-N986B TWRP RAM boot

RAM-booting TWRP 3.7.0 on the Exynos Galaxy Note20 Ultra (SM-N986B) through S-Boot Fastboot and UEFI, with build notes, validation evidence, and documented limitations.

The RAM handoff uses overlong USB `SET_SEL` handling observed on the pinned ATE3 S-Boot build to control a Fastboot memory-write and callback path. This is a device-local finding, not a stock `fastboot boot` command. See the [vulnerability analysis](docs/FASTBOOT_VULNERABILITY.md) for evidence and scope.

## Observed result

| Gate | Result |
| --- | --- |
| Tested phone and bootloader | `SM-N986B`, `N986BXXU0ATE3` |
| Transfer | 162,560 × 512-byte payload packets; 162,570 acknowledged OUT transfers in the saved run |
| Boot path | Android → S-Boot Fastboot → RAM-loaded EDK II/UEFI → Exynos990 Linux recovery → TWRP |
| TWRP | `3.7.0_11-0` GUI displayed; touch navigation observed |
| Upload-mode verification | FD and package stream matched two RAM reads and the sent source |
| Storage | UFS, RPMB and DWMMC disabled in the tested FDT; Mount list empty |
| Return to Android | A later ADB receipt reported boot complete, warranty bit `0`, Verified Boot `green` |

![TWRP main menu](evidence/photos/twrp-main.jpg)

The [Mount screen](evidence/photos/twrp-mount.jpg) and [File Manager in `/dev`](evidence/photos/twrp-file-manager.jpg) show the scope of the demonstrated UI. No partition mount, backup, restore, recovery ADB/MTP, or permanent installation was validated.

## Read in order

1. [Porting design and memory map](docs/PORTING.md)
2. [Observed S-Boot Fastboot vulnerability and its limits](docs/FASTBOOT_VULNERABILITY.md)
3. [Exact tested profile and replay sequence](docs/REPLAY.md)
4. [Evidence and limits](docs/EVIDENCE.md)
5. [Inputs, provenance and publication status](docs/SOURCES_AND_RELEASE.md)
6. [Windows x86, x64 and Arm64 builds and USB setup](docs/WINDOWS.md)
7. [EFI source recipe](sources/efi/README.md) and [TWRP stream reconstruction](sources/twrp/README.md)

Run `python scripts/verify_public_evidence.py` to check the staged photos and public evidence manifest. If you hold the original local build outputs, `python scripts/verify_public_evidence.py --artifacts <directory>` also verifies the frozen FD, stream, EFI, FDT and initramfs hashes. This command performs no device I/O.

## Repository status

This is a **launcher, source recipe, documentation and evidence release candidate**. The new standalone launcher reproduces the pinned USB packet sequence and passes offline checks against the frozen UI10V bytes. It has not yet been run on the phone. The Linux/TWRP image, Samsung-derived DT/ECT material, raw RAM dumps and device receipts are not bundled in the public repository or release. A clean checkout cannot replay the boot until the exact FD and stream are supplied locally. The stream, initrd and FDT recipes reproduced the tested hashes from the official TWRP image and a separately supplied live N986B FDT. The EFI recipe requires the stock ECT and builds an untested variant whose hashes differ from the successful FD/EFI. A bit-for-bit FD rebuild and source-only builds of the official kernel and TWRP userspace remain unverified. The [release checklist](docs/SOURCES_AND_RELEASE.md) names the remaining work.

Windows candidate ZIPs contain x86, x64 or arm64 launchers with matching libusb DLLs and the documentation. A candidate ZIP alone is **not runnable**: its `artifacts/` payload is absent. With the exact successful files already held locally, run `scripts/package_local_bundle.py` or `scripts/build_local_windows.ps1` to create a private ZIP containing the launcher, DLL, FD and stream. The launcher then validates the payload before USB transfer. See the [replay steps](docs/REPLAY.md).

The original TWRP image was obtained from [Team Win's `c2s` download page](https://dl.twrp.me/c2s/). Team Win prohibits mirroring its images without written permission. The stream embeds that exact image, so the public release cannot include the successful stream without distribution rights. The recovery source is available from [Team Win](https://github.com/TeamWin/android_bootable_recovery).

Original code and documentation are [MIT licensed](LICENSE); the three evidence photographs and all third-party inputs are excluded. See [source notices](NOTICE.md).
