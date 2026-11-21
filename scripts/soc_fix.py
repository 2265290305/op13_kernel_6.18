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
    # nr_irqs is no longer exported in 6.18; irq_get_nr_irqs() is
    ("drivers/soc/qcom/gic_intr_routing.c", "i < nr_irqs;", "i < irq_get_nr_irqs();"),
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
