# N986B UI10V EFI and FD build sources

This directory carries the N986B-specific EDK II source overlay for the
RAM-booted TWRP GUI demonstration. It is scoped to the tested UI10V VTS-off
firmware, not the earlier diagnostic variants. `overlay/` contains the exact
UI10V application, its EDK II platform descriptions, the high-RAM memory map,
and the required platform changes. The upstream EDK II tree and its submodules
are pinned below instead of copied into this repository.

The public source cannot produce the frozen binary by itself: the loader
embeds a **stock N986B ECT** copied from the owner's device. That 0x4B000-byte
firmware input is intentionally absent from Git. `prepare_sources.py` accepts
it locally and refuses a size or SHA-256 mismatch. Never commit the generated
`N986BFreshFullEct.h` or the raw ECT.

## Pinned inputs

| Input | Revision or identity |
| --- | --- |
| [edk2-exynos](https://github.com/sonic011gamer/edk2-exynos) | `c00035413a9df469414b31529640bf1da28859db` |
| [TianoCore edk2](https://github.com/tianocore/edk2) submodule | `e7aac7fc137e247edad22f7ee53b9a1fba227397` |
| [edk2-platforms](https://github.com/tianocore/edk2-platforms) submodule | `982212662c71b6c734b7578526071d6b78da3bcc` |
| [SimpleInit](https://github.com/BigfootACA/simple-init) submodule | `29e062805776db5ab7a61d07ef040d43aed71161` |
| `Platform/EFI_Binaries` submodule | `87ac13a39d88790fd1a7f4bf5550f14aa3d8ed15` |
| LLVM MinGW toolchain | `llvm-mingw-20261020`, UCRT x86-64 Windows build |
| Stock ECT, supplied separately | 307,200 bytes, SHA-256 `32a642074aa5168aede2cededf3af62c13cd20eb9212517fe517bfbfbbc70caa` |

The upstream `Platform/EFI_Binaries` submodule contains a prebuilt
`LinuxSimpleMassStorage.efi` referenced by the firmware volume. Its source is
identified in that submodule's INF as
[BigfootACA/linux-simple-mass-storage](https://github.com/BigfootACA/linux-simple-mass-storage).
Keep the upstream submodules and their license notices intact when publishing
derived firmware. The EDK II board source is BSD-2-Clause; SimpleInit includes
GPL components and other separately licensed libraries.

## Build on Windows

Install Git, Python 3, LLVM MinGW `20261020`, GNU Make for Windows, and the
EDK II BaseTools executables for Windows (`GenFv.exe`, `GenFw.exe`, `GenSec.exe`,
and the other BaseTools programs). Build BaseTools from the pinned edk2 source
if they are unavailable, following the
[TianoCore Windows setup guide](https://www.tianocore.org/tianocore-wiki.github.io/build-tooling/environment-setup/windows_systems.html).
The Python and PowerShell entry points use no machine-specific paths.

```powershell
git clone https://github.com/sonic011gamer/edk2-exynos.git edk2-exynos
git -C edk2-exynos checkout c00035413a9df469414b31529640bf1da28859db
git -C edk2-exynos submodule update --init --recursive

python sources/efi/prepare_sources.py --tree edk2-exynos --ect C:\private\N986B-stock-ECT.bin
powershell -ExecutionPolicy Bypass -File sources/efi/build_ui10v.ps1 `
  -Tree edk2-exynos -LlvmBin C:\toolchains\llvm-mingw-20261020\bin `
  -MakeExe C:\toolchains\make\make.exe
```

Run these commands from this repository's root; the `edk2-exynos` clone may be
placed elsewhere by changing `--tree` and `-Tree`. A short absolute path is
recommended because EDK II generates deep build paths. The preparation step
checks the top-level commit and each submodule, overlays 19 source files,
generates the private ECT C header, and creates `work/edk2-conf`. The build
uses `DEBUG_CLANG38`, AARCH64, an FD base of `0x90000000`, and an FD size of
`0x700000`.

Expected outputs within the EDK II clone:

```text
Build/ui10v/DEBUG_CLANG38/FV/EXYNOS990_UEFI.fd
Build/ui10v/DEBUG_CLANG38/AARCH64/N986BUi10V.efi
```

The tested frozen artifacts are labeled `N986B-TWRP-UI10V-VTS-OFF-RAM.fd`
(SHA-256 `0ac10b5ae7ed996102d4ff74ee8f0d2002d57088fa804c93a1d2b271ebb06c01`)
and `N986BUi10V.efi`
(SHA-256 `a274548662f9c88167facf96e1bbe3aa0a7bedf2e2e0c7f589364af2abcd1fa5`).
The script recreates the source configuration; matching these binary hashes
also requires the exact toolchain, BaseTools, stock ECT, and build environment.
A fresh independent build and hash match have not yet been demonstrated.

## Boot contract

`N986BUi10V.inf` uses firmware-file GUID
`F9F65EBA-151E-4DFC-AA46-D6015D924DD9`, which the platform boot manager
selects when `N986B_RECOVERY_RELOCATED_ECT_BRANCH_BOOT=1`. The loader reads
the separate RAM stream at `0xA8000000` and hands off a Linux kernel with a
relocated initramfs and FDT. The FD alone does not contain the TWRP kernel,
initramfs, or full stream; see the sibling TWRP source recipe for those inputs.

The tested UI10V FDT disables UFS, RPMB, eMMC, and VTS. This was a RAM-only GUI
demonstration. The empty Mount page is expected; do not infer working backup,
restore, install, decryption, or block-device support from the GUI photos.

## Overlay provenance

The overlay copies changed files from the tested UI10V source snapshot.
Existing upstream files keep their original copyright headers. The original
stock ECT byte array, generated build products, extracted device partitions,
and unrelated diagnostic branches are excluded. Review upstream and
submodule license terms before redistributing a newly built FD.
