# Replay the frozen UI10V RAM boot

This guide applies to the exact recorded `SM-N986B / N986BXXU0ATE3` profile and UI10V bytes. The release-candidate launcher has **not yet had its own live N986B run**; the successful TWRP run used the earlier research sender. The launcher performs the same pinned packet sequence and must be validated on the phone before being promoted to a tested release.

## Files to prepare on the Windows host

```text
N986B-TWRP-RAMBOOT.exe            x86, x64 or arm64 build matching the PC
libusb-1.0.dll                    bundled with each Windows candidate ZIP
evidence/
  fbinput-analysis.json
  vts-off-analysis.json
artifacts/                        local private inputs; never commit
  N986B-TWRP-UI10V-VTS-OFF-RAM.fd
  recovery-ui10v-ram-stream.bin
  N986BUi10V.efi                  optional independent hash check
  n986b-twrp-ui10v-vts-disabled.dtb       optional
  n986b-twrp-ui10v-ramdisk.cpio.gz        optional
private/                          local receipts; never commit
```

The FD and stream are required and their sizes/SHA-256 must match [`ui10v-public.json`](../evidence/ui10v-public.json). The stream contains TWRP userspace and is not redistributed here. The EXE does not create the image from the official `c2s` download. An exact UI10V image must be built or otherwise available locally; the current repository is not a source-complete image builder. The two evidence JSON files are included to preserve the exact prior A/B gates from the successful development sequence.

## 1. Capture a fresh Android receipt

Install Google's Android SDK Platform-Tools so `adb` is on `PATH`, then keep
stock Android running with one authorized ADB device connected:

```powershell
.\N986B-TWRP-RAMBOOT.exe prepare --receipt .\private\adb.json --adb adb
```

The command reads `ro.product.model`, bootloader, warranty bit, Verified Boot state and Debug High. It stores the connected device's serial **only in the local private receipt** so the run can be tied to the current handset. The receipt expires after 15 minutes; rerun `prepare` to replace it with a fresh receipt. Do not upload it. `prepare` does not enter Fastboot or write to the phone.

Then enter S-Boot Fastboot:

```powershell
adb reboot bootloader
```

The tested phone shows `entering fastboot mode...`; Windows sees USB `18D1:0002`. This endpoint must be accessible through WinUSB/libusb. The preparation receipt proves the Android profile before the mode change; the launcher cannot re-read Android properties after Fastboot entry.

## 2. Check the frozen package

```powershell
.\N986B-TWRP-RAMBOOT.exe plan --artifacts .\artifacts
```

`plan` performs no USB I/O. It checks the FD/stream hashes, stream manifest geometry, component hashes, the 80-byte callback and the FDT's disabled VTS/storage nodes. The public evidence verifier offers an additional local-only check:

```powershell
python scripts\verify_public_evidence.py --artifacts .\artifacts
```

## 3. Execute from Fastboot

With the tested phone already in Fastboot, double-click the EXE or run its interactive launch mode from the directory layout above:

```powershell
.\N986B-TWRP-RAMBOOT.exe launch
```

The launcher validates the fresh Android receipt, both pinned prior A/B evidence files and the exact FD/stream before opening USB. It prints the profile and image hash and asks you to type `BOOT N986B`. It then performs the nine setup transfers, 162,560 separate 512-byte data transfers and one `UEFITERM` transfer. Its receipt distinguishes an acknowledged terminal transfer from a device disconnect after the payload. A completed host payload is a transport result; confirm TWRP on the screen.

For scripted use, the equivalent explicit command is:

```powershell
.\N986B-TWRP-RAMBOOT.exe send `
  --artifacts .\artifacts `
  --adb-receipt .\private\adb.json `
  --fbinput-evidence .\evidence\fbinput-analysis.json `
  --vts-evidence .\evidence\vts-off-analysis.json `
  --send-receipt .\private\send.json `
  --confirm-combined-sha256 4affaa0cf66ba86538204699a7d5daed34a84f05052e8fac67b4791c0e45e82d `
  --confirm-device-profile SM-N986B/N986BXXU0ATE3 `
  --confirm-resident-sboot-sha256 d0f631d6320977c5b7509ff1457ee8c22878ca6b39619653c8361389c2fa3080 `
  --confirm-warranty-bit-zero --confirm-debug-high
```

The resident S-Boot hash is a pin from the original analyzed image; the Fastboot interface does not independently re-hash it. The operator must use this profile only when the stock bootloader build and independently established S-Boot identity match. The sender never invokes a Fastboot flash or unlock command.

## 4. Interpret the phone and collect proof

The expected visual sequence is TianoCore/UEFI, Linux recovery boot, and TWRP `3.7.0_11-0`. Test only menu navigation for this storage-disabled image. The Mount page should have no partitions.

For an evidence run, photograph the GUI and inspect the current Linux printk ring through a separate read-only `BOOTLOADER UPLOAD` A/B capture. The research capture script and native Upload dumper are not included in this public candidate. Do not describe the new launcher as live-validated until its exact executable hash, send receipt, Upload equality and TWRP screen are recorded together.

To enter Upload from the TWRP screen on the tested device, hold Volume Down + Power through screen-off until `BOOTLOADER UPLOAD` is actually displayed. The recorded Upload USB ID was `04E8:685D`. A release at screen-off may restart Android. The original trial used a one-shot host reset after capture; a later ADB receipt checked Android's reported state.
