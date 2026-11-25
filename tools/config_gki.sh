#!/bin/bash
# config_gki.sh <kernel src> <out dir> [make args...]: gki_defconfig plus what the OP13 port needs.
set -e
C=$(cd "$1" && pwd); O=$2; shift 2
mkdir -p "$O"; O=$(cd "$O" && pwd)
M="make -C $C O=$O ARCH=arm64 LLVM=1 LLVM_IAS=1 $*"
$M gki_defconfig > "$O/../gki-config.log" 2>&1
# kernel-own modules the stock second stage loads that gki_defconfig lacks (as the reference;
# STM_PROTO_BASIC left out: it needs STM, which is a vendor module here)
# the kernel's name: 6.18.<n>$KNAME (no "-4k", no git hash: scripts/env.sh passes LOCALVERSION= so
# setlocalversion appends nothing)
KNAME=-palaziks.ShiftPorts
GKI_MODS="MTD MTD_BLKDEVS MTD_BLOCK MTD_OOPS MTD_BLOCK2MTD MTD_OF_PARTS QCOM_PMIC_GLINK
	  UCSI_PMIC_GLINK USB_EHSET_TEST_FIXTURE IR_SPI IIO_BUFFER_CB
	  TLS PTP_1588_CLOCK_KVM DRM_LONTIUM_LT9611UXC COMMON_CLK_SCMI"
# (clk-scmi: the kernel's own, stock loads it from vendor_dlkm and coresight's atclk is an SCMI
# clock -- the SoC repo's copy does not build for 6.18, without it coresight defers for ever, test-40)
# (atmel_mxt_ts and goodix_ts: the phone's are Qualcomm's touch-drivers techpack ones, build_vendor.sh)
# and the ones only a selector reaches: snd-soc-hdmi-codec (the LT9611UXC bridge above) -- y or m.
# Not usb_f_rndis: with the gadget configfs built in it can only be built in too, and Qualcomm's
# usb_f_gsi (USB, adb) exports the same rndis_* functions -- modpost refused it and with it the whole
# SoC build (run 45217710500). usb_f_gsi's RNDIS is the one this phone uses.
GKI_SELECTED="SND_SOC_HDMI_CODEC"
args=""
for c in $GKI_MODS; do args="$args -m $c"; done
# STATIC_USERMODEHELPER off: the reference's batch module loader is a usermode helper.
# MEMCG_V1: ColorOS mounts the v1 memory cgroup (test-45: "cgroup: Unknown subsys name 'memory'"),
# as the stock 6.6 kernel offers it; 6.18 has it behind its own option, off in gki_defconfig.
# Debug info and BTF as gki_defconfig and the stock kernel have them (DWARF5, zstd-compressed,
# DEBUG_INFO_BTF): BPF programs and tools read the kernel's types from /sys/kernel/btf/vmlinux.
# Symbol CRCs from DWARF (gendwarfksyms), as gki_defconfig has them: Rust needs it with MODVERSIONS
# (init/Kconfig), and with Rust go ashmem -- Android's, in Rust since 6.12 -- and the Rust binder
# module; genksyms here had turned all three off (olddefconfig, silently). SHA-256 module
# signatures: hosts with a strict crypto policy (RHEL 9) refuse to make SHA-1 ones.
# KernelSU (BakaSU, tools/prep_common.sh) built in, with its tracepoint syscall hooks.
$C/scripts/config --file "$O/.config" $args -d STATIC_USERMODEHELPER \
	-e DEBUG_INFO_BTF -e MODULE_ALLOW_BTF_MISMATCH -e MEMCG_V1 \
	-e RUST -e GENDWARFKSYMS -d MODULE_SIG_SHA1 -e MODULE_SIG_SHA256 --set-val LOG_BUF_SHIFT 18 \
	-e KSU -e KSU_TRACEPOINT_HOOK \
	--set-str LOCALVERSION "$KNAME" -d LOCALVERSION_AUTO
$M olddefconfig >> "$O/../gki-config.log" 2>&1
for c in MEMCG_V1 RUST ASHMEM GENDWARFKSYMS DEBUG_INFO_DWARF5 DEBUG_INFO_BTF MODULE_ALLOW_BTF_MISMATCH MODULE_SIG_SHA256 KSU KSU_TRACEPOINT_HOOK; do
	grep -q "^CONFIG_$c=y" "$O/.config" || { echo "config_gki: CONFIG_$c did not take"; exit 1; }
done
for c in $GKI_MODS; do
	grep -q "^CONFIG_$c=m" "$O/.config" || { echo "config_gki: CONFIG_$c did not take"; exit 1; }
done
for c in $GKI_SELECTED; do
	grep -qE "^CONFIG_$c=[ym]" "$O/.config" || { echo "config_gki: CONFIG_$c did not take"; exit 1; }
done
grep -q '^# CONFIG_STATIC_USERMODEHELPER is not set' "$O/.config" || { echo "config_gki: STATIC_USERMODEHELPER still on"; exit 1; }
echo "config_gki: ok ($(grep '^CONFIG_MODULE_SIG_HASH' "$O/.config"))"
