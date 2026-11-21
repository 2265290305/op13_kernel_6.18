#!/bin/bash
# build_oplus.sh: the OnePlus 13's own first-stage boot modules (OnePlus' SM8750 sources,
# src/mods8750/vendor/oplus/kernel/boot), as external modules against out/gki and the SoC build:
# boot parameter parsing (oplusboot, ftm mode, charger present, build variant, CDT), boot mode,
# project info (/proc/oplusVersion) and the bootloader log. Each group copied into out/oplus and
# built there; modules collected in out/oplusmods, a log per group in out/oplus-log.
set -e
. "$(dirname "$0")/env.sh"
SRC=$ROOT/src/mods8750/vendor/oplus/kernel/boot
W=$ROOT/out/oplus
OUTM=$ROOT/out/oplusmods
LOG=$ROOT/out/oplus-log
[ -f "$S/Module.symvers" ] || { echo "build_oplus: build the SoC modules first"; exit 1; }
rm -rf "$W" "$OUTM" && mkdir -p "$W/inc/soc/oplus" "$OUTM" "$LOG"
# OnePlus' headers by the paths its kernel tree has them at
ln -s "$SRC/include" "$W/inc/soc/oplus/boot"
ln -s "$SRC/include" "$W/inc/soc/oplus/system"

# name | directory | make variables
SETS=(
	"cmdline_parser|cmdline_parser|CONFIG_OPLUS_FEATURE_OPLUSBOOT=m CONFIG_OPLUS_FEATURE_FTMMODE=m CONFIG_OPLUS_FEATURE_CHARGERPRESENT=m CONFIG_OPLUS_FEATURE_BUILDVARIANT=m CONFIG_OPLUS_FEATURE_CDT=m"
	"bootmode|bootmode|CONFIG_OPLUS_FEATURE_BOOTMODE=m"
	# the stock module reports SM8750 / QCOM
	"projectinfo|oplus_projectinfo|CONFIG_OPLUS_SYSTEM_KERNEL_QCOM=y CONFIG_OPLUS_FEATURE_OPROJECT=m OPLUS_VND_BUILD_PLATFORM=SM8750 OPLUS_VND_BUILD_CHIPSET_COMPANY=QCOM"
	"bootloader_log|bootloader_log|CONFIG_OPLUS_FEATURE_BOOTLOADER_LOG=m"
)
SYMS=$S/Module.symvers
ok=0; bad=0
for entry in "${SETS[@]}"; do
	IFS='|' read -r name dir vars <<< "$entry"
	cp -r "$SRC/$dir" "$W/$name"
	set +e
	# shellcheck disable=SC2086
	"${KMAKE[@]}" M="$W/$name" modules -j"$J" KBUILD_EXTRA_SYMBOLS="$SYMS" \
		NOSTDINC_FLAGS="-nostdinc -I$S/include -I$W/inc" KCFLAGS="-Wno-error" $vars > "$LOG/$name.log" 2>&1
	rc=$?
	set -e
	echo "build_oplus: $name: make exit $rc, $(find "$W/$name" -name '*.ko' | wc -l) modules"
	if [ $rc -ne 0 ]; then
		bad=$((bad + 1))
		grep -E ': (fatal )?error: |^ERROR: modpost' "$LOG/$name.log" | sed -E "s|$W/||" | head -8 || true
		continue
	fi
	ok=$((ok + 1))
	[ -f "$W/$name/Module.symvers" ] && SYMS="$SYMS $W/$name/Module.symvers"
	find "$W/$name" -name '*.ko' -exec cp {} "$OUTM/" \;
done
echo "build_oplus: built $ok, failed $bad; modules: $(ls "$OUTM" | tr '\n' ' ')"
[ "$bad" -eq 0 ]
