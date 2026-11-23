#!/bin/bash
# build_vendor.sh: every OnePlus driver the stock phone loads, from the OnePlus 13's own 6.6 sources
# (src/mods8750/vendor/oplus), as OnePlus' Bazel build defines them -- not a hand-made list.
#
#  1. The sources are copied once (out/vendor/tree): OnePlus' tree, Qualcomm's techpacks as OnePlus 13's
#     6.6 tree has them, Qualcomm's touch-drivers techpack, the NFC chips' drivers and the driver
#     directories of the OnePlus 13's own vendor kernel (scripts/fetch.sh).
#  2. scripts/bzl_eval.py runs the BUILD.bazel/.bzl files there (Starlark, run as Python with Bazel's
#     built-ins stubbed) and records every module: sources, include directories, defines, copts,
#     defconfig, the modules it links against. Then the copy goes through the 6.12 -> 6.18 sweeps
#     and this port's own edits, like the other builds.
#  3. scripts/vendor_kbuild.py writes a Kbuild.<module> per module into its package and the build
#     order: the modules the stock lists name (device/op13/stock) and what they need, less what the
#     other builds (SoC, techpacks, kernel, OnePlus boot and touch modules) make already.
#  4. Each module: make M=<package> MO=out/vendor/obj/<module> OPMOD=<module>, against the GKI build,
#     the SoC configuration (forced in, env.sh) and the Module.symvers of everything built before it.
#  5. The stock modules made from plain Makefiles instead (scripts/vendor_mkplan.py): each directory
#     built once with the options that switch them on -- the OnePlus 13 vendor kernel's last.
#
# A module that fails is left out with the ones that need it; the boot image is made without it.
# Modules in out/vendormods (and their names in out/vendormods.list, for mklists.py: they load last,
# probing in the background), a log each in out/vendor-log, the summary in out/vendor-log/summary.txt.
set -e
. "$(dirname "$0")/env.sh"
SRC=$ROOT/src/mods8750
W=$ROOT/out/vendor
T=$W/tree
OUTM=$ROOT/out/vendormods
LOG=$ROOT/out/vendor-log
[ -f "$S/Module.symvers" ] || { echo "build_vendor: build the SoC modules first"; exit 1; }
rm -rf "$W" "$OUTM" "$LOG" && mkdir -p "$T/vendor" "$W/obj" "$W/inc/soc/oplus" "$W/inc/linux" "$OUTM" "$LOG"
CONF=$W/soc-autoconf.h
soc_autoconf "$CONF"

QREPOS=$(cd "$SRC/vendor/qcom/opensource" && ls -d -- */ | tr -d / | grep -v -- '-devicetree$' | tr '\n' ' ')
# 1. the build copy: OnePlus' tree, the NFC chips' (ST, NXP) and OnePlus' NFC driver, which only the
# SM8850 release has
cp -r "$SRC/vendor/oplus" "$T/vendor/oplus"
cp -r "$SRC/vendor/st" "$SRC/vendor/nxp" "$T/vendor/"
mkdir -p "$T/vendor/qcom/opensource"
for r in $QREPOS; do cp -r "$SRC/vendor/qcom/opensource/$r" "$T/vendor/qcom/opensource/"; done
# Qualcomm's touch-drivers techpack (scripts/fetch.sh), which OnePlus' release does not carry
if [ -d "$ROOT/src/touch-drivers" ]; then
	cp -r "$ROOT/src/touch-drivers" "$T/vendor/qcom/opensource/touch-drivers" && rm -rf "$T/vendor/qcom/opensource/touch-drivers/.git"
	QREPOS="$QREPOS touch-drivers"
fi
# 2. the definitions: OnePlus' own, and Qualcomm's techpacks as OnePlus 13's 6.6 tree has them
# (audio, Wi-Fi, Bluetooth, camera, video, EVA, data/IPA, SPU, ...; their device trees aside).
# build_tp.sh builds some of the techpacks already (from the SM8850 release): those modules are
# skipped below, their headers still serve the others.
# (read in the build copy, before its fixes; OnePlus' macro file from its kernel_platform)
BZL_MACROS=$SRC/kernel_platform/oplus/bazel python3 -I "$ROOT/scripts/bzl_eval.py" "$T" "$W/modules.json" \
	vendor/oplus $(for r in $QREPOS; do echo "vendor/qcom/opensource/$r"; done)

