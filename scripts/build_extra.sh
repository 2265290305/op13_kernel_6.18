#!/bin/bash
# build_extra.sh: OnePlus drivers past the boot itself, from the OnePlus 13's own 6.6 sources
# (src/mods8750/vendor/oplus/kernel), built as external modules against out/gki, the SoC build and
# build_oplus.sh's modules. Now: the touch screen (Synaptics TCM over SPI, "synaptics,tcm-spi-hbp" in
# the stock device tree: oplus_bsp_synaptics_tcm2) with what it needs -- the touch event notifier,
# OnePlus' touch helpers, the firmware-update helper, /proc/devinfo (device_info) and the log
# core's netlink (olc, also in the stock first stage).
#
# Each module is built from a copy with a Kbuild written here from OnePlus' own Bazel definition
# (oplus_local_modules.bzl: sources, defines, header paths); the 6.6 Makefiles key everything off
# options our configuration does not have. A module that fails is left out, with the ones that need
# it; the boot image is made without it. Modules in out/extramods, a log each in out/extra-log.
set -e
. "$(dirname "$0")/env.sh"
SRC=$ROOT/src/mods8750/vendor/oplus/kernel
W=$ROOT/out/extra
OUTM=$ROOT/out/extramods
LOG=$ROOT/out/extra-log
[ -f "$S/Module.symvers" ] || { echo "build_extra: build the SoC modules first"; exit 1; }
rm -rf "$W" "$OUTM" && mkdir -p "$W/inc/soc/oplus/dft" "$OUTM" "$LOG"
# the headers by the paths OnePlus' Bazel build gives them (<soc/oplus/...>)
# the SoC configuration, forced in as for the techpacks (env.sh)
CONF=$W/soc-autoconf.h
soc_autoconf "$CONF"
ln -s "$SRC/boot/include" "$W/inc/soc/oplus/system"
ln -s "$SRC/boot/include" "$W/inc/soc/oplus/boot"
ln -s "$SRC/dft/include/olc.h" "$W/inc/soc/oplus/dft/olc.h"
ln -s "$SRC/device_info/device_info/bazel/device_info.h" "$W/inc/soc/oplus/device_info.h"
ln -s "$SRC/touchpanel/touchpanel_notify/bazel/touchpanel_event_notify.h" "$W/inc/soc/oplus/touchpanel_event_notify.h"
# the rest of what the SoC repo links into OnePlus' tree, from the OnePlus 13's (env.sh)
oplus_overlay "$W/inc" "$ROOT/src/mods8750/vendor/oplus"
# oplus_touchscreen_v2's headers, which the Synaptics driver includes too. Each copy keeps its source
# directory's name: OnePlus' headers include one another by ../<that name>/...
TPV2=$W/oplus_touchscreen_v2

# name | directory | objects (module-y) | extra flags | modules it needs (of this list)
SETS=(
	"device_info|device_info/device_info|device_info.o|-DCONFIG_OPLUS_FEATURE_OPROJECT_MODULE=1|"
	"olc|dft/common/olc|olc_main.o olc_debug.o||"
	"oplus_bsp_tp_notify|touchpanel/touchpanel_notify|touchpanel_event_notify.o||"
	"oplus_bsp_fw_update|touchpanel/kernelFwUpdate|kernelFwUpdate.o||"
	"oplus_bsp_tp_custom|touchpanel/oplus_touchscreen_v2|touch_custom/touch.o|-DCONFIG_OPLUS_FEATURE_OPROJECT=1|"
	# its Bazel defines; the olc path of its exception report (stock links against olc)
	"oplus_bsp_synaptics_tcm2|touchpanel/synaptics_hbp|syna_tcm2.o tcm/synaptics_touchcom_core_v1.o tcm/synaptics_touchcom_core_v2.o tcm/synaptics_touchcom_func_base.o tcm/synaptics_touchcom_func_touch.o tcm/synaptics_touchcom_func_reflash.o tcm/synaptics_touchcom_func_romboot.o syna_tcm2_platform_spi.o syna_tcm2_sysfs.o syna_tcm2_testing.o synaptics_common.o touchpanel_proc.o touch_comon_api/touch_comon_api.o touchpanel_autotest/touchpanel_autotest.o touchpanel_healthinfo/touchpanel_healthinfo.o touchpanel_healthinfo/touchpanel_exception.o|-DCONFIG_TOUCHPANEL_NOTIFY=1 -DCONFIG_TOUCHPANEL_OPLUS_MODULE=1 -DBUILD_BY_BAZEL=1 -DCONFIG_QCOM_PANEL_EVENT_NOTIFIER=1 -DCONFIG_OPLUS_FEATURE_OLC_MODULE=1 -I$TPV2 -I$TPV2/touchpanel_notify|oplus_bsp_tp_notify oplus_bsp_tp_custom oplus_bsp_fw_update device_info olc"
)
SYMS="$S/Module.symvers $(ls "$ROOT"/out/oplus/*/Module.symvers 2>/dev/null | tr '\n' ' ')"
ok=0; bad=0; failed=" "
for entry in "${SETS[@]}"; do
	IFS='|' read -r name dir objs defs needs <<< "$entry"
	for n in $needs; do
		case $failed in *" $n "*) echo "build_extra: $name: left out ($n failed)"; bad=$((bad + 1)); failed="$failed$name "; continue 2;; esac
	done
	D=$W/$(basename "$dir")
	cp -r "$SRC/$dir" "$D"
	python3 -I "$REF/k618_fix618.py" "$D" | grep -v 'k618_fix618: 0 files changed' || true
	python3 -I "$ROOT/scripts/oplus_fix.py" "$D"
	# trace headers name their directory from the kernel's include/trace, in OnePlus' tree layout
	grep -rlZ "TRACE_INCLUDE_PATH.*vendor/oplus/kernel/$dir" "$D" | xargs -0 -r \
		sed -i -E "s#(define[[:space:]]+TRACE_INCLUDE_PATH[[:space:]]+)[./]*vendor/oplus/kernel/$dir#\1$D#"
	# its own directory first: the Synaptics driver has copies of oplus_touchscreen_v2's headers.
	# A one-file module named as its file needs no object list (kbuild would take it as its own part)
	{
		echo "obj-m += $name.o"
		[ "$objs" = "$name.o" ] || echo "$name-y := $objs"
		echo "ccflags-y := -I\$(src) $defs"
	} > "$D/Kbuild"
	set +e
	"${KMAKE[@]}" M="$D" modules -j"$J" KBUILD_EXTRA_SYMBOLS="$SYMS" \
		NOSTDINC_FLAGS="-nostdinc -I$W/inc -I$S/include" KCFLAGS="-Wno-error -include $CONF" > "$LOG/$name.log" 2>&1
	rc=$?
	set -e
	if [ $rc -ne 0 ] || [ ! -f "$D/$name.ko" ]; then
		echo "build_extra: $name: FAILED (make exit $rc)"
		grep -E ': (fatal )?error: |^ERROR: modpost|WARNING: modpost: .*undefined' "$LOG/$name.log" | sed -E "s|$W/||" | head -12 || true
		bad=$((bad + 1)); failed="$failed$name "
		continue
	fi
	echo "build_extra: $name: built"
	ok=$((ok + 1))
	SYMS="$SYMS $D/Module.symvers"
	cp "$D/$name.ko" "$OUTM/"
done
echo "build_extra: built $ok, failed $bad; modules: $(ls "$OUTM" | tr '\n' ' ')"
[ "$bad" -eq 0 ]
