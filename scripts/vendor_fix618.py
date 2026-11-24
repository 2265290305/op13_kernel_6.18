#!/usr/bin/env python3
"""vendor_fix618.py <dir>...: the 6.6 -> 6.18 API changes that OnePlus' and Qualcomm's 6.6 driver
sources trip over, beyond what the reference's k618_fix618.py does. Mechanical, idempotent, on
every .c/.h under the directories. Each rule is a kernel change between 6.6 and 6.18:

  platform remove        struct platform_driver.remove returns void (6.11): an int-returning
                         remove function becomes void, its returns plain returns
  bin_attribute          sysfs binary attribute read/write take a const struct bin_attribute (6.13)
  proc_handler           sysctl handlers take a const struct ctl_table (6.11)
  struct fd              fd.file is fd_file(fd) (6.12)
  asm/unaligned.h        moved to linux/unaligned.h (6.12)
  strlcpy                removed (6.8): strscpy
  pwm_apply_state        pwm_apply_might_sleep (6.8)
  DAI formats            SND_SOC_DAIFMT_CB{S,M}_CF{S,M} -> CB{C,P}_CF{C,P} (6.x)
  ANDROID_KABI           the reserved fields are __kabi_reservedN in 6.18's android_kabi.h
  no_llseek              removed (6.12): a NULL .llseek is the same
  dma-fence              .fence_value_str/.timeline_value_str gone; __dma_fence_is_later(fence, a, b)
  compression            the legacy crypto_comp API is gone (6.15+): hybridswap's zcomp on acomp,
                         legacy compress registrations dropped where scomp is there, scomp's
                         per-stream allocators in .streams
  snd_soc_unregister_component   a macro now (dev only): a function pointer to it goes through a
                         small wrapper
  missing includes       vmalloc/vfree, platform_device_id, devm_gpio_request: headers 6.6
                         pulled in indirectly and 6.18 does not

Prints the files it changed. A rule only applies where its old form is there.
"""
import os
import re
import sys

changed = {}


def note(path, rule):
	changed.setdefault(path, set()).add(rule)


def find_body(text, start):
	"""the index range of the {...} block starting at the first '{' from start."""
	i = text.find("{", start)
	if i < 0:
		return None
	depth = 0
	for j in range(i, len(text)):
		c = text[j]
		if c == "{":
			depth += 1
		elif c == "}":
			depth -= 1
			if depth == 0:
				return i, j
	return None


def wrap_external_remove(text, path):
	"""a platform_driver whose .remove is defined in another file (still returning int there): a
	void wrapper here that calls it."""
	for blk in re.finditer(r"^(?:static\s+)?(?:const\s+)?struct\s+platform_driver\s+\w+\s*=\s*\{.*?\n\};", text, re.S | re.M):
		m = re.search(r"\.remove\s*=\s*(\w+)\s*,", blk.group(0))
		if not m or m.group(1).startswith("k618_"):
			continue
		f = m.group(1)
		if re.search(r"\b(?:int|void)\s+(?:__exit\s+)?%s\s*\(\s*struct\s+platform_device" % re.escape(f), text):
			continue		# defined (or declared) here: fix_platform_remove's
		wrap = ("/* 6.18: platform_driver.remove returns void (vendor_fix618.py) */\n"
			"static void k618_remove_%s(struct platform_device *pdev)\n{\n\t%s(pdev);\n}\n\n") % (f, f)
		newblk = blk.group(0).replace(m.group(0), m.group(0).replace(f, "k618_remove_" + f), 1)
		text = text.replace(blk.group(0), wrap + newblk, 1)
		note(path, "platform remove (wrapper)")
	return text


