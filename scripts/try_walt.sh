#!/bin/bash
# try_walt.sh: compile WALT (sched-walt, Qualcomm's window-assisted load tracking, which the stock
# phone loads in its first stage, with sched-penalty) for 6.18 on its own, to see what it takes --
# the image does not get it yet. WALT is off in this port (configs/op13_overrides.bzl): it hooks the
# scheduler's internals, and with it on, a WALT that does not build would take the SoC modules that
# call it along with it. Here it is the SM8850 SoC repo's 6.12 WALT with OnePlus' options (its
# registry entry in kernel/sched/walt/modules.bzl), and the OnePlus 13 6.6 vendor kernel's
# penalty.c as sched-penalty, against the SoC build and every OnePlus module built so far.
# Logs: out/walt-try/sched-walt.log, sched-penalty.log. Never fails the build.
. "$(dirname "$0")/env.sh"
W=$ROOT/out/walt-try
rm -rf "$W" && mkdir -p "$W/inc/linux"
cp -r "$S/kernel/sched/walt" "$W/walt"
python3 -I "$ROOT/scripts/vendor_fix618.py" "$W/walt"
CONF=$W/soc-autoconf.h
soc_autoconf "$CONF"
OMRG=$(find "$ROOT/out/vendor" -path '*cpu/oplus_omrg/oplus_omrg.h' 2>/dev/null | head -1)
[ -n "$OMRG" ] && ln -sfn "$OMRG" "$W/inc/linux/oplus_omrg.h"
SYMS="$S/Module.symvers $(find "$ROOT/out/vendor" "$ROOT/out/oplus" "$ROOT/out/extra" -name Module.symvers 2>/dev/null | tr '\n' ' ') $(ls "$ROOT"/out/tp-log/*.symvers 2>/dev/null | tr '\n' ' ')"
# WALT's objects as its registry entry lists them (sched-walt)
OBJS=$(python3 -I - "$S/kernel/sched/walt/modules.bzl" <<'PY'
import re, sys
t = open(sys.argv[1]).read()
m = re.search(r'name = "kernel/sched/walt/sched-walt",.*?srcs = \[(.*?)\]', t, re.S)
print(" ".join(s.split("/")[-1][:-2] + ".o" for s in re.findall(r'"([^"]+\.c)"', m.group(1))))
PY
)
COPTS="-DCONFIG_OPLUS_FEATURE_SCHED_ASSIST -DCONFIG_OPLUS_SCHED_HALT_MASK_PRT -DCONFIG_OPLUS_FEATURE_FRAME_BOOST -DCONFIG_OPLUS_FEATURE_SCHED_EXT -DCONFIG_OPLUS_FEATURE_GEAS"
{
	echo "obj-m += sched-walt.o"
	echo "sched-walt-y := $OBJS"
	echo "ccflags-y += -I\$(src) -DCONFIG_SCHED_WALT_MODULE=1 $COPTS"
} > "$W/walt/Kbuild"
"${KMAKE[@]}" M="$W/walt" modules -j"$J" KBUILD_EXTRA_SYMBOLS="$SYMS" \
	NOSTDINC_FLAGS="-nostdinc -I$S/include -I$W/inc -idirafter $C" KCFLAGS="-Wno-error -include $CONF" \
	> "$W/sched-walt.log" 2>&1
echo "try_walt: sched-walt: make exit $?, $(grep -c ': error: ' "$W/sched-walt.log") errors"
grep -E ': (fatal )?error: |^ERROR: modpost' "$W/sched-walt.log" | sed -E "s|$W/||" | sort -u | head -40
# sched-penalty: the OnePlus 13's own (6.6 vendor kernel), next to WALT's headers
if [ -f "$ROOT/src/msm8750/kernel/sched/walt/penalty.c" ]; then
	cp "$ROOT/src/msm8750/kernel/sched/walt/penalty."[ch] "$W/walt/"
	{
		echo "obj-m += sched-penalty.o"
		echo "sched-penalty-y := penalty.o"
		echo "ccflags-y += -I\$(src) -DCONFIG_SCHED_WALT_MODULE=1 $COPTS"
	} > "$W/walt/Kbuild"
	"${KMAKE[@]}" M="$W/walt" modules -j"$J" KBUILD_EXTRA_SYMBOLS="$SYMS $W/walt/Module.symvers" \
		NOSTDINC_FLAGS="-nostdinc -I$S/include -I$W/inc -idirafter $C" KCFLAGS="-Wno-error -include $CONF" \
		> "$W/sched-penalty.log" 2>&1
	echo "try_walt: sched-penalty: make exit $?"
	grep -E ': (fatal )?error: |^ERROR: modpost' "$W/sched-penalty.log" | sed -E "s|$W/||" | sort -u | head -20
fi
exit 0
