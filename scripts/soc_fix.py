#!/usr/bin/env python3
"""soc_fix.py <soc> <kernel>: the SoC repo's 6.12 -> 6.18 fixes the reference port did not need
(it built canoe's module set for kalama; these are modules the OnePlus 13 loads). Run after the
reference's k618_fix618.py, on a fresh checkout each build. Idempotent."""

import os
import shutil
import subprocess
import sys

# files the SoC repo carries in a 6.12 copy where the kernel's own 6.18 one is the right source
FROM_KERNEL = [
    # the 6.12 copy's match callbacks take a non-const pointer (6.18's device_match_t: const void *)
    "drivers/hwmon/hwmon.c",
]

# (file, old, new)
EDITS = [
    # the OnePlus 13's alert slider (oplus_bsp_tri_key) registers as TRI_STATE_KEY_FOR_SEC too, a
    # client the OnePlus 13's own 6.6 header has after POGOPIN and the SM8850 one does not. Every user
    # of the enum (SoC, techpacks, OnePlus modules) is built from this header, so it is added here
    ("include/linux/soc/qcom/panel_event_notifier.h",
     "\tPANEL_EVENT_NOTIFIER_CLIENT_POGOPIN,\n",
     "\tPANEL_EVENT_NOTIFIER_CLIENT_POGOPIN,\n\tPANEL_EVENT_NOTIFIER_CLIENT_TRI_STATE_KEY_FOR_SEC,\n"),
    # nr_irqs is no longer exported in 6.18; irq_get_nr_irqs() is
    ("drivers/soc/qcom/gic_intr_routing.c", "i < nr_irqs;", "i < irq_get_nr_irqs();"),
    # the reference's key-manager step before the first wrapped key (ice.c, k618_ice_hwkm_setup) is
    # its 5.15 kalama driver's: the OnePlus 13's own qcom_ice and tmecom-intf have no such step
    # (tmecom-intf exports only tmecom_process_request / tmelog_process_request). On sun it blocked
    # every key (test-25, without tmecom-intf) and hung vold's first one (test-26, with it). Off,
    # with qcom_ice.k618_tpkey=1 to bring it back
    ("drivers/soc/qcom/ice.c",
     "static int k618_ice_hwkm_setup(struct qcom_ice *ice)\n{\n",
     "static bool k618_tpkey;\nmodule_param(k618_tpkey, bool, 0444);\n\n"
     "static int k618_ice_hwkm_setup(struct qcom_ice *ice)\n{\n\tif (!k618_tpkey)\n\t\treturn 0;\t/* op13: scripts/soc_fix.py */\n"),
    # sdhci-msm (stock first stage): the kernel's sdhci-cqhci.h, included first, pulls in the
    # kernel's cqhci.h, whose guard then hides the SoC's own (its cqhci_host_ops has
    # enhanced_strobe_mask, the kernel's does not) -- the SoC's first
    ("drivers/mmc/host/sdhci-msm.c",
     "#include \"drivers/mmc/host/sdhci-cqhci.h\"\n#include \"drivers/mmc/host/sdhci-pltfm.h\"\n#include \"cqhci.h\"\n",
     "#include \"cqhci.h\"\t/* op13: the SoC's, ahead of the kernel's (scripts/soc_fix.py) */\n"
     "#include \"drivers/mmc/host/sdhci-cqhci.h\"\n#include \"drivers/mmc/host/sdhci-pltfm.h\"\n"),
    # sdhci-msm: the host is device-managed since 6.16 (devm_mmc_alloc_host); sdhci_pltfm_free() is
    # gone and nothing is left to free (SoC build: "call to undeclared function 'sdhci_pltfm_free'")
    ("drivers/mmc/host/sdhci-msm.c",
     "\tsdhci_pltfm_free(pdev);\n",
     "\t/* op13: devm host (6.16+), nothing to free (scripts/soc_fix.py) */\n"),
    # the reference's Xiaomi UFS sysfs nodes (ufs-qcom-mi.c: ufs_monitor, ufscld, which Xiaomi's ROM
    # reads) do not belong on the OnePlus 13: out of the probe and remove of its storage driver
    ("drivers/ufs/host/ufs-qcom.c",
     "/* k618: the Xiaomi sysfs nodes (ufs_monitor, ufscld) the ROM reads; see that file */\n#include \"ufs-qcom-mi.c\"\n",
     "/* op13: no Xiaomi UFS nodes (scripts/soc_fix.py) */\n"),
    ("drivers/ufs/host/ufs-qcom.c",
     "\t/* k618: ufs_monitor now, ufscld once the async scan has found the device */\n"
     "\tk618_ufs_mi_probe(platform_get_drvdata(pdev));\n",
     "\t/* op13: no Xiaomi UFS nodes (scripts/soc_fix.py) */\n"),
    ("drivers/ufs/host/ufs-qcom.c", "\n\tk618_ufs_mi_remove(hba);\n\tufshcd_remove(hba);",
     "\n\tufshcd_remove(hba);\t/* op13: no Xiaomi UFS nodes */"),
    # 6.18's blk-crypto calls the standard key type RAW
    ("drivers/mmc/host/cqhci-crypto.c", "profile->key_types_supported = BLK_CRYPTO_KEY_TYPE_STANDARD;",
     "profile->key_types_supported = BLK_CRYPTO_KEY_TYPE_RAW;"),
]

# files the generic 6.18 API rules (scripts/vendor_fix618.py) are run on: SoC modules the stock
# lists load that only those changes keep from building (const bin_attribute, devm_gpio_request)
VENDOR_FIX = ["drivers/soc/qcom/qfprom-sys.c", "drivers/spi/q2spi-msm-geni.c"]


def main(argv):
    soc, kernel = argv[1], argv[2]
    n = 0
    for rel in FROM_KERNEL:
        src, dst = os.path.join(kernel, rel), os.path.join(soc, rel)
        if open(src, "rb").read() != open(dst, "rb").read():
            shutil.copyfile(src, dst)
            n += 1
    for rel, old, new in EDITS:
        path = os.path.join(soc, rel)
        text = open(path, encoding="utf-8", errors="surrogateescape").read()
        if new in text:
            continue
        if old in text:
            open(path, "w", encoding="utf-8", errors="surrogateescape", newline="").write(text.replace(old, new))
            n += 1
        elif new not in text:
            print(f"soc_fix: {rel}: text to change not found", file=sys.stderr)
            return 1
    # the generic 6.18 API rules, on the files that need them only
    vf = [os.path.join(soc, rel) for rel in VENDOR_FIX if os.path.exists(os.path.join(soc, rel))]
    if vf:
        subprocess.run([sys.executable, "-I", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "vendor_fix618.py")] + vf, check=True)
    print(f"soc_fix: {n} changes")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