def fix_platform_remove(text, path):
	text = wrap_external_remove(text, path)
	names = set(re.findall(r"\.remove\s*=\s*(?:__exit_p\(\s*)?(\w+)", text))
	for name in names:
		sig = re.compile(r"(static\s+)?int\s+(__exit\s+)?" + re.escape(name) +
			r"\s*\(\s*struct\s+platform_device\s*\*\s*\w*\s*\)")
		# prototypes first
		def proto(m):
			return m.group(0).replace("int", "void", 1)
		new = []
		pos = 0
		for m in sig.finditer(text):
			end = m.end()
			rest = text[end:end + 3].lstrip()
			if rest.startswith(";"):
				new.append(text[pos:m.start()] + proto(m))
				pos = end
				continue
			body = find_body(text, end)
			if not body or text[end:body[0]].strip():
				continue
			b0, b1 = body
			inner = text[b0:b1 + 1]
			inner = re.sub(r"\breturn\s+0\s*;", "return;", inner)
			inner = re.sub(r"\breturn\s+([^;]+);", lambda r: "{ (void)(%s); return; }" % r.group(1).strip()
				if r.group(1).strip() else "return;", inner)
			new.append(text[pos:m.start()] + proto(m) + text[end:b0] + inner)
			pos = b1 + 1
			note(path, "platform remove")
		if new:
			new.append(text[pos:])
			text = "".join(new)
	return text


RULES = [
	("asm/unaligned.h", re.compile(r"#include\s*<asm/unaligned\.h>"), "#include <linux/unaligned.h>"),
	("strlcpy", re.compile(r"\bstrlcpy\s*\("), "strscpy("),
	("pwm_apply_state", re.compile(r"\bpwm_apply_state\s*\("), "pwm_apply_might_sleep("),
	("ANDROID_KABI", re.compile(r"\bandroid_kabi_reserved(\d+)\b"), r"__kabi_reserved\1"),
	# the legacy GPIO direction flags (6.x): GPIOF_IN, GPIOF_OUT_INIT_LOW
	("GPIOF", re.compile(r"\bGPIOF_DIR_IN\b"), "GPIOF_IN"),
	("GPIOF", re.compile(r"\bGPIOF_DIR_OUT\b"), "GPIOF_OUT_INIT_LOW"),
	("no_llseek", re.compile(r"(\.llseek\s*=\s*)no_llseek\b"), r"\1NULL"),
	# the inode times are behind accessors (6.7): a helper updating one in place gets a copy written back
	("inode times", re.compile(r"\b(\w+)\(\s*&\s*(file_inode\(\s*\w+\s*\)|\w+)->i_(m|a)time\s*\)\s*;"),
		r"{ struct timespec64 __k618_t = inode_get_\3time(\2); \1(&__k618_t); inode_set_\3time_to_ts(\2, __k618_t); }"),
	# the kernel's own private headers, by the path OnePlus' tree layout gives them: from the kernel
	# source (build_vendor.sh puts it after every other include directory)
	("kernel headers", re.compile(r'#include\s*"(?:\.\./)+(kernel/(?:irq|sched|locking|time|cgroup|workqueue|rcu)/[\w./-]+\.h)"'),
		r"#include <\1>"),
	# cfs_rq.h_nr_running is h_nr_queued since 6.14 (h_nr_runnable leaves the delayed ones out)
	("h_nr_queued", re.compile(r"\bh_nr_running\b"), "h_nr_queued"),
	# dma_fence_ops lost its debug printers (6.12); __dma_fence_is_later takes the fence first (6.13)
	("dma-fence", re.compile(r"^[ \t]*\.(?:fence|timeline)_value_str\s*=\s*\w+\s*,[ \t]*\n", re.M), ""),
	("dma-fence", re.compile(r"\b__dma_fence_is_later\(\s*([^,()]+?)\s*,\s*([^,()]+?)\s*,\s*(\w+)->ops\s*\)"),
		r"__dma_fence_is_later(\3, \1, \2)"),
	("bin_attribute", re.compile(r"(\(\s*struct\s+file\s*\*\s*\w+\s*,\s*struct\s+kobject\s*\*\s*\w+\s*,\s*)"
		r"(struct\s+bin_attribute\s*\*)"), r"\1const \2"),
	("proc_handler", re.compile(r"\(\s*struct\s+ctl_table\s*\*(\s*\w+\s*,\s*int\s+\w+\s*,\s*void\b)"),
		r"(const struct ctl_table *\1"),
]
DAIFMT = {"S": "C", "M": "P"}


