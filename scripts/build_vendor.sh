#!/bin/bash
# build_vendor.sh: every OnePlus driver the stock phone loads, from OnePlus' own sources as its Bazel
# build defines them -- not a hand-made list. Two passes:
#
#   pass 1  the OnePlus 13's own 6.6 tree (src/mods8750): OnePlus' modules, Qualcomm's techpacks as
#           that tree has them, Qualcomm's touch-drivers techpack, the NFC chips' drivers, and the
#           driver directories of the OnePlus 13's own vendor kernel (src/msm8750, scripts/fetch.sh)
#   pass 2  what pass 1 could not build, again from OnePlus' 6.12 tree for the OnePlus 15
#           (src/mods8850): the same ColorOS 16 drivers, already ported past most of the kernel
#           changes 6.6 -> 6.12 (the scheduler's vendor hooks, block layer, dma-fence, ...)
#
# Each pass:
#  1. copies the sources into out/vendor/<pass>/tree;
#  2. scripts/bzl_eval.py runs the BUILD.bazel/.bzl files there (Starlark, run as Python with Bazel's
#     built-ins stubbed) and records every module: sources, include directories, defines, copts,
#     defconfig, the modules it links against; then the copy goes through the 6.12 -> 6.18 sweeps
#     (k618_fix618.py, tp_fix.py) and this port's own (oplus_fix.py, vendor_fix618.py);
#  3. scripts/vendor_kbuild.py writes a Kbuild.<module> per module into its package and the build
#     order: the wanted modules and what they need, less what is built already;
#  4. builds each: make -k M=<package> MO=<obj>/<module> OPMOD=<module> (-k: every file that does not
#     compile is in the log, not only the first), against the GKI build, the SoC
#     configuration (forced in, env.sh) and the Module.symvers of everything built before it;
#  5. builds the wanted modules that have only plain Makefiles (scripts/vendor_mkplan.py): each
#     directory once, with the options that switch them on.
#
# A module that fails is left out with the ones that need it; the boot image is made without it.
# Modules in out/vendormods (their names in out/vendormods.list, for mklists.py: they load last,
# probing in the background), a log each in out/vendor-log, the summary in out/vendor-log/summary.txt
# and the modules no pass built in out/vendor-log/failed.txt.
set -e
. "$(dirname "$0")/env.sh"
W=$ROOT/out/vendor
OUTM=$ROOT/out/vendormods
LOG=$ROOT/out/vendor-log
ST=$ROOT/device/op13/stock
[ -f "$S/Module.symvers" ] || { echo "build_vendor: build the SoC modules first"; exit 1; }
rm -rf "$W" "$OUTM" "$LOG" && mkdir -p "$W" "$OUTM" "$LOG"
CONF=$W/soc-autoconf.h
soc_autoconf "$CONF"
: > "$LOG/summary.txt"

# what the other builds make already (SoC, techpacks, the kernel's own, OnePlus' boot and touch
# modules): not made again
HAVE=$W/have
mkdir -p "$HAVE"
for f in $(find "$S" "$ROOT/out/gki-staging" "$ROOT/out/tpmods" "$ROOT/out/oplusmods" "$ROOT/out/extramods" -name '*.ko' 2>/dev/null); do
	: > "$HAVE/$(basename "$f")"
done
SYMS="$S/Module.symvers $(ls "$ROOT"/out/tp-log/*.symvers "$ROOT"/out/oplus/*/Module.symvers "$ROOT"/out/extra/*/Module.symvers 2>/dev/null | tr '\n' ' ')"
# the OnePlus 13 vendor kernel's device-tree bindings (the other chipsets' clocks), after every other
# header: only those, its linux/ headers are 6.6's
mkdir -p "$W/inc8750"
[ -d "$ROOT/src/msm8750/include/dt-bindings" ] && ln -sfn "$ROOT/src/msm8750/include/dt-bindings" "$W/inc8750/dt-bindings"
ok=0; bad=0

