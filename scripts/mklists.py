#!/usr/bin/env python3
"""mklists.py <rd lib/modules dir> <stock dir> <report dir>: the module lists of our layer.

  modules.load (+ .recovery, .charger)  first-stage init's list: the phone's own first-stage
                                        order, only the modules we have, then k618_load last
  k618_batch.load                       what k618_load loads, one child process each: the phone's
                                        second stage (vendor_dlkm, then system_dlkm) that we have,
                                        in dependency order -- after switch_root our ramdisk is gone
                                        and the ROM's own second stage only has the 6.6 modules
  modules.softdep                       depmod's, plus k618_load after every first-stage module:
                                        this phone loads its first stage in parallel
                                        (androidboot.load_modules_parallel), where only
                                        dependencies and pre-softdeps order anything
  modules.options                       k618_load's parameters
  modules.blocklist                     the phone's

A module listed but missing ends first-stage init, so every list names only modules in the layer.
"""

import os
import shutil
import sys


def canon(name):
    return os.path.basename(name.strip()).removesuffix(".ko").replace("-", "_")


def read_list(path):
    return [line.strip() for line in open(path) if line.strip() and not line.startswith("#")]


def main(argv):
    rd, stock, report = argv[1], argv[2], argv[3]
    have = {canon(f): f for f in os.listdir(rd) if f.endswith(".ko")}
    blocked = {canon(line.split()[1]) for line in read_list(f"{stock}/modules.blocklist")
               if line.startswith("blocklist ")}
    deps = {}
    for line in open(f"{rd}/modules.dep"):
        m, _, d = line.strip().partition(":")
        deps[os.path.basename(m)] = [os.path.basename(x) for x in d.split()]

    first, missing_first = [], []
    for n in read_list(f"{stock}/first_stage.load"):
        k = canon(n)
        (first if k in have else missing_first).append(have.get(k, n))
    first = [m for m in first if canon(m) != "k618_load"]

    # everything init loads for the first stage, dependencies included
    in_init, todo = set(), list(first)
    while todo:
        m = todo.pop()
        if m not in in_init:
            in_init.add(m)
            todo += deps.get(m, [])

    wanted, missing_second = [], []
    for lst in ("vendor_dlkm.load", "system_dlkm.load"):
        for n in read_list(f"{stock}/{lst}"):
            k = canon(n)
            if k not in have:
                missing_second.append(os.path.basename(n))
            elif k not in blocked and have[k] not in in_init and have[k] not in wanted:
                wanted.append(have[k])
    # modules no stock list names stay in the layer for modprobe on demand, never loaded blindly:
    # some are self-tests (torture, KUnit) that must not run on a phone
    extra = sorted(f for k, f in have.items() if f not in in_init and f not in wanted
                   and k not in blocked and k != "k618_load")
    ordered, placed = [], set()

    def place(m, path=()):
        if m in placed or m in in_init or m in path:
            return
        for d in deps.get(m, []):
            place(d, path + (m,))
        placed.add(m)
        ordered.append(m)
    for m in wanted:
        place(m)

    init_list = first + ["k618_load.ko"]
    for name in ("modules.load", "modules.load.recovery", "modules.load.charger"):
        open(f"{rd}/{name}", "w").write("".join(m + "\n" for m in init_list))
    open(f"{rd}/k618_batch.load", "w").write("".join(m + "\n" for m in ordered))
    with open(f"{rd}/modules.softdep", "a") as f:
        f.write("# op13: the batch loader after the whole first stage\n")
        f.write("softdep k618_load pre: " + " ".join(canon(m) for m in first) + "\n")
    open(f"{rd}/modules.options", "w").write(
        "options k618_load list=/lib/modules/k618_batch.load dir=/lib/modules helper=/k618_umh\n")
    shutil.copy(f"{stock}/modules.blocklist", f"{rd}/modules.blocklist")

    os.makedirs(report, exist_ok=True)
    open(f"{report}/first-stage-missing.txt", "w").write("".join(m + "\n" for m in missing_first))
    open(f"{report}/second-stage-missing.txt", "w").write("".join(m + "\n" for m in missing_second))
    print(f"mklists: first stage {len(first)} of the phone's {len(first) + len(missing_first)} "
          f"(+ k618_load); batch {len(ordered)}; {len(extra)} on demand only; "
          f"second-stage modules we lack: {len(missing_second)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