def include_if(text, used, header):
	if re.search(used, text) and header not in text:
		m = list(re.finditer(r"^#include\s*[<\"].*$", text, re.M))
		if m:
			at = m[0].start()
			return text[:at] + "#include <%s>\n" % header + text[at:], True
	return text, False


# OnePlus' hybridswap zram keeps the zcomp of zram before 6.12, on the legacy crypto_comp API that
# 6.18 no longer has: the same zcomp on acomp. Synchronous algorithms only (CRYPTO_ALG_ASYNC masked:
# the scomp-backed lz4/zstd/zstdn_o): compression runs under the per-CPU stream's local lock, where
# it must not sleep; linear buffers (the nondma source/destination).
ZCOMP_H = [("struct crypto_comp *tfm;", "struct crypto_acomp *tfm;\n\tstruct acomp_req *req;")]
ZCOMP_C = [
	("#include <linux/crypto.h>\n", "#include <linux/crypto.h>\n#include <crypto/acompress.h>\n"),
	("\tif (!IS_ERR_OR_NULL(zstrm->tfm))\n\t\tcrypto_free_comp(zstrm->tfm);",
	 "\tif (zstrm->req)\n\t\tacomp_request_free(zstrm->req);\n\tzstrm->req = NULL;\n"
	 "\tif (!IS_ERR_OR_NULL(zstrm->tfm))\n\t\tcrypto_free_acomp(zstrm->tfm);"),
	("\tzstrm->tfm = crypto_alloc_comp(comp->name, 0, 0);",
	 "\tzstrm->tfm = crypto_alloc_acomp(comp->name, 0, CRYPTO_ALG_ASYNC);\n"
	 "\tzstrm->req = IS_ERR_OR_NULL(zstrm->tfm) ? NULL : acomp_request_alloc(zstrm->tfm);"),
	("if (IS_ERR_OR_NULL(zstrm->tfm) || !zstrm->buffer) {", "if (IS_ERR_OR_NULL(zstrm->tfm) || !zstrm->req || !zstrm->buffer) {"),
	("crypto_has_comp(comp, 0, 0)", "crypto_has_acomp(comp, 0, CRYPTO_ALG_ASYNC)"),
]
ZCOMP_RX = [
	(re.compile(r"return\s+crypto_comp_compress\(\s*zstrm->tfm\s*,\s*src\s*,\s*PAGE_SIZE\s*,\s*zstrm->buffer\s*,\s*dst_len\s*\)\s*;"),
	 "acomp_request_set_callback(zstrm->req, 0, NULL, NULL);\n"
	 "\tacomp_request_set_src_nondma(zstrm->req, src, PAGE_SIZE);\n"
	 "\tacomp_request_set_dst_nondma(zstrm->req, zstrm->buffer, *dst_len);\n"
	 "\t{\n\t\tint ret = crypto_acomp_compress(zstrm->req);\n\n"
	 "\t\t*dst_len = zstrm->req->dlen;\n\t\treturn ret;\n\t}"),
	(re.compile(r"return\s+crypto_comp_decompress\(\s*zstrm->tfm\s*,\s*src\s*,\s*src_len\s*,\s*dst\s*,\s*&dst_len\s*\)\s*;"),
	 "acomp_request_set_callback(zstrm->req, 0, NULL, NULL);\n"
	 "\tacomp_request_set_src_nondma(zstrm->req, src, src_len);\n"
	 "\tacomp_request_set_dst_nondma(zstrm->req, dst, dst_len);\n"
	 "\treturn crypto_acomp_decompress(zstrm->req);"),
]


