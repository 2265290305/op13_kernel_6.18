#!/usr/bin/env python3
"""soc_select.py: which SoC-repo modules to build for the OnePlus 13.

  select <soc> <evaluated .config> <kernel .config> <stock dir> <gki modules dir> <drop file>
      the registry modules whose .ko the phone's own lists load (first stage, vendor_dlkm,
      system_dlkm) and whose option the evaluated configuration enables -- less the ones the kernel
      build already makes (its option set in the kernel's own .config, or a .ko of the same name:
      zram, zsmalloc, the DRM display helpers ...), less the dropped ones and whatever needs them
  owners <soc> <build log>
      the registry modules that own the files with compile errors, or that modpost refused

Building everything sun_perf enables pulls in modules this phone never loads (virtio, SD card,
copies of the kernel's own helpers), and one compile error anywhere stops modpost for all.
"""

import os
import re
import sys


def registry(soc):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ref_8550", "kernel-6.18"))
    import k618_soc_kbuild as kb  # the reference's reader of Qualcomm's modules.bzl files
    return kb, kb.load_registry(soc)


def canon(name):
    return os.path.basename(name.strip()).removesuffix(".ko").replace("-", "_")


def select(soc, evaluated, kernel, stock, gki, drop_file):
    kb, mods = registry(soc)
    cfg = kb.read_config(evaluated)
    kcfg = kb.read_config(kernel)
    by_name = {m["name"]: m for m in mods.values()}
    wanted = set()
    for lst in ("first_stage.load", "vendor_dlkm.load", "system_dlkm.load"):
        wanted |= {canon(line) for line in open(os.path.join(stock, lst)) if line.strip()}
    own = set()
    for dp, _dn, fns in os.walk(gki):
        own |= {canon(f) for f in fns if f.endswith(".ko")}
    dropped = set()
    if os.path.exists(drop_file):
        dropped = {line.strip() for line in open(drop_file) if line.strip()}

    def enabled(m):
        return kb.enabled(cfg, m["config"])

    def closure(name, seen):
        for d in by_name[name]["deps"]:
            if d in by_name and enabled(by_name[d]) and d not in seen:
                seen.add(d)
                closure(d, seen)
        return seen

    out = []
    for name, m in sorted(by_name.items()):
        k = canon(m["out"])
        if k not in wanted or k in own or not enabled(m) or name in dropped:
            continue
        if m["config"] and kcfg.get(m["config"], "n") in ("y", "m"):
            continue
        if closure(name, set()) & dropped:
            continue
        out.append(name)
    print("\n".join(out))
    print(f"soc_select: {len(out)} modules (of {len(by_name)} in the registry)", file=sys.stderr)
    return 0


def owners(soc, log):
    _kb, mods = registry(soc)
    by_src, by_out = {}, {}
    for m in mods.values():
        by_out[canon(m["out"])] = m["name"]
        srcs = list(m["srcs"])
        for v in m["conditional_srcs"].values():
            for lst in (v.values() if isinstance(v, dict) else [v]):
                srcs += list(lst) if isinstance(lst, (list, tuple)) else []
        for s in srcs:
            by_src.setdefault(s, set()).add(m["name"])
    found = set()
    soc = soc.rstrip("/") + "/"
    for line in open(log, errors="replace"):
        e = re.match(r"(\S+?\.[ch]):\d+:\d+: (?:fatal )?error: ", line)
        if e:
            f = e.group(1).removeprefix(soc)
            # an error in a header: every module that lists it, else the one compiling it
            found |= by_src.get(f, set())
            continue
        e = re.search(r"^ERROR: modpost: .* \[(\S+\.ko)\] ", line) or re.search(r"\[(\S+\.ko)\] undefined", line)
        if e and canon(e.group(1)) in by_out:
            found.add(by_out[canon(e.group(1))])
    # a compile error reported for a file no module lists (a .c included by another): the module
    # whose object failed, from make's own "*** [...] Error" lines
    for line in open(log, errors="replace"):
        e = re.search(r"\*\*\* \[\S+: (\S+)\.o\] Error", line)
        if e:
            f = e.group(1).removeprefix(soc) + ".c"
            found |= by_src.get(f, set())
    print("\n".join(sorted(found)))
    return 0


def main(argv):
    if argv[1] == "select":
        return select(*argv[2:8])
    if argv[1] == "owners":
        return owners(argv[2], argv[3])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
