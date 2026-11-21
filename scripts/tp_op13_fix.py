#!/usr/bin/env python3
"""tp_op13_fix.py <techpack root>: techpack fixes of this port's own (sun's configuration builds code
the reference's kalama build did not), applied after scripts/tp_fix.py. Idempotent."""

import os
import sys

# (file, old, new)
EDITS = [
    # sun_perf_gpuconf has KGSL_USE_SHMEM: android_rvh_shmem_get_folio passes the folio order since
    # 6.12.18 -- in 6.18 too, not only up to 6.13
    ("graphics-kernel/kgsl_sharedmem.c",
     "#if ((KERNEL_VERSION(6, 12, 18) <= LINUX_VERSION_CODE) && \\\n"
     "\t(KERNEL_VERSION(6, 13, 0) > LINUX_VERSION_CODE))\n"
     "static void kgsl_shmem_fill_page(",
     "#if (KERNEL_VERSION(6, 12, 18) <= LINUX_VERSION_CODE)\n"
     "static void kgsl_shmem_fill_page("),
    # display_modules.bzl lists msm/hdmi/hdmi_power.c and hdmi_parser.c among the HDMI sources
    # (sun's conf has HDMI on), the Kbuild does not (modpost: hdmi_power_put, hdmi_parser_put
    # undefined). The only other .bzl sources it lacks are behind options sun leaves off.
    ("display-drivers/msm/Kbuild",
     "\t\t\t\thdmi/hdmi_pll_snps.o \\\n",
     "\t\t\t\thdmi/hdmi_pll_snps.o \\\n\t\t\t\thdmi/hdmi_power.o \\\n\t\t\t\thdmi/hdmi_parser.o \\\n"),
    # The OnePlus 13's composer (6.6-era, OnePlus' SM8750 sde_drm.h) passes sde_drm_scaler_v2
    # without the eight fields the 6.12 release appends (edge_bleed_sup_en .. halo_suppress_coeff):
    # read what it sends, the rest zero (off), not 32 bytes of whatever follows in its memory
    ("display-drivers/msm/sde/sde_plane.c",
     "\tif (copy_from_user(&scale_v2, usr, sizeof(scale_v2))) {\n",
     "\t/* op13: the 6.6 composer's sde_drm_scaler_v2 ends before edge_bleed_sup_en */\n"
     "\tmemset(&scale_v2, 0, sizeof(scale_v2));\n"
     "\tif (copy_from_user(&scale_v2, usr, offsetof(struct sde_drm_scaler_v2, edge_bleed_sup_en))) {\n"),
    ("display-drivers/msm/sde/sde_crtc.c",
     "\t\t\tif (copy_from_user(&scaler_v2, scaler_v2_usr,\n"
     "\t\t\t\t\tsizeof(scaler_v2))) {\n",
     "\t\t\t/* op13: the 6.6 composer's sde_drm_scaler_v2 ends before edge_bleed_sup_en */\n"
     "\t\t\tmemset(&scaler_v2, 0, sizeof(scaler_v2));\n"
     "\t\t\tif (copy_from_user(&scaler_v2, scaler_v2_usr,\n"
     "\t\t\t\t\toffsetof(struct sde_drm_scaler_v2, edge_bleed_sup_en))) {\n"),
]


def main(argv):
    root = argv[1]
    n = 0
    for rel, old, new in EDITS:
        path = os.path.join(root, rel)
        if not os.path.exists(path):
            continue
        text = open(path, encoding="utf-8", errors="surrogateescape").read()
        if new in text:
            continue
        if old in text:
            open(path, "w", encoding="utf-8", errors="surrogateescape", newline="").write(text.replace(old, new))
            n += 1
        else:
            print(f"tp_op13_fix: {rel}: text to change not found", file=sys.stderr)
            return 1
    print(f"tp_op13_fix: {n} changes")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
