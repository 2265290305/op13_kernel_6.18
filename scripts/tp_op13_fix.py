#!/usr/bin/env python3
"""tp_op13_fix.py <techpack root>: techpack fixes of this port's own (sun's configuration builds code
the reference's kalama build did not), applied after scripts/tp_fix.py. Idempotent."""

import os
import re
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
    # H2F_MSG_CONTEXT_POINTERS as the OnePlus 13's GMU firmware takes it: the SM8850 release appends
    # dcvs_profile_addr (its GMU DCVS profiles, which sun's GPU does not use), the SM8750 one ends at
    # gmu_context_queue_addr. test-43: the first GPU context surfaceflinger made got "HFI Error
    # Received: 8 1345 HandleHfiCommand" back, then a GMU fault and a snapshot.
    # The OnePlus 13's composer asks for the touch-down event as 0x80000014 (its sde_drm.h); the
    # SM8850 release put VM_RECLAIM there and moved TP_TOUCHDOWN to 0x80000015. test-43: "failed to
    # enable event 80000014". OnePlus 13's numbers.
    ("display-drivers/include/uapi/display/drm/sde_drm.h",
     "#define DRM_EVENT_VM_RECLAIM 0X80000014\n#ifdef OPLUS_FEATURE_DISPLAY\n"
     "#define DRM_EVENT_TP_TOUCHDOWN 0x80000015 /* tp touch down event */\n",
     "#define DRM_EVENT_VM_RECLAIM 0X80000015\t/* op13: TP_TOUCHDOWN's number in the 6.6 user space */\n"
     "#ifdef OPLUS_FEATURE_DISPLAY\n#define DRM_EVENT_TP_TOUCHDOWN 0x80000014 /* tp touch down event */\n"),
    # Colour-processing blobs from the 6.6 composer are shorter than the SM8850 structs: the demura
    # config without cfg0_param_7/8 (8 bytes), the dither config without the extended matrix (1028).
    # Take them zero-padded (the new fields' 0 is their default) instead of refusing them.
    # test-43: "invalid blob len 8560 exp 8568 feature 38".
    ("display-drivers/msm/sde/sde_color_processing.c",
     "\tif (blob->length != prop_node->prop_blob_sz) {\n"
     "\t\tDRM_ERROR(\"invalid blob len %zd exp %d feature %d\\n\",\n"
     "\t\t    blob->length, prop_node->prop_blob_sz, prop_node->feature);\n",
     "\t/* op13: the 6.6 composer's shorter demura (-8) and dither (-1028) configs, zero-padded */\n"
     "\tif (blob->length < prop_node->prop_blob_sz &&\n"
     "\t    (prop_node->prop_blob_sz - blob->length == 8 ||\n"
     "\t     prop_node->prop_blob_sz - blob->length == 1028)) {\n"
     "\t\tstruct drm_property_blob *nb = drm_property_create_blob(crtc->dev,\n"
     "\t\t\t\t\tprop_node->prop_blob_sz, NULL);\n\n"
     "\t\tif (!IS_ERR(nb)) {\n"
     "\t\t\tmemcpy(nb->data, blob->data, blob->length);\n"
     "\t\t\tdrm_property_blob_put(blob);\n"
     "\t\t\tblob = nb;\n"
     "\t\t}\n"
     "\t}\n"
     "\tif (blob->length != prop_node->prop_blob_sz) {\n"
     "\t\tDRM_ERROR(\"invalid blob len %zd exp %d feature %d\\n\",\n"
     "\t\t    blob->length, prop_node->prop_blob_sz, prop_node->feature);\n"),
    ("graphics-kernel/adreno_hfi.h",
     "\tu32 gmu_context_queue_addr;\n\tu32 dcvs_profile_addr;\n} __packed;",
     "\tu32 gmu_context_queue_addr;\n\t/* op13: no dcvs_profile_addr (SM8750 GMU firmware) */\n} __packed;"),
    ("graphics-kernel/adreno_gen8_hwsched_hfi.c",
     "\tcmd.version = 1;\n\tcmd.dcvs_profile_addr = GMU_BUF_ADDR(md);\n",
     "\tcmd.version = 1;\n\t(void)md;\t/* op13: no dcvs_profile_addr (SM8750 GMU firmware) */\n"),
]


def gpu_as_op13(root):
    """The OnePlus 13's GPU (Adreno 830: gen8_0_1, Sun v2's DT; gen8_0_0 for v1) as the OnePlus 13's
    own KGSL sets it up: without the GMU thermal mitigation, the thermal profile and the
    no-fault-tolerance timeout the SM8850 release sends its GMU (OnePlus took them out for SM8750:
    "bug:8274887"), and without the CLX table: OnePlus' SM8750 KGSL builds the same table in code,
    but here the GMU firmware answers it with error 115 every boot (test-40 and test-44 sent it and
    hung; test-43 left it out and its GPU came up). test-40: the phone's GMU firmware answered the boot handshake with HFI error 115
    (ResMgrCalibrate) and stopped acking, the GPU never came up, surfaceflinger kept dying."""
    path = os.path.join(root, "graphics-kernel/adreno-gpulist.h")
    if not os.path.exists(path):
        return 0
    text = open(path, encoding="utf-8", errors="surrogateescape").read()
    n = 0

    def fix(m):
        nonlocal n
        b = m.group(0)
        b2 = b.replace("ADRENO_ACD | ADRENO_CLX | ADRENO_GMU_THERMAL_MITIGATION,", "ADRENO_ACD | ADRENO_CLX,")
        b2 = re.sub(r"\n\t\.(cl_no_ft_timeout_ms|therm_profile|clx_tbl) =[^\n]*,", "", b2)
        if b2 != b:
            n += 1
        return b2
    text = re.sub(r"static const struct adreno_gen8_core adreno_gpu_core_gen8_0_[01] = \{.*?\n\};", fix, text,
                  flags=re.S)
    if n:
        open(path, "w", encoding="utf-8", errors="surrogateescape", newline="").write(text)
    return n


def main(argv):
    root = argv[1]
    n = gpu_as_op13(root)
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