# and the OnePlus 13's own vendor kernel's driver directories (scripts/fetch.sh: the drivers only it
# has), searched last; its headers after everyone else's
if [ -d "$ROOT/src/msm8750/drivers" ]; then
	mkdir -p "$T/msm8750" && cp -r "$ROOT/src/msm8750/drivers" "$T/msm8750/"
	python3 -I "$REF/k618_fix618.py" "$T/msm8750" | grep -v 'k618_fix618: 0 files changed' || true
fi
mkdir -p "$T/vendor/oplus8850/kernel" && cp -r "$ROOT/src/mods8850/vendor/oplus/kernel/nfc" "$T/vendor/oplus8850/kernel/"
for d in "$T"/vendor/*; do
	python3 -I "$REF/k618_fix618.py" "$d" | grep -v 'k618_fix618: 0 files changed' || true
	python3 -I "$ROOT/scripts/oplus_fix.py" "$d"
done
# the reference's 6.12 -> 6.18 techpack fixes (not its Xiaomi or 5.15 ones), as build_tp.sh
python3 -I "$ROOT/scripts/tp_fix.py" "$REF" "$T/vendor/qcom/opensource"
# and the 6.6 -> 6.18 API changes these 6.6 sources meet (platform remove, const sysfs/sysctl
# callbacks, struct fd, unaligned.h, strlcpy, DAI formats, ...)
python3 -I "$ROOT/scripts/vendor_fix618.py" "$T/vendor" "$T/msm8750"
# trace headers name their own directory relative to the kernel's include/trace, in their tree's
# layout (../../../vendor/..., ../../kernel/oplus_cpu/...): each relative one becomes the absolute
# directory of the header that defines it
grep -rlZ --include='*.h' -E 'define[[:space:]]+[A-Z0-9_]*TRACE_INCLUDE_PATH[[:space:]]+\.' "$T" | while IFS= read -r -d '' h; do
	sed -i -E "s#(define[[:space:]]+[A-Z0-9_]*TRACE_INCLUDE_PATH[[:space:]]+)\.[^[:space:]]*#\1$(dirname "$h")#" "$h"
done
# the charger's generated IC tables (its Bazel rule oplus_chg_ic_cfg runs this script), where its
# header target (oplus_chg_v2_ic_cfg_headers) has them
CHG=$T/vendor/oplus/kernel/charger/bazel
for d in oplus_chg_ic_cfg oplus_chg_v2_ic_cfg; do
	mkdir -p "$CHG/$d"
	python3 "$CHG/v2/scripts/ic_cfg_parse.py" -hd "$CHG/$d/oplus_chg_ic_cfg.h" -s "$CHG/$d/oplus_chg_ic_cfg_str.h" \
		-df "$CHG/$d/oplus_chg_ic_auto_debug.h" "$CHG/v2/config/oplus_chg_ic.json" > "$LOG/charger-ic-cfg.log" 2>&1 \
		|| echo "build_vendor: the charger's IC tables were not made (charger-ic-cfg.log)"
done
# the headers OnePlus' kernel tree has under include/soc/oplus and include/linux, by those paths;
# boot's as a whole set in each place (oplus_project.h includes oplus_project_data_ocdt.h next to it)
K=$T/vendor/oplus/kernel
lnk() { [ -e "$2" ] && { mkdir -p "$W/inc/$(dirname "$1")"; ln -sfn "$2" "$W/inc/$1"; }; return 0; }
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
# OnePlus' cpu tree as its kernel has it (kernel/oplus_cpu): includes of "../kernel/oplus_cpu/..."
# resolve from the include directory above
mkdir -p "$W/kernel" && ln -sfn "$K/cpu" "$W/kernel/oplus_cpu"
# the OnePlus 13 vendor kernel's device-tree bindings (the other chipsets' clocks), after every other
# header: only those, its linux/ headers are 6.6's
mkdir -p "$W/inc8750" && [ -d "$ROOT/src/msm8750/include/dt-bindings" ] \
	&& ln -sfn "$ROOT/src/msm8750/include/dt-bindings" "$W/inc8750/dt-bindings"

# what the other builds make already (SoC, techpacks, the kernel's own, OnePlus' boot and touch
# modules): not made again
HAVE=$W/have
mkdir -p "$HAVE"
for f in $(find "$S" "$ROOT/out/gki-staging" "$ROOT/out/tpmods" "$ROOT/out/oplusmods" "$ROOT/out/extramods" -name '*.ko' 2>/dev/null); do
	: > "$HAVE/$(basename "$f")"
done

# 3. Kbuild files and the order
ST=$ROOT/device/op13/stock
python3 -I "$ROOT/scripts/vendor_kbuild.py" "$W/modules.json" "$T" \
	"$ST/first_stage.load:$ST/vendor_dlkm.load:$ST/system_dlkm.load" \
	"$HAVE" "$W/plan.txt"

# 4. build
SYMS="$S/Module.symvers $(ls "$ROOT"/out/tp-log/*.symvers "$ROOT"/out/oplus/*/Module.symvers "$ROOT"/out/extra/*/Module.symvers 2>/dev/null | tr '\n' ' ')"
ok=0; bad=0; failed=" "; : > "$LOG/summary.txt"
while IFS='|' read -r name pkg base needs; do
	for n in $needs; do
		case $failed in *" $n "*)
			echo "build_vendor: $name: left out ($n failed)" | tee -a "$LOG/summary.txt"
			bad=$((bad + 1)); failed="$failed$name "; continue 2;;
		esac
	done
	MO=$W/obj/$name
	mkdir -p "$MO"
	set +e
	"${KMAKE[@]}" M="$T/$pkg" MO="$MO" OPMOD="$base" modules -j"$J" KBUILD_EXTRA_SYMBOLS="$SYMS" \
		NOSTDINC_FLAGS="-nostdinc -I$S/include -I$W/inc -idirafter $W/inc8750" \
		KCFLAGS="-Wno-error -include $CONF" > "$LOG/$name.log" 2>&1
	rc=$?
	set -e
	if [ $rc -ne 0 ] || [ ! -f "$MO/$base.ko" ]; then
		echo "build_vendor: $name: FAILED (make exit $rc)" | tee -a "$LOG/summary.txt"
		grep -E ': (fatal )?error: |^ERROR: modpost' "$LOG/$name.log" | sed -E "s|$T/||" | head -6 \
			| tee -a "$LOG/summary.txt" || true
		bad=$((bad + 1)); failed="$failed$name "
		continue
	fi
	echo "build_vendor: $name: built" | tee -a "$LOG/summary.txt"
	ok=$((ok + 1))
	SYMS="$SYMS $MO/Module.symvers"
	cp "$MO/$base.ko" "$OUTM/"
done < "$W/plan.txt"
# 5. the stock modules OnePlus makes from plain Makefiles: each directory built once, with the
# options that switch its wanted modules on set to m (and defined for the C code)
python3 -I "$ROOT/scripts/vendor_mkplan.py" "$T" \
	"$ST/first_stage.load:$ST/vendor_dlkm.load:$ST/system_dlkm.load" \
	"$HAVE:$OUTM" "$W/mkplan.txt" \
	vendor/oplus vendor/st vendor/nxp vendor/oplus8850 vendor/qcom/opensource msm8750
while IFS='|' read -r dir opts names; do
	tag=mk-$(echo "$dir" | tr '/' '_')
	MO=$W/obj/$tag
	mkdir -p "$MO"
	vars=; defs=
	for o in $opts; do vars="$vars $o=m"; defs="$defs -D${o}_MODULE=1"; done
	set +e
	# shellcheck disable=SC2086
	"${KMAKE[@]}" M="$T/$dir" MO="$MO" modules -j"$J" KBUILD_EXTRA_SYMBOLS="$SYMS" $vars \
		NOSTDINC_FLAGS="-nostdinc -I$S/include -I$W/inc -idirafter $W/inc8750" \
		KCFLAGS="-Wno-error -include $CONF $defs" \
		> "$LOG/$tag.log" 2>&1
	rc=$?
	set -e
	for n in $names; do
		ko=$(find "$MO" -name "$n.ko" -o -name "$(echo "$n" | tr '_' '-').ko" | head -1)
		if [ -n "$ko" ]; then
			echo "build_vendor: $n: built ($dir)" | tee -a "$LOG/summary.txt"
			ok=$((ok + 1)); cp "$ko" "$OUTM/"
		else
			echo "build_vendor: $n: FAILED ($dir, make exit $rc)" | tee -a "$LOG/summary.txt"
			bad=$((bad + 1))
		fi
	done
	[ $rc -eq 0 ] || grep -E ': (fatal )?error: |^ERROR: modpost' "$LOG/$tag.log" | sed -E "s|$T/||" | head -6 \
		| tee -a "$LOG/summary.txt" || true
	[ -f "$MO/Module.symvers" ] && SYMS="$SYMS $MO/Module.symvers"
done < "$W/mkplan.txt"
ls "$OUTM" | sed 's/\.ko$//' > "$ROOT/out/vendormods.list"
echo "build_vendor: built $ok, failed $bad" | tee -a "$LOG/summary.txt"
[ "$bad" -eq 0 ]
