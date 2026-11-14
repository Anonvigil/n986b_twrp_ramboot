# UI10V live result and evidence

The successful session took place on 8 November 2026 with `SM-N986B / N986BXXU0ATE3`. The public, device-identifier-free facts are in [`ui10v-public.json`](../evidence/ui10v-public.json). SHA-256 values allow a holder of the original local artifacts to compare the exact bytes without distributing firmware, TWRP or RAM dumps.

## Independent observations

1. The sender recorded 162,560 acknowledged 512-byte payload packets, nine setup OUT transfers and one terminal OUT transfer. This establishes transport completion for the recorded image.
2. A later `BOOTLOADER UPLOAD` capture read the stream, FD, callback and runtime FDT twice. The two stream reads equalled the sent source byte-for-byte. FDT checks found VTS and storage nodes disabled.
3. A structural scan of the A/B Linux printk ring found 14,717 valid records. Recovery mode was selected, the `recovery` service started at about 63.374 seconds, and later records ran under task name `recovery`.
4. Three photos show the TWRP main menu, an empty Mount screen and File Manager browsing `/dev`. The distinct screens support the reported touch navigation.
5. After the RAM session, a separate Android ADB receipt reported boot complete, Knox warranty bit `0`, Verified Boot `green` and Debug High `0x4948` on that device.

## Photographs

| View | Evidence |
| --- | --- |
| [Main menu](../evidence/photos/twrp-main.jpg) | TWRP `3.7.0_11-0` GUI displayed |
| [Mount](../evidence/photos/twrp-mount.jpg) | No listed partitions; Storage displays `0 MB` |
| [File Manager](../evidence/photos/twrp-file-manager.jpg) | `/dev` could be browsed through the UI |

The photographs preserve their source SHA-256 values in the public manifest. They contain color-profile metadata but no GPS or device serial metadata in the examined EXIF tags.

## Measurement limits

The custom `/dev/kmsg` markers expected before and during recovery were absent from both the A2 and `sec_debug_next_full` captures. The live result relies on valid recovery records plus photographs; the mere presence of marker text in the initramfs is not execution proof.

The tested FDT deliberately disabled `/ufs@0x13100000`, `/ufs-srpmb`, `/dwmmc2@132E0000` and VTS. The empty Mount page is consistent with that design. This run did not prove partition access, backup, restore, Install/Wipe behavior, MTP, recovery ADB, or permanent recovery installation. A later storage-enabled experiment would need its own write-boundary review and evidence.

The reported Knox/Verified Boot properties are post-run Android observations. They are not a physical fuse measurement or a guarantee for other phones and firmware versions.
