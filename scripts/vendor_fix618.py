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


def fix(path):
	try:
		text = open(path, encoding="utf-8", errors="surrogateescape").read()
	except OSError:
		return
	orig = text
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
