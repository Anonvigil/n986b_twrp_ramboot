# TWRP/Linux input reconstruction

`build_ui10v_stream.py` reconstructs the **exact tested UI10V RAM stream** from
two inputs that are not committed here. It performs file operations only; it
has no USB or device access. The generated stream matched the recorded
75,890,688-byte file at SHA-256
`d1bfd029728be897f6bc5721e1c1abfcab41b0a84d5ca20591b8ea0911304f7b`.

## Inputs

| Input | SHA-256 | Why it is needed |
| --- | --- | --- |
| Official Team Win `twrp-3.7.0_11-0-c2s.img` | `8a4dc7914d5ce0b6e2dae900433a853ad35a1606b5a94f3e9042ae85c6f2a771` | Contains the exact Linux kernel and TWRP recovery userspace used in the successful run. Obtain it from [Team Win's `c2s` page](https://dl.twrp.me/c2s/) and check the hash locally. |
| Device-specific, already merged and storage-disabled base DTB | `78eae5000a548edca8e5ad80f73a1b28b2e443b9d26ddd10f7b0e84adac9f35c` | Contains the tested N986B memory map, overlay, and disabled `/ufs@0x13100000`, `/ufs-srpmb`, and `/dwmmc2@132E0000` nodes. This repository does not distribute this derived device binary. |

The base DTB was prepared from the selected recovery device tree, overlay 4,
and the N986B memory map, then edited to disable the three storage controllers.
The hash is the input contract for this exact rebuild. A different N986B
revision needs a separately measured DTB and cannot claim byte-for-byte
equivalence with this UI10V run.

## Rebuild

Install Python 3 and `fdtput` from `device-tree-compiler`. For example, run
the following from a WSL/Linux shell in the repository root:

```sh
python3 sources/twrp/build_ui10v_stream.py \
  --official-image /path/to/twrp-3.7.0_11-0-c2s.img \
  --base-dtb /path/to/n986b-storage-disabled-base.dtb \
  --output-dir /path/to/private-output
```

The script checks the input hashes, archive member count, original recovery
executable, intermediate and final DTBs, final initrd, component placement,
and the complete stream hash. It stops on a mismatch. Successful output:

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `n986b-twrp-ui10v-ramdisk.cpio.gz` | 17,667,760 | `078814b1c8bf94153a1cdda1a076161eb9f5ab68cf58acd7691076dee811f436` |
| `n986b-twrp-ui10v-vts-disabled.dtb` | 528,004 | `f055c5915815a705f196fd236ff24856859092fc88fcb4a2be3fd0e2de148769` |
| `recovery-ui10v-ram-stream.bin` | 75,890,688 | `d1bfd029728be897f6bc5721e1c1abfcab41b0a84d5ca20591b8ea0911304f7b` |

## What is source and what is an input

The script contains the recovery init edits, deterministic gzip/newc
repacking, FDT edits, manifest layout, and SHA-256 gates. The checked-in
[`official-kernel.config`](official-kernel.config) is the configuration
extracted from the tested kernel (SHA-256 of this text file:
`8f9ef96d47f491b64ddb7c9c442e1fa70994eae9bfb68824d4e8db181acc680e`).
It helps compare future kernel builds, but is not the kernel source or a proof
that a newly compiled kernel is byte-identical. The exact kernel and recovery
userspace source revisions used by the upstream image have not been established.
[Team Win's recovery source](https://github.com/TeamWin/android_bootable_recovery)
is available upstream, and the kernel source must be matched separately to
the official recovery image before a source-only rebuild can be claimed.

The tested UEFI FD is built separately; see the EFI source recipe in this
repository. Its original stock ECT input is not included. None of the image,
DTB, initrd, or ECT bytes are committed in this directory. The script's output
is not a flashable recovery image and is not a device-independent TWRP build.
