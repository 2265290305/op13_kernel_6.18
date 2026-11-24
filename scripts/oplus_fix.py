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
    # oplus_uprobe calls uprobe_register/uprobe_unregister through addresses it looks up by name. In
    # 6.12+ uprobe_register takes a ref_ctr_offset and returns the struct uprobe, which
    # uprobe_unregister_nosync() then takes, followed by uprobe_unregister_sync() before the consumer
    # may go: the old 3-argument calls would jump into them with the wrong arguments. Each
    # oplus_uprobe keeps its struct uprobe.
    ("oplus_uprobe.c",
     "\tstruct uprobe_consumer  consumer;\n",
     "\tstruct uprobe_consumer  consumer;\n\tstruct uprobe          *k618_up;\t/* 6.12+: what uprobe_register returned */\n"),
    ("oplus_uprobe.c",
     "typedef int (*uprobe_register_t)(struct inode *, loff_t, struct uprobe_consumer *);\n"
     "typedef void (*uprobe_unregister_t)(struct inode *, loff_t , struct uprobe_consumer *);\n",
     "typedef struct uprobe *(*uprobe_register_t)(struct inode *, loff_t, loff_t, struct uprobe_consumer *);\n"
     "typedef void (*uprobe_unregister_t)(struct uprobe *, struct uprobe_consumer *);\t/* _nosync */\n"),
    ("oplus_uprobe.c",
     "\tint ret = 0;\n\n\tret = uprobe_register_funcptr(inode, offset, consumer);\n\n\treturn ret;\n}\n",
     "\tstruct oplus_uprobe *ou = container_of(consumer, struct oplus_uprobe, consumer);\n"
     "\tstruct uprobe *up = uprobe_register_funcptr(inode, offset, 0, consumer);\n\n"
     "\tif (IS_ERR(up))\n\t\treturn PTR_ERR(up);\n\tou->k618_up = up;\n\treturn 0;\n}\n"),
    ("oplus_uprobe.c",
     "{\n\tuprobe_unregister_funcptr(inode, offset, consumer);\n}\n",
     "{\n\tstruct oplus_uprobe *ou = container_of(consumer, struct oplus_uprobe, consumer);\n"
     "\tstatic void (*k618_sync)(void);\n\n"
     "\tif (!ou->k618_up)\n\t\treturn;\n"
     "\tuprobe_unregister_funcptr(ou->k618_up, consumer);\n\tou->k618_up = NULL;\n"
     "\tif (!k618_sync) {\n\t\tstruct kprobe kp = { .symbol_name = \"uprobe_unregister_sync\" };\n\n"
     "\t\tif (!register_kprobe(&kp)) {\n\t\t\tk618_sync = (void (*)(void))kp.addr;\n\t\t\tunregister_kprobe(&kp);\n\t\t}\n\t}\n"
     "\tif (k618_sync)\n\t\tk618_sync();\n}\n"),
    # exit_mm_optimize copies memcontrol.c's private memcg_vmstats_percpu (6.6 layout) to read a
    # memcg's LRU sizes: on 6.18 that layout is different (and MEM_CGROUP_NTARGETS gone). The LRU
    # sizes from the public per-node counters instead, as OnePlus' own commented-out version did
    # (one memory node on this phone); try_to_free_mem_cgroup_pages takes a swappiness (NULL: the
    # memcg's own) since 6.12.
    ("exit_mm_optimize.c",
     "/*\n * FIXME : memcg->vmstats_percpu pointer",
     "#if 0\t/* op13: 6.6's private memcg layout, not 6.18's (scripts/oplus_fix.py) */\n"
     "/*\n * FIXME : memcg->vmstats_percpu pointer"),
    ("exit_mm_optimize.c",
     "\tunsigned long\t\ttargets[MEM_CGROUP_NTARGETS];\n} ____cacheline_aligned;\n",
     "\tunsigned long\t\ttargets[MEM_CGROUP_NTARGETS];\n} ____cacheline_aligned;\n#endif\n"),
    ("exit_mm_optimize.c",
     "\tint idx = LRU_BASE + stat_item;\n\tlong x = 0;\n\tint cpu;\n\n"
     "\tfor_each_possible_cpu(cpu)\n\t\tx += per_cpu(memcg->vmstats_percpu->state[idx], cpu);\n"
     "#ifdef CONFIG_SMP\n\tif (x < 0)\n\t\tx = 0;\n#endif\n\treturn x;\n",
     "\tstruct mem_cgroup_per_node *mz = memcg ? memcg->nodeinfo[0] : NULL;\n"
     "\tunsigned long nr = 0;\n\tint zid;\n\n\tif (!mz)\n\t\treturn 0;\t/* op13: public per-node LRU sizes */\n"
     "\tfor (zid = 0; zid < MAX_NR_ZONES; zid++)\n\t\tnr += READ_ONCE(mz->lru_zone_size[zid][stat_item]);\n"
     "\treturn nr;\n"),
    ("exit_mm_optimize.c",
     "try_to_free_mem_cgroup_pages(memcg, batch, gfp_mask, reclaim_options);",
     "try_to_free_mem_cgroup_pages(memcg, batch, gfp_mask, reclaim_options, NULL);"),
    ("oplus_uprobe.c",
     "static struct kprobe uprobe_unregister_kp = {\n\t.symbol_name = \"uprobe_unregister\"\n};",
     "static struct kprobe uprobe_unregister_kp = {\n\t.symbol_name = \"uprobe_unregister_nosync\"\n};"),
]


def main(argv):
    n = 0
    for dp, _dn, fns in os.walk(argv[1]):
        for name, old, new in EDITS:
            if name not in fns:
                continue
            path = os.path.join(dp, name)
            text = open(path, encoding="utf-8", errors="surrogateescape").read()
            if new and new in text:
                continue		# already applied (some edits keep the old text inside the new)
            if old in text:
                open(path, "w", encoding="utf-8", errors="surrogateescape", newline="").write(text.replace(old, new))
                n += 1
    if n:
        print(f"oplus_fix: {n} changes in {argv[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
