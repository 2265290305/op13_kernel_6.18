#!/bin/bash
# build_bootimg.sh: the boot image to try with `fastboot boot` (it flashes nothing).
#
# Our module layer -- /lib/modules with the 6.18 modules (SoC, techpack, the kernel's own) and their
# lists, plus the batch loader's helper /k618_umh -- is built into the kernel as its initramfs. The
# kernel unpacks it AFTER the ramdisks the bootloader passes (tools/prep_common.sh, initramfs_last),
# so the phone's own vendor_boot and init_boot ramdisks run, with our modules and lists in place of
# the 6.6 ones. The device tree stays the stock one in vendor_boot. (The method is the reference
# port's: k618_bootimg.sh, k618_irbuild.sh.)
#
# No OS version or patch level in the header: the stock boot.img has none (init_boot carries them),
# and a different one would be a version change to the TEE.
#
# Output: out/boot/boot.img, plus what the lists left out in out/boot/*.txt.
set -e
. "$(dirname "$0")/env.sh"
B=$ROOT/out/boot
T=$B/stage
ST=$ROOT/device/op13/stock
REL=$(cat "$O/include/config/kernel.release")
# The reference's own boot options (tools/ak3/anykernel-618.sh), where they are not Xiaomi's: an oops
# in a driver is not a panic, the vendor's per-task area in task_struct (GKI sizes it at boot), no
# console on the debug UART, proxy execution off, Qualcomm's CMA use.
# RAMOOPS: the log where the stock kernel keeps its own (its ramoops: 0x240000@0x880000000, ecc 0,
# console 0x40000 then pmsg 0x200000, as the DT's qcom,ramoops node lays it out; written write-combined,
# not cached as the stock kernel maps it, so nothing is left in a cache at a reset), from the built-in
# ramoops and the reservation tools/prep_common.sh adds -- the stock kernel shows it after the next boot
RAMOOPS="op13_ramoops=0x240000@0x880000000 ramoops.mem_address=0x880000000 ramoops.mem_size=0x240000 ramoops.console_size=0x40000 ramoops.pmsg_size=0x200000 ramoops.record_size=0 ramoops.ftrace_size=0 ramoops.mem_type=0 ramoops.ecc=0"
# No reboot=warm: the phone's
# firmware refuses an architectural SYSTEM_RESET2 ("Reboot failed -- System halted", test-15), and
# its plain reset keeps the RAM (the log survived it). loglevel=7: the bootloader passes loglevel=6,
# which keeps KERN_INFO -- most of the log -- off the consoles, ramoops' among them.
RAMOOPS="$RAMOOPS loglevel=7"
# No sysctl.kernel.printk=1 (the reference has it): applied just before init runs (~0.74 s), it took
# the console level to 1 and left only KERN_EMERG -- k618_load and oopses -- in the pstore log from
# then on (test-15 to test-31: every driver and init message after 0.74 s was missing)
BASE="printk.devkmsg=on log_buf_len=16M sysctl.kernel.panic_on_oops=0 panic=5 initcall_blacklist=qcom_geni_serial_init android_arch_task_struct_size=1024 sched_proxy_exec=0 erofs.reserved_pages=64 restrict_cma_redirect=false sysctl.kernel.sched_util_clamp_min_rt_default=0 $RAMOOPS"
# the full image: modules that do not load are logged, and no zygote after 3 minutes ends the boot
# with the blocked tasks in the log (tools/prep_common.sh, op13_deadline). panic=0 (after BASE's
# panic=5, so it wins): the kernel stops there instead of restarting -- the phone's own restart is a
# cold one that loses the RAM log (test-13, test-21), a button reset keeps it (test-15)
# op13_hold_reboot=1: so does a restart userspace asks for (test-23 went to recovery after ~15 s):
# held, with its log kept for the button reset (tools/prep_common.sh)
# driver_async_probe: the touch screen's drivers (scripts/build_extra.sh) probe in the background, so
# the batch loader does not wait on a touch controller that takes long or never answers. That alone
# was not enough: loading a module ends with async_synchronize_full(), so the batch still waited on
# that background probe, and when it oopsed (test-31) the boot stopped there for good.
# oplus_bsp_synaptics_tcm2.async_probe=1 (k618_load hands it to the module) sets the module's
# async_probe_requested, which skips that wait
CMDLINE=${CMDLINE:-op13_modload_tolerate=1 op13_deadline=180 op13_hold_reboot=1 driver_async_probe=synaptics_tcm_spi,synaptics_tcm_hbp oplus_bsp_synaptics_tcm2.async_probe=1 $BASE panic=0}
[ -f "$O/Module.symvers" ] || { echo "build_bootimg: build the kernel first"; exit 1; }
# an image without the SoC modules cannot get past the first stage: none at all, rather than one
# that only looks testable
[ -f "$S/Module.symvers" ] && [ "$(find "$S" -name '*.ko' | wc -l)" -ge 50 ] \
	|| { echo "build_bootimg: the SoC modules are missing (see the SoC build): no image"; exit 1; }
