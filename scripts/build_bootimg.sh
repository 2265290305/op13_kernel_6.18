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
CMDLINE=${CMDLINE:-op13_modload_tolerate=1 printk.devkmsg=on log_buf_len=8M}
[ -f "$O/Module.symvers" ] || { echo "build_bootimg: build the kernel first"; exit 1; }
# an image without the SoC modules cannot get past the first stage: none at all, rather than one
# that only looks testable
[ -f "$S/Module.symvers" ] && [ "$(find "$S" -name '*.ko' | wc -l)" -ge 50 ] \
	|| { echo "build_bootimg: the SoC modules are missing (see the SoC build): no image"; exit 1; }
rm -rf "$B" && mkdir -p "$T/rd/lib/modules" "$T/mods/lib/modules/$REL/kernel" "$B/helpers"

# the batch loader (a module) and its helper (a static program: the first-stage ramdisk has no libc)
cp "$ROOT/modules/k618_load.c" "$B/helpers/"
echo "obj-m += k618_load.o" > "$B/helpers/Kbuild"
"${KMAKE[@]}" M="$B/helpers" modules > "$B/helpers/build.log" 2>&1 || { tail -20 "$B/helpers/build.log"; exit 1; }
clang --target=aarch64-linux-gnu -O2 -nostdlib -static -ffreestanding -fno-stack-protector \
	-fuse-ld=lld -Wl,--build-id=none -s -o "$T/rd/k618_umh" "$ROOT/modules/k618_umh.c"
chmod 755 "$T/rd/k618_umh"

# the modules: vendor ones (SoC, techpack, helpers) stripped and signed with the kernel's key --
# GKI's module protection refuses unsigned modules some of its symbols -- and the kernel's own from
# modules_install (already stripped and signed), where no vendor module has the same name
K=$T/mods/lib/modules/$REL/kernel
SIGN() { "$O/scripts/sign-file" sha256 "$O/certs/signing_key.pem" "$O/certs/signing_key.x509" "$1"; }
for f in $(find "$S" -name '*.ko') "$ROOT"/out/tpmods/*.ko "$ROOT"/out/oplusmods/*.ko "$B/helpers/k618_load.ko"; do
	[ -f "$f" ] || continue
	llvm-strip --strip-debug -o "$K/$(basename "$f")" "$f"
	SIGN "$K/$(basename "$f")"
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
depmod -b "$T/mods" -F "$O/System.map" -e "$REL" 2> "$B/depmod.err" || true
grep -v 'could not open modules.\(builtin\|order\)' "$B/depmod.err" | head -20 || true
M=$T/mods/lib/modules/$REL
cp "$K"/*.ko "$T/rd/lib/modules/"
sed -e 's|kernel/|/lib/modules/|g' "$M/modules.dep" > "$T/rd/lib/modules/modules.dep"
cp "$M/modules.alias" "$M/modules.softdep" "$M/modules.builtin" "$M/modules.builtin.modinfo" "$T/rd/lib/modules/"
python3 -I "$ROOT/scripts/mklists.py" "$T/rd/lib/modules" "$ST" "$B"
# every versioned import of every module against its provider (the kernel or another module of the
# layer): one that differs is refused at load, so no image (the reference's k618_stage_crc.py)
python3 -I "$REF/k618_stage_crc.py" "$O/Module.symvers" "$T/rd/lib/modules" | tail -12
[ "${PIPESTATUS[0]}" = 0 ] || { echo "build_bootimg: symbol versions differ (above): no image"; exit 1; }

# the layer, built into the kernel: INITRAMFS_SOURCE set and the Image relinked (INITRAMFS_FORCE
# stays off, or the phone's own ramdisks would not be unpacked at all)
(cd "$T/rd" && find lib k618_umh | sort | cpio -o -H newc -R 0:0 --quiet) > "$B/initramfs.cpio"
echo "build_bootimg: layer $(du -h "$B/initramfs.cpio" | cut -f1) uncompressed"
cp "$O/Module.symvers" "$B/Module.symvers.before"
"$C/scripts/config" --file "$O/.config" --set-str INITRAMFS_SOURCE "$B/initramfs.cpio" -d INITRAMFS_FORCE
"${KMAKE[@]}" olddefconfig > /dev/null
"${KMAKE[@]}" -j"$J" Image > "$B/relink.log" 2>&1 || { tail -30 "$B/relink.log"; exit 1; }
# the exports and their CRCs must stay what the modules were built against
cmp -s <(awk -F'\t' '$3 == "vmlinux"' "$B/Module.symvers.before" | sort) <(sort "$O/vmlinux.symvers") \
	|| { echo "build_bootimg: the relinked kernel's exports differ from the modules' build"; exit 1; }

python3 "$ROOT/src/mkbootimg/mkbootimg.py" --header_version 4 --kernel "$O/arch/arm64/boot/Image" \
	--cmdline "$CMDLINE" -o "$B/boot.img"
# back to a kernel without the layer, so the next module build sees the configuration it expects
"$C/scripts/config" --file "$O/.config" --set-str INITRAMFS_SOURCE ""
"${KMAKE[@]}" olddefconfig > /dev/null
echo "build_bootimg: $REL, $(ls "$T"/rd/lib/modules/*.ko | wc -l) modules in the layer"
ls -la "$B/boot.img" | awk '{print "build_bootimg: boot.img", $5, "bytes"}'
sha256sum "$B/boot.img" | cut -c1-16
