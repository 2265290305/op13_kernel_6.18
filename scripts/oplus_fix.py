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
    # hybridswap's zram: the block limits and features go to blk_alloc_disk() (6.10+), as the
    # kernel's own zram does; the blk_queue_* setters and QUEUE_FLAG_NONROT/SYNCHRONOUS are gone
    ("zram_drv.c",
     '\tzram->disk = blk_alloc_disk(NUMA_NO_NODE);\n\tif (!zram->disk) {\n\t\tpr_err("Error allocating disk structure for device %d\\n",\n\t\t\tdevice_id);\n\t\tret = -ENOMEM;\n',
     '\t{\t/* op13: 6.10+ block limits and features, as the kernel\'s own zram (scripts/oplus_fix.py) */\n\t\tstruct queue_limits lim = {\n\t\t\t.logical_block_size\t= ZRAM_LOGICAL_BLOCK_SIZE,\n\t\t\t.physical_block_size\t= PAGE_SIZE,\n\t\t\t.io_min\t\t\t= PAGE_SIZE,\n\t\t\t.io_opt\t\t\t= PAGE_SIZE,\n\t\t\t.discard_granularity\t= PAGE_SIZE,\n\t\t\t.max_hw_discard_sectors\t= UINT_MAX,\n#if ZRAM_LOGICAL_BLOCK_SIZE == PAGE_SIZE\n\t\t\t.max_write_zeroes_sectors = UINT_MAX,\n#endif\n\t\t\t.features\t\t= BLK_FEAT_STABLE_WRITES | BLK_FEAT_SYNCHRONOUS,\n\t\t};\n\n\t\tzram->disk = blk_alloc_disk(&lim, NUMA_NO_NODE);\n\t}\n\tif (IS_ERR(zram->disk)) {\n\t\tpr_err("Error allocating disk structure for device %d\\n",\n\t\t\tdevice_id);\n\t\tret = PTR_ERR(zram->disk);\n'),
    ("zram_drv.c",
     "\t/* zram devices sort of resembles non-rotational disks */\n\tblk_queue_flag_set(QUEUE_FLAG_NONROT, zram->disk->queue);\n\tblk_queue_flag_set(QUEUE_FLAG_SYNCHRONOUS, zram->disk->queue);\n\n\t/*\n\t * To ensure that we always get PAGE_SIZE aligned\n\t * and n*PAGE_SIZED sized I/O requests.\n\t */\n\tblk_queue_physical_block_size(zram->disk->queue, PAGE_SIZE);\n\tblk_queue_logical_block_size(zram->disk->queue,\n\t\t\t\t\tZRAM_LOGICAL_BLOCK_SIZE);\n\tblk_queue_io_min(zram->disk->queue, PAGE_SIZE);\n\tblk_queue_io_opt(zram->disk->queue, PAGE_SIZE);\n\tzram->disk->queue->limits.discard_granularity = PAGE_SIZE;\n\tblk_queue_max_discard_sectors(zram->disk->queue, UINT_MAX);\n\n\t/*\n\t * zram_bio_discard() will clear all logical blocks if logical block\n\t * size is identical with physical block size(PAGE_SIZE). But if it is\n\t * different, we will skip discarding some parts of logical blocks in\n\t * the part of the request range which isn't aligned to physical block\n\t * size.  So we can't ensure that all discarded logical blocks are\n\t * zeroed.\n\t */\n\tif (ZRAM_LOGICAL_BLOCK_SIZE == PAGE_SIZE)\n\t\tblk_queue_max_write_zeroes_sectors(zram->disk->queue, UINT_MAX);\n\n\tblk_queue_flag_set(QUEUE_FLAG_STABLE_WRITES, zram->disk->queue);\n",
     '\t/* op13: non-rotational is the default, the rest is in lim above (blk_alloc_disk) */\n'),
    # hybridswap's hybridmain.c: the same copied 6.6 memcg_vmstats_percpu as exit_mm_optimize (its
    # memcg_page_state_local read swap usage through it) -> the exported memcg_page_state(); and
    # the 6.6 hook android_vh_alloc_pages_slowpath(gfp, order, alloc_start), which 6.18 split into
    # _start/_end -- _end fires where it did (got_pg) with the same gfp/order/start: an adapter
    ("hybridmain.c",
     "/*\n * FIXME : memcg->vmstats_percpu pointer",
     "#if 0\t/* op13: 6.6's private memcg layout, not 6.18's (scripts/oplus_fix.py) */\n"
     "/*\n * FIXME : memcg->vmstats_percpu pointer"),
    ("hybridmain.c",
     "\tunsigned long\t\ttargets[MEM_CGROUP_NTARGETS];\n} ____cacheline_aligned;\n",
     "\tunsigned long\t\ttargets[MEM_CGROUP_NTARGETS];\n} ____cacheline_aligned;\n#endif\n"),
    ("hybridmain.c",
     "\tlong x = 0;\n\tint cpu;\n\n\tfor_each_possible_cpu(cpu)\n\t\tx += per_cpu(memcg->vmstats_percpu->state[idx], cpu);\n"
     "#ifdef CONFIG_SMP\n\tif (x < 0)\n\t\tx = 0;\n#endif\n\treturn x;\n",
     "\treturn memcg_page_state(memcg, idx);\t/* op13: exported in 6.18 */\n"),
    ("hybridmain.c",
     "struct hybridswapd_operations *hybridswapd_ops;\n",
     "struct hybridswapd_operations *hybridswapd_ops;\n\n"
     "/* op13: 6.18's android_vh_alloc_pages_slowpath_end, called where 6.6's _slowpath hook was */\n"
     "static void k618_slowpath_end(void *data, gfp_t *gfp_mask, unsigned int order,\n"
     "\t\tunsigned long alloc_start, u64 stime, unsigned long did_some_progress,\n"
     "\t\tunsigned long pages_reclaimed, int retry_loop_count)\n{\n"
     "\tif (hybridswapd_ops && hybridswapd_ops->vh_alloc_pages_slowpath)\n"
     "\t\thybridswapd_ops->vh_alloc_pages_slowpath(data, *gfp_mask, order, alloc_start);\n}\n"),
    ("hybridmain.c",
     "register_trace_android_vh_alloc_pages_slowpath(hybridswapd_ops->vh_alloc_pages_slowpath, NULL)",
     "register_trace_android_vh_alloc_pages_slowpath_end(k618_slowpath_end, NULL)"),
    # mm_osvelte's ashmem statistics (sys-ashmem.c) read the C ashmem driver's struct ashmem_area;
    # 6.18's ashmem is the Rust driver, whose area is reachable only through accessors that take a
    # mutex -- and this walk runs from an fd iteration in atomic context (GFP_ATOMIC). Left out:
    # the rest of mm_osvelte (memory tracking, lowmem debug, dma-buf statistics) does not need it
    ("Makefile",
     "oplus_bsp_mm_osvelte-$(CONFIG_ASHMEM) += sys-ashmem.o\n",
     "# op13: sys-ashmem.o left out (scripts/oplus_fix.py)\n"),
    ("sys-memstat.c",
     "\tdir_entry = mtrack_procs[MTRACK_ASHMEM];\n\tif (dir_entry)\n\t\tcreate_ashmem_procfs(dir_entry);\n",
     "\t/* op13: no ashmem statistics on 6.18's Rust ashmem (scripts/oplus_fix.py) */\n"),
    # android_vh_do_futex gained the futex address first (6.12 ACK); the handler does not use it
    ("futex.c",
     "static void android_vh_do_futex_handler(void *unused, int cmd,",
     "static void android_vh_do_futex_handler(void *unused, u32 __user *uaddr, int cmd,"),
    # binder_watcher: the kernel's binder_alloc.h has its own binder_alloc_buffer_size() now, and
    # the mapping's start is alloc->vm_start (6.12): the module's copy under its own name
    ("binder_watcher.c", "binder_alloc_buffer_size(", "oplus_binder_alloc_buffer_size("),
    ("binder_watcher.c", "return alloc->buffer + alloc->buffer_size - buffer->user_data;",
     "return alloc->vm_start + alloc->buffer_size - buffer->user_data;"),
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
