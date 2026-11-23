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
# LOCALVERSION= (set, empty): the release is 6.18.<n> + CONFIG_LOCALVERSION, nothing appended
KMAKE=(make -C "$C" O="$O" ARCH=arm64 LLVM=1 LLVM_IAS=1 LOCALVERSION=)

# soc_autoconf OUT: the vendor configuration as code built outside the SoC tree must see it -- the SoC
# build's evaluated options (src/soc/gen/autoconf_vendor.h; the kernel's own autoconf.h has none of
# them), less the other chipsets' selectors and less KGSL's own governors (KGSL builds those itself).
# Every build against the SoC headers needs it forced in: those headers turn functions into inline
# stubs when an option looks off (smem.h's qcom_smem_get() then "returns" 0x13, and OnePlus'
# project info crashed reading it, test-31).
# The options build_soc.sh sets on beyond sun_perf (out/soc-forced-opts.txt) are left out too: they are
# there to build the SoC modules the phone loads, and the code built against the SoC from outside
# sees sun_perf's configuration as before (one of them, tmecom, cost securemsm's link: test-26).
soc_autoconf() {
	local forced=" "
	[ -f "$ROOT/out/soc-forced-opts.txt" ] && forced=" $(cut -d= -f1 "$ROOT/out/soc-forced-opts.txt" | tr '\n' ' ')"
	awk -v forced="$forced" '
	     /^#ifndef CONFIG_/ { o = $2; sub(/_MODULE$/, "", o); if (index(forced, " " o " ")) { skip = 3 } }
	     /^#ifndef CONFIG_ARCH_/ && $2 != "CONFIG_ARCH_SUN" { skip = 3 }
	     /^#ifndef CONFIG_DEVFREQ_GOV_QCOM_(ADRENO_TZ|GPUBW_MON)(_MODULE)?$/ { skip = 3 }
	     skip { skip--; next } { print }' "$S/gen/autoconf_vendor.h" > "$1"
	grep -q 'CONFIG_ARCH_SUN' "$1" || { echo "soc_autoconf: CONFIG_ARCH_SUN is not in the SoC configuration"; return 1; }
}
