#!/bin/bash
# build_soc.sh [module ...]: the SoC repo's modules for sun (configs/sun_perf.bzl + the port's
# overrides), built out of tree against out/gki, as the reference's k618_soc_build.sh does for
# kalama: the dicts evaluated with Kconfig on top of the kernel's .config, then a generated Kbuild,
# and make keeps going past errors. With no names, every module the configuration enables.
# Log in out/soc-build.log, the first error of each file in out/soc-errors.txt.
set -e
. "$(dirname "$0")/env.sh"
KC=$ROOT/out/soc-kconfig
LOG=$ROOT/out/soc-build.log
[ -f "$O/Module.symvers" ] || { echo "build_soc: build the kernel first (scripts/build_gki.sh)"; exit 1; }
# from the committed tree each time: the 6.12 -> 6.18 fixes are made again
git -C "$S" checkout -q -- .
python3 -I "$REF/k618_fix618.py" "$S"
cp "$ROOT/configs/op13_overrides.bzl" "$S/configs/"
CFG=configs/sun_perf.bzl,op13_overrides.bzl
mkdir -p "$S/gen" "$KC"
python3 -I "$REF/k618_soc_kbuild.py" copies "$S" "$C"
# the SoC repo's Kconfig files in one (less the OnePlus one that was not published)
grep -v 'drivers/power/oplus/Kconfig' "$S/Kconfig.msm" > "$S/gen/Kconfig.msm"
KCONFIG_EXT_PREFIX=$S/ "$S/flatten_kconfig.sh" "$S/gen/Kconfig.msm" > "$S/gen/Kconfig.ext"
python3 -I "$REF/k618_soc_kbuild.py" fragment "$S" "$S/$CFG" > "$S/gen/fragment.config"
ok=
for try in $(seq 1 40); do
	cat "$O/.config" "$S/gen/fragment.config" > "$KC/.config"
	make -C "$C" O="$KC" ARCH=arm64 LLVM=1 LLVM_IAS=1 KCONFIG_EXT_PREFIX="$S/gen/" \
		olddefconfig > "$ROOT/out/soc-kconfig.log" 2>&1 && { ok=1; break; }
	# a dependency loop between the SoC Kconfig and the kernel's own: the SoC side's edge goes
	python3 -I "$REF/k618_kconfig_fix.py" "$S/gen/Kconfig.ext" "$ROOT/out/soc-kconfig.log" \
		|| { tail -20 "$ROOT/out/soc-kconfig.log"; exit 1; }
done
[ -n "$ok" ] || { echo "build_soc: kconfig still failing after $try tries"; exit 1; }
python3 -I "$REF/k618_soc_kbuild.py" kbuild "$S" "$KC/.config" "$O/.config" "$@"
start=$(date +%s)
set +e
"${KMAKE[@]}" M="$S" -k -j"$J" modules > "$LOG" 2>&1
rc=$?
set -e
echo "build_soc: make exit $rc in $(( $(date +%s) - start )) s; modules built: \
$(find "$S" -name '*.ko' -newer "$S/Kbuild" | wc -l) of $(grep -c '^obj-m' "$S/Kbuild")"
grep -E ': (fatal )?error: ' "$LOG" | sed -E "s|$S/||" | awk -F: '!seen[$1]++' > "$ROOT/out/soc-errors.txt" || true
echo "build_soc: files with errors: $(wc -l < "$ROOT/out/soc-errors.txt")"
grep -E ': (fatal )?error: ' "$LOG" | sed -E 's/.*error: //' | sed -E "s/'[^']*'/'X'/g" | sort | uniq -c | sort -rn | head -25 || true
grep -E '^ERROR: modpost' "$LOG" | head -40 || true
exit $rc
