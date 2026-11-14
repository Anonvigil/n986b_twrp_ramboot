# Porting design: N986B RAM-loaded recovery

## Target and measured boundary

The successful profile is `SM-N986B / N986BXXU0ATE3`, Exynos 990. The tested UI10V image starts from Android, enters Samsung S-Boot Fastboot (`18D1:0002`), sends a volatile UEFI firmware volume and high-memory package, starts an AArch64 UEFI application, then hands off to a Linux recovery kernel and initramfs. Linux starts the TWRP `recovery` service. The tested image leaves UFS/RPMB/DWMMC disabled, so the GUI has no usable partition list.

This profile's S-Boot offsets, callback ABI, RAM map and kernel device tree are build-specific. A matching model number alone does not establish compatibility. Capture a new bootloader and RAM profile for a different firmware or device revision.

## Boot chain

```text
Android ADB
  └─ adb reboot bootloader
     └─ S-Boot Fastboot (USB 18D1:0002)
        └─ callback-assisted RAM transfer, FD + high package + UEFITERM
           └─ EDK II/TianoCore UEFI (FD at 0x90000000)
              └─ N986BUi10V.efi, GUID F9F65EBA-151E-4DFC-AA46-D6015D924DD9
                 └─ Exynos990 Linux recovery kernel, DTB, initramfs
                    └─ Android recovery init → TWRP 3.7.0_11-0
```

The transport is a device-specific S-Boot callback path. It is not the standard `fastboot boot` command. In the tested run the 80-byte high-stream callback staged at `0x8B000000` used entry `0xE81EC280` and next-packet pointer `0xE83483F8`. These addresses came from the exact resident S-Boot image with SHA-256 `d0f631d6320977c5b7509ff1457ee8c22878ca6b39619653c8361389c2fa3080`. They are a record of this run, not offsets to apply blindly elsewhere.

The transfer sent the 0x700000-byte FD to `0x90000000`, then the package from `0xA8000000` through `0xAC860000`. Its terminal packet was ASCII `UEFITERM` (`55 45 46 49 54 45 52 4D`). A host acknowledgement established receipt by the transport; the later Linux records and phone screen established execution.

## Memory layout

| Region | Physical address | Purpose |
| --- | --- | --- |
| UEFI FD | `0x90000000..0x90700000` | Firmware volume and boot application |
| High package | `0xA8000000..0xAC860000` | 4 KiB manifest, kernel image, FDT and initramfs |
| Linux kernel destination | `0xA0080000` | Within `0xA0000000..0xA3000000` reservation |
| Runtime initramfs | `0xA4000000..0xA50D96B0` | Within `0xA4000000..0xA6000000` reservation |
| Runtime FDT | `0xA6000000` | Within 2 MiB reservation |
| ECT copy | `0xA7000000` | 0x4B000 bytes within a 0x50000 span |

The UEFI application checks component SHA-256 hashes, claims exact EFI pages, copies each component into its reserved destination, prepares the Exynos990 handoff context, exits boot services, and enters Linux. The application file GUID must match the UEFI boot option. A previous mismatch reached UEFI Shell instead of Linux. Kernel and initramfs destinations must be checked against the current UEFI memory map: an earlier attempt detected an overlap.

## Build stages that produced UI10V

1. **Profile the target.** Read the model, bootloader build, reported warranty/Verified Boot/Debug High state and resident S-Boot hash. Capture a live memory map and device tree. Map every transport and Linux destination and prove there is no overlap.
2. **Prepare the recovery userspace.** The tested executable was TWRP `3.7.0_11-0` from the official `c2s` recovery image. Build an initramfs with Android recovery init, the executable and its libraries. Arrange `/dev/fb0` before starting `recovery`. The tested fstab had no block entries.
3. **Prepare the kernel and DTB.** Use the N986B Exynos990 Linux recovery kernel and matching FDT. Merge the runtime memory reservations and boot arguments. For the proven UI10V FDT, `/ufs@0x13100000`, `/ufs-srpmb`, `/dwmmc2@132E0000` and `/vts@0x15510000` had `status = "disabled"`. The UI10 → UI10V semantic FDT change was only the VTS status. Its ten initcall blacklist tokens were frozen in the build manifest; they apply to this exact kernel.
4. **Build the UEFI application and FD.** Include the boot application under GUID `F9F65EBA-151E-4DFC-AA46-D6015D924DD9`; target AARCH64 EDK II `DEBUG`/`CLANG38` in the recorded build. Package a 0x700000-byte FD and a high stream with a 4 KiB manifest carrying physical addresses, sizes and SHA-256 values.
5. **Check on the host.** Parse the FDT and manifest, verify all component hashes and memory bounds, test positive and negative cases of the sender and Upload verifier, and inspect the exact compiled FD/stream hashes. A byte-different build is a new candidate.
6. **Run and prove one candidate.** Obtain fresh Android and prior diagnostic receipts, transfer into S-Boot Fastboot, observe UEFI/Linux/TWRP, capture Upload RAM twice, inspect structurally valid Linux recovery records, then verify the Android state after reset.

The recorded UI10V builder was a *derivative* build: it took a pinned earlier UI10 stream/initramfs and made the VTS-only DT change plus updated UEFI hashes. A complete clean-room kernel/TWRP source build needs the exact upstream revisions, configuration, patches and all redistributable inputs to be added and checked separately. [Sources and release status](SOURCES_AND_RELEASE.md) tracks this dependency gap.

## Known stop signatures

| Screen or log | Check |
| --- | --- |
| TianoCore then UEFI Shell | Application FFS GUID, boot-option GUID, FD hash and inclusion |
| `claiming exact EFI pages for Linux handoff` | Read current-run Linux printk RAM; this is the final UEFI console line, not proof of Linux entry |
| Automatic `BOOTLOADER UPLOAD` | Capture crash RAM; check the last valid initcall and exception |
| `samsung_vts_probe` exception | Compare the VTS-only FDT delta and UI10V DTB hash |
| TWRP menu with empty Mount | Expected from the tested storage-disabled FDT |