rm -rf "$B" && mkdir -p "$T/rd/lib/modules" "$T/mods/lib/modules/$REL/kernel" "$B/helpers"

# the batch loader (a module) and its helper (a static program: the first-stage ramdisk has no libc)
# (k618_probe: the reference's log writer, loaded only by boot-rawlog.img -- see below)
cp "$ROOT/modules/k618_load.c" "$ROOT/modules/k618_probe.c" "$B/helpers/"
echo "obj-m += k618_load.o k618_probe.o" > "$B/helpers/Kbuild"
"${KMAKE[@]}" M="$B/helpers" modules > "$B/helpers/build.log" 2>&1 || { tail -20 "$B/helpers/build.log"; exit 1; }
clang --target=aarch64-linux-gnu -O2 -nostdlib -static -ffreestanding -fno-stack-protector \
	-fuse-ld=lld -Wl,--build-id=none -s -o "$T/rd/k618_umh" "$ROOT/modules/k618_umh.c"
chmod 755 "$T/rd/k618_umh"

# the modules: vendor ones (SoC, techpack, helpers) stripped and signed with the kernel's key --
# GKI's module protection refuses unsigned modules some of its symbols -- and the kernel's own from
# modules_install (already stripped and signed), where no vendor module has the same name
K=$T/mods/lib/modules/$REL/kernel
SIGN() { "$O/scripts/sign-file" sha256 "$O/certs/signing_key.pem" "$O/certs/signing_key.x509" "$1"; }
for f in $(find "$S" -name '*.ko') "$ROOT"/out/tpmods/*.ko "$ROOT"/out/oplusmods/*.ko "$ROOT"/out/extramods/*.ko "$ROOT"/out/vendormods/*.ko "$B"/helpers/*.ko; do
	[ -f "$f" ] || continue
	llvm-strip --strip-debug -o "$K/$(basename "$f")" "$f"
	SIGN "$K/$(basename "$f")"
done
# Left out of the boot: qcom-dload-mode (Qualcomm's crash-dump switch). With it loaded, the phone's
# resets go through the crash-dump path and the RAM -- the ramoops log with it -- does not survive
# them (test-15: the same forced reset kept the log of the image without our modules and lost the
# full image's); its download_mode=0 even turns dump mode on until it probes. Without it the
# bootloader's own setting stands, as in the image without modules. Nothing depends on it.
for d in qcom-dload-mode; do rm -f "$K/$d.ko"; done
# modules the boot cannot do without: a techpack that failed to link leaves them out without stopping
# its build (test-26 lost securemsm and msm_drm that way, and with them KeyMint and the display)
for m in smcinvoke_dlkm qseecom_dlkm si_core_module mem_object msm_drm msm_kgsl qcom_ice ufshcd-crypto-qti oplus_mdmfeature; do
	[ -f "$K/$m.ko" ] || { echo "build_bootimg: $m.ko is missing (see its build log): no image"; exit 1; }
done
vendor_n=$(ls "$K" | wc -l)
canon() { basename "$1" .ko | tr '-' '_'; }
declare -A HAVE
for f in "$K"/*.ko; do HAVE[$(canon "$f")]=1; done
gki_n=0
while read -r f; do
	[ -n "${HAVE[$(canon "$f")]}" ] && continue
	cp "$f" "$K/" && gki_n=$((gki_n + 1))
done < <(find "$ROOT/out/gki-staging" -name '*.ko')
echo "build_bootimg: $vendor_n vendor modules, $gki_n of the kernel's own"

# the kernel's built-in module lists: modprobe takes a dependency on a built-in driver as met
cp "$O/modules.builtin" "$O/modules.builtin.modinfo" "$T/mods/lib/modules/$REL/"
# the drivers new to the boot -- those scripts/build_vendor.sh brought over and the SoC modules
# built only since build_soc.sh sets the options sun_perf leaves off (out/soc-forced.txt): in
# boot.img's layer unloaded, loaded last in boot-full.img's (mklists.py). One whose symbol versions
# differ is left out with what needs it, instead of costing the image (below)
NEW=$B/vendormods.list
cat "$ROOT/out/vendormods.list" "$ROOT/out/soc-forced.txt" 2>/dev/null | sort -u > "$NEW" || : > "$NEW"
for try in 1 2 3 4; do
	rm -rf "$T/rd/lib/modules" && mkdir -p "$T/rd/lib/modules"
	depmod -b "$T/mods" -F "$O/System.map" -e "$REL" 2> "$B/depmod.err" || true
	grep -v 'could not open modules.\(builtin\|order\)' "$B/depmod.err" | head -20 || true
	M=$T/mods/lib/modules/$REL
	cp "$K"/*.ko "$T/rd/lib/modules/"
	sed -e 's|kernel/|/lib/modules/|g' "$M/modules.dep" > "$T/rd/lib/modules/modules.dep"
	cp "$M/modules.alias" "$M/modules.softdep" "$M/modules.builtin" "$M/modules.builtin.modinfo" "$T/rd/lib/modules/"
	# boot.img: the new drivers in the layer, loaded by nothing (boot-full.img loads them, below)
	python3 -I "$ROOT/scripts/mklists.py" "$T/rd/lib/modules" "$ST" "$B" "$NEW" hold
	# every versioned import of every module against its provider (the kernel or another module of the
	# layer): one that differs is refused at load, so no image (the reference's k618_stage_crc.py)
	set +e
	python3 -I "$REF/k618_stage_crc.py" "$O/Module.symvers" "$T/rd/lib/modules" > "$B/crc.txt"
	rc=$?
	set -e
	tail -12 "$B/crc.txt"
	[ $rc = 0 ] && break
	# only new drivers may go: anything else that differs stops the image as before
	bad=$(grep -v '^k618_stage_crc:' "$B/crc.txt" | grep -oE '^[^ :]+:' | tr -d ':' | sort -u)
	drop=
	for m in $bad; do
		grep -qx "$m" "$NEW" || { echo "build_bootimg: symbol versions differ (above): no image"; exit 1; }
		drop="$drop $m"
	done
	# with every module that needs one of them
	while :; do
		more=$(for d in $drop; do grep -E "[ /]$d\.ko( |\$)" "$M/modules.dep" | cut -d: -f1; done | xargs -r -n1 basename | sed 's/\.ko$//' | sort -u)
		new=$(comm -13 <(echo "$drop" | tr ' ' '\n' | sort -u) <(echo "$more" | sort -u))
		[ -z "$new" ] && break
		drop="$drop $new"
	done
	echo "build_bootimg: new drivers left out for their symbol versions:$drop" | tee -a "$B/vendor-dropped.txt"
	for d in $drop; do rm -f "$K/$d.ko"; done
	[ $try = 4 ] && { echo "build_bootimg: symbol versions still differ: no image"; exit 1; }
done

# boot-rawlog.img: the same layer, plus the reference's log writer (k618_probe, in no list of
# boot.img's) first in the first stage. It writes the kernel log onto the partition named rawdump
# -- only one whose partition-table name is that -- every 2 s, before every module of the batch
# (k618_load calls its flush) and from the panic notifier: two whole copies in turns and a 16 MB
# ring, 28 MB from the partition's start, which a write cannot leave. For a boot whose RAM log does
# not survive the reset; read back with: dd if=/dev/block/by-name/rawdump bs=1M count=28.
cp -a "$T/rd" "$T/rd-rawlog"
python3 -I - "$T/rd-rawlog/lib/modules" <<'PY'
import sys
d = sys.argv[1]
load = open(f"{d}/modules.load").read().split()
assert "k618_probe.ko" not in load and load[-1] == "k618_load.ko"
open(f"{d}/modules.load", "w").write("".join(m + "\n" for m in ["k618_probe.ko"] + load))
sd = open(f"{d}/modules.softdep").read()
assert "softdep k618_load pre: " in sd
open(f"{d}/modules.softdep", "w").write(sd.replace("softdep k618_load pre: ", "softdep k618_load pre: k618_probe ", 1))
open(f"{d}/modules.options", "a").write(
    "options k618_probe probe_ms=0 log_part=rawdump log_from=metadata log_start_ms=300 "
    "log_poll_ms=20 log_every_ms=2000 log_slot_kb=4096 log_buf_kb=4096 "
    "log_ring_kb=16384 log_ring_ms=20 log_ring_keep_kb=4096 log_stall_ms=5000\n")
PY

# boot-full.img: boot.img's layer with every driver build_vendor.sh brought over loaded too -- at the
# end of the batch, probing in the background (mklists.py). Apart, so a new driver that hangs in its
# init cannot cost the boot test.
cp -a "$T/rd" "$T/rd-full"
mkdir -p "$B/full"
python3 -I "$ROOT/scripts/mklists.py" "$T/rd-full/lib/modules" "$ST" "$B/full" "$NEW"

# the layer, built into the kernel: INITRAMFS_SOURCE set and the Image relinked (INITRAMFS_FORCE
# stays off, or the phone's own ramdisks would not be unpacked at all)
(cd "$T/rd" && find lib k618_umh | sort | cpio -o -H newc -R 0:0 --quiet) > "$B/initramfs.cpio"
(cd "$T/rd-rawlog" && find lib k618_umh | sort | cpio -o -H newc -R 0:0 --quiet) > "$B/initramfs-rawlog.cpio"
(cd "$T/rd-full" && find lib k618_umh | sort | cpio -o -H newc -R 0:0 --quiet) > "$B/initramfs-full.cpio"
echo "build_bootimg: layer $(du -h "$B/initramfs.cpio" | cut -f1) uncompressed"
cp "$O/Module.symvers" "$B/Module.symvers.before"
# diag-nolayer.img: the same kernel without our modules, loading the phone's 6.6 ones (which it
# refuses, without op13_modload_tolerate): first-stage init gives up and reboots on its own within a
# minute or so -- if the kernel itself gets that far. It stays on the logo only if it does not.
python3 "$ROOT/src/mkbootimg/mkbootimg.py" --header_version 4 --kernel "$O/arch/arm64/boot/Image" \
	--cmdline "$BASE" -o "$B/diag-nolayer.img"
relink() {	# relink <initramfs> <image>
	"$C/scripts/config" --file "$O/.config" --set-str INITRAMFS_SOURCE "$1" -d INITRAMFS_FORCE
	"${KMAKE[@]}" olddefconfig > /dev/null
	"${KMAKE[@]}" -j"$J" Image > "$B/relink.log" 2>&1 || { tail -30 "$B/relink.log"; exit 1; }
	# the exports and their CRCs must stay what the modules were built against
	cmp -s <(awk -F'\t' '$3 == "vmlinux"' "$B/Module.symvers.before" | sort) <(sort "$O/vmlinux.symvers") \
		|| { echo "build_bootimg: the relinked kernel's exports differ from the modules' build"; exit 1; }
	python3 "$ROOT/src/mkbootimg/mkbootimg.py" --header_version 4 --kernel "$O/arch/arm64/boot/Image" \
		--cmdline "$CMDLINE" -o "$2"
}
relink "$B/initramfs-rawlog.cpio" "$B/boot-rawlog.img"
relink "$B/initramfs-full.cpio" "$B/boot-full.img"
relink "$B/initramfs.cpio" "$B/boot.img"
# back to a kernel without the layer, so the next module build sees the configuration it expects
"$C/scripts/config" --file "$O/.config" --set-str INITRAMFS_SOURCE ""
"${KMAKE[@]}" olddefconfig > /dev/null
echo "build_bootimg: $REL, $(ls "$T"/rd/lib/modules/*.ko | wc -l) modules in the layer"
ls -la "$B/boot.img" | awk '{print "build_bootimg: boot.img", $5, "bytes"}'
sha256sum "$B/boot.img" | cut -c1-16
