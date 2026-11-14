# Source notices

`scripts/ramboot.py` adapts the callback encoding and USB transfer sequence from
[Osmium](https://git.froth.zone/max/osmium), local revision
`d0c50daa9e4284127803c990f8e1a49c01574f13`. Osmium's repository declares
the [Unlicense](https://unlicense.org/). The N986B profile and UI10V validation
logic were added for this experimental release candidate.

The [EFI source overlay](sources/efi/README.md) derives from the Exynos EDK II
board tree and TianoCore components. Their copyright and redistribution terms
are retained in source headers and [the board-tree license](sources/efi/UPSTREAM_LICENSE).
The stock ECT input used for the tested FD is not included in this repository.

The linked [Team Win recovery source](https://github.com/TeamWin/android_bootable_recovery)
and [official `c2s` image page](https://dl.twrp.me/c2s/) are separate upstream
projects. Team Win's download page prohibits mirroring its content without
written permission. The tested RAM stream embeds the official recovery image,
so it is excluded from the public repository and release. The local-use bundle
builder does not download or publish it.

Windows candidate ZIPs bundle the matching `libusb-1.0.dll` from the official
[libusb v1.0.30 release](https://github.com/libusb/libusb/releases/tag/v1.0.30).
libusb is licensed under LGPL-2.1-or-later. Its complete license text is in
[`third_party/libusb-COPYING`](third_party/libusb-COPYING); corresponding source
is available from the linked release. The DLL remains a separate dynamically
loaded library and is not covered by this repository's MIT license.

The MIT license in this repository covers original code and documentation,
except the separately licensed EFI source overlay.
The three evidence photographs are excluded from that license, as are all
third-party software and firmware inputs.
