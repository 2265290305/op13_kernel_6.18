#!/usr/bin/env python3
"""oplus_fix.py <dir>: 6.6 -> 6.18 fixes for OnePlus' own drivers (a copy under out/oplus), by file
name, wherever the file is in that copy. Idempotent."""

import os
import sys

# (file name, old, new)
EDITS = [
    # platform_driver.remove returns void since 6.11
    ("bootloader_log.c",
     "static int __exit bootloader_log_remove(struct platform_device *pdev)\n{\n\treturn -EBUSY;\n}",
     "static void bootloader_log_remove(struct platform_device *pdev)\n{\n}"),
    # the kernel's private procfs header by a path from OnePlus' tree layout (drivers/soc/oplus/...);
    # nothing of it is used (proc_create_data and pde_data are public)
    ("device_info.c", '#include "../../../../fs/proc/internal.h"\n', ""),
]


def main(argv):
    n = 0
    for dp, _dn, fns in os.walk(argv[1]):
        for name, old, new in EDITS:
            if name not in fns:
                continue
            path = os.path.join(dp, name)
            text = open(path, encoding="utf-8", errors="surrogateescape").read()
            if old in text:
                open(path, "w", encoding="utf-8", errors="surrogateescape", newline="").write(text.replace(old, new))
                n += 1
    if n:
        print(f"oplus_fix: {n} changes in {argv[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
