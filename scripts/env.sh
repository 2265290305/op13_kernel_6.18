# env.sh: paths and toolchain for the build scripts (sourced).
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
C=$ROOT/src/common		# ACK 6.18
O=$ROOT/out/gki			# its build
S=$ROOT/src/soc			# Qualcomm/OnePlus SoC modules (sm8850 tree, built for sun)
REF=$ROOT/ref_8550/kernel-6.18	# the reference port's helpers
J=${JOBS:-$(nproc)}

# the compiler: Google's clang-r584948c (22.0.1) when scripts/get_clang.sh fetched it, else LLVM 22
# from apt.llvm.org (what CI installs), else whatever clang is on PATH
for CLANG_DIR in "$ROOT/toolchain/clang-r584948c/bin" /usr/lib/llvm-22/bin; do
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
# KCPPFLAGS: what Android's own builds give every compile, the kernel and each vendor module
# (Kleaf's COMMON_KCFLAGS; the SoC repo's build.config.common): vendor code chooses its Android
# paths by it -- qcacld's IOMMU setup, cnss, ... (KCPPFLAGS, not KCFLAGS: scripts set KCFLAGS)
KMAKE=(make -C "$C" O="$O" ARCH=arm64 LLVM=1 LLVM_IAS=1 LOCALVERSION= KCPPFLAGS=-D__ANDROID_COMMON_KERNEL__)

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
	# OnePlus' feature switches for its own modules (device/op13/oplus-features.config): the SoC repo's
	# sun configuration is Qualcomm's and has none; OnePlus' code is built as OnePlus builds it
	# soc_autoconf OUT techpacks: less the switches that make code call into OnePlus' modules, built
	# after the techpacks: MM_OSVELTE has KGSL register with mm_osvelte's memory tracker
	# (register_mtrack_debugger), and modpost failed msm_kgsl -- and with it every image (run
	# 45427714881). The GPU does not wait on a memory statistics module that may not build.
	local drop=" "
	[ "$2" = techpacks ] && drop=" CONFIG_OPLUS_FEATURE_MM_OSVELTE "
	awk -F= -v drop="$drop" '/^CONFIG_/ && !index(drop, " " $1 " ") { n = $1; if ($2 == "m") n = n "_MODULE"; printf "#ifndef %s\n#define %s 1\n#endif\n", n, n }' \
		"$ROOT/device/op13/oplus-features.config" >> "$1"
}

# oplus_overlay DIR TREE: the SoC repo's include links into OnePlus' tree (include/soc/oplus/boot,
# include/linux/sched_assist.h, ... -> ../vendor/oplus/...) made again in DIR, pointing into TREE
# (a vendor/oplus directory) wherever TREE has the file and DIR has nothing at that path yet. The
# SoC repo is the OnePlus 15's: since its links resolve (fetch.sh's vendor/oplus), code from the
# OnePlus 13's tree got the OnePlus 15's oplus_project.h, sched_assist.h, ... ahead of its own
# (projectinfo: "use of undeclared identifier 'PRE_EVB1'", and every module needing get_project).
# DIR goes ahead of the SoC's include directory.
oplus_overlay() {
	local d=$1 t=$2 l rel
	(cd "$S" && find include -type l -lname '*vendor/oplus/*') | while read -r l; do
		rel=$(readlink "$S/$l"); rel=${rel#*vendor/oplus/}
		[ -e "$t/$rel" ] || continue
		[ -e "$d/${l#include/}" ] && continue
		mkdir -p "$d/$(dirname "${l#include/}")"
		ln -sfn "$t/$rel" "$d/${l#include/}"
	done
	# headers the SoC repo carries as old copies instead of links (with oplus_midplat.h, which
	# _data_ocdt.h includes from its own directory): its oplus_project.h/_data_ocdt.h have
	# no FACTORY_MODE (OnePlus' wireless pen) and number PCB_VERSION otherwise than the project
	# info module, built from TREE's kernel/boot/include, does
	for l in oplus_project.h oplus_project_data_ocdt.h oplus_midplat.h; do
		[ -e "$t/kernel/boot/include/$l" ] && [ ! -e "$d/soc/oplus/system/$l" ] || continue
		mkdir -p "$d/soc/oplus/system"
		ln -sfn "$t/kernel/boot/include/$l" "$d/soc/oplus/system/$l"
	done
}
