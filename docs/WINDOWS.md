# Windows launcher builds

The release-candidate launcher is built with PyInstaller 6.22.3. The GitHub Actions matrix creates **x86** and **x64** console EXEs with Python 3.9 and an **arm64** EXE with Python 3.13. PyInstaller documents support for Windows 8 and newer; this project targets Windows 10 and 11 hosts. The x86 build is the candidate for Windows 10 on Arm, where Microsoft documents x86 application emulation. The native arm64 build targets Windows 11 on Arm. This project has not yet tested the launcher on every host architecture or Windows release.

## Build locally

From the repository root on a Windows host with the desired Python architecture:

```powershell
py -3.9 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -m unittest discover -s scripts -p 'test_*.py' -v
.\.venv\Scripts\python.exe -m PyInstaller --onefile --console --clean --name N986B-TWRP-RAMBOOT scripts\ramboot.py
.\dist\N986B-TWRP-RAMBOOT.exe --help
```

Build x86 with a 32-bit Python installation and x64 with a 64-bit one; check with `python -c "import struct; print(struct.calcsize('P') * 8)"`. PyInstaller is not a cross-compiler. The workflow uses the architecture selector in GitHub's official `setup-python` action. [PyInstaller support matrix](https://pypi.org/project/pyinstaller/6.22.3/), [setup-python architecture input](https://github.com/actions/setup-python/blob/main/README.md), [Windows 11 Arm runner](https://github.com/actions/runner-images/blob/main/README.md), [Microsoft Windows on Arm emulation note](https://github.com/MicrosoftDocs/windows-dev-docs/blob/docs/landing/arm-docs/apps-on-arm-x86-emulation.md).

For a native arm64 local build on Windows 11 on Arm, use arm64 Python 3.13 instead of the `py -3.9` line above. The x86 candidate is the Windows 10 on Arm fallback. The workflow pins libusb v1.0.30 by archive SHA-256, bundles the x86/x64 MinGW DLLs or native arm64 DLL, and runs a no-phone DLL probe for each build.

## Runtime inputs

The EXE does not include the frozen FD/stream or TWRP binary. Use local files whose hashes match [`ui10v-public.json`](../evidence/ui10v-public.json). The candidate ZIP bundles a matching-architecture `libusb-1.0.dll` from the pinned [upstream v1.0.30 release](https://github.com/libusb/libusb/releases/tag/v1.0.30); its LGPL-2.1-or-later text is included. For local EXE builds, place the matching DLL beside the EXE. The device's Fastboot interface must have a compatible WinUSB driver; follow libusb's [Windows backend guidance](https://github.com/libusb/libusb/wiki/Windows). Google's [Android SDK Platform-Tools](https://developer.android.com/tools/releases/platform-tools) supplies `adb` for the separate Android receipt step. Do not substitute a DLL of the other process architecture.

The launcher targets the **SM-N986B ATE3 phone profile** regardless of which supported Windows host architecture runs it. The candidate workflow runs `probe-usb` with the bundled DLL on each architecture, without opening the phone. A Windows build passing these checks does not establish a successful USB transfer on every PC. WinUSB setup and a new live N986B run with an A/B Upload check remain necessary before any executable is described as proven.
