#!/usr/bin/env python3
"""par_fix618.py <reference dir> <jobs> <dir>...: the reference's k618_fix618.py over each dir, its
files spread over <jobs> processes. Each file is fixed by k618_fix618.fix_file(path, rel) with rel
relative to the dir given, exactly as k618_fix618.py <dir> does it (the same walk, the same skips),
so the result is the same; only faster (one dir took ~3 min a pass in build_vendor.sh)."""
import multiprocessing
import os
import sys

sys.path.insert(0, sys.argv[1])
import k618_fix618 as k  # noqa: E402


def files(top):
	top = top.rstrip("/")
	for dp, _dn, fns in os.walk(top):
		if "/.git" in dp or dp.endswith("/gen"):
			continue
		for fn in fns:
			p = os.path.join(dp, fn)
			if fn.endswith((".c", ".h")) and os.path.isfile(p) and not os.path.islink(p):
				yield p, os.path.relpath(p, top)


def one(job):
	p, rel = job
	return rel if k.fix_file(p, rel) else None


def main(argv):
	jobs = max(1, int(argv[2]))
	with multiprocessing.Pool(jobs) as pool:
		for top in argv[3:]:
			if not os.path.isdir(top):
				continue
			changed = [r for r in pool.map(one, list(files(top)), chunksize=16) if r]
			print(f"k618_fix618: {len(changed)} files changed ({top})")
			for c in changed[:40]:
				print("  ", c)
	return 0


if __name__ == "__main__":
	sys.exit(main(sys.argv))
