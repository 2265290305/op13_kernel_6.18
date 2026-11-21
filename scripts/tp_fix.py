#!/usr/bin/env python3
"""tp_fix.py <ref kernel-6.18 dir> <techpack root>: the reference's techpack edits
(k618_tp_fix.py) that are not Xiaomi- or kalama-specific, applied the same way.

The reference's list mixes 6.12 -> 6.18 build fixes with the Xiaomi 13 family's device work (its
display extension, the 13 Ultra's camera, kalama's IPA layout, the 5.15 video/EVA copies) and with
adaptations to its ROM's 5.15-era user space (smcinvoke's 32-bit ABI, synx v1, display structs).
For the OnePlus 13 (sun) only the build fixes apply: its 6.6-era user space speaks the 6.12
release's smcinvoke ABI word for word (include/uapi/linux/smcinvoke.h is identical in OnePlus'
SM8750 and SM8850 sources). So edits whose text names a Xiaomi model, mi_disp, kalama, the 5.15
copies or 5.15 itself are skipped, as are the smcinvoke ABI headers' and the generated Xiaomi
display files. Idempotent."""

import os
import re
import sys

DEVICE = re.compile(r"xiaomi|\bmi_|k618_mi|mi_disp|ultra|nuwa|ishtar|fuxi|kalama|madrid|panel_id"
                    r"|-515|_515|k618_ois|k618_park|5\.15|5_15", re.I)
# the smcinvoke ABI the reference narrowed to 5.15's (both copies of the header)
SKIP_FILES = ("securemsm-kernel/include/uapi/linux/smcinvoke.h", "securemsm-kernel/include/linux/smcinvoke.h")
SKIP_GENERATED = ("display-drivers/msm/mi_disp_k618.c", "display-drivers/msm/mi_disp_k618.h")
SKIP_REPOS = ("video-driver-515", "eva-kernel-515")


def load(ref):
    path = os.path.join(ref, "k618_tp_fix.py")
    ns = {"__file__": path, "__name__": "k618_tp_fix"}
    exec(compile(open(path, encoding="utf-8").read(), path, "exec"), ns)  # noqa: S102
    return ns


def main(argv):
    ns = load(argv[1])
    root = argv[2].rstrip("/")
    wrote = swept = applied = skipped = missing = 0
    for rel, text in ns["GENERATED"]:
        if rel in SKIP_GENERATED or rel.split("/")[0] in SKIP_REPOS:
            continue
        path = os.path.join(root, rel)
        if not os.path.isdir(os.path.dirname(path)):
            continue
        if not (os.path.exists(path) and open(path, encoding="utf-8").read() == text):
            open(path, "w", encoding="utf-8", newline="\n").write(text)
            wrote += 1
    for repo, old, new in ns["SWEEPS"]:
        if repo in SKIP_REPOS:
            continue
        for dp, _dn, fns in os.walk(os.path.join(root, repo)):
            for fn in fns:
                if not fn.endswith((".c", ".h")):
                    continue
                p = os.path.join(dp, fn)
                text = open(p, encoding="utf-8", errors="surrogateescape").read()
                if old in text:
                    open(p, "w", encoding="utf-8", errors="surrogateescape", newline="").write(text.replace(old, new))
                    swept += 1
    for rel, old, new in ns["EDITS"]:
        if rel.split("/")[0] in SKIP_REPOS or rel in SKIP_FILES or DEVICE.search(rel + old + new):
            skipped += 1
            continue
        path = os.path.join(root, rel)
        if not os.path.exists(path):
            continue
        text = open(path, encoding="utf-8", errors="surrogateescape").read()
        # the reference's idempotency rules (k618_tp_fix.py main())
        if old in new:
            if new in text:
                continue
        elif new and new in text and old not in text:
            continue
        if old not in text:
            missing += 1
            print(f"tp_fix: {rel}: text to change not found", file=sys.stderr)
            continue
        open(path, "w", encoding="utf-8", errors="surrogateescape", newline="").write(text.replace(old, new))
        applied += 1
    print(f"tp_fix: {wrote} generated, {swept} sweep hits, {applied} edits applied, "
          f"{skipped} device-specific skipped, {missing} not found")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
