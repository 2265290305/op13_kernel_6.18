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
		# defined (or declared) here: fix_platform_remove's -- unless the same function is also
		# stored in another int-returning pointer (pogo_keyboard: client->remove = it), which keeps it int
		if re.search(r"\b(?:int|void)\s+(?:__exit\s+)?%s\s*\(\s*struct\s+platform_device" % re.escape(f), text) \
				and not re.search(r"->\s*\w+\s*=\s*%s\s*;" % re.escape(f), text):
			continue
		wrap = ("/* 6.18: platform_driver.remove returns void (vendor_fix618.py) */\n"
			"static void k618_remove_%s(struct platform_device *pdev)\n{\n\t(void)%s(pdev);\n}\n\n") % (f, f)
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
	# zpool is gone (6.18, CONFIG_ZPOOL with it): its header only where the zpool code still is
	("zpool.h", re.compile(r"(?<!#ifdef CONFIG_ZPOOL\n)^#include\s*<linux/zpool\.h>[ \t]*$", re.M),
		"#ifdef CONFIG_ZPOOL\n#include <linux/zpool.h>\n#endif"),
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
	# the runnable ones without the delayed-dequeue ones: h_nr_runnable (6.14; h_nr_delayed is gone)
	("h_nr_runnable", re.compile(r"\b([\w>.-]+?)->h_nr_queued\s*-\s*\1->h_nr_delayed\b"), r"\1->h_nr_runnable"),
	# EEVDF's bookkeeping renamed (6.18): min_vruntime -> zero_vruntime, the weighted key sum and the
	# weight behind avg_vruntime() -> sum_w_vruntime, sum_weight
	("eevdf fields", re.compile(r"\b(cfs_rq|cfs)->min_vruntime\b"), r"\1->zero_vruntime"),
	("eevdf fields", re.compile(r"\b(cfs_rq|cfs)->avg_vruntime\b"), r"\1->sum_w_vruntime"),
	("eevdf fields", re.compile(r"\b(cfs_rq|cfs)->avg_load\b"), r"\1->sum_weight"),
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


def insert_top_level(text, marker, code):
	"""code placed after the last #include ahead of marker's first use that no #if encloses."""
	first = text.index(marker)
	at, any_at, depth = 0, 0, 0
	for x in re.finditer(r"^[ \t]*#[ \t]*(if|ifdef|ifndef|endif|include)\b.*$", text, re.M):
		if x.start() >= first:
			break
		if x.group(1) in ("if", "ifdef", "ifndef"):
			depth += 1
		elif x.group(1) == "endif":
			depth = max(depth - 1, 0)
		else:
			any_at = x.end()
			if depth == 0:
				at = x.end()
	# a header's includes are all inside its guard: after the last one before the use, then
	at = at or any_at
	return text[:at] + "\n" + code + text[at:]


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
		# the timer by its tokens, whitespace between them free: datarmnet-ext's generated sources
		# break "&X.\nY" over lines, and an exact match missed them (rmnet_mem's and rmnet_shs'
		# timers were set up with no callback: "WARNING: ... __hrtimer_setup", test-46)
		tok = re.findall(r"\w+|[^\w\s]", t)
		amp = tok[:1] == ["&"]
		lhs = r"\s*".join(re.escape(x) for x in (tok[1:] if amp else tok)) + (r"\s*\.\s*" if amp else r"\s*->\s*")
		a = re.compile(r"\s*" + lhs + r"function\s*=\s*([^;]+?)\s*;").match(text, m.end())
		if not a:
			# an array of timers set up in a loop, each one's callback assigned after by index (the
			# charger's ufcs_timer.c): 6.18's placeholder callback for that, not NULL (a WARN each)
			if re.search(r"\[\s*\w+\s*\]\s*$", t):
				out.append(text[pos:m.start()] + "hrtimer_setup(%s, hrtimer_dummy_timeout, %s, %s);"
					% (t, m.group(2), m.group(3)))
				pos = m.end()
			continue		# otherwise none right after: k618_fix618's
		out.append(text[pos:m.start()] + "hrtimer_setup(%s, %s, %s, %s);" % (t, a.group(1), m.group(2), m.group(3)))
		pos = a.end()
	if not out:
		return text
	note(path, "hrtimer_setup")
	return "".join(out) + text[pos:]


