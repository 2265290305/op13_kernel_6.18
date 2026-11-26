#!/bin/bash
# build_walt.sh: WALT -- Qualcomm's window-assisted load tracking scheduler and its "walt" cpufreq
# governor (sched-walt), with OnePlus' yield penalty (sched-penalty) -- the two modules the stock
# phone loads first in its first stage.
#
# sched-walt: the SM8850 SoC repo's WALT (6.12; it knows sun: walt_config.c's "SUN"), with OnePlus'
# options (its registry entry in kernel/sched/walt/modules.bzl). It calls into OnePlus' scheduler
# modules (sched_assist, frame_boost, task_overload, cpufreq_bouncing), built by build_vendor.sh, so
# it is built after them, out of the SoC tree; the SoC modules themselves stay built without
# CONFIG_SCHED_WALT (configs/op13_overrides.bzl), against walt.h's stubs, as before.
# sched-penalty: the OnePlus 13's own (its 6.6 vendor kernel's penalty.c), against WALT's headers.
#
# Modules in out/waltmods, their names in out/waltmods.list: build_bootimg.sh treats them as drivers
# new to the boot (boot.img holds them, boot-full.img loads them at the end of the batch). Logs in
# out/walt-log. A module that does not build is left out (the image is made without it).
set -e
. "$(dirname "$0")/env.sh"
W=$ROOT/out/walt
OUTM=$ROOT/out/waltmods
LOG=$ROOT/out/walt-log
[ -f "$S/Module.symvers" ] || { echo "build_walt: build the SoC modules first"; exit 1; }
rm -rf "$W" "$OUTM" "$LOG" && mkdir -p "$W/inc/linux" "$OUTM" "$LOG"
: > "$ROOT/out/waltmods.list"
cp -r "$S/kernel/sched/walt" "$W/walt"
python3 -I "$ROOT/scripts/vendor_fix618.py" "$W/walt"
python3 -I "$ROOT/scripts/walt_fix.py" "$W/walt"
# its trace header names its directory from the kernel's include/trace (../../kernel/sched/walt): here
sed -i -E "s#(define[[:space:]]+TRACE_INCLUDE_PATH[[:space:]]+)\.[^[:space:]]*#\1$W/walt#" "$W"/walt/*.h
CONF=$W/soc-autoconf.h
soc_autoconf "$CONF"
OMRG=$(find "$ROOT/out/vendor" -path '*cpu/oplus_omrg/oplus_omrg.h' 2>/dev/null | head -1)
[ -n "$OMRG" ] && ln -sfn "$OMRG" "$W/inc/linux/oplus_omrg.h"
SYMS="$S/Module.symvers $(find "$ROOT/out/vendor" "$ROOT/out/oplus" "$ROOT/out/extra" -name Module.symvers 2>/dev/null | tr '\n' ' ') $(ls "$ROOT"/out/tp-log/*.symvers 2>/dev/null | tr '\n' ' ')"
# OnePlus' options for WALT (modules.bzl's copts) and its headers by OnePlus' paths
COPTS="-DCONFIG_OPLUS_ADD_CORE_CTRL_MASK -DCONFIG_OPLUS_FEATURE_SCHED_ASSIST -DCONFIG_OPLUS_SCHED_HALT_MASK_PRT -DCONFIG_OPLUS_FEATURE_FRAME_BOOST -DCONFIG_OPLUS_FEATURE_SCHED_EXT -DCONFIG_OPLUS_FEATURE_GEAS"
INCS="-nostdinc -I$S/include -I$W/inc -I$ROOT/src/mods8850/vendor/oplus/kernel/cpu/sched -I$ROOT/src/mods8850/vendor/oplus/kernel/cpu -idirafter $C"
# kmake <dir> <log> <extra symbols>
kmake() {
	set +e
	"${KMAKE[@]}" M="$1" modules -j"$J" KBUILD_EXTRA_SYMBOLS="$3" NOSTDINC_FLAGS="$INCS" \
		KCFLAGS="-Wno-error -include $CONF" > "$2" 2>&1
	local rc=$?
	set -e
	return $rc
}

# sched-walt: its objects as its registry entry lists them
OBJS=$(python3 -I - "$S/kernel/sched/walt/modules.bzl" <<'PY'
import re, sys
t = open(sys.argv[1]).read()
m = re.search(r'name = "kernel/sched/walt/sched-walt",.*?srcs = \[(.*?)\]', t, re.S)
print(" ".join(s.split("/")[-1][:-2] + ".o" for s in re.findall(r'"([^"]+\.c)"', m.group(1))))
PY
)
{
	echo "obj-m += sched-walt.o"
	echo "sched-walt-y := $OBJS"
	echo "ccflags-y += -I\$(src) -DCONFIG_SCHED_WALT_MODULE=1 $COPTS"
} > "$W/walt/Kbuild"
if kmake "$W/walt" "$LOG/sched-walt.log" "$SYMS" && [ -f "$W/walt/sched-walt.ko" ]; then
	cp "$W/walt/sched-walt.ko" "$OUTM/"
	echo sched-walt >> "$ROOT/out/waltmods.list"
	echo "build_walt: sched-walt: built ($(grep -c ' warning: ' "$LOG/sched-walt.log") warnings)"
else
	echo "build_walt: sched-walt: FAILED"
	grep -E ': (fatal )?error: |^ERROR: modpost|WARNING: modpost: .*undefined' "$LOG/sched-walt.log" | sed -E "s|$W/||" | sort -u | head -40 || true
	exit 1
fi

# sched-penalty: the OnePlus 13's own, in a directory of its own next to WALT's headers
P=$W/penalty
mkdir -p "$P"
cp "$ROOT/src/msm8750/kernel/sched/walt/penalty."[ch] "$P/"
python3 -I "$ROOT/scripts/vendor_fix618.py" "$P"
{
	echo "obj-m += sched-penalty.o"
	echo "sched-penalty-y := penalty.o"
	echo "ccflags-y += -I\$(src) -I$W/walt -DCONFIG_SCHED_WALT_MODULE=1 $COPTS"
} > "$P/Kbuild"
if kmake "$P" "$LOG/sched-penalty.log" "$SYMS $W/walt/Module.symvers" && [ -f "$P/sched-penalty.ko" ]; then
	cp "$P/sched-penalty.ko" "$OUTM/"
	echo sched-penalty >> "$ROOT/out/waltmods.list"
	echo "build_walt: sched-penalty: built"
else
	echo "build_walt: sched-penalty: FAILED (sched-walt stays)"
	grep -E ': (fatal )?error: |^ERROR: modpost|WARNING: modpost: .*undefined' "$LOG/sched-penalty.log" | sed -E "s|$W/||" | sort -u | head -20 || true
	exit 1
fi
echo "build_walt: $(ls "$OUTM" | tr '\n' ' ')"
