# OnePlus 13 · Linux 6.18

An Android common kernel **6.18** port for the **OnePlus 13** (Snapdragon 8 Elite, **SM8750** / `sun`), with the vendor modules rebuilt for 6.18.

> **Status: first test images — not booted on a phone yet.** Only test with `fastboot boot` (see below); nothing here flashes your phone.

| | |
|:--|:--|
| Device | OnePlus 13, SM8750 |
| Target ROM | ColorOS 16.0.10 CN (stock kernel `6.6.118-android15-8`) |
| Kernel | ACK `android17-6.18` at 6.18.32 (`ff4a6c3b`) |
| Builds | [GitHub Actions](../../actions) — kernel `Image` and modules as artifacts |

## How it works

A 6.6 kernel's vendor modules cannot load on 6.18, so the port is mostly about the modules:

1. **Kernel** — Google's ACK 6.18 with a small set of edits the vendor drivers need ([`tools/prep_common.sh`](tools/prep_common.sh)) and `gki_defconfig` plus a few options ([`tools/config_gki.sh`](tools/config_gki.sh)).
2. **SoC drivers** — clocks, pinctrl, interconnects, RPMh, SMMU, UFS, USB, … from OnePlus' SM8850 (OnePlus 15) kernel tree, which already carries the SM8750 `sun` target. The 6.12 → 6.18 adaptation comes from the Xiaomi 13 port (see credits); the build uses the `sun_perf` config ([`scripts/build_soc.sh`](scripts/build_soc.sh), [`configs/op13_overrides.bzl`](configs/op13_overrides.bzl)).
3. **Multimedia / connectivity drivers** — Qualcomm techpack repos built for `sun` ([`scripts/build_tp.sh`](scripts/build_tp.sh)): secure world (smcinvoke, qseecom, …), synx, fences, MMRM, DSP (fastrpc), display (`msm_drm`) and GPU (`msm_kgsl`). Only the reference port's generic 6.18 fixes are applied — not its adaptations to Xiaomi's 5.15-era user space: the OnePlus 13's user space speaks the 6.12 release's interfaces. *Video, camera, audio, Wi-Fi, Bluetooth: not yet.*
4. **OnePlus drivers** — the boot modules (`oplusboot`, boot mode, project info, …) from OnePlus' SM8750 sources ([`scripts/build_oplus.sh`](scripts/build_oplus.sh)). *The other `oplus_*` modules (scheduler, storage, charger, …): not yet.*
5. **Boot image** ([`scripts/build_bootimg.sh`](scripts/build_bootimg.sh)) — the modules and their load lists are built into the kernel as an initramfs unpacked *after* the stock ramdisks, so they replace the 6.6 modules without touching `vendor_boot`, `init_boot` or `vendor_dlkm`. That is what lets a single `fastboot boot boot.img` test the whole thing. First-stage init loads the phone's own first-stage order; the second stage's modules (USB, remoteproc, secure world, display, GPU, …) are loaded right after it, one child process each, by the reference's batch loader (the ramdisk is gone after `switch_root`). `op13_modload_tolerate=1` on the command line makes a module that fails to load a log line instead of the end of the boot.

The stock device tree (in `vendor_boot`) stays in use, so the drivers have to match OnePlus' SM8750 bindings.

## Building

Every push to `main` builds in GitHub Actions (Google's clang `r584948c`, ccache). Locally, on an x86_64 or arm64 Linux host:

```bash
bash scripts/fetch.sh        # all sources at pinned revisions (src/, ref_8550/)
bash scripts/get_clang.sh    # Google's clang (x86_64 hosts; otherwise clang from PATH)
bash scripts/build_gki.sh    # kernel -> out/gki
bash scripts/build_soc.sh    # SoC modules for sun -> src/soc/**/*.ko
```

[`tools/remote_payload.py`](tools/remote_payload.py) pulls single partitions out of an OTA zip over HTTP without downloading the whole package (`list`, or `extract OUTDIR boot vendor_boot ...`).

## Testing

Download `boot.img` from the latest successful run's artifact (`op13-618-<n>` on the [Actions](../../actions) page), then:

```bash
adb reboot bootloader
fastboot boot boot.img
```

`fastboot boot` runs the image once from RAM; the next reboot is your installed kernel again. **Never `fastboot flash` these images.**

After a failed attempt, boot your normal system and save the previous boot's log (needs root on the stock kernel):

```bash
adb shell su -c 'cat /sys/fs/pstore/console-ramoops*' > console-ramoops.txt
adb shell su -c 'ls -la /sys/fs/pstore'
```

`qcom_dynamic_ramoops` is the first module the image loads, so the log covers the first stage too. Look for `op13:` lines — modules that did not load.

## Credits

- **[JiaqiLi404/android_kernel_618_for_sm8550](https://github.com/JiaqiLi404/android_kernel_618_for_sm8550)** — the Xiaomi 13 Pro (SM8550) 6.18 port this project is based on: its 6.12 → 6.18 SoC integration, the vendor-module build approach, the GKI edits and the boot-image method are reused here.
- **[OnePlusOSS](https://github.com/OnePlusOSS)** — [android_kernel_oneplus_sm8850](https://github.com/OnePlusOSS/android_kernel_oneplus_sm8850), [android_kernel_modules_and_devicetree_oneplus_sm8850](https://github.com/OnePlusOSS/android_kernel_modules_and_devicetree_oneplus_sm8850) and [android_kernel_modules_and_devicetree_oneplus_sm8750](https://github.com/OnePlusOSS/android_kernel_modules_and_devicetree_oneplus_sm8750).
- **Qualcomm** — the SoC and techpack drivers in those trees.
- **Google** — [Android Common Kernel](https://android.googlesource.com/kernel/common), [clang prebuilts](https://android.googlesource.com/platform/prebuilts/clang/host/linux-x86) and [mkbootimg](https://android.googlesource.com/platform/system/tools/mkbootimg).
- **[palazik/android_kernel_common_oneplus_sm8750](https://github.com/palazik/android_kernel_common_oneplus_sm8750)** — the OnePlus 13 6.6 kernel this port starts from.

## License

GPL-2.0, as the kernel sources it builds — see [LICENSE](LICENSE).
