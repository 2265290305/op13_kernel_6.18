#!/bin/bash
# get_clang.sh: Google's clang-r584948c (the reference's pinned compiler) into toolchain/. x86_64 only.
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
D=$ROOT/toolchain/clang-r584948c
REV=4a7d0a5e443c27d8f68fbd46abfab464e1355a69
[ "$(uname -m)" = x86_64 ] || { echo "get_clang: prebuilt clang is x86_64 only; using clang from PATH"; exit 0; }
if [ ! -x "$D/bin/clang" ]; then
	mkdir -p "$D"
	curl -fsSL --retry 5 "https://android.googlesource.com/platform/prebuilts/clang/host/linux-x86/+archive/$REV/clang-r584948c.tar.gz" \
		| tar -xz -C "$D"
fi
"$D/bin/clang" --version | head -1
