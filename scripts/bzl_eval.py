#!/usr/bin/env python3
"""bzl_eval.py: OnePlus' module definitions, as its Bazel (Kleaf) build has them, without Bazel.

OnePlus defines every out-of-tree driver of the OnePlus 13 in Starlark: BUILD.bazel files that load
oplus_local_modules.bzl (and, for the charger, a set of helper scripts), whose
define_oplus_ddk_module() calls reach Kleaf's ddk_module() through OnePlus' own macro file. Starlark
is close enough to Python that those files run as Python here, with Bazel's built-ins (load, glob,
select, package, the rules) replaced by small stand-ins. OnePlus' macro file itself is run as it is;
only ddk_module() and ddk_headers() at the bottom are ours, and they record what they are given.

usage: bzl_eval.py <tree root> <out.json> <package dir>...
  tree root: the directory Bazel labels start from (holds vendor/oplus/...)
  package dir: directories (below the root) searched for BUILD.bazel files

Output: {"modules": [...], "headers": {...}} -- each module with its package, output name, sources
(after glob and conditional_srcs), include directories, defines, copts, the modules it links against
and the header targets it uses, and its kconfig/defconfig files; each header target with its
directories.
"""
import fnmatch
import json
import os
import re
import sys
import types

ROOT = os.path.abspath(sys.argv[1])
OUT = sys.argv[2]
PKGS = sys.argv[3:]
# the configuration these files are evaluated for: sun, perf, OnePlus' 6.6 kernel
TARGET, VARIANT, KVER = "sun", "perf", "6.6"
MACROS = os.path.join(ROOT, "kernel_platform/oplus/bazel")
# the kernel options conditional_srcs and select() test: the stock 6.6 configuration plus each
# module's own defconfig (applied when the module is recorded)
CONFIG = {}

modules, headers, errors = [], {}, []


def stock_config(path):
	for line in open(path, errors="ignore"):
		m = re.match(r"(CONFIG_\w+)=(.*)", line.strip())
		if m:
			CONFIG[m.group(1)] = m.group(2).strip('"')


class Glob:
	"""native.glob: relative to the package of the BUILD file being evaluated (as in Bazel, also
	when called from a macro in another file)."""

	def __call__(self, include, exclude=(), allow_empty=True, exclude_directories=1):
		base = os.path.join(ROOT, CUR["pkg"])
		files = []
		for d, ds, fs in os.walk(base, followlinks=True):
			ds[:] = [x for x in ds if not x.startswith(".")]
			for f in fs:
				files.append(os.path.relpath(os.path.join(d, f), base))
		def match(p, pats):
			for pat in pats:
				# Bazel's ** matches any number of directories, including none
				rx = re.escape(pat).replace(r"\*\*/", "(?:.*/)?").replace(r"\*\*", ".*") \
					.replace(r"\*", "[^/]*").replace(r"\?", "[^/]")
				if re.fullmatch(rx, p):
					return True
			return False
		return sorted(p for p in files if match(p, include) and not match(p, exclude))


def noop(*a, **k):
	return None


class Native(types.SimpleNamespace):
	pass


class Anything:
	"""attr, ctx and the like: any attribute is a function that does nothing."""

	def __getattr__(self, n):
		return noop


def rule(implementation=None, **k):
	"""a custom rule (the charger's generated headers): defining it is enough here; its targets
	are made by the build script."""
	return noop


def startype(x):
	"""Starlark's type(): a name, as the charger's scripts compare it."""
	for t, n in ((bool, "bool"), (int, "int"), (str, "string"), (dict, "dict"), (list, "list"),
			(tuple, "tuple"), (type(None), "NoneType")):
		if isinstance(x, t):
			return n
	return "function" if callable(x) else "struct"


def struct(**k):
	return types.SimpleNamespace(**k)


def fail(msg="", *a):
	raise RuntimeError("fail(): %s" % msg)


def select(d, no_match_error=None):
	"""select() on configuration settings: the one for our target, else the default."""
	for k, v in d.items():
		if TARGET in str(k) and VARIANT in str(k):
			return v
	for k, v in d.items():
		if TARGET in str(k):
			return v
	return d.get("//conditions:default", [] if not d else type(list(d.values())[0])())


def label_to_path(pkg, label):
	"""a label -> (package directory, target name)."""
	if label.startswith("//"):
		p, _, n = label[2:].partition(":")
		return p, n or os.path.basename(p)
	if label.startswith(":"):
		return pkg, label[1:]
	if ":" in label:
		p, _, n = label.partition(":")
		return os.path.join(pkg, p), n
	return pkg, label