def fix_zcomp(path, text):
	if not re.search(r"hybridswap[^/]*/zcomp\.[ch]$", path):
		return text
	for old, new in (ZCOMP_H if path.endswith(".h") else ZCOMP_C):
		if old in text and new not in text:
			text = text.replace(old, new)
			note(path, "zcomp on acomp")
	if path.endswith(".c"):
		for rx, new in ZCOMP_RX:
			text2 = rx.sub(new, text)
			if text2 != text:
				note(path, "zcomp on acomp")
				text = text2
	return text


def fix_comp_alg(path, text):
	"""a compression algorithm registered both the legacy way (crypto_alg with cra_u.compress, gone in
	6.18) and as scomp: the scomp one alone, its per-stream context allocators in 6.18's .streams
	(no tfm argument: these do not use it)."""
	if "struct scomp_alg" not in text or "coa_compress" not in text:
		return text
	for m in list(re.finditer(r"static\s+struct\s+crypto_alg\s+(\w+)\s*=\s*\{.*?\n\};\n", text, re.S)):
		if "coa_compress" not in m.group(0):
			continue
		name = m.group(1)
		text = text.replace(m.group(0), "/* 6.18: the legacy compress registration of %s removed (vendor_fix618.py) */\n" % name)
		text = re.sub(r"\bcrypto_register_alg\(\s*&%s\s*\)" % name, "0", text)
		text = re.sub(r"\bcrypto_unregister_alg\(\s*&%s\s*\)\s*;" % name, ";", text)
		note(path, "legacy compress alg")
	am = re.search(r"\.alloc_ctx\s*=\s*(\w+)\s*,", text)
	fm = re.search(r"\.free_ctx\s*=\s*(\w+)\s*,", text)
	if am and fm and re.search(r"void\s*\*\s*%s\s*\(\s*struct\s+crypto_scomp\s*\*" % am.group(1), text):
		a, f = am.group(1), fm.group(1)
		wrappers = ("static void *k618_%s(void)\n{\n\treturn %s(NULL);\n}\n\n"
			"static void k618_%s(void *ctx)\n{\n\t%s(NULL, ctx);\n}\n\n") % (a, a, f, f)
		text = text.replace(am.group(0), ".streams = {\n\t\t.alloc_ctx = k618_%s,\n\t\t.free_ctx = k618_%s,\n\t}," % (a, f), 1)
		text = text.replace(fm.group(0), "", 1)
		sm = re.search(r"static\s+struct\s+scomp_alg\s+\w+\s*=", text)
		text = text[:sm.start()] + wrappers + text[sm.start():]
		note(path, "scomp streams")
	return text


def balanced_args(text, start):
	"""the arguments of the call whose '(' is at start: (list of top-level argument strings, end)."""
	depth, args, cur, i = 0, [], [], start
	while i < len(text):
		c = text[i]
		if c == "(":
			depth += 1
			if depth == 1:
				i += 1
				continue
		elif c == ")":
			depth -= 1
			if depth == 0:
				args.append("".join(cur))
				return args, i + 1
		elif c == "," and depth == 1:
			args.append("".join(cur))
			cur = []
			i += 1
			continue
		cur.append(c)
		i += 1
	return None, start


def fix_assign_str(path, text):
	"""__assign_str(dst) takes the field alone since 6.10 (the source is __string()'s)."""
	out, pos = [], 0
	for m in re.finditer(r"\b__assign_str\s*\(", text):
		if m.start() < pos:
			continue
		args, end = balanced_args(text, m.end() - 1)
		if not args or len(args) < 2:
			continue
		out.append(text[pos:m.start()] + "__assign_str(%s)" % args[0].strip())
		pos = end
	if not out:
		return text
	note(path, "__assign_str")
	return "".join(out) + text[pos:]


def const_param(text, names, pattern, repl):
	"""in the definitions and prototypes of the named functions, pattern -> repl in the parameters."""
	for name in names:
		rx = re.compile(r"(\b%s\s*\()([^;{)]*\))" % re.escape(name))
		text = rx.sub(lambda m: m.group(1) + re.sub(pattern, repl, m.group(2)), text)
	return text


