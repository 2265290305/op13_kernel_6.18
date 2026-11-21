#!/bin/bash
# fetch.sh: every source input at a pinned revision (shallow), into src/ and ref_8550/. Idempotent.
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

# path | url | revision
INPUTS=(
	"src/common|https://android.googlesource.com/kernel/common|ff4a6c3bb0f471a9dd186293a47b62c83829b97d"
	"ref_8550|https://github.com/JiaqiLi404/android_kernel_618_for_sm8550.git|c3956156ce7c4193c451dfda531fad72d35bfebb"
	"src/soc|https://github.com/OnePlusOSS/android_kernel_oneplus_sm8850.git|fc30e54174d254ff7f33622a9278e4435f6718d2"
	"src/mods8850|https://github.com/OnePlusOSS/android_kernel_modules_and_devicetree_oneplus_sm8850.git|5ab2a689ff87d7d28c511f1762cf41c1b90d965a"
	"src/mods8750|https://github.com/OnePlusOSS/android_kernel_modules_and_devicetree_oneplus_sm8750.git|d50b305f7da9e14715a25120a4ac7b1a4b8b97c3"
	"src/mkbootimg|https://android.googlesource.com/platform/system/tools/mkbootimg|f5c284e8998dd8a085cf027bb518b6c2b84cf744"
)

fetch() {
	local path=$1 url=$2 rev=$3
	if [ -d "$path/.git" ] && git -C "$path" rev-parse -q --verify HEAD > /dev/null; then
		echo "$path: present ($(git -C "$path" rev-parse --short HEAD))"
		return
	fi
	mkdir -p "$path"
	git -C "$path" init -q
	git -C "$path" remote add origin "$url" 2> /dev/null || true
	git -C "$path" fetch -q --depth 1 --no-tags origin "$rev"
	git -C "$path" -c advice.detachedHead=false checkout -q FETCH_HEAD
	echo "$path: $(git -C "$path" rev-parse --short HEAD)"
}

pids=()
for item in "${INPUTS[@]}"; do
	IFS='|' read -r path url rev <<< "$item"
	fetch "$path" "$url" "$rev" &
	pids+=($!)
done
for p in "${pids[@]}"; do wait "$p"; done

# the reference's 6.18 SoC integration (6.12 -> 6.18 fixes, plus kalama, which sun does not use)
SOC=src/soc
want=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["target_tree"])' ref_8550/provenance/soc-baseline.json)
if [ "$(git -C $SOC log -1 --format=%s)" != "Apply reference 6.18 SoC integration" ]; then
	git -C $SOC apply --index --whitespace=nowarn "$ROOT/ref_8550/patches/soc-sm8550.patch"
	[ "$(git -C $SOC write-tree)" = "$want" ] || { echo "fetch: SoC tree differs from the reference"; exit 1; }
	git -C $SOC -c user.name=op13-port -c user.email=op13-port@localhost commit -q -m "Apply reference 6.18 SoC integration"
fi
echo "src/soc: reference integration $(git -C $SOC rev-parse --short HEAD) (tree $want)"
