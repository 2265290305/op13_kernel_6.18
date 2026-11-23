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


def fix_platform_remove(text, path):
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
	("no_llseek", re.compile(r"(\.llseek\s*=\s*)no_llseek\b"), r"\1NULL"),
	# the inode times are behind accessors (6.7): a helper updating one in place gets a copy written back
	("inode times", re.compile(r"\b(\w+)\(\s*&\s*(file_inode\(\s*\w+\s*\)|\w+)->i_(m|a)time\s*\)\s*;"),
		r"{ struct timespec64 __k618_t = inode_get_\3time(\2); \1(&__k618_t); inode_set_\3time_to_ts(\2, __k618_t); }"),
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
	# kernel/sched/sched.h has css_tg() since 6.7: a file that includes it drops its own copy
	if "kernel/sched/sched.h" in text:
		text2 = re.sub(r"static\s+inline\s+struct\s+task_group\s*\*\s*css_tg\s*\(\s*struct\s+cgroup_subsys_state\s*\*\s*\w+\s*\)\s*\{[^{}]*\}\n",
			"/* css_tg(): kernel/sched/sched.h has it in 6.18 (vendor_fix618.py) */\n", text)
		if text2 != text:
			note(path, "css_tg")
			text = text2
	if path.endswith(".c"):
		text = fix_platform_remove(text, path)
		# a function pointer to the snd_soc_unregister_component macro
		if re.search(r"\bsnd_soc_unregister_component\b(?!\s*\()", text):
			text = re.sub(r"\bsnd_soc_unregister_component\b(?!\s*\()", "k618_snd_soc_unregister_component", text)
			m = list(re.finditer(r"^#include\s*[<\"].*$", text, re.M))
			at = m[-1].end() if m else 0
			text = (text[:at] + "\n/* 6.18: snd_soc_unregister_component() is a macro (vendor_fix618.py) */\n"
				"static void k618_snd_soc_unregister_component(struct device *dev)\n"
				"{\n\tsnd_soc_unregister_component_by_driver(dev, NULL);\n}\n" + text[at:])
			note(path, "snd_soc_unregister_component")
		for used, header in ((r"\bv(?:malloc|zalloc|free)\s*\(", "linux/vmalloc.h"),
				(r"\bstruct\s+platform_device_id\b", "linux/mod_devicetable.h"),
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