def required_literal(pattern):
	"""the longest identifier (5+ characters) a pattern requires: outside any group, character class
	or escape, and not under a quantifier -- a file without it cannot match, so the rule is skipped
	there (unanchored rules starting with a class ran at every position of every file: the
	preparation of the vendor trees went from ~9 to ~21 min a pass)"""
	best, depth, i, cls = "", 0, 0, False
	while i < len(pattern):
		c = pattern[i]
		if c == "\\":
			i += 2
			continue
		if cls:
			cls = c != "]"
		elif c == "[":
			cls = True
		elif c == "(":
			depth += 1
		elif c == ")":
			depth -= 1
		elif depth == 0 and (c.isalpha() or c == "_"):
			j = i
			while j < len(pattern) and (pattern[j].isalnum() or pattern[j] == "_"):
				j += 1
			run = pattern[i:j]
			if j < len(pattern) and pattern[j] in "?*{":
				run = run[:-1]		# its last character is optional
			if len(run) >= 5 and len(run) > len(best):
				best = run
			i = j
			continue
		elif c == "|" and depth == 0:
			return ""		# alternatives at the top: nothing is required
		i += 1
	return best


RULE_LITERALS = [required_literal(rx.pattern) for _n, rx, _r in RULES]


def fix(path):
	try:
		text = open(path, encoding="utf-8", errors="surrogateescape").read()
	except OSError:
		return
	orig = text
	text = fix_zcomp(path, text)
	text = fix_comp_alg(path, text)
	for (name, rx, repl), lit in zip(RULES, RULE_LITERALS):
		if lit and lit not in text:
			continue		# cannot match: the literal it requires is not there
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
		# its flags are the low bits of .word (6.12): FDPUT_POS_UNLOCK set or tested there
		text2 = re.sub(r"\b%s\.flags(\s*(?:\|=|&=?)\s*~?\s*FDPUT_)" % re.escape(var), r"%s.word\1" % var, text2)
		if text2 != text:
			note(path, "struct fd")
			text = text2
	# android_vh_page_should_be_protected lost its u64 *data argument (6.12 ACK); OnePlus' handlers
	# never read it
	text2 = re.sub(r"(s8\s+priority\s*,\s*)u64\s*\*\s*\w+\s*,(\s*int\s*\*\s*should_protect)", r"\1\2", text)
	if text2 != text:
		note(path, "page_should_be_protected hook")
		text = text2
	# blk_rq_map_kern() lost its request_queue argument (6.16): (q, rq, buf, len, gfp) -> (rq, ...)
	text2 = re.sub(r"\bblk_rq_map_kern\(\s*[\w>.-]+\s*,(\s*[\w>.-]+\s*,[^,;()]+,[^,;()]+,[^,;()]+\))",
		r"blk_rq_map_kern(\1", text)
	if text2 != text:
		note(path, "blk_rq_map_kern")
		text = text2
	# UTP_CMD_TYPE_DEV_MANAGE left ufshci.h (6.x: device commands are UFS_STORAGE ones); its value
	if "UTP_CMD_TYPE_DEV_MANAGE" in text and "define UTP_CMD_TYPE_DEV_MANAGE" not in text:
		text = re.sub(r"(\A(?:.*\n)*?#include\s*[<\"].*\n)",
			r"\1#ifndef UTP_CMD_TYPE_DEV_MANAGE\n#define UTP_CMD_TYPE_DEV_MANAGE 0x2\t/* gone from ufshci.h (vendor_fix618.py) */\n#endif\n",
			text, count=1)
		note(path, "UTP_CMD_TYPE_DEV_MANAGE")
	# cpufreq_get_policy() is gone (6.x): what it did -- a copy of the CPU's policy -- through
	# cpufreq_cpu_get()/cpufreq_cpu_put() (game_opt)
	if re.search(r"\bcpufreq_get_policy\s*\(", text) and "k618_cpufreq_get_policy" not in text \
			and not re.search(r"^\w[^;]*\bcpufreq_get_policy\s*\([^;]*\)\s*\{", text, re.M):
		text = re.sub(r"\bcpufreq_get_policy\s*\(", "k618_cpufreq_get_policy(", text)
		text = insert_top_level(text, "k618_cpufreq_get_policy(",
			"/* 6.x: cpufreq_get_policy() is gone (vendor_fix618.py) */\n"
			"static int k618_cpufreq_get_policy(struct cpufreq_policy *policy, unsigned int cpu)\n{\n"
			"\tstruct cpufreq_policy *p = cpufreq_cpu_get(cpu);\n\n"
			"\tif (!p)\n\t\treturn -EINVAL;\n\tmemcpy(policy, p, sizeof(*policy));\n"
			"\tcpufreq_cpu_put(p);\n\treturn 0;\n}\n")
		note(path, "cpufreq_get_policy")
	# file->f_path is const (6.13)
	text2 = re.sub(r"(?<!const )\bstruct\s+path\s*\*\s*(\w+)\s*=\s*(&\s*\(?[^;]*->\s*f_path\s*\)?\s*;)",
		r"const struct path *\1 = \2", text)
	if text2 != text:
		note(path, "const f_path")
		text = text2
	# wakeup sources in a header too (the fingerprint driver's wakelock.h): <linux/device.h>
	if path.endswith(".h") and re.search(r"\bwakeup_source_(?:add|remove|create|register)\s*\(", text) \
			and "linux/device.h" not in text and "pm_wakeup.h" not in text:
		text, did = include_if(text, r".", "linux/device.h")
		if did:
			note(path, "include linux/device.h")
	# GPIO_DYNAMIC_BASE left the public headers (6.x; still 512 in gpiolib.h) and GPIOF_INIT_LOW/HIGH
	# are gone (6.18): their old values, where a file still uses them (OnePlus' camera actuator)
	for name, val in (("GPIO_DYNAMIC_BASE", "512"), ("GPIOF_INIT_LOW", "(0 << 1)"), ("GPIOF_INIT_HIGH", "(1 << 1)")):
		if re.search(r"\b%s\b" % name, text) and not re.search(r"#\s*define\s+%s\b" % name, text):
			text = insert_top_level(text, name, "#ifndef %s\n#define %s %s\t/* gone in 6.18 (vendor_fix618.py) */\n#endif\n"
				% (name, name, val))
			note(path, name)
	# try_to_free_mem_cgroup_pages() takes a swappiness pointer since 6.12 (NULL: the memcg's own); a
	# file's own extern copy of the old prototype goes (linux/swap.h has it)
	if "try_to_free_mem_cgroup_pages" in text:
		text2 = re.sub(r"^[ \t]*extern\s+unsigned\s+long\s+try_to_free_mem_cgroup_pages\s*\([^;]*\)\s*;[ \t]*\n", "",
			text, flags=re.M)
		out, i = [], 0
		for m in re.finditer(r"\btry_to_free_mem_cgroup_pages\s*\(", text2):
			j, depth, commas = m.end(), 1, 0
			while j < len(text2) and depth:
				c = text2[j]
				depth += c == "("
				depth -= c == ")"
				commas += c == "," and depth == 1
				j += 1
			# a call with the old four arguments (a definition or a prototype has types: skipped)
			if commas == 3 and not re.search(r"\bstruct\s+mem_cgroup\s*\*", text2[m.end():j]):
				out.append(text2[i:j - 1] + ", NULL)")
				i = j
		text2 = "".join(out) + text2[i:]
		if text2 != text:
			note(path, "try_to_free_mem_cgroup_pages")
			text = text2
	# bus match callbacks take a const driver (6.11): the bus's to_<x>_driver() helpers have to take
	# one too (Qualcomm's soundwire: swr_device_match -> to_swr_driver) -- container_of drops it
	text2 = re.sub(r"(static\s+inline\s+struct\s+\w+\s*\*\s*to_\w+_driver\s*\()\s*struct\s+device_driver\s*\*",
		r"\1const struct device_driver *", text)
	if text2 != text:
		note(path, "const to_*_driver")
		text = text2
	# the thermal core keeps trip descriptors since 6.12: tz->trips[i] is a struct thermal_trip_desc
	# (its .trip the trip), each with its own instance list (thermal_instances/trip_node: tz-wide
	# thermal_instances/tz_node are gone), and __thermal_zone_get_trip() is gone (oplus_ipa_thermal)
	if re.search(r"->thermal_instances\s*,\s*tz_node|__thermal_zone_get_trip\s*\(|struct\s+thermal_trip\s*\*\s*\w+\s*=\s*&\s*\w+->trips\[", text):
		text = re.sub(r"(struct\s+thermal_trip\s*\*\s*\w+\s*=\s*&\s*\w+->trips\[[^\];]+\])(\s*;)", r"\1.trip\2", text)
		text = re.sub(r"\blist_for_each_entry\(\s*(\w+)\s*,\s*&\s*(\w+)->thermal_instances\s*,\s*tz_node\s*\)",
			r"k618_for_each_tz_instance(\2, \1)", text)
		if "__thermal_zone_get_trip" in text and "k618_thermal_zone_get_trip" not in text:
			text = re.sub(r"\b__thermal_zone_get_trip\s*\(", "k618_thermal_zone_get_trip(", text)
		marker = "k618_for_each_tz_instance" if "k618_for_each_tz_instance" in text else "k618_thermal_zone_get_trip"
		if "define k618_for_each_tz_instance" not in text:
			text = insert_top_level(text, marker,
				"/* 6.12+ thermal core: trip descriptors (vendor_fix618.py) */\n"
				"#define k618_for_each_tz_instance(tz, inst) \\\n"
				"\tfor (struct thermal_trip_desc *__k618_td = (tz)->trips; \\\n"
				"\t     __k618_td - (tz)->trips < (tz)->num_trips; __k618_td++) \\\n"
				"\t\tlist_for_each_entry(inst, &__k618_td->thermal_instances, trip_node)\n"
				"static inline int k618_thermal_zone_get_trip(struct thermal_zone_device *tz, int id,\n"
				"\t\tstruct thermal_trip *trip)\n{\n"
				"\tif (!tz || id < 0 || id >= tz->num_trips || !trip)\n\t\treturn -EINVAL;\n"
				"\t*trip = tz->trips[id].trip;\n\treturn 0;\n}\n")
		note(path, "thermal trip descriptors")
	# init_dummy_netdev() is static since 6.13 (alloc_netdev_dummy() allocates one): IPA and Wi-Fi
	# embed theirs (NAPI only). What alloc_netdev() + the dummy init set up, on the embedded one
	if re.search(r"\binit_dummy_netdev\s*\(", text) and "k618_init_dummy_netdev" not in text \
			and not re.search(r"^\w[^;]*\binit_dummy_netdev\s*\([^;]*\)\s*\{", text, re.M):
		text = re.sub(r"\binit_dummy_netdev\s*\(", "k618_init_dummy_netdev(", text)
		text = insert_top_level(text, "k618_init_dummy_netdev(",
			"/* 6.13+: init_dummy_netdev() is not exported; a NAPI-only dummy (vendor_fix618.py) */\n"
			"#ifndef K618_INIT_DUMMY_NETDEV\n#define K618_INIT_DUMMY_NETDEV\n"
			"static inline int k618_init_dummy_netdev(struct net_device *dev)\n{\n"
			"\tmemset(dev, 0, sizeof(*dev));\n"
			"\tINIT_LIST_HEAD(&dev->napi_list);\n\tINIT_LIST_HEAD(&dev->unreg_list);\n"
			"\tINIT_LIST_HEAD(&dev->close_list);\n\tINIT_LIST_HEAD(&dev->link_watch_list);\n"
			"\tINIT_LIST_HEAD(&dev->ptype_all);\n\tINIT_LIST_HEAD(&dev->ptype_specific);\n"
			"\tmutex_init(&dev->lock);\n\tdev_net_set(dev, &init_net);\n"
			"\tdev->reg_state = NETREG_DUMMY;\n"
			"\tset_bit(__LINK_STATE_PRESENT, &dev->state);\n\tset_bit(__LINK_STATE_START, &dev->state);\n"
			"\treturn 0;\n}\n#endif\n")
		note(path, "init_dummy_netdev")
	# struct sched_param is in linux/sched.h (6.x): a file's own copy goes (camera's request manager)
	text2 = re.sub(r"^struct\s+sched_param\s*\{[^}]*\};[ \t]*\n", "/* 6.x: struct sched_param is linux/sched.h's (vendor_fix618.py) */\n",
		text, flags=re.M)
	if text2 != text:
		note(path, "sched_param")
		text = text2
	# blkdev_get_by_dev()/blkdev_put() are gone (6.9+): bdev_file_open_by_dev() hands back a file,
	# put when done -- as the kernel's own zram does. The files opened, by their bdev (hybridswap)
	if re.search(r"\bblkdev_get_by_dev\s*\(", text) and "k618_blkdev_get_by_dev" not in text:
		text = re.sub(r"\bblkdev_get_by_dev\s*\(", "k618_blkdev_get_by_dev(", text)
		text = re.sub(r"\bblkdev_put\s*\(", "k618_blkdev_put(", text)
		# set_blocksize() takes the opened file (6.10+): the one this shim opened for the bdev
		text = re.sub(r"\bset_blocksize\s*\(", "k618_set_blocksize(", text)
		marker = "k618_blkdev_put(" if text.find("k618_blkdev_put(") != -1 and \
			text.find("k618_blkdev_put(") < text.find("k618_blkdev_get_by_dev(") else "k618_blkdev_get_by_dev("
		text = insert_top_level(text, marker,
			"/* 6.9+: block devices are opened as files (vendor_fix618.py) */\n"
			"static struct file *k618_bdev_files[8];\n"
			"static struct block_device *k618_blkdev_get_by_dev(dev_t dev, unsigned int mode, void *holder,\n"
			"\t\tconst struct blk_holder_ops *hops)\n{\n"
			"\tstruct file *f = bdev_file_open_by_dev(dev, (__force blk_mode_t)mode, holder, hops);\n"
			"\tint i;\n\n\tif (IS_ERR(f))\n\t\treturn ERR_CAST(f);\n"
			"\tfor (i = 0; i < ARRAY_SIZE(k618_bdev_files); i++)\n"
			"\t\tif (!k618_bdev_files[i]) {\n\t\t\tk618_bdev_files[i] = f;\n\t\t\treturn file_bdev(f);\n\t\t}\n"
			"\tfput(f);\n\treturn ERR_PTR(-EMFILE);\n}\n\n"
			"static void k618_blkdev_put(struct block_device *bdev, void *holder)\n{\n\tint i;\n\n"
			"\tfor (i = 0; i < ARRAY_SIZE(k618_bdev_files); i++)\n"
			"\t\tif (k618_bdev_files[i] && file_bdev(k618_bdev_files[i]) == bdev) {\n"
			"\t\t\tfput(k618_bdev_files[i]);\n\t\t\tk618_bdev_files[i] = NULL;\n\t\t\treturn;\n\t\t}\n}\n\n"
			"static int __maybe_unused k618_set_blocksize(struct block_device *bdev, int size)\n{\n\tint i;\n\n"
			"\tfor (i = 0; i < ARRAY_SIZE(k618_bdev_files); i++)\n"
			"\t\tif (k618_bdev_files[i] && file_bdev(k618_bdev_files[i]) == bdev)\n"
			"\t\t\treturn set_blocksize(k618_bdev_files[i], size);\n"
			"\treturn -EINVAL;\n}\n")
		note(path, "blkdev_get_by_dev")
	# attribute_group.bin_attrs holds const pointers (6.15): the lists it is given become const
	names = set(re.findall(r"\.bin_attrs\s*=\s*(\w+)\s*,", text))
	for nm in names:
		text2 = re.sub(r"\bstatic\s+struct\s+bin_attribute\s*\*\s*%s\s*\[\]" % re.escape(nm),
			"static const struct bin_attribute *const %s[]" % nm, text)
		if text2 != text:
			note(path, "const bin_attrs")
			text = text2
	# alarm callbacks return void (6.18: enum alarmtimer_restart is gone). Every OnePlus/Qualcomm one
	# returns ALARMTIMER_NORESTART -- none re-arms through its return value
	if "enum alarmtimer_restart" in text and "ALARMTIMER_RESTART;" not in text:
		text = re.sub(r"\benum\s+alarmtimer_restart\b", "void", text)
		text = re.sub(r"\breturn\s+ALARMTIMER_NORESTART\s*;", "return;", text)
		note(path, "alarm callbacks void")
	# NR_BOUNCE is gone (6.16, no bounce buffering left): it counted 0 pages here anyway
	text2 = re.sub(r"\b(?:global_)?zone_page_state\(\s*(?:\w+\s*,\s*)?NR_BOUNCE\s*\)", "0UL", text)
	if text2 != text:
		note(path, "NR_BOUNCE")
		text = text2
	# dma_buf_get_each() is gone (6.16): the exported iterator walks the same list, a reference held
	# on each buffer while the callback looks at it
	# so is android16-6.12's get_dmabuf_debugfs_data(): the same walk with the same callback
	# (mm_osvelte's sys-dmabuf, the stability helper's lowmem watcher)
	text2 = re.sub(r"\bget_dmabuf_debugfs_data\s*\(", "dma_buf_get_each(", text)
	if text2 != text:
		note(path, "get_dmabuf_debugfs_data")
		text = text2
	if re.search(r"\bdma_buf_get_each\s*\(", text) and "k618_dma_buf_get_each" not in text:
		text = re.sub(r"\bdma_buf_get_each\s*\(", "k618_dma_buf_get_each(", text)
		first = text.index("k618_dma_buf_get_each(")
		at, depth = 0, 0
		for x in re.finditer(r"^[ \t]*#[ \t]*(if|ifdef|ifndef|endif|include)\b.*$", text, re.M):
			if x.start() >= first:
				break
			if x.group(1) in ("if", "ifdef", "ifndef"):
				depth += 1
			elif x.group(1) == "endif":
				depth = max(depth - 1, 0)
			elif depth == 0:
				at = x.end()
		text = (text[:at] + "\n/* 6.16: dma_buf_get_each() is gone (vendor_fix618.py) */\n"
			"static int k618_dma_buf_get_each(int (*cb)(const struct dma_buf *, void *), void *priv)\n{\n"
			"\tstruct dma_buf *b;\n\tint ret = 0;\n\n"
			"\tfor (b = dma_buf_iter_begin(); b; b = dma_buf_iter_next(b)) {\n"
			"\t\tret = cb(b, priv);\n\t\tif (ret) {\n\t\t\tdma_buf_put(b);\n\t\t\tbreak;\n\t\t}\n\t}\n"
			"\treturn ret;\n}\n" + text[at:])
		if "MODULE_IMPORT_NS" not in text or "DMA_BUF" not in text:
			text += '\nMODULE_IMPORT_NS("DMA_BUF");\n'
		note(path, "dma_buf_get_each")
	# v4l2_fh_add()/v4l2_fh_del() take the file (6.18) only to set or clear its private_data: drivers
	# that keep their own private_data (video's msm_vidc) pass a scratch one, as before
	if re.search(r"\bv4l2_fh_(?:add|del)\(\s*[^,()]+\)", text) and "k618_v4l2_fh_add" not in text:
		text = re.sub(r"\bv4l2_fh_(add|del)\(\s*([^,()]+)\)", r"k618_v4l2_fh_\1(\2)", text)
		marker = re.search(r"k618_v4l2_fh_(?:add|del)\(", text).group(0)
		text = insert_top_level(text, marker,
			"/* 6.18: v4l2_fh_add/_del take a file to set its private_data (vendor_fix618.py) */\n"
			"static inline void k618_v4l2_fh_add(struct v4l2_fh *fh)\n{\n"
			"\tstruct file f = {};\n\n\tv4l2_fh_add(fh, &f);\n}\n\n"
			"static inline void k618_v4l2_fh_del(struct v4l2_fh *fh)\n{\n"
			"\tstruct file f = {};\n\n\tv4l2_fh_del(fh, &f);\n}\n")
		note(path, "v4l2_fh_add/del")
	# vb2_queue.num_buffers is private since 6.8: vb2_get_num_buffers()
	text2 = re.sub(r"([\w.\[\]>-]*\bvb2q)->num_buffers\b", r"vb2_get_num_buffers(\1)", text) if "num_buffers" in text else text
	if text2 != text:
		note(path, "vb2 num_buffers")
		text = text2
	# gpio_free_array() is gone (6.18): each one freed, as the OnePlus 15's camera does
	text2 = re.sub(r"\bgpio_free_array\(\s*([^,()]+?)\s*,\s*([^;()]+?)\s*\);",
		r"{ unsigned int k618_i; for (k618_i = 0; k618_i < (\2); k618_i++) gpio_free((\1)[k618_i].gpio); }",
		text)
	if text2 != text:
		note(path, "gpio_free_array")
		text = text2
	# the sched_stat_runtime tracepoint has no vruntime since 6.8: its handlers lose that parameter
	# (as the OnePlus 15's game_opt has them)
	for name in set(re.findall(r"\bregister_trace_sched_stat_runtime\(\s*(\w+)", text)):
		text2 = re.sub(r"(\b%s\s*\(\s*void\s*\*\s*\w+\s*,\s*struct\s+task_struct\s*\*\s*\w+\s*,\s*u64\s+\w+)"
			r"\s*,\s*u64\s+\w+\s*\)" % re.escape(name), r"\1)", text)
		if text2 != text:
			note(path, "sched_stat_runtime")
			text = text2
	# plist_node_init() without <linux/plist.h>, which 6.6's headers pulled in (OnePlus 13's
	# sched_assist sa_common.h)
	text, did = include_if(text, r"\bplist_(?:node_init|head_init|add|del)\s*\(", "linux/plist.h")
	if did:
		note(path, "include linux/plist.h")
	# a driver's .remove that is __exit: modpost rejects the reference from the driver structure
	# (a section mismatch is an error in 6.18: fpga_monitor); an ordinary function, as remove is
	for name in set(re.findall(r"\.remove\s*=\s*__exit_p\(\s*(\w+)\s*\)", text)):
		text2 = re.sub(r"\.remove\s*=\s*__exit_p\(\s*%s\s*\)" % name, ".remove = %s" % name, text)
		text2 = re.sub(r"(\b(?:static\s+)?(?:int|void)\s+)__exit\s+(%s\s*\()" % name, r"\1\2", text2)
		if text2 != text:
			note(path, "__exit remove")
			text = text2
	# device_find_child()'s match callback takes const data (device_match_t, 6.13+): the charger's
	# dev_is_pm8550b and the like
	for name in set(re.findall(r"\bdevice_find_child\(\s*[^,()]+,\s*[^,()]+,\s*(\w+)\s*\)", text)):
		text2 = re.sub(r"(\bint\s+%s\s*\(\s*struct\s+device\s*\*\s*\w+\s*,\s*)void\s*\*" % re.escape(name),
			r"\1const void *", text)
		if text2 != text:
			note(path, "device_find_child match")
			text = text2
	# page->index is gone (6.16, the folio's): hybridswap stores a sector in its bio pages' index
	text2 = re.sub(r"((?:\b\w+\s*(?:->|\.)\s*)*\bdest_pages\[\s*\w+\s*\])->index\b", r"page_folio(\1)->index", text) if "dest_pages" in text else text
	if text2 != text:
		note(path, "page index")
		text = text2
	# android_rvh_after_dequeue_task passes dequeue_task()'s result too (6.18 ACK): its handlers
	# (OnePlus' sched_tune) take it, unused
	for name in set(re.findall(r"\bregister_trace_android_rvh_after_dequeue_task\(\s*(\w+)", text)):
		text2 = re.sub(r"(\b%s\s*\(\s*void\s*\*\s*\w+\s*,\s*struct\s+rq\s*\*\s*\w+\s*,\s*struct\s+task_struct"
			r"\s*\*\s*\w+\s*,\s*int\s+\w+)\s*\)" % re.escape(name), r"\1, bool *k618_dequeue_result)", text)
		if text2 != text:
			note(path, "after_dequeue_task")
			text = text2
	# hrtimer_clock_base.get_time is gone (6.18): the timer's clock through hrtimer_cb_get_time()
	text2 = text
	if "->get_time()" in text:
		text2 = re.sub(r"(&?)\b([\w.>-]+?)\.base->get_time\(\)", lambda m: "hrtimer_cb_get_time(&%s)" % m.group(2) if not m.group(1) else m.group(0), text2)
		text2 = re.sub(r"\b([\w>-]+?)->base->get_time\(\)", r"hrtimer_cb_get_time(\1)", text2)
	if text2 != text:
		note(path, "hrtimer get_time")
		text = text2
	# eventfd_signal() takes no count since 6.8 (it was 1)
	text2 = text
	if "eventfd_signal" in text2:
		text2 = re.sub(r"\beventfd_signal\(\s*([^,()]+?)\s*,\s*1\s*\)", r"eventfd_signal(\1)", text2)
		# ... and returns nothing: an assignment of its result gets what it returned, 1
		text2 = re.sub(r"\b(\w+)\s*=\s*eventfd_signal\(([^;]+?)\)\s*;", r"eventfd_signal(\2);\n\t\1 = 1;\t/* op13: void since 6.8 */", text2)
	# page_memcg() is gone: the page's folio's
	if "page_memcg" in text2:
		text2 = re.sub(r"\bpage_memcg\(\s*([\w>.-]+)\s*\)", r"folio_memcg(page_folio(\1))", text2)
	# struct memory_notify has no status_change_nid (6.17+): the node of the range's first page
	if "status_change_nid" in text2:
		text2 = re.sub(r"\b(\w+)->status_change_nid\b", r"pfn_to_nid(\1->start_pfn)", text2)
	if text2 != text:
		note(path, "eventfd/page_memcg/memory_notify")
		text = text2
	# page_mapcount() is gone (6.15): a page's folio's mapcount
	text2 = re.sub(r"\bpage_mapcount\(\s*(\w+)\s*\)", r"folio_mapcount(page_folio(\1))", text)
	if text2 != text:
		note(path, "page_mapcount")
		text = text2
	# uprobe_consumer handlers take the session cookie (__u64 *data) since 6.12
	text2 = re.sub(r"(\(\s*struct\s+uprobe_consumer\s*\*\s*\w+\s*,\s*(?:unsigned\s+long\s+\w+\s*,\s*)?"
		r"struct\s+pt_regs\s*\*\s*\w+)\s*\)(\s*\{)", r"\1, __u64 *data)\2", text)
	if text2 != text:
		note(path, "uprobe handlers")
		text = text2
	# kernel/irq/internals.h has irq_is_nmi() itself (6.x): a file's own copy gets its own name; and
	# desc->kstat_irqs is a per-CPU struct irqstat (its count in .cnt) since 6.10
	if re.search(r"^static\s+(?:inline\s+)?bool\s+irq_is_nmi\s*\(", text, re.M) and "internals.h" in text:
		text = re.sub(r"\birq_is_nmi\b", "k618_irq_is_nmi", text)
		note(path, "irq_is_nmi")
	text2 = re.sub(r"\*\s*per_cpu_ptr\(\s*([\w>.-]+?->kstat_irqs)\s*,\s*(\w+)\s*\)", r"per_cpu_ptr(\1, \2)->cnt", text)
	if text2 != text:
		note(path, "kstat_irqs")
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
			# after an include no #if encloses (fingerprint's fp_platform.c ends its includes in an
			# #if/#else: the helper went into the branch the build does not take)
			text = insert_top_level(text, "k618_devm_gpio_request(", DEVM_GPIO)
			note(path, "devm_gpio_request")
		# struct thermal_zone_device is opaque outside drivers/thermal (6.x): its definition
		if re.search(r"\bstruct\s+thermal_zone_device\b", text) and \
				re.search(r"\b\w*tz\w*->(type|temperature|last_temperature|devdata|ops|tzp|mode|id|device)\b", text) and \
				"thermal_core.h" not in text:
			text, did = include_if(text, r".", "drivers/thermal/thermal_core.h")
			if did:
				note(path, "thermal_core.h")
		# v4l2_ioctl_ops lost vidioc_g_ctrl/vidioc_s_ctrl (6.x: the control framework handles them)
		text2 = re.sub(r"^[ \t]*\.vidioc_(?:[gs]_ctrl|queryctrl)\s*=\s*\w+\s*,[ \t]*\n", "", text, flags=re.M)
		if text2 != text:
			note(path, "v4l2 g/s_ctrl")
			text = text2
		text = fix_platform_remove(text, path)
		# a function pointer to the snd_soc_unregister_component macro
		if re.search(r"\bsnd_soc_unregister_component\b(?!\s*\()", text):
			text = re.sub(r"\bsnd_soc_unregister_component\b(?!\s*\()", "k618_snd_soc_unregister_component", text)
			# after the last #include before its first use that no #if encloses (some files include
			# more further down; aw882xx's last one sits in a version #if that is false)
			first = text.index("k618_snd_soc_unregister_component")
			at, depth = 0, 0
			for x in re.finditer(r"^[ \t]*#[ \t]*(if|ifdef|ifndef|endif|include)\b.*$", text, re.M):
				if x.start() >= first:
					break
				d = x.group(1)
				if d in ("if", "ifdef", "ifndef"):
					depth += 1
				elif d == "endif":
					depth = max(depth - 1, 0)
				elif depth == 0:
					at = x.end()
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
		if os.path.isfile(top):
			fix(top)
			continue
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