def ddk_module(name, srcs=(), out=None, local_defines=None, copts=None, includes=None,
		conditional_srcs=None, linux_includes=None, hdrs=None, deps=(), kernel_build="",
		kconfig=None, defconfig=None, config=None, **kw):
	if "_%s_" % TARGET not in kernel_build + "_" and not kernel_build.endswith("%s_%s" % (TARGET, VARIANT)):
		return		# the other targets OnePlus builds these for (parrot)
	pkg = CUR["pkg"]
	conf = dict(CONFIG)
	defs = []
	for opt, val in PKG_CONF.get(pkg, {}).items():
		conf[opt] = val
		defs.append((opt, val))
	if defconfig:
		for f in resolve_files(pkg, defconfig):
			for line in open(os.path.join(ROOT, f), errors="ignore"):
				m = re.match(r"(CONFIG_\w+)=(.*)", line.strip())
				if m:
					conf[m.group(1)] = m.group(2).strip('"')
					defs.append((m.group(1), m.group(2).strip('"')))
	files = list(srcs or [])
	for opt, branches in (conditional_srcs or {}).items():
		on = conf.get(opt, "n") in ("y", "m")
		files += branches.get(on, [])
	ko, hd = [], []
	for d in deps or ():
		if d == "//msm-kernel:all_headers" or d.startswith("//msm-kernel"):
			continue
		dp, dn = label_to_path(pkg, d)
		(hd if ("%s:%s" % (dp, dn)) in headers else ko).append("%s:%s" % (dp, dn))
	modules.append({
		"package": pkg, "name": name, "out": out or name + ".ko",
		"srcs": [s for s in files if isinstance(s, str)],
		"includes": list(includes or []), "linux_includes": list(linux_includes or []),
		"local_defines": list(local_defines or []), "copts": list(copts or []),
		"deps": ko,
		"hdrs": ["%s:%s" % label_to_path(pkg, h) for h in (hdrs or []) if isinstance(h, str) and
			(h.startswith(":") or h.startswith("//"))],
		"kconfig": resolve_files(pkg, kconfig) if kconfig else [],
		"defconfig": resolve_files(pkg, defconfig) if defconfig else [],
		"defconfig_options": defs,
	})


def resolve_files(pkg, x):
	"""a label or a list of them (files, or genrule-made ones we cannot have) -> package paths."""
	out = []
	for one in (x if isinstance(x, (list, tuple)) else [x]):
		if not isinstance(one, str):
			continue
		p, n = label_to_path(pkg, one)
		f = os.path.join(p, n)
		if os.path.isfile(os.path.join(ROOT, f)):
			out.append(f)
	return out


def ddk_headers(name, hdrs=(), includes=(), linux_includes=(), **kw):
	pkg = CUR["pkg"]
	headers["%s:%s" % (pkg, name)] = {
		"package": pkg,
		"includes": [os.path.normpath(os.path.join(pkg, i)) for i in includes or ()],
		"linux_includes": [os.path.normpath(os.path.join(pkg, i)) for i in linux_includes or ()],
		"hdrs": [h for h in (hdrs or []) if isinstance(h, str)],
	}


CUR = {"pkg": ""}
PKG_CONF = {}
CACHE = {}


def shim_modules():
	paths = types.SimpleNamespace(join=os.path.join, basename=os.path.basename,
		dirname=os.path.dirname, relativize=os.path.relpath, normalize=os.path.normpath)
	sets = types.SimpleNamespace(make=set, to_list=list, union=lambda *s: set().union(*s),
		contains=lambda s, x: x in s)
	return {
		"//build/kernel/kleaf:kernel.bzl": {"ddk_module": ddk_module, "ddk_headers": ddk_headers,
			"kernel_module": noop, "kernel_module_group": noop, "ddk_config": noop,
			"kernel_modules_install": noop},
		"//build/kernel/kleaf:hermetic_tools.bzl": {"hermetic_genrule": noop, "hermetic_exec": noop},
		"//build/kernel/oplus:oplus_modules_dist.bzl": {"ddk_copy_to_dist_dir": noop},
		"//msm-kernel:target_variants.bzl": {"get_all_la_variants": lambda: [(TARGET, VARIANT)],
			"get_all_variants": lambda: [(TARGET, VARIANT)],
			"la_variants": [VARIANT], "la_targets": [TARGET]},
		"//build/bazel_common_rules/dist:dist.bzl": {"copy_to_dist_dir": noop},
		"@bazel_skylib//lib:paths.bzl": {"paths": paths},
		"@bazel_skylib//lib:sets.bzl": {"sets": sets},
		"@bazel_skylib//rules:write_file.bzl": {"write_file": noop},
	}


SHIMS = None


