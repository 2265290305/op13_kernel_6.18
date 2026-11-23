#!/usr/bin/env python3
"""soc_fix.py <soc> <kernel>: the SoC repo's 6.12 -> 6.18 fixes the reference port did not need
(it built canoe's module set for kalama; these are modules the OnePlus 13 loads). Run after the
reference's k618_fix618.py, on a fresh checkout each build. Idempotent."""

import os
import shutil
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
]


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
    print(f"soc_fix: {n} changes")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
