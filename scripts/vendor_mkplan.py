#!/usr/bin/env python3
"""vendor_mkplan.py: the stock modules OnePlus builds from plain Makefiles (no Bazel definition),
found by the Makefile line that makes each one.

usage: vendor_mkplan.py <tree> <wanted lists> <have dirs> <plan out> <search dir>...
  tree: the build copy (search dirs are relative to it)
  wanted lists, have dirs: as vendor_kbuild.py (colon-separated)
  plan out: one line per directory: directory|options|module names -- the options its Makefile
        switches the wanted modules on with ("obj-$(CONFIG_X) += name.o"), to be set to m

Run after vendor_kbuild.py: the directories it wrote a Kbuild into are Bazel packages, built there.
"""
import os
import re
import sys

TREE, WANT, HAVE, PLAN = sys.argv[1:5]
SEARCH = sys.argv[5:]


def norm(n):
	n = os.path.basename(n.strip())
	return (n[:-3] if n.endswith(".ko") else n).replace("-", "_")


wanted = set()
for f in WANT.split(":"):
	if os.path.isfile(f):
		wanted |= {norm(l.split()[0]) for l in open(f) if l.strip() and not l.startswith("#")}
have = set()
for d in HAVE.split(":"):
	if os.path.isdir(d):
		have |= {norm(x) for x in os.listdir(d) if x.endswith(".ko")}

found = {}		# module -> (dir, option)
for s in SEARCH:
	for dp, ds, fs in os.walk(os.path.join(TREE, s)):
		ds[:] = sorted(x for x in ds if not x.startswith("."))
		for f in ("Makefile", "Kbuild"):
			if f not in fs:
				continue
			text = open(os.path.join(dp, f), errors="ignore").read()
			if text.startswith("# OPMOD"):
				continue		# ours (a Bazel package)
			text = text.replace("\\\n", " ")
			for m in re.finditer(r"^\s*obj-(\$\((CONFIG_\w+)\)|m|y)\s*\+?=\s*(.+)$", text, re.M):
				for o in m.group(3).split():
					if o.endswith(".o"):
						n = norm(o[:-2])
						if n in wanted and n not in have and n not in found:
							found[n] = (os.path.relpath(dp, TREE), m.group(2) or "")

bydir = {}
for n, (d, opt) in sorted(found.items()):
	e = bydir.setdefault(d, [set(), []])
	if opt:
		e[0].add(opt)
	e[1].append(n)
	# the options of the module's own parts too ("<name>-$(CONFIG_X) += part.o"): oplus_haptic's
	# Awinic and SI drivers (CONFIG_AW_HAPTIC, CONFIG_SIH_HAPTIC) -- left out, its core alone did not link
	for f in ("Makefile", "Kbuild"):
		mf = os.path.join(TREE, d, f)
		if os.path.isfile(mf):
			mt = open(mf, errors="ignore").read().replace("\\\n", " ")
			for pm in re.finditer(r"^\s*([\w-]+)-\$\((CONFIG_\w+)\)\s*[:+]?=(.*)$", mt, re.M):
				if norm(pm.group(1)) != n:
					continue
				# not a part whose source OnePlus did not publish (schedinfo's perf_schedinfo.c:
				# "No rule to make target 'perf_schedinfo.o'" cost the whole module)
				parts = [o[:-2] for o in pm.group(3).split() if o.endswith(".o")]
				if all(any(os.path.exists(os.path.join(TREE, d, o + x)) for x in (".c", ".S", ""))
						or re.search(r"^\s*%s-(?:y|objs)\s*[:+]?=" % re.escape(os.path.basename(o)), mt, re.M)
						for o in parts):
					e[0].add(pm.group(2))
with open(PLAN, "w") as p:
	for d, (opts, names) in sorted(bydir.items()):
		p.write("%s|%s|%s\n" % (d, " ".join(sorted(opts)), " ".join(names)))
print("vendor_mkplan: %d modules from %d Makefile directories" % (len(found), len(bydir)))
