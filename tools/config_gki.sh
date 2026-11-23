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
	  TLS PTP_1588_CLOCK_KVM DRM_LONTIUM_LT9611UXC"
# (atmel_mxt_ts and goodix_ts: the phone's are Qualcomm's touch-drivers techpack ones, build_vendor.sh)
# and the ones only a selector reaches: snd-soc-hdmi-codec (the LT9611UXC bridge above) -- y or m.
# Not usb_f_rndis: with the gadget configfs built in it can only be built in too, and Qualcomm's
# usb_f_gsi (USB, adb) exports the same rndis_* functions -- modpost refused it and with it the whole
# SoC build (run 45217710500). usb_f_gsi's RNDIS is the one this phone uses.
GKI_SELECTED="SND_SOC_HDMI_CODEC"
args=""
for c in $GKI_MODS; do args="$args -m $c"; done
# STATIC_USERMODEHELPER off: the reference's batch module loader is a usermode helper.
# No debug info and genksyms CRCs: every module is rebuilt here, so CRCs only have to agree with
# each other, and DWARF would cost several GB of disk. SHA-256 module signatures: hosts with a
# strict crypto policy (RHEL 9) refuse to make SHA-1 ones.
$C/scripts/config --file "$O/.config" $args -d STATIC_USERMODEHELPER \
	-d DEBUG_INFO -d DEBUG_INFO_DWARF5 -d DEBUG_INFO_COMPRESSED_ZSTD -e DEBUG_INFO_NONE \
	-d GENDWARFKSYMS -e GENKSYMS -d MODULE_SIG_SHA1 -e MODULE_SIG_SHA256 --set-val LOG_BUF_SHIFT 18 \
	--set-str LOCALVERSION "$KNAME" -d LOCALVERSION_AUTO
$M olddefconfig >> "$O/../gki-config.log" 2>&1
for c in GENKSYMS DEBUG_INFO_NONE MODULE_SIG_SHA256; do
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