def fix_callbacks(path, text):
	orig = text
	# bus_type.match takes a const struct device_driver (6.11)
	names = set(re.findall(r"\.match\s*=\s*(\w+)\s*,", text))
	text = const_param(text, names, r"(?<!const )\bstruct\s+device_driver\s*\*", "const struct device_driver *")
	# snd_soc_dai_ops: set_channel_map's slot arrays and get_channel_map's dai are const (6.11): a
	# wrapper of the new type in front of each (the functions themselves pass them on as they were)
	for op, wrap in (("set_channel_map",
			"static int k618_%(f)s(struct snd_soc_dai *dai, unsigned int tx_num, const unsigned int *tx_slot,\n"
			"\t\tunsigned int rx_num, const unsigned int *rx_slot)\n{\n"
			"\treturn %(f)s(dai, tx_num, (unsigned int *)tx_slot, rx_num, (unsigned int *)rx_slot);\n}\n\n"),
			("get_channel_map",
			"static int k618_%(f)s(const struct snd_soc_dai *dai, unsigned int *tx_num, unsigned int *tx_slot,\n"
			"\t\tunsigned int *rx_num, unsigned int *rx_slot)\n{\n"
			"\treturn %(f)s((struct snd_soc_dai *)dai, tx_num, tx_slot, rx_num, rx_slot);\n}\n\n")):
		for f in set(re.findall(r"\.%s\s*=\s*(\w+)\s*," % op, text)):
			if f.startswith("k618_"):
				continue
			m = re.search(r"^static\s+(?:const\s+)?struct\s+snd_soc_dai_ops\b", text, re.M)
			if not m:
				continue
			text = text[:m.start()] + wrap % {"f": f} + text[m.start():]
			text = re.sub(r"(\.%s\s*=\s*)%s\s*," % (op, re.escape(f)), r"\1k618_%s," % f, text)
	if text != orig:
		note(path, "const callbacks")
	return text


# devm_gpio_request() is gone (6.17): the same through gpio_request() and a devres action
DEVM_GPIO = (
	"\n/* 6.18: devm_gpio_request() is gone (vendor_fix618.py) */\n"
	"static void k618_devm_gpio_free(void *gpio)\n{\n\tgpio_free((unsigned long)gpio);\n}\n\n"
	"static int k618_devm_gpio_request(struct device *dev, unsigned int gpio, const char *label)\n{\n"
	"\tint rc = gpio_request(gpio, label);\n\n\tif (rc)\n\t\treturn rc;\n"
	"\treturn devm_add_action_or_reset(dev, k618_devm_gpio_free, (void *)(unsigned long)gpio);\n}\n")


# functions kernel/sched/sched.h has in 6.18 that OnePlus' 6.6 files carry their own copies of
SCHED_H_FUNCS = ("css_tg", "uclamp_bucket_id")


def fix_hrtimer_expr(path, text):
	"""hrtimer_init(T, C, M); T.function = <any expression>; -> hrtimer_setup(T, <expr>, C, M); (the
	reference's k618_fix618 takes only a plain name there, and falls back to the file's only hrtimer
	callback otherwise: the touch panel's per-finger timers from a function table got a wrong one)"""
	out, pos = [], 0
	for m in re.finditer(r"\bhrtimer_init\(\s*([^,;]+?)\s*,\s*([^,;]+?)\s*,\s*([^,;)]+?)\s*\);", text):
		if m.start() < pos:
			continue
		t = m.group(1)
		lhs = re.escape(t[1:].strip()) + r"\s*\." if t.startswith("&") else re.escape(t) + r"\s*->"
		a = re.compile(r"\s*" + lhs + r"function\s*=\s*([^;]+?)\s*;").match(text, m.end())
		if not a or re.fullmatch(r"\w+", a.group(1)):
			continue		# none right after, or a plain name: k618_fix618's
		out.append(text[pos:m.start()] + "hrtimer_setup(%s, %s, %s, %s);" % (t, a.group(1), m.group(2), m.group(3)))
		pos = a.end()
	if not out:
		return text
	note(path, "hrtimer_setup")
	return "".join(out) + text[pos:]


