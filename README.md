# OnePlus 13 · Linux 6.18

An Android common kernel **6.18** port for the **OnePlus 13** (Snapdragon 8 Elite, **SM8750** / `sun`), with the vendor modules rebuilt for 6.18.

> **Status: work in progress — does not boot yet.** Only test with `fastboot boot` (see below); nothing here flashes your phone.

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
3. **Multimedia / connectivity drivers** (display, GPU, secure world, DSP, video, camera, audio, Wi-Fi, …) — Qualcomm techpack repos built for `sun`. *In progress.*
4. **OnePlus drivers** (`oplus_*`) — from OnePlus' SM8750 sources, ported to 6.18. *In progress.*
5. **Boot image** — the modules and their load lists are built into the kernel as an initramfs unpacked *after* the stock ramdisks, so they replace the 6.6 modules without touching `vendor_boot`, `init_boot` or `vendor_dlkm`. That is what lets a single `fastboot boot boot.img` test the whole thing. *In progress.*

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

```bash
fastboot boot boot.img
```

`fastboot boot` runs the image once from RAM; the next reboot is your installed kernel again. Keep root on the stock kernel so logs (`/sys/fs/pstore`) can be read after a failed attempt.

## Credits

- **[JiaqiLi404/android_kernel_618_for_sm8550](https://github.com/JiaqiLi404/android_kernel_618_for_sm8550)** — the Xiaomi 13 Pro (SM8550) 6.18 port this project is based on: its 6.12 → 6.18 SoC integration, the vendor-module build approach, the GKI edits and the boot-image method are reused here.
- **[OnePlusOSS](https://github.com/OnePlusOSS)** — [android_kernel_oneplus_sm8850](https://github.com/OnePlusOSS/android_kernel_oneplus_sm8850), [android_kernel_modules_and_devicetree_oneplus_sm8850](https://github.com/OnePlusOSS/android_kernel_modules_and_devicetree_oneplus_sm8850) and [android_kernel_modules_and_devicetree_oneplus_sm8750](https://github.com/OnePlusOSS/android_kernel_modules_and_devicetree_oneplus_sm8750).
- **Qualcomm** — the SoC and techpack drivers in those trees.
- **Google** — [Android Common Kernel](https://android.googlesource.com/kernel/common), [clang prebuilts](https://android.googlesource.com/platform/prebuilts/clang/host/linux-x86) and [mkbootimg](https://android.googlesource.com/platform/system/tools/mkbootimg).
- **[palazik/android_kernel_common_oneplus_sm8750](https://github.com/palazik/android_kernel_common_oneplus_sm8750)** — the OnePlus 13 6.6 kernel this port starts from.

## License

GPL-2.0, as the kernel sources it builds — see [LICENSE](LICENSE).