def builtins_for(pkg):
	nat = Native(glob=Glob(), genrule=noop, filegroup=noop, alias=noop, exports_files=noop,
		sh_binary=noop, py_binary=noop, cc_library=noop, package_name=lambda: pkg,
		existing_rule=lambda n: None, existing_rules=lambda: {})
	return {
		"native": nat, "glob": nat.glob, "struct": struct, "fail": fail, "select": select,
		"package": noop, "genrule": noop, "filegroup": noop, "alias": noop, "exports_files": noop,
		"py_binary": noop, "sh_binary": noop, "cc_library": noop, "config_setting": noop,
		"bool_flag": noop, "string_flag": noop, "licenses": noop,
		"True": True, "False": False, "None": None, "print": lambda *a, **k: None,
		"ddk_module": ddk_module, "ddk_headers": ddk_headers,
		"visibility": noop, "rule": rule, "attr": Anything(), "provider": lambda *a, **k: noop,
		"DefaultInfo": noop, "depset": lambda *a, **k: [], "Label": lambda x: x, "type": startype,
	}


def load_file(path, pkg):
	"""run one .bzl file (once) and give its globals."""
	key = os.path.normpath(path)
	if key in CACHE:
		return CACHE[key]
	env = builtins_for(pkg)
	env["load"] = lambda label, *names, **alias: do_load(env, pkg, label, names, alias)
	src = open(path, errors="ignore").read()
	CACHE[key] = env
	exec(compile(src, path, "exec"), env)
	# the charger's per-target configuration (charger/bazel/defconfig/config_define.bzl) has canoe
	# (SM8850) only, not sun: the same ADSP-charger design and charger-v2 framework, so sun takes it
	cfg = env.get("oplus_config")
	if isinstance(cfg, dict) and "qcom" in cfg:
		if TARGET not in cfg["qcom"] and "canoe" in cfg["qcom"]:
			cfg["qcom"][TARGET] = cfg["qcom"]["canoe"]
		# and on Qualcomm 6.6 those options are the configuration its modules are built with (its
		# conditional_srcs and #ifdefs test them): kept for the package being evaluated
		PKG_CONF[CUR["pkg"]] = dict(cfg["qcom"].get(TARGET, {}).get(VARIANT, {}))
	return env


def do_load(env, pkg, label, names, alias):
	global SHIMS
	if SHIMS is None:
		SHIMS = shim_modules()
	if label in SHIMS:
		src = SHIMS[label]
	elif label.startswith("//build/kernel/oplus:"):
		src = load_file(os.path.join(MACROS, label.split(":", 1)[1]), "kernel_platform/oplus/bazel")
	elif label.startswith(":") or label.startswith("//vendor/"):
		p, n = label_to_path(pkg, label)
		src = load_file(os.path.join(ROOT, p, n), p)
	elif label.startswith("//"):
		p, n = label_to_path(pkg, label)
		f = os.path.join(ROOT, p, n)
		if not os.path.isfile(f):
			raise RuntimeError("cannot load %s" % label)
		src = load_file(f, p)
	else:
		raise RuntimeError("cannot load %s" % label)
	for n in names:
		env[n] = src[n] if n in src else noop
	for a, n in alias.items():
		env[a] = src[n] if n in src else noop


def main():
	stock = os.environ.get("STOCK_CONFIG")
	if stock and os.path.isfile(stock):
		stock_config(stock)
	# OnePlus' macro file: OPLUS_FEATURES and the kernel version come from its variant file,
	# which its build generates; ours names sun/perf and the 6.6 kernel these sources are for
	variant = os.path.join(MACROS, "oplus_modules_variant.bzl")
	CACHE[os.path.normpath(variant)] = {
		"bazel_support_target": [TARGET], "bazel_support_variant": [VARIANT],
		"LINUX_KERNEL_VERSION": KVER, "OPLUS_FEATURES": os.environ.get("OPLUS_FEATURES", ""),
	}
	builds = []
	for p in PKGS:
		for d, ds, fs in os.walk(os.path.join(ROOT, p)):
			ds[:] = sorted(x for x in ds if not x.startswith("."))
			if "BUILD.bazel" in fs:
				builds.append(os.path.relpath(d, ROOT))
	# header targets first, so a module's deps can be told apart from linked modules
	for passno in (0, 1):
		if passno == 1:
			modules.clear()
		for pkg in builds:
			CUR["pkg"] = pkg
			for k in [k for k in CACHE if k.startswith(os.path.join(ROOT, pkg) + "/")]:
				del CACHE[k]
			try:
				load_file(os.path.join(ROOT, pkg, "BUILD.bazel"), pkg)
			except Exception as e:		# noqa: BLE001 -- report and go on with the others
				if passno == 1:
					errors.append("%s: %s: %s @ %s" % (pkg, type(e).__name__, e, " <- ".join("%s:%d" % (os.path.relpath(f.filename, ROOT), f.lineno) for f in __import__("traceback").extract_tb(e.__traceback__)[-3:])))
			CACHE.pop(os.path.normpath(os.path.join(ROOT, pkg, "BUILD.bazel")), None)
	json.dump({"modules": modules, "headers": headers, "errors": errors}, open(OUT, "w"), indent=1)
	print("bzl_eval: %d BUILD files, %d modules, %d header targets, %d errors"
		% (len(builds), len(modules), len(headers), len(errors)))
	for e in errors:
		print("bzl_eval: " + e)


main()
