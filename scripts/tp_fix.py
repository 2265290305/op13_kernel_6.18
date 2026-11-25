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
                    r"|-515|_515|k618_ois|k618_park|5\.15|5_15"
                    # the reference's NFC probe tracing (its header is not generated here) and its
                    # removal of OnePlus' boot_mode.h from nxp's i2c_drv.c, whose OnePlus 13 copy
                    # uses get_boot_mode() (factory mode)
                    r"|K618_NFC_STEP|own boot driver", re.I)
# the smcinvoke ABI the reference narrowed to 5.15's (both copies of the header)
SKIP_FILES = ("securemsm-kernel/include/uapi/linux/smcinvoke.h", "securemsm-kernel/include/linux/smcinvoke.h",
              # the camera interconnect lookup redirected for Xiaomi's 5.15 DT: its wrapper is skipped
              # as 5.15-specific, its rename was not -- camera lost cam_soc_bus_client_register
              # (test-48). The OnePlus 13's DT (a 6.6 one) has the path names 6.5+ needs.
              "camera-kernel/drivers/cam_utils/cam_soc_icc.c")
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
    # the device edits, and with them every edit using a k618_ name only a device edit defines (the
    # Xiaomi Wi-Fi file names: the regdb edit names k618_regdb_name, which the skipped Xiaomi block
    # defines -- applied alone, cnss2 did not build)
    def device(rel, old, new):
        return rel.split("/")[0] in SKIP_REPOS or rel in SKIP_FILES or DEVICE.search(rel + old + new)
    DEF = re.compile(r"^[ \t]*(?:(?:static|const|unsigned|signed|struct\s+\w+|enum\s+\w+|\w+_t|char|int|long|"
                     r"bool|void|u8|u16|u32|u64)\s+\**)+(k618_\w+)\s*[=;(\[]", re.M)
    use = lambda s: set(re.findall(r"\bk618_\w+", s))
    dev = {i for i, e in enumerate(ns["EDITS"]) if device(*e)}
    while True:
        names = set()
        for i in dev:
            _rel, old, new = ns["EDITS"][i]
            names |= set(DEF.findall(new)) - set(DEF.findall(old))
        for i, (_rel, old, new) in enumerate(ns["EDITS"]):
            if i not in dev:
                names -= set(DEF.findall(new))
        more = {i for i, (_rel, old, new) in enumerate(ns["EDITS"])
                if i not in dev and (use(new) - use(old)) & names}
        if not more:
            break
        dev |= more
    for i, (rel, old, new) in enumerate(ns["EDITS"]):
        if i in dev:
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