# prepare <pass dir> <modules source> [kernel version it is written for, 6.6]: the build copy of one source tree, its module definitions
# (<pass dir>/modules.json), its fixes and the include directory its OnePlus headers are reached by
prepare() {
	local P=$1 SRC=$2 KV=${3:-6.6} T=$1/tree r d h p
	mkdir -p "$T/vendor/qcom/opensource" "$P/inc/soc/oplus" "$P/inc/linux"
	QREPOS=$(cd "$SRC/vendor/qcom/opensource" && ls -d -- */ | tr -d / | grep -v -- '-devicetree$' | tr '\n' ' ')
	cp -r "$SRC/vendor/oplus" "$T/vendor/oplus"
	# directory links inside the tree become copies, as Bazel's sandbox has them: through a link,
	# "<dir>/../x" resolves next to the link's target (charger/bazel/v2 -> ../v2: v2's
	# <../voocphy/...> found the old v1 voocphy, duplicate definitions in oplus_chg_v2)
	find "$T/vendor/oplus" -type l -xtype d | while read -r l; do
		tgt=$(readlink -f "$l")
		case $tgt in "$T"/*) rm "$l" && cp -r "$tgt" "$l" ;; esac
	done
	for d in st nxp; do [ -d "$SRC/vendor/$d" ] && cp -r "$SRC/vendor/$d" "$T/vendor/"; done
	for r in $QREPOS; do cp -r "$SRC/vendor/qcom/opensource/$r" "$T/vendor/qcom/opensource/"; done
	# the definitions, read before the copy's fixes; OnePlus' macro file from that tree's kernel_platform
	STOCK_CONFIG=$ROOT/out/soc-kconfig/.config:$ROOT/device/op13/oplus-features.config \
	BZL_KVER=$KV BZL_MACROS=$SRC/kernel_platform/oplus/bazel python3 -I "$ROOT/scripts/bzl_eval.py" "$T" "$P/modules.json" \
		vendor/oplus $(for r in $QREPOS; do echo "vendor/qcom/opensource/$r"; done)
	# this port's fixes first as well: some patterns the reference's sweep would take wrongly
	# (an hrtimer callback from a table)
	python3 -I "$ROOT/scripts/vendor_fix618.py" "$T/vendor" > /dev/null
	for d in "$T"/vendor/* "$T"/msm8750; do
		[ -d "$d" ] || continue
		python3 -I "$REF/k618_fix618.py" "$d" | grep -v 'k618_fix618: 0 files changed' || true
		python3 -I "$ROOT/scripts/oplus_fix.py" "$d"
	done
	# the reference's 6.12 -> 6.18 techpack fixes (not its Xiaomi or 5.15 ones), as build_tp.sh, and
	# the API changes these sources meet (scripts/vendor_fix618.py)
	python3 -I "$ROOT/scripts/tp_fix.py" "$REF" "$T/vendor/qcom/opensource"
	python3 -I "$ROOT/scripts/vendor_fix618.py" "$T/vendor" "$T/msm8750"
	# trace headers name their own directory relative to the kernel's include/trace, in their tree's
	# layout (../../../vendor/..., ../../kernel/oplus_cpu/...): each relative one becomes the absolute
	# directory of the header that defines it -- where the trace file it names is there: OnePlus'
	# camera cam_trace_custom.h says "." for Qualcomm's cam_trace.h in another directory, found
	# through the include path as before (camera: "cam_module_utils/./cam_trace.h not found")
	grep -rlZ --include='*.h' --include='*.c' -E 'define[[:space:]]+[A-Z0-9_]*TRACE_INCLUDE_PATH[[:space:]]+\.' "$T" | while IFS= read -r -d '' h; do
		f=$(sed -n -E 's#^[[:space:]]*\#[[:space:]]*define[[:space:]]+TRACE_INCLUDE_FILE[[:space:]]+([^[:space:]]+).*#\1#p' "$h" | head -1)
		[ -n "$f" ] || f=$(basename "$h" .h)
		[ -e "$(dirname "$h")/$f.h" ] || continue
		sed -i -E "s#(define[[:space:]]+[A-Z0-9_]*TRACE_INCLUDE_PATH[[:space:]]+)\.[^[:space:]]*#\1$(dirname "$h")#" "$h"
	done
	# the charger's generated IC tables (its Bazel rule oplus_chg_ic_cfg runs this script), where its
	# header target (oplus_chg_v2_ic_cfg_headers) has them
	local CHG=$T/vendor/oplus/kernel/charger/bazel
	if [ -f "$CHG/v2/scripts/ic_cfg_parse.py" ]; then
		for d in oplus_chg_ic_cfg oplus_chg_v2_ic_cfg; do
			mkdir -p "$CHG/$d"
			python3 "$CHG/v2/scripts/ic_cfg_parse.py" -hd "$CHG/$d/oplus_chg_ic_cfg.h" -s "$CHG/$d/oplus_chg_ic_cfg_str.h" \
				-df "$CHG/$d/oplus_chg_ic_auto_debug.h" "$CHG/v2/config/oplus_chg_ic.json" > "$P/charger-ic-cfg.log" 2>&1 \
				|| echo "build_vendor: the charger's IC tables were not made ($P/charger-ic-cfg.log)"
		done
	fi
	# the headers OnePlus' kernel tree has under include/soc/oplus and include/linux, by those paths;
	# boot's as a whole set in each place (oplus_project.h includes oplus_project_data_ocdt.h next to it)
	local K=$T/vendor/oplus/kernel
	lnk() { [ -e "$2" ] && { mkdir -p "$P/inc/$(dirname "$1")"; ln -sfn "$2" "$P/inc/$1"; }; return 0; }
	for h in "$K"/boot/include/*.h; do
		for p in soc/oplus soc/oplus/boot soc/oplus/system; do lnk "$p/$(basename "$h")" "$h"; done
	done
	for h in olc.h kernel_fb.h; do
		for p in soc/oplus/dft soc/oplus/system; do lnk "$p/$h" "$K/dft/include/$h"; done
	done
	lnk soc/oplus/device_info.h "$K/device_info/device_info/bazel/device_info.h"
	lnk soc/oplus/touchpanel_event_notify.h "$K/touchpanel/touchpanel_notify/bazel/touchpanel_event_notify.h"
	lnk soc/oplus/fpga_notify.h "$K/device_info/oplus_fpga/fpga_notify/fpga_notify.h"
	lnk soc/oplus/magcvr_notify.h "$K/device_info/magnetic_cover/magtransfer/magcvr_notify.h"
	lnk soc/oplus/dfr/oplus_bsp_dfr_ubt.h "$K/dfr/include/oplus_bsp_dfr_ubt.h"
	lnk soc/oplus/dfr/theia_send_event.h "$K/dfr/include/theia_send_event.h"
	lnk soc/oplus/system/oplus_mm_kevent_fb.h "$K/multimedia/feedback/common/oplus_mm_kevent_fb.h"
	lnk soc/oplus/system/oplus_trace_sensor.h "$T/vendor/oplus/sensor/kernel/oplus_trace_sensor/oplus_trace_sensor.h"
	lnk linux/oplus_kevent.h "$K/secureguard/gki2.0/rootguard_new/oplus_kevent.h"
	lnk linux/pogo_common.h "$K/device_info/pogo_keyboard/pogo_common.h"
	lnk soc/oplus/oplus_trackpoint_report.h "$T/vendor/qcom/opensource/display-drivers/oplus/common/trackpoint/oplus_trackpoint_report.h"
	lnk st_uapi.h "$T/vendor/st/opensource/driver/include/uapi/linux/nfc/st_uapi.h"
	# the UFS trace events moved into the UFS core (6.x): by their old path
	lnk trace/events/ufs.h "$C/drivers/ufs/core/ufs_trace.h"
	lnk ufs_trace.h "$C/drivers/ufs/core/ufs_trace.h"
	lnk ufs_trace_types.h "$C/drivers/ufs/core/ufs_trace_types.h"
	lnk pinctrl-msm.h "$S/drivers/pinctrl/qcom/pinctrl-msm.h"
	lnk trace/events/ufs_trace_types.h "$C/drivers/ufs/core/ufs_trace_types.h"
	# OnePlus' cpu tree as its kernel has it (kernel/oplus_cpu): includes of "../kernel/oplus_cpu/..."
	# resolve from the include directory above
	mkdir -p "$P/kernel" && ln -sfn "$K/cpu" "$P/kernel/oplus_cpu"
	# and the rest of what the SoC repo links into OnePlus' tree, from this tree (env.sh)
	oplus_overlay "$P/inc" "$T/vendor/oplus"
}

# build <pass dir> <wanted lists> <search dirs for Makefile-only modules...>
build() {
	local P=$1 WANT=$2 T=$1/tree name pkg base needs n MO rc dir opts names tag vars defs o ko _l
	shift 2
	python3 -I "$ROOT/scripts/vendor_kbuild.py" "$P/modules.json" "$T" "$WANT" "$HAVE:$OUTM" "$P/plan.txt"
	# in dependency levels (a module after everything it links against), each level's modules side
	# by side, one per CPU: most of them need nothing of one another
	python3 -I - "$P/plan.txt" > "$P/levels.txt" <<'PY'
import sys
plan = [l.rstrip("\n").split("|") for l in open(sys.argv[1]) if l.strip()]
names = {p[0] for p in plan}
lvl = {}
for name, _pkg, _base, needs in plan:		# the plan is in dependency order
	lvl[name] = 1 + max([lvl.get(n, 0) for n in needs.split() if n in names] + [0])
for p in plan:
	print("%d|%s" % (lvl[p[0]], "|".join(p)))
PY
	: > "$P/failed"
	local level max
	max=$(cut -d'|' -f1 "$P/levels.txt" | sort -n | tail -1)
	for level in $(seq 1 "${max:-0}"); do
		while IFS='|' read -r _l name pkg base needs; do
			[ "$_l" = "$level" ] || continue
			for n in $needs; do
				if grep -qx "$n" "$P/failed"; then
					echo "build_vendor: $name: left out ($n failed)" | tee -a "$LOG/summary.txt"
					echo "$name" >> "$P/failed"; continue 2
				fi
			done
			while [ "$(jobs -rp | wc -l)" -ge "$J" ]; do wait -n || true; done
			(
				MO=$P/obj/$name
				mkdir -p "$MO"
				"${KMAKE[@]}" -k M="$T/$pkg" MO="$MO" OPMOD="$base" modules -j1 KBUILD_EXTRA_SYMBOLS="$SYMS" \
					NOSTDINC_FLAGS="-nostdinc -I$P/inc -I$S/include -I$S/include/uapi -idirafter $W/inc8750 -idirafter $C -idirafter $S" \
					KCFLAGS="-Wno-error -include $CONF" > "$LOG/$(basename "$P")-$name.log" 2>&1
				echo "$? $MO/$base.ko" > "$MO/.result"
			) < /dev/null &
		done < "$P/levels.txt"
		wait
		# the level's results, in plan order
		while IFS='|' read -r _l name pkg base needs; do
			[ "$_l" = "$level" ] || continue
			MO=$P/obj/$name
			[ -f "$MO/.result" ] || continue
			read -r rc ko < "$MO/.result"
			if [ "$rc" -ne 0 ] || [ ! -f "$ko" ]; then
				echo "build_vendor: $name: FAILED ($(basename "$P"), make exit $rc)" | tee -a "$LOG/summary.txt"
				grep -E ': (fatal )?error: |^ERROR: modpost' "$LOG/$(basename "$P")-$name.log" | sed -E "s|$T/||" | head -6 \
					| tee -a "$LOG/summary.txt" || true
				echo "$name" >> "$P/failed"
				continue
			fi
			echo "build_vendor: $name: built ($(basename "$P"))" | tee -a "$LOG/summary.txt"
			ok=$((ok + 1))
			SYMS="$SYMS $MO/Module.symvers"
			cp "$ko" "$OUTM/"
		done < "$P/levels.txt"
	done
	# the wanted modules made from plain Makefiles: each directory built once, with the options that
	# switch its wanted modules on set to m (and defined for the C code)
	python3 -I "$ROOT/scripts/vendor_mkplan.py" "$T" "$WANT" "$HAVE:$OUTM" "$P/mkplan.txt" "$@"
	while IFS='|' read -r dir opts names; do
		tag=$(basename "$P")-mk-$(echo "$dir" | tr '/' '_')
		MO=$P/obj/$tag
		mkdir -p "$MO"
		vars=; defs=
		for o in $opts; do vars="$vars $o=m"; defs="$defs -D${o}_MODULE=1"; done
		# the symbol versions of everything built so far, less those of the modules this make makes
		# itself (its Makefile may make again one built already: modpost refuses an export twice) --
		# only those: obj-m and obj-$(CONFIG_X) with X one of ours or on in the kernel's configuration.
		# The rest stay (pinctrl-tuna needs the SoC's pinctrl-msm, which sits in the same Makefile
		# behind an option that is off here).
		python3 -I - "$T/$dir" "$MO/extra.symvers" "$opts" "$O/include/config/auto.conf" $SYMS <<'PY'
import os, re, sys
d, out, opts, autoconf, files = sys.argv[1], sys.argv[2], set(sys.argv[3].split()), sys.argv[4], sys.argv[5:]
on = set(opts)
if os.path.isfile(autoconf):
	on |= {l.split("=")[0] for l in open(autoconf) if re.match(r"CONFIG_\w+=[ym]$", l.strip())}
mine = set()
for f in ("Makefile", "Kbuild"):
	p = os.path.join(d, f)
	if os.path.isfile(p):
		t = open(p, errors="ignore").read().replace("\\\n", " ")
		for m in re.finditer(r"^\s*obj-(m|\$\((CONFIG_\w+)\))\s*[:+]?=\s*(.+)$", t, re.M):
			if m.group(1) == "m" or m.group(2) in on:
				mine |= {o[:-2].replace("-", "_") for o in m.group(3).split() if o.endswith(".o")}
with open(out, "w") as w:
	for f in files:
		if not os.path.isfile(f):
			continue
		for line in open(f, errors="ignore"):
			cols = line.rstrip("\n").split("\t")
			if len(cols) > 2 and os.path.basename(cols[2]).replace("-", "_") in mine:
				continue
			w.write(line)
PY
		set +e
		# shellcheck disable=SC2086
		"${KMAKE[@]}" -k M="$T/$dir" MO="$MO" modules -j"$J" KBUILD_EXTRA_SYMBOLS="$MO/extra.symvers" $vars \
			NOSTDINC_FLAGS="-nostdinc -I$P/inc -I$S/include -I$S/include/uapi -idirafter $W/inc8750 -idirafter $C -idirafter $S" \
			KCFLAGS="-Wno-error -include $CONF $defs" > "$LOG/$tag.log" 2>&1
		rc=$?
		set -e
		# one file that does not build stops the whole directory (msm8750's clocks: tcsrcc-tuna took
		# eleven others with it): each module not made is tried again on its own, with only the
		# option that switches it on
		if [ $rc -ne 0 ] && [ "$(echo $names | wc -w)" -gt 1 ]; then
			for n in $names; do
				[ -n "$(find "$MO" -name "$n.ko" -o -name "$(echo "$n" | tr '_' '-').ko" | head -1)" ] && continue
				o1=$(python3 -I - "$T/$dir" "$n" <<'PY2'
import os, re, sys
d, n = sys.argv[1], sys.argv[2]
for f in ("Makefile", "Kbuild"):
	p = os.path.join(d, f)
	if os.path.isfile(p):
		t = open(p, errors="ignore").read().replace("\\\n", " ")
		for m in re.finditer(r"^\s*obj-\$\((CONFIG_\w+)\)\s*[:+]?=\s*(.+)$", t, re.M):
			if any(o[:-2].replace("-", "_") == n for o in m.group(2).split()):
				print(m.group(1)); sys.exit(0)
PY2
)
				[ -n "$o1" ] || continue
				MO1=$MO-$n; mkdir -p "$MO1"; cp "$MO/extra.symvers" "$MO1/"
				set +e
				"${KMAKE[@]}" -k M="$T/$dir" MO="$MO1" modules -j"$J" KBUILD_EXTRA_SYMBOLS="$MO1/extra.symvers" "$o1=m" \
					NOSTDINC_FLAGS="-nostdinc -I$P/inc -I$S/include -I$S/include/uapi -idirafter $W/inc8750 -idirafter $C -idirafter $S" \
					KCFLAGS="-Wno-error -include $CONF -D${o1}_MODULE=1" > "$LOG/$tag-$n.log" 2>&1
				set -e
				ko=$(find "$MO1" -name "$n.ko" -o -name "$(echo "$n" | tr '_' '-').ko" | head -1)
				[ -n "$ko" ] && cp "$ko" "$MO/" && [ -f "$MO1/Module.symvers" ] && SYMS="$SYMS $MO1/Module.symvers"
			done
		fi
		for n in $names; do
			ko=$(find "$MO" -name "$n.ko" -o -name "$(echo "$n" | tr '_' '-').ko" | head -1)
			if [ -n "$ko" ]; then
				echo "build_vendor: $n: built ($dir)" | tee -a "$LOG/summary.txt"
				ok=$((ok + 1)); cp "$ko" "$OUTM/"
			else
				echo "build_vendor: $n: FAILED ($dir, make exit $rc)" | tee -a "$LOG/summary.txt"
			fi
		done
		[ $rc -eq 0 ] || grep -E ': (fatal )?error: |^ERROR: modpost' "$LOG/$tag.log" | sed -E "s|$T/||" | head -6 \
			| tee -a "$LOG/summary.txt" || true
		[ -f "$MO/Module.symvers" ] && SYMS="$SYMS $MO/Module.symvers"
	done < "$P/mkplan.txt"
	return 0
}

# the wanted modules no pass has built yet (stock lists, less what exists): one name a line
still_wanted() {
	python3 -I - "$1" "$HAVE" "$OUTM" "$ST/first_stage.load" "$ST/vendor_dlkm.load" "$ST/system_dlkm.load" \
		"$ST/../no-source.txt" <<'PY'
import os, sys
out, have, outm, *lists = sys.argv[1:]
nosrc = lists.pop()
c = lambda n: os.path.basename(n.strip()).removesuffix(".ko").replace("-", "_")
got = {c(f) for d in (have, outm) for f in os.listdir(d)}
skip = {c(l) for l in open(nosrc) if l.strip() and not l.startswith("#")} if os.path.isfile(nosrc) else set()
want = []
for l in lists:
	for line in open(l):
		n = c(line)
		if n and n not in got and n not in skip and n not in want:
			want.append(n)
open(out, "w").write("".join(n + ".ko\n" for n in want))
print(len(want))
PY
}

# pass 1: the OnePlus 13's own 6.6 tree, with Qualcomm's touch-drivers, the NFC drivers of the
# SM8850 release and the OnePlus 13 vendor kernel's driver directories
P1=$W/op13
prepare "$P1" "$ROOT/src/mods8750"
if [ -d "$ROOT/src/touch-drivers" ]; then
	cp -r "$ROOT/src/touch-drivers" "$P1/tree/vendor/qcom/opensource/touch-drivers" && rm -rf "$P1/tree/vendor/qcom/opensource/touch-drivers/.git"
	BZL_MACROS=$ROOT/src/mods8750/kernel_platform/oplus/bazel python3 -I "$ROOT/scripts/bzl_eval.py" "$P1/tree" \
		"$P1/touch.json" vendor/qcom/opensource/touch-drivers
	python3 -I - "$P1/modules.json" "$P1/touch.json" <<'PY'
import json, sys
a, b = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
a["modules"] += b["modules"]; a["headers"].update(b["headers"])
json.dump(a, open(sys.argv[1], "w"))
PY
	python3 -I "$REF/k618_fix618.py" "$P1/tree/vendor/qcom/opensource/touch-drivers" | grep -v 'k618_fix618: 0 files changed' || true
	python3 -I "$ROOT/scripts/vendor_fix618.py" "$P1/tree/vendor/qcom/opensource/touch-drivers"
fi
mkdir -p "$P1/tree/vendor/oplus8850/kernel" && cp -r "$ROOT/src/mods8850/vendor/oplus/kernel/nfc" "$P1/tree/vendor/oplus8850/kernel/"
python3 -I "$REF/k618_fix618.py" "$P1/tree/vendor/oplus8850" | grep -v 'k618_fix618: 0 files changed' || true
python3 -I "$ROOT/scripts/vendor_fix618.py" "$P1/tree/vendor/oplus8850"
if [ -d "$ROOT/src/msm8750/drivers" ]; then
	mkdir -p "$P1/tree/msm8750" && cp -r "$ROOT/src/msm8750/drivers" "$P1/tree/msm8750/"
	python3 -I "$REF/k618_fix618.py" "$P1/tree/msm8750" | grep -v 'k618_fix618: 0 files changed' || true
	python3 -I "$ROOT/scripts/vendor_fix618.py" "$P1/tree/msm8750"
fi
build "$P1" "$ST/first_stage.load:$ST/vendor_dlkm.load:$ST/system_dlkm.load" \
	vendor/oplus vendor/st vendor/nxp vendor/oplus8850 vendor/qcom/opensource msm8750

# pass 2: what is still missing, from OnePlus' 6.12 tree for the OnePlus 15
n=$(still_wanted "$W/wanted2.txt")
echo "build_vendor: pass 1 built $ok; $n still wanted, from the OnePlus 15's 6.12 tree" | tee -a "$LOG/summary.txt"
if [ "$n" -gt 0 ]; then
	P2=$W/op15
	prepare "$P2" "$ROOT/src/mods8850" 6.12
	build "$P2" "$W/wanted2.txt" vendor/oplus vendor/qcom/opensource
fi

# late SoC modules: the SoC build drops what does not link, and some SoC modules link against
# OnePlus' (on the OnePlus 13 the charger, oplus_chg_v2, exports qti_battery_charger_get_prop and
# register_hboost_event_notifier, which the flash LEDs and qcom-hv-haptics use) -- built before
# OnePlus' existed. Each dropped one that is still wanted is tried once more, alone, against
# everything built by now (its objects in out/soc-late, the SoC tree's own Kbuild put back after).
still_wanted "$W/wanted-late.txt" > /dev/null
if [ -s "$ROOT/out/soc-dropped.txt" ] && [ -f "$S/Kbuild" ]; then
	cp "$S/Kbuild" "$W/soc-Kbuild.saved"
	# the SoC tree is built in place: 6.18 refuses a separate-output build (MO=) of a tree with a
	# modules.order ("The external module source tree is not clean": run 45427714881 built none of
	# these), so it is set aside meanwhile
	[ -f "$S/modules.order" ] && mv "$S/modules.order" "$W/soc-modules.order.saved"
	LSYMS="$O/Module.symvers $S/Module.symvers $(find "$W" -name Module.symvers 2>/dev/null | tr '\n' ' ') \
$(find "$ROOT/out/oplus" "$ROOT/out/extra" -name Module.symvers 2>/dev/null | tr '\n' ' ') \
$(ls "$ROOT"/out/tp-log/*.symvers 2>/dev/null | tr '\n' ' ')"
	while read -r m; do
		k=$(basename "$m" | tr '-' '_')
		grep -qx "$k.ko" "$W/wanted-late.txt" || continue
		MO=$ROOT/out/soc-late/$k
		rm -rf "$MO" && mkdir -p "$MO"
		python3 -I "$REF/k618_soc_kbuild.py" kbuild "$S" "$ROOT/out/soc-kconfig/.config" "$O/.config" "$m" \
			> "$LOG/soc-late-$k.log" 2>&1 || continue
		set +e
		"${KMAKE[@]}" M="$S" MO="$MO" -j"$J" modules KBUILD_EXTRA_SYMBOLS="$LSYMS" >> "$LOG/soc-late-$k.log" 2>&1
		set -e
		ko=$(find "$MO" -name "$(basename "$m").ko" | head -1)
		if [ -n "$ko" ]; then
			echo "build_vendor: $k: built (SoC, after OnePlus' modules)" | tee -a "$LOG/summary.txt"
			cp "$ko" "$OUTM/"; ok=$((ok + 1))
		else
			echo "build_vendor: $k: FAILED (SoC, late)" | tee -a "$LOG/summary.txt"
			grep -E ': (fatal )?error: |^ERROR: modpost' "$LOG/soc-late-$k.log" | head -4 | tee -a "$LOG/summary.txt" || true
		fi
	done < "$ROOT/out/soc-dropped.txt"
	cp "$W/soc-Kbuild.saved" "$S/Kbuild"
	[ -f "$W/soc-modules.order.saved" ] && mv "$W/soc-modules.order.saved" "$S/modules.order"
fi

# OnePlus/Qualcomm modules that failed only for symbols a late SoC module exports (swr_haptics:
# qcom-hv-haptics' register_hboost_event_notifier), built once more now that those are there
LATE=$(find "$ROOT/out/soc-late" -name Module.symvers 2>/dev/null | tr '\n' ' ')
if [ -n "$LATE" ]; then
	SYMS="$SYMS $LATE"
	for P in "$P1" ${P2:+"$P2"}; do
		[ -f "$P/failed" ] || continue
		while read -r name; do
			L=$LOG/$(basename "$P")-$name.log
			[ -f "$L" ] && grep -q '^ERROR: modpost: .* undefined!' "$L" || continue
			grep -qE ': (fatal )?error: ' "$L" && continue
			still=0
			for sym in $(sed -n -E 's/^ERROR: modpost: "([^"]+)" .* undefined!/\1/p' "$L"); do
				cat $LATE | awk -v s="$sym" '$2 == s { f = 1 } END { exit !f }' || still=1
			done
			[ "$still" -eq 0 ] || continue
			pkg=; base=
			IFS='|' read -r _l _n pkg base _needs < <(awk -F'|' -v n="$name" '$2 == n' "$P/levels.txt") || true
			[ -n "$pkg" ] || continue
			MO=$P/obj/$name
			set +e
			"${KMAKE[@]}" -k M="$P/tree/$pkg" MO="$MO" OPMOD="$base" modules -j"$J" KBUILD_EXTRA_SYMBOLS="$SYMS" \
				NOSTDINC_FLAGS="-nostdinc -I$P/inc -I$S/include -I$S/include/uapi -idirafter $W/inc8750 -idirafter $C -idirafter $S" \
				KCFLAGS="-Wno-error -include $CONF" > "$L.late" 2>&1
			set -e
			if [ -f "$MO/$base.ko" ]; then
				echo "build_vendor: $name: built ($(basename "$P"), after the late SoC modules)" | tee -a "$LOG/summary.txt"
				cp "$MO/$base.ko" "$OUTM/"; ok=$((ok + 1))
			else
				echo "build_vendor: $name: FAILED again after the late SoC modules ($L.late)" | tee -a "$LOG/summary.txt"
			fi
		done < "$P/failed"
	done
fi

n=$(still_wanted "$LOG/failed.txt")
ls "$OUTM" | sed 's/\.ko$//' > "$ROOT/out/vendormods.list"
echo "build_vendor: built $ok; not built: $n (failed.txt)" | tee -a "$LOG/summary.txt"
[ "$n" -eq 0 ]
