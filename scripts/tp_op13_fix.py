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
]


def main(argv):
    root = argv[1]
    n = 0
    for rel, old, new in EDITS:
        path = os.path.join(root, rel)
        if not os.path.exists(path):
            continue
        text = open(path, encoding="utf-8", errors="surrogateescape").read()
        if old in text:
            open(path, "w", encoding="utf-8", errors="surrogateescape", newline="").write(text.replace(old, new))
            n += 1
        elif new not in text:
            print(f"tp_op13_fix: {rel}: text to change not found", file=sys.stderr)
            return 1
    print(f"tp_op13_fix: {n} changes")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
