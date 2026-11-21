# env.sh: paths and toolchain for the build scripts (sourced).
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
C=$ROOT/src/common		# ACK 6.18
O=$ROOT/out/gki			# its build
S=$ROOT/src/soc			# Qualcomm/OnePlus SoC modules (sm8850 tree, built for sun)
REF=$ROOT/ref_8550/kernel-6.18	# the reference port's helpers
J=${JOBS:-$(nproc)}

# the compiler: Google's clang when scripts/get_clang.sh fetched it, else Ubuntu's LLVM 19 (what CI
# installs), else whatever clang is on PATH
for CLANG_DIR in "$ROOT/toolchain/clang-r584948c/bin" /usr/lib/llvm-19/bin; do
	[ -x "$CLANG_DIR/clang" ] && { PATH=$CLANG_DIR:$PATH; break; }
done
# ccache in front of clang only (as `clang` on PATH: ccache finds the real one behind it)
if [ "${USE_CCACHE:-1}" = 1 ] && command -v ccache > /dev/null; then
	mkdir -p "$ROOT/toolchain/ccache-bin"
	ln -sfn "$(command -v ccache)" "$ROOT/toolchain/ccache-bin/clang"
	PATH=$ROOT/toolchain/ccache-bin:$PATH
	export CCACHE_BASEDIR=$ROOT CCACHE_NOHASHDIR=1 CCACHE_SLOPPINESS=time_macros,include_file_mtime,include_file_ctime
fi
export PATH
export KBUILD_BUILD_HOST=build-host KBUILD_BUILD_USER=build-user KBUILD_BUILD_VERSION=1
export KBUILD_BUILD_TIMESTAMP="Sat Nov 21 00:00:00 UTC 2026"
KMAKE=(make -C "$C" O="$O" ARCH=arm64 LLVM=1 LLVM_IAS=1)
