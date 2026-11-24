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
    # the fingerprint driver's wake_lock shim: wakeup_source_add/remove are gone (6.18), only
    # registered wakeup sources: the lock holds one
    ("wakelock.h",
     'struct wake_lock {\n    struct wakeup_source ws;\n};',
     'struct wake_lock {\n    struct wakeup_source *ws;\t/* op13: registered (6.18) */\n};'),
    ("wakelock.h",
     '    if (lock) {\n        memset(&lock->ws, 0, sizeof(lock->ws));\n        lock->ws.name = name;\n    }\n    wakeup_source_add(&lock->ws);\n}',
     '    if (lock)\n        lock->ws = wakeup_source_register(NULL, name);\t/* op13: 6.18 */\n}'),
    ("wakelock.h",
     '    wakeup_source_remove(&lock->ws);\n    if (!lock) {\n        return;\n    }\n    __pm_relax(&lock->ws);\n}',
     '    if (!lock || !lock->ws) {\n        return;\n    }\n    __pm_relax(lock->ws);\n    wakeup_source_unregister(lock->ws);\t/* op13 */\n    lock->ws = NULL;\n}'),
    ("wakelock.h",
     '__pm_stay_awake(&lock->ws);',
     '__pm_stay_awake(lock->ws);'),
    ("wakelock.h",
     '__pm_wakeup_event(&lock->ws, jiffies_to_msecs(timeout));',
     '__pm_wakeup_event(lock->ws, jiffies_to_msecs(timeout));'),
    ("wakelock.h",
     '    __pm_relax(&lock->ws);\n}\n\nstatic inline int wake_lock_active',
     '    __pm_relax(lock->ws);\n}\n\nstatic inline int wake_lock_active'),
    ("wakelock.h",
     'return lock->ws.active;',
     'return lock->ws && lock->ws->active;'),
    ("oplus_uprobe.c",
     "static struct kprobe uprobe_unregister_kp = {\n\t.symbol_name = \"uprobe_unregister\"\n};",
     "static struct kprobe uprobe_unregister_kp = {\n\t.symbol_name = \"uprobe_unregister_nosync\"\n};"),
    # sched_assist: its own declaration of the scheduler's set_next_entity() clashes with 6.18's
    # (sched.h: a third argument, first -- true where a pick makes the entity current, as
    # pick_next_task_fair() does)
    ("sa_fair.c",
     "extern void set_next_entity(struct cfs_rq *cfs_rq, struct sched_entity *se);\n", ""),
    ("sa_fair.c",
     "\t\t\tset_next_entity(cfs_rq, *se);\n",
     "\t\t\tset_next_entity(cfs_rq, *se, true);\n"),
    # frame_boost: android_vh_binder_restore_priority has no task argument in 6.18; binder calls it
    # from the replying thread itself (binder_transaction(), before binder_restore_priority(thread))
    ("frame_group.c",
     "\tregister_trace_android_vh_binder_restore_priority(fbg_binder_restore_priority_hook, NULL);\n",
     "\tregister_trace_android_vh_binder_restore_priority(k618_fbg_binder_restore_priority_hook, NULL);\n"),
    ("frame_group.c",
     "\n/*\n * fbg_binder_restore_priority_hook - check if the binder thread",
     "\nstatic void fbg_binder_restore_priority_hook(void *unused, struct binder_transaction *t,\n"
     "\tstruct task_struct *task);\n\n"
     "/* op13: the 6.18 hook (scripts/oplus_fix.py) -- the task is the replying binder thread */\n"
     "static void k618_fbg_binder_restore_priority_hook(void *unused, struct binder_transaction *t)\n"
     "{\n\tfbg_binder_restore_priority_hook(unused, t, current);\n}\n"
     "\n/*\n * fbg_binder_restore_priority_hook - check if the binder thread"),
    # binder_strategy: the same 6.18 android_vh_binder_restore_priority, without the task (the
    # replying thread: current)
    ("binder_sched.c",
     "\tregister_trace_android_vh_binder_restore_priority(\n\t\tandroid_vh_binder_restore_priority_handler, NULL);\n",
     "\tregister_trace_android_vh_binder_restore_priority(\n\t\tk618_binder_restore_priority_handler, NULL);\n"),
    ("binder_sched.c",
     "\nvoid register_binder_sched_vendor_hooks(void)\n{\n",
     "\n/* op13: the 6.18 hook (scripts/oplus_fix.py) -- the task is the replying binder thread */\n"
     "static void k618_binder_restore_priority_handler(void *unused, struct binder_transaction *t)\n"
     "{\n\tandroid_vh_binder_restore_priority_handler(unused, t, current);\n}\n"
     "\nvoid register_binder_sched_vendor_hooks(void)\n{\n"),
    # memleak_detect's slub copy: mm/slab.h has slub_debug_orig_size() itself in 6.18, and the slab
    # lock is SL_locked (= PG_locked) on the slab's memdesc_flags_t, taken and released as 6.18's
    # slub.c does (bit_spin_unlock: the other bits of those flags change concurrently)
    ("slub_track.c",
     "static inline bool slub_debug_orig_size(struct kmem_cache *s)\n{\n\treturn (kmem_cache_debug_flags(s, SLAB_STORE_USER) &&\n\t\t\t\t(s->flags & SLAB_KMALLOC));\n}\n",
     ""),
    ("slub_track.c",
     "\tbit_spin_lock(PG_locked, &page->flags);\n",
     "\tbit_spin_lock(SL_locked, &slab->flags.f);\t/* op13: as 6.18's slub.c */\n"),
    ("slub_track.c",
     "\t__bit_spin_unlock(PG_locked, &page->flags);\n",
     "\tbit_spin_unlock(SL_locked, &slab->flags.f);\t/* op13: as 6.18's slub.c */\n"),
    # charger v2: <../voocphy/...> and <../charger_ic/...> mean v2's own directories (found through
    # v2/include in Bazel's sandbox, where nothing above the package is visible); here the package
    # directory comes first and its parent holds the v1 charger, whose voocphy headers clash with
    # v2's enums (oplus_chg_v2: "redefinition of enumerator 'TRACK_CP_ERR_DEFAULT'"). Relative to
    # the file instead, which lands in v2.
    ("oplus_hal_adsp.c", "#include <../voocphy/oplus_adsp_voocphy.h>", '#include "../voocphy/oplus_adsp_voocphy.h"'),
    ("oplus_hal_sm8450.c", "#include <../voocphy/oplus_adsp_voocphy.h>", '#include "../voocphy/oplus_adsp_voocphy.h"'),
    ("oplus_adsp_voocphy.c", "#include <../charger_ic/oplus_hal_sm8450.h>", '#include "../charger_ic/oplus_hal_sm8450.h"'),
    ("oplus_adsp_voocphy.c", "#include <../charger_ic/oplus_hal_adsp.h>", '#include "../charger_ic/oplus_hal_adsp.h"'),
    ("oplus_chglib.c", "#include <../voocphy/oplus_voocphy.h>", '#include "../oplus_voocphy.h"'),
    # oplus_locking / sched_assist_locking: the lock-time hooks 6.18's ACK dropped, on the ones it has
    ("oplus_locking.c", "#include <trace/hooks/dtask.h>\n", "#include <trace/hooks/dtask.h>\n#include <trace/hooks/rwsem.h>\n\n/*\n * op13: android16-6.12's android_vh_record_{mutex,rtmutex,rwsem,pcpu_rwsem}_*starttime(lock,\n * jiffies) on 6.18's lock acquired/released hooks (scripts/oplus_fix.py): the handler gets jiffies\n * when the lock is taken and 0 when it is let go, as the 6.12 hooks called it\n */\n#define K618_LOCKTIME(name, type, acq, rel)\t\t\t\t\t\t\\\nstatic void (*k618_##name##_fn)(void *, type *, unsigned long);\t\t\t\\\nstatic void *k618_##name##_data;\t\t\t\t\t\t\t\\\nstatic void k618_##name##_acq(void *u, type *l)\t\t\t\t\t\\\n{\t\t\t\t\t\t\t\t\t\t\t\\\n\tk618_##name##_fn(k618_##name##_data, l, jiffies);\t\t\t\t\\\n}\t\t\t\t\t\t\t\t\t\t\t\\\nstatic void k618_##name##_rel(void *u, type *l)\t\t\t\t\t\\\n{\t\t\t\t\t\t\t\t\t\t\t\\\n\tk618_##name##_fn(k618_##name##_data, l, 0);\t\t\t\t\t\\\n}\t\t\t\t\t\t\t\t\t\t\t\\\nstatic inline int register_trace_android_vh_##name(void (*fn)(void *, type *, unsigned long), void *data) \\\n{\t\t\t\t\t\t\t\t\t\t\t\\\n\tint ret;\t\t\t\t\t\t\t\t\t\\\n\t\t\t\t\t\t\t\t\t\t\t\\\n\tk618_##name##_fn = fn;\t\t\t\t\t\t\t\t\\\n\tk618_##name##_data = data;\t\t\t\t\t\t\t\\\n\tret = register_trace_android_vh_##acq(k618_##name##_acq, NULL);\t\t\\\n\tif (ret)\t\t\t\t\t\t\t\t\t\\\n\t\treturn ret;\t\t\t\t\t\t\t\t\\\n\tret = register_trace_android_vh_##rel(k618_##name##_rel, NULL);\t\t\\\n\tif (ret)\t\t\t\t\t\t\t\t\t\\\n\t\tunregister_trace_android_vh_##acq(k618_##name##_acq, NULL);\t\t\\\n\treturn ret;\t\t\t\t\t\t\t\t\t\\\n}\t\t\t\t\t\t\t\t\t\t\t\\\nstatic inline int unregister_trace_android_vh_##name(void (*fn)(void *, type *, unsigned long), void *data) \\\n{\t\t\t\t\t\t\t\t\t\t\t\\\n\tunregister_trace_android_vh_##rel(k618_##name##_rel, NULL);\t\t\t\\\n\treturn unregister_trace_android_vh_##acq(k618_##name##_acq, NULL);\t\t\\\n}\nK618_LOCKTIME(record_mutex_lock_starttime, struct mutex, mutex_lock_acquired, mutex_lock_released)\nK618_LOCKTIME(record_rtmutex_lock_starttime, struct rt_mutex, rtmutex_lock_acquired, rtmutex_lock_released)\n#ifdef CONFIG_PCPU_RWSEM_LOCKING_PROTECT\nK618_LOCKTIME(record_pcpu_rwsem_starttime, struct percpu_rw_semaphore, pcpu_rwsem_lock_acquired,\n\tpcpu_rwsem_lock_released)\n#endif\n\n/* an rwsem: taken by a reader or the writer, let go by either */\nstatic void (*k618_rwsem_fn)(void *, struct rw_semaphore *, unsigned long);\nstatic void *k618_rwsem_data;\nstatic void k618_rwsem_racq(void *u, struct rw_semaphore *s, struct list_head *w)\n{\n\tk618_rwsem_fn(k618_rwsem_data, s, jiffies);\n}\nstatic void k618_rwsem_wacq(void *u, struct rw_semaphore *s)\n{\n\tk618_rwsem_fn(k618_rwsem_data, s, jiffies);\n}\nstatic void k618_rwsem_rel(void *u, struct rw_semaphore *s)\n{\n\tk618_rwsem_fn(k618_rwsem_data, s, 0);\n}\nstatic inline int unregister_trace_android_vh_record_rwsem_lock_starttime(\n\tvoid (*fn)(void *, struct rw_semaphore *, unsigned long), void *data)\n{\n\tunregister_trace_android_vh_clear_rwsem_writer_owned(k618_rwsem_rel, NULL);\n\tunregister_trace_android_vh_clear_rwsem_reader_owned(k618_rwsem_rel, NULL);\n\tunregister_trace_android_vh_record_rwsem_writer_owned(k618_rwsem_wacq, NULL);\n\treturn unregister_trace_android_vh_record_rwsem_reader_owned(k618_rwsem_racq, NULL);\n}\nstatic inline int register_trace_android_vh_record_rwsem_lock_starttime(\n\tvoid (*fn)(void *, struct rw_semaphore *, unsigned long), void *data)\n{\n\tint ret;\n\n\tk618_rwsem_fn = fn;\n\tk618_rwsem_data = data;\n\tret = register_trace_android_vh_record_rwsem_reader_owned(k618_rwsem_racq, NULL);\n\tif (!ret)\n\t\tret = register_trace_android_vh_record_rwsem_writer_owned(k618_rwsem_wacq, NULL);\n\tif (!ret)\n\t\tret = register_trace_android_vh_clear_rwsem_reader_owned(k618_rwsem_rel, NULL);\n\tif (!ret)\n\t\tret = register_trace_android_vh_clear_rwsem_writer_owned(k618_rwsem_rel, NULL);\n\tif (ret)\n\t\tunregister_trace_android_vh_record_rwsem_lock_starttime(fn, data);\n\treturn ret;\n}\n"),
    ("sched_assist_locking.c", "#include <trace/hooks/dtask.h>\n", "#include <trace/hooks/dtask.h>\n#include <trace/hooks/rwsem.h>\n\n/*\n * op13: android16-6.12's android_vh_record_{mutex,rtmutex,rwsem,pcpu_rwsem}_*starttime(lock,\n * jiffies) on 6.18's lock acquired/released hooks (scripts/oplus_fix.py): the handler gets jiffies\n * when the lock is taken and 0 when it is let go, as the 6.12 hooks called it\n */\n#define K618_LOCKTIME(name, type, acq, rel)\t\t\t\t\t\t\\\nstatic void (*k618_##name##_fn)(void *, type *, unsigned long);\t\t\t\\\nstatic void *k618_##name##_data;\t\t\t\t\t\t\t\\\nstatic void k618_##name##_acq(void *u, type *l)\t\t\t\t\t\\\n{\t\t\t\t\t\t\t\t\t\t\t\\\n\tk618_##name##_fn(k618_##name##_data, l, jiffies);\t\t\t\t\\\n}\t\t\t\t\t\t\t\t\t\t\t\\\nstatic void k618_##name##_rel(void *u, type *l)\t\t\t\t\t\\\n{\t\t\t\t\t\t\t\t\t\t\t\\\n\tk618_##name##_fn(k618_##name##_data, l, 0);\t\t\t\t\t\\\n}\t\t\t\t\t\t\t\t\t\t\t\\\nstatic inline int register_trace_android_vh_##name(void (*fn)(void *, type *, unsigned long), void *data) \\\n{\t\t\t\t\t\t\t\t\t\t\t\\\n\tint ret;\t\t\t\t\t\t\t\t\t\\\n\t\t\t\t\t\t\t\t\t\t\t\\\n\tk618_##name##_fn = fn;\t\t\t\t\t\t\t\t\\\n\tk618_##name##_data = data;\t\t\t\t\t\t\t\\\n\tret = register_trace_android_vh_##acq(k618_##name##_acq, NULL);\t\t\\\n\tif (ret)\t\t\t\t\t\t\t\t\t\\\n\t\treturn ret;\t\t\t\t\t\t\t\t\\\n\tret = register_trace_android_vh_##rel(k618_##name##_rel, NULL);\t\t\\\n\tif (ret)\t\t\t\t\t\t\t\t\t\\\n\t\tunregister_trace_android_vh_##acq(k618_##name##_acq, NULL);\t\t\\\n\treturn ret;\t\t\t\t\t\t\t\t\t\\\n}\t\t\t\t\t\t\t\t\t\t\t\\\nstatic inline int unregister_trace_android_vh_##name(void (*fn)(void *, type *, unsigned long), void *data) \\\n{\t\t\t\t\t\t\t\t\t\t\t\\\n\tunregister_trace_android_vh_##rel(k618_##name##_rel, NULL);\t\t\t\\\n\treturn unregister_trace_android_vh_##acq(k618_##name##_acq, NULL);\t\t\\\n}\nK618_LOCKTIME(record_mutex_lock_starttime, struct mutex, mutex_lock_acquired, mutex_lock_released)\nK618_LOCKTIME(record_rtmutex_lock_starttime, struct rt_mutex, rtmutex_lock_acquired, rtmutex_lock_released)\n#ifdef CONFIG_PCPU_RWSEM_LOCKING_PROTECT\nK618_LOCKTIME(record_pcpu_rwsem_starttime, struct percpu_rw_semaphore, pcpu_rwsem_lock_acquired,\n\tpcpu_rwsem_lock_released)\n#endif\n\n/* an rwsem: taken by a reader or the writer, let go by either */\nstatic void (*k618_rwsem_fn)(void *, struct rw_semaphore *, unsigned long);\nstatic void *k618_rwsem_data;\nstatic void k618_rwsem_racq(void *u, struct rw_semaphore *s, struct list_head *w)\n{\n\tk618_rwsem_fn(k618_rwsem_data, s, jiffies);\n}\nstatic void k618_rwsem_wacq(void *u, struct rw_semaphore *s)\n{\n\tk618_rwsem_fn(k618_rwsem_data, s, jiffies);\n}\nstatic void k618_rwsem_rel(void *u, struct rw_semaphore *s)\n{\n\tk618_rwsem_fn(k618_rwsem_data, s, 0);\n}\nstatic inline int unregister_trace_android_vh_record_rwsem_lock_starttime(\n\tvoid (*fn)(void *, struct rw_semaphore *, unsigned long), void *data)\n{\n\tunregister_trace_android_vh_clear_rwsem_writer_owned(k618_rwsem_rel, NULL);\n\tunregister_trace_android_vh_clear_rwsem_reader_owned(k618_rwsem_rel, NULL);\n\tunregister_trace_android_vh_record_rwsem_writer_owned(k618_rwsem_wacq, NULL);\n\treturn unregister_trace_android_vh_record_rwsem_reader_owned(k618_rwsem_racq, NULL);\n}\nstatic inline int register_trace_android_vh_record_rwsem_lock_starttime(\n\tvoid (*fn)(void *, struct rw_semaphore *, unsigned long), void *data)\n{\n\tint ret;\n\n\tk618_rwsem_fn = fn;\n\tk618_rwsem_data = data;\n\tret = register_trace_android_vh_record_rwsem_reader_owned(k618_rwsem_racq, NULL);\n\tif (!ret)\n\t\tret = register_trace_android_vh_record_rwsem_writer_owned(k618_rwsem_wacq, NULL);\n\tif (!ret)\n\t\tret = register_trace_android_vh_clear_rwsem_reader_owned(k618_rwsem_rel, NULL);\n\tif (!ret)\n\t\tret = register_trace_android_vh_clear_rwsem_writer_owned(k618_rwsem_rel, NULL);\n\tif (ret)\n\t\tunregister_trace_android_vh_record_rwsem_lock_starttime(fn, data);\n\treturn ret;\n}\n"),
    # sched_assist's copies of fair.c: 6.18's sched.h has attach_task()/attach_one_task() itself
    # (static inline) and declares sysctl_sched_migration_cost (const_debug is gone): the copies
    # out of the way, the module's migration cost its own variable
    ("sa_balance.c",
     "const_debug unsigned int sysctl_sched_migration_cost\t= 500000UL;\n",
     "/* op13: its own copy; sched.h declares the kernel's (scripts/oplus_fix.py) */\n"
     "static unsigned int k618_sched_migration_cost = 500000UL;\n"
     "#define sysctl_sched_migration_cost k618_sched_migration_cost\n"),
    ("sa_balance.c",
     "static void attach_task(struct rq *rq, struct task_struct *p)\n{\n",
     "static void __maybe_unused k618_fair_attach_task(struct rq *rq, struct task_struct *p)\n{\n"),
    ("sa_balance.c",
     "static void attach_one_task(struct rq *rq, struct task_struct *p)\n{\n",
     "static void __maybe_unused k618_fair_attach_one_task(struct rq *rq, struct task_struct *p)\n{\n"),
    # Wi-Fi (qcacld sme_api.c, OnePlus' extended latency levels): its two ini items are missing from
    # struct cfg_values in this build ("no member named '__CFG_LATENCY_FLAGS_LOW_EXT_internal'"):
    # their defaults (cfg_mlme_fe_wlm.h's CFG_DEFAULT_*_EXT_FLAGS) instead of the ini lookup
    ("sme_api.c", "cfg_get(mac->psoc, CFG_LATENCY_FLAGS_LOW_EXT)", "\"0x184c03\" /* op13 */"),
    ("sme_api.c", "cfg_get(mac->psoc, CFG_LATENCY_FLAGS_ULTLOW_EXT)", "\"0x180c03\" /* op13 */"),
    # the wireless pen (built from its Makefile) uses oplus_project.h's boot modes (FACTORY_MODE),
    # which exist under OnePlus' Qualcomm platform switch, as its kernel config had it
    ("oplus_cps8601.c",
     "#ifndef CONFIG_DISABLE_OPLUS_FUNCTION\n#include <soc/oplus/system/oplus_project.h>",
     "#ifndef CONFIG_OPLUS_SYSTEM_KERNEL_QCOM\t/* op13: scripts/oplus_fix.py */\n#define CONFIG_OPLUS_SYSTEM_KERNEL_QCOM 1\n#endif\n"
     "#ifndef CONFIG_DISABLE_OPLUS_FUNCTION\n#include <soc/oplus/system/oplus_project.h>"),
    # locking_strategy's rwsem.c keeps its own rwsem_owner()/is_rwsem_reader_owned(), which 6.18's
    # linux/rwsem.h now declares (non-static): its copies under their own names
    ("rwsem.c",
     "static inline struct task_struct *rwsem_owner(struct rw_semaphore *sem)\n",
     "/* op13: 6.18's rwsem.h declares these (scripts/oplus_fix.py) */\n"
     "#define rwsem_owner k618_rwsem_owner\n#define is_rwsem_reader_owned k618_is_rwsem_reader_owned\n"
     "static inline struct task_struct *rwsem_owner(struct rw_semaphore *sem)\n"),
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
