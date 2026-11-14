# Source notices

`scripts/ramboot.py` adapts the callback encoding and USB transfer sequence from
[Osmium](https://git.froth.zone/max/osmium), local revision
`d0c50daa9e4284127803c990f8e1a49c01574f13`. Osmium's repository declares
the [Unlicense](https://unlicense.org/). The N986B profile and UI10V validation
logic were added for this experimental release candidate.

The linked [Team Win recovery source](https://github.com/TeamWin/android_bootable_recovery)
and [official `c2s` image page](https://dl.twrp.me/c2s/) are separate upstream
projects. This repository does not contain their recovery image or executable.

Windows candidate ZIPs bundle the matching `libusb-1.0.dll` from the official
[libusb v1.0.30 release](https://github.com/libusb/libusb/releases/tag/v1.0.30).
libusb is licensed under LGPL-2.1-or-later. Its complete license text is in
[`third_party/libusb-COPYING`](third_party/libusb-COPYING); corresponding source
is available from the linked release. The DLL remains a separate dynamically
loaded library and is not covered by this repository's MIT license.

The MIT license in this repository covers original code and documentation.
The three evidence photographs are excluded from that license, as are all
third-party software and firmware inputs.
