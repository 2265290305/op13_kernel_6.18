#!/usr/bin/env python3
"""walt_fix.py <dir>: 6.12 -> 6.18 fixes for WALT (the SM8850 SoC repo's kernel/sched/walt, a copy
under out/walt, after the reference's k618_fix618.py and scripts/vendor_fix618.py). Idempotent: an
edit whose new text is there already (a removal: whose old text is gone) is skipped; otherwise old
text that is missing is an error."""

import os
import sys

# (file, old, new)
EDITS = [
    # 6.18's pick_task() takes the rq_flags (a class may drop the rq lock with them: sched_ext's
    # balance): migrate_tasks() holds the ones its caller pinned
    ("walt_halt.c",
     "\t\tnext = pick_task(rq);\n",
     "\t\tnext = pick_task(rq, rf);\t/* op13: 6.18 (scripts/walt_fix.py) */\n"),
    # 6.18's struct binder_transaction has no need_reply: a transaction that waits for a reply is one
    # that is neither one-way nor itself a reply
    ("walt_cfs.c",
     "bndrtrans && bndrtrans->need_reply && ",
     "bndrtrans && !bndrtrans->is_async && !bndrtrans->is_reply && "),
    # android_vh_binder_restore_priority passes the transaction alone, from the thread whose priority
    # is restored (6.12 passed that thread, always `current` there)
    ("walt_cfs.c",
     "static void binder_restore_priority_hook(void *data,\n"
     "\t\t\t\tstruct binder_transaction *bndrtrans, struct task_struct *task)\n{\n",
     "static void binder_restore_priority_hook(void *data,\n"
     "\t\t\t\tstruct binder_transaction *bndrtrans)\n{\n"
     "\tstruct task_struct *task = current;\t/* op13: 6.18 (scripts/walt_fix.py) */\n"),
    # kernel/sched/sched.h declares set_next_entity() (6.18 added `first`); WALT's own stale
    # declaration of it goes -- WALT never calls it
    ("walt_cfs.c",
     "extern void set_next_entity(struct cfs_rq *cfs_rq, struct sched_entity *se);\n",
     ""),
    # OnePlus' CPU close loop (oplus_bsp_close_loop) steers the governor's utilization through two
    # callbacks it registers with WALT and asks WALT for a frequency update: this tree calls the first
    # callback but defines neither, nor the functions close_loop calls -- the OnePlus 13's own WALT
    # (its 6.6 vendor kernel's kernel/sched/walt) has all of it, taken from there
    ("walt.h",
     "#if IS_ENABLED(CONFIG_OPLUS_FEATURE_FRAME_BOOST)\n#include <frame_boost/frame_group.h>\n#endif\n",
     "#if IS_ENABLED(CONFIG_OPLUS_FEATURE_FRAME_BOOST)\n#include <frame_boost/frame_group.h>\n#endif\n\n"
     "/* op13: the OnePlus 13's WALT (scripts/walt_fix.py) */\n"
     "#if IS_ENABLED(CONFIG_OPLUS_FEATURE_CPU_CLOSE_LOOP)\n"
     "extern void walt_cl_update_util_ops(\n"
     "\tunsigned long (*)(int cpu, unsigned long orig, bool ed_active),\n"
     "\tunsigned long (*)(int cpu, unsigned long orig, bool ed_active));\n"
     "extern void walt_trig_cpufreq_update(int cpu);\n"
     "#endif\n"),
    ("cpufreq_walt.c",
     "static unsigned long waltgov_get_util(struct waltgov_cpu *wg_cpu)\n",
     "/* op13: the OnePlus 13's WALT (scripts/walt_fix.py) */\n"
     "#if IS_ENABLED(CONFIG_OPLUS_FEATURE_CPU_CLOSE_LOOP)\n"
     "static unsigned long cl_util_dummy(int cpu, unsigned long orig, bool ed_active)\n"
     "{\n\treturn orig;\n}\n\n"
     "static unsigned long cl_boost_util_dummy(int cpu, unsigned long orig, bool ed_active)\n"
     "{\n\treturn orig;\n}\n\n"
     "static unsigned long (*walt_cl_util)(int cpu, unsigned long orig, bool ed_active) = cl_util_dummy;\n"
     "static unsigned long (*walt_cl_boost_util)(int cpu, unsigned long orig, bool ed_active) = cl_boost_util_dummy;\n\n"
     "void walt_cl_update_util_ops(\n"
     "\tunsigned long (*cl_util)(int cpu, unsigned long orig, bool ed_active),\n"
     "\tunsigned long (*cl_boost_util)(int cpu, unsigned long orig, bool ed_active))\n"
     "{\n"
     "\twalt_cl_util = cl_util;\n"
     "\twalt_cl_boost_util = cl_boost_util;\n"
     "\tpr_info(\"%s updated\\n\", __func__);\n"
     "}\n"
     "EXPORT_SYMBOL_GPL(walt_cl_update_util_ops);\n\n"
     "void walt_trig_cpufreq_update(int cpu)\n"
     "{\n"
     "\tif (cpu == -1) {\n"
     "\t\tstruct walt_sched_cluster *cluster;\n\n"
     "\t\tfor_each_sched_cluster(cluster) {\n"
     "\t\t\tcpumask_t cluster_online_cpus;\n"
     "\t\t\tunsigned int num_cpus, i = 1;\n"
     "\t\t\tint wflag = WALT_CPUFREQ_BOOST_UPDATE_BIT;\n\n"
     "\t\t\tcpumask_and(&cluster_online_cpus, &cluster->cpus, cpu_online_mask);\n"
     "\t\t\tnum_cpus = cpumask_weight(&cluster_online_cpus);\n\n"
     "\t\t\tfor_each_cpu(cpu, &cluster_online_cpus) {\n"
     "\t\t\t\tif (i == num_cpus)\n"
     "\t\t\t\t\twaltgov_run_callback(cpu_rq(cpu), wflag);\n"
     "\t\t\t\telse\n"
     "\t\t\t\t\twaltgov_run_callback(cpu_rq(cpu), wflag | WALT_CPUFREQ_CONTINUE_BIT);\n"
     "\t\t\t\t++i;\n"
     "\t\t\t}\n"
     "\t\t}\n"
     "\t} else {\n"
     "\t\twaltgov_run_callback(cpu_rq(cpu), WALT_CPUFREQ_BOOST_UPDATE_BIT);\n"
     "\t}\n"
     "}\n"
     "EXPORT_SYMBOL_GPL(walt_trig_cpufreq_update);\n"
     "#endif\n\n"
     "static unsigned long waltgov_get_util(struct waltgov_cpu *wg_cpu)\n"),
    ("cpufreq_walt.c",
     "\t\tstruct waltgov_cpu *wg_cpu, unsigned int reason)\n{\n\tif (boost_util && boost_util >= *cur_util) {\n",
     "\t\tstruct waltgov_cpu *wg_cpu, unsigned int reason)\n{\n"
     "#if IS_ENABLED(CONFIG_OPLUS_FEATURE_CPU_CLOSE_LOOP)\t/* op13: the OnePlus 13's WALT (scripts/walt_fix.py) */\n"
     "\tboost_util = walt_cl_boost_util(wg_cpu->cpu, boost_util, wg_cpu->walt_load.ed_active);\n"
     "#endif\n\n"
     "\tif (boost_util && boost_util >= *cur_util) {\n"),
]


def main(argv):
    d = argv[1]
    n = bad = 0
    for name, old, new in EDITS:
        path = os.path.join(d, name)
        text = open(path, encoding="utf-8").read()
        if new and new in text:
            continue
        if not new and old not in text:
            continue		# a removal made already
        if old not in text:
            print(f"walt_fix: {name}: text to change not found: {old[:60]!r}")
            bad += 1
            continue
        open(path, "w", encoding="utf-8", newline="").write(text.replace(old, new, 1))
        n += 1
    print(f"walt_fix: {n} changes in {d}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
