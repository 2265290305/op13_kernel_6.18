#!/bin/bash
# build_gki.sh: ACK 6.18 with the port's edits and config -> out/gki (Image, in-tree modules), and
# the in-tree modules installed (stripped) under out/gki-staging.
set -e
. "$(dirname "$0")/env.sh"
bash "$ROOT/tools/prep_common.sh"
bash "$ROOT/tools/config_gki.sh" "$C" "$O"
start=$(date +%s)
# KernelSU (drivers/kernelsu) includes SELinux's generated headers (flask.h, av_permissions.h) from
# the object tree; in one parallel build nothing orders it after security/selinux, so that first
{ "${KMAKE[@]}" -j"$J" security/selinux/ && "${KMAKE[@]}" -j"$J" Image modules; } > "$ROOT/out/gki-build.log" 2>&1 || {
	grep -E ': (fatal )?error: |\*\*\* ' "$ROOT/out/gki-build.log" | head -30
	echo "build_gki: FAILED after $(( $(date +%s) - start )) s"
	exit 1
}
rm -rf "$ROOT/out/gki-staging"
"${KMAKE[@]}" INSTALL_MOD_PATH="$ROOT/out/gki-staging" INSTALL_MOD_STRIP=1 modules_install > /dev/null
# the build/ and source/ links lead back into the tree (the artifact upload would follow them)
rm -f "$ROOT"/out/gki-staging/lib/modules/*/build "$ROOT"/out/gki-staging/lib/modules/*/source
grep -qE '^6\.18\.[0-9]+-palaziks\.ShiftPorts$' "$O/include/config/kernel.release" \
	|| { echo "build_gki: kernel release is $(cat "$O/include/config/kernel.release")"; exit 1; }
echo "build_gki: built in $(( $(date +%s) - start )) s: $(cat "$O/include/config/kernel.release"), \
$(find "$ROOT/out/gki-staging" -name '*.ko' | wc -l) modules, $(grep -c ' warning: ' "$ROOT/out/gki-build.log") warnings"