def fix(path):
	try:
		text = open(path, encoding="utf-8", errors="surrogateescape").read()
	except OSError:
		return
	orig = text
	text = fix_zcomp(path, text)
	text = fix_comp_alg(path, text)
	for name, rx, repl in RULES:
		text2 = rx.sub(repl, text)
		if text2 != text:
			note(path, name)
			text = text2
	text2 = re.sub(r"\bSND_SOC_DAIFMT_CB([SM])_CF([SM])\b",
		lambda m: "SND_SOC_DAIFMT_CB%s_CF%s" % (DAIFMT[m.group(1)], DAIFMT[m.group(2)]), text)
	if text2 != text:
		note(path, "DAI formats")
		text = text2
	# struct fd: .file / .flags
	for var in set(re.findall(r"\bstruct\s+fd\s+(\w+)", text)):
		text2 = re.sub(r"\b%s\.file\b" % re.escape(var), "fd_file(%s)" % var, text)
		if text2 != text:
			note(path, "struct fd")
			text = text2
	# nr_irqs is not exported in 6.18: irq_get_nr_irqs() (where the file has no nr_irqs of its own)
	if re.search(r"\bnr_irqs\b", text) and not re.search(r"\b(?:int|unsigned|u32|u16|size_t)\s+(?:int\s+)?nr_irqs\b|->nr_irqs|\.nr_irqs", text):
		text2 = re.sub(r"\bnr_irqs\b(?!\s*\()", "irq_get_nr_irqs()", text)
		if text2 != text:
			note(path, "nr_irqs")
			text = text2
	# kernel/sched/sched.h has css_tg() since 6.7: a file that includes it drops its own copy
	if "kernel/sched/sched.h" in text:
		for fn in SCHED_H_FUNCS:
			text2 = re.sub(r"^(?:static\s+)?(?:inline\s+)?[\w \t\*]*?\b%s\s*\([^)]*\)\s*\{(?:[^{}]|\{[^{}]*\})*\}\n" % fn,
				"/* %s(): kernel/sched/sched.h has it in 6.18 (vendor_fix618.py) */\n" % fn, text, flags=re.M)
			if text2 != text:
				note(path, "sched.h " + fn)
				text = text2
	text = fix_assign_str(path, text)
	text = fix_hrtimer_expr(path, text)
	# OnePlus' boot headers (oplus_project.h, oplus_midplat.h ...) use u32/int32_t with no header for them
	if "/boot/include/" in path and path.endswith(".h") and "#include <linux/types.h>" not in text:
		m = re.search(r"^#define\s+\w+_H_*\s*$", text, re.M)
		if m:
			text = text[:m.end()] + "\n#include <linux/types.h>" + text[m.end():]
			note(path, "include linux/types.h")
	# OnePlus' project info (get_eng_version, FACTORY, AGING ...) used where its header is included only
	# under some option (Wi-Fi's cnss2/debug.h: inside IPC_LOGGING): included unconditionally too
	if re.search(r"\bget_eng_version\s*\(", text) and "soc/oplus/system/oplus_project.h" in text \
			and "/* k618: oplus_project.h */" not in text:
		m = re.search(r"^#include\s*[<\"].*$", text, re.M)
		if m:
			text = text[:m.end()] + "\n#include <soc/oplus/system/oplus_project.h> /* k618: oplus_project.h */" + text[m.end():]
			note(path, "oplus_project.h")
	if path.endswith(".c"):
		text = fix_callbacks(path, text)
		if re.search(r"\bdevm_gpio_request\s*\(", text) and "k618_devm_gpio_request" not in text:
			text = re.sub(r"\bdevm_gpio_request\s*\(", "k618_devm_gpio_request(", text)
			if "linux/gpio.h" not in text:
				text, _ = include_if(text, r".", "linux/gpio.h")
			m = list(re.finditer(r"^#include\s*[<\"].*$", text, re.M))
			at = m[-1].end() if m else 0
			text = text[:at] + "\n" + DEVM_GPIO + text[at:]
			note(path, "devm_gpio_request")
		# struct thermal_zone_device is opaque outside drivers/thermal (6.x): its definition
		if re.search(r"\bstruct\s+thermal_zone_device\b", text) and \
				re.search(r"\b\w*tz\w*->(type|temperature|last_temperature|devdata|ops|tzp|mode|id|device)\b", text) and \
				"thermal_core.h" not in text:
			text, did = include_if(text, r".", "drivers/thermal/thermal_core.h")
			if did:
				note(path, "thermal_core.h")
		# v4l2_ioctl_ops lost vidioc_g_ctrl/vidioc_s_ctrl (6.x: the control framework handles them)
		text2 = re.sub(r"^[ \t]*\.vidioc_[gs]_ctrl\s*=\s*\w+\s*,[ \t]*\n", "", text, flags=re.M)
		if text2 != text:
			note(path, "v4l2 g/s_ctrl")
			text = text2
		text = fix_platform_remove(text, path)
		# a function pointer to the snd_soc_unregister_component macro
		if re.search(r"\bsnd_soc_unregister_component\b(?!\s*\()", text):
			text = re.sub(r"\bsnd_soc_unregister_component\b(?!\s*\()", "k618_snd_soc_unregister_component", text)
			# after the last #include before its first use (some files include more further down)
			first = text.index("k618_snd_soc_unregister_component")
			m = [x for x in re.finditer(r"^#include\s*[<\"].*$", text, re.M) if x.end() < first]
			at = m[-1].end() if m else 0
			text = (text[:at] + "\n/* 6.18: snd_soc_unregister_component() is a macro (vendor_fix618.py) */\n"
				"static void k618_snd_soc_unregister_component(struct device *dev)\n"
				"{\n\tsnd_soc_unregister_component_by_driver(dev, NULL);\n}\n" + text[at:])
			note(path, "snd_soc_unregister_component")
		for used, header in ((r"\bv(?:malloc|zalloc|free)\s*\(", "linux/vmalloc.h"),
				(r"\bstruct\s+platform_device_id\b", "linux/mod_devicetable.h"),
				(r"\bstruct\s+platform_(?:device|driver)\b", "linux/platform_device.h"),
				(r"\balarmtimer_restart\b|\bstruct\s+alarm\b", "linux/alarmtimer.h"),
				# (wakeup sources: <linux/device.h>, which includes pm_wakeup.h; that one must not be
				# included on its own -- doing so broke audio's gpr and every module after it)
				(r"\bwakeup_source_(?:add|remove|create|register)\s*\(", "linux/device.h"),
				(r"\bdevm_gpio_request(?:_one)?\s*\(", "linux/gpio.h")):
			text, did = include_if(text, used, header)
			if did:
				note(path, "include " + header)
	if text != orig:
		open(path, "w", encoding="utf-8", errors="surrogateescape", newline="").write(text)


def main(argv):
	for top in argv[1:]:
		for dp, ds, fs in os.walk(top):
			ds[:] = [d for d in ds if d != ".git"]
			for f in fs:
				if f.endswith((".c", ".h")):
					fix(os.path.join(dp, f))
	rules = {}
	for p, rs in changed.items():
		for r in rs:
			rules[r] = rules.get(r, 0) + 1
	print("vendor_fix618: %d files changed (%s)" % (len(changed), ", ".join("%s %d" % kv for kv in sorted(rules.items()))))
	return 0


if __name__ == "__main__":
	sys.exit(main(sys.argv))
