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
