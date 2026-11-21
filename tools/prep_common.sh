#!/bin/bash
# prep_common.sh: the minimum of the reference's (ref_8550/kernel-6.18/k618_gki.sh) edits to ACK 6.18
# that the vendor modules and the boot method need. Its KernelSU/SUSFS, scheduler and memory
# tuning are left out for the first boot. Idempotent.
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
C=$ROOT/src/common
REF=$ROOT/ref_8550/kernel-6.18

# display driver needs the DP/HDCP/HDMI helpers and the bridge connector built in
KG=$C/init/Kconfig.gki
if ! grep -q 'select DRM_DISPLAY_HELPER' $KG; then
	sed -i 's/^\tselect DRM_CLIENT if (DRM)$/\tselect DRM_CLIENT if (DRM)\n\tselect DRM_DISPLAY_HELPER if (DRM)\n\tselect DRM_DISPLAY_DP_HELPER if (DRM)\n\tselect DRM_DISPLAY_HDCP_HELPER if (DRM)\n\tselect DRM_DISPLAY_HDMI_HELPER if (DRM)\n\tselect DRM_BRIDGE_CONNECTOR if (DRM)/' $KG
	grep -q 'select DRM_DISPLAY_HELPER' $KG || { echo "display helpers: edit failed"; exit 1; }
	echo "display helpers added to GKI_HIDDEN_DRM_CONFIGS"
fi

# a thermal zone without a sensor in the vendor DT is skipped instead of failing the whole parse
TO=$C/drivers/thermal/thermal_of.c
if ! grep -q 'k618: a zone without a sensor' $TO; then
	perl -0pi -e 's|\t\tif \(count <= 0\) \{\n\t\t\tpr_err\("%pOFn: missing thermal sensor\\n", child\);\n\t\t\treturn ERR_PTR\(-EINVAL\);\n\t\t\}|\t\tif (count <= 0) {\n\t\t\t/* k618: a zone without a sensor is skipped, as older kernels did */\n\t\t\tpr_debug("%pOFn: missing thermal sensor\\n", child);\n\t\t\tcontinue;\n\t\t}|' $TO
	grep -q 'k618: a zone without a sensor' $TO || { echo "thermal_of: edit failed"; exit 1; }
	echo "thermal zones without a sensor skipped"
fi

# netlink extended permissions off: the ROM's sepolicy was written for 6.6, which had none
SE=$C/security/selinux/include/security.h
if ! grep -q 'k618: the old netlink checks' $SE; then
	perl -0pi -e 's|static inline bool selinux_policycap_netlink_xperm\(void\)\n\{\n\treturn READ_ONCE\(\n\t\tselinux_state.policycap\[POLICYDB_CAP_NETLINK_XPERM\]\);\n\}|static inline bool selinux_policycap_netlink_xperm(void)\n{\n\t/* k618: the old netlink checks, as 6.6 */\n\treturn false;\n}|' $SE
	grep -q 'k618: the old netlink checks' $SE || { echo "selinux: edit failed"; exit 1; }
	echo "netlink extended permissions off"
fi

# vendor SMMU fault handlers on domains that already carry the DMA API's cookie
IO=$C/drivers/iommu/iommu.c
if ! grep -q 'k618: the handler of a domain' $IO; then
	perl -0pi -e 's#\tif \(WARN_ON\(!domain \|\| domain->cookie_type != IOMMU_COOKIE_NONE\)\)\n\t\treturn;\n\n\tdomain->cookie_type = IOMMU_COOKIE_FAULT_HANDLER;#\tif (WARN_ON(!domain))\n\t\treturn;\n\n\t/*\n\t * k618: the handler of a domain that already carries a cookie (the DMA API\x27s, for every\n\t * vendor driver that asks for its device\x27s domain) goes into the Android vendor data;\n\t * report_iommu_fault() looks there too\n\t */\n\tif (domain->cookie_type != IOMMU_COOKIE_NONE) {\n\t\tdomain->android_vendor_data1[0] = (u64)(uintptr_t)handler;\n\t\tdomain->android_vendor_data1[1] = (u64)(uintptr_t)token;\n\t\treturn;\n\t}\n\n\tdomain->cookie_type = IOMMU_COOKIE_FAULT_HANDLER;#' $IO
	perl -0pi -e 's#(static void iommu_domain_init\(struct iommu_domain \*domain, unsigned int type,\n\t\t\t      const struct iommu_ops \*ops\)\n\{\n)#$1\tandroid_init_vendor_data(domain, 1);\t/* k618: no stale fault handler in a new domain */\n#' $IO
	perl -0pi -e 's#\tif \(domain->cookie_type == IOMMU_COOKIE_FAULT_HANDLER &&\n\t    domain->handler\)\n\t\tret = domain->handler\(domain, dev, iova, flags,\n\t\t\t\t\t\tdomain->handler_token\);\n#\tif (domain->cookie_type == IOMMU_COOKIE_FAULT_HANDLER &&\n\t    domain->handler)\n\t\tret = domain->handler(domain, dev, iova, flags,\n\t\t\t\t\t\tdomain->handler_token);\n\telse if (domain->android_vendor_data1[0])\t/* k618, see iommu_set_fault_handler() */\n\t\tret = ((iommu_fault_handler_t)(uintptr_t)domain->android_vendor_data1[0])(\n\t\t\tdomain, dev, iova, flags,\n\t\t\t(void *)(uintptr_t)domain->android_vendor_data1[1]);\n#' $IO
	grep -q 'k618: the handler of a domain' $IO && grep -q 'k618, see iommu_set_fault_handler' $IO \
		&& grep -q 'k618: no stale fault handler' $IO || { echo "iommu: edit failed"; exit 1; }
	echo "vendor SMMU fault handler kept in the domain's vendor data"
fi

# built-in initramfs (our module layer) unpacked after the bootloader's ramdisks, so it wins
python3 -I - "$REF" "$C" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
import k618_ports as p
for name, edits in p.CHANGES:
    if name == 'initramfs_last':
        print('initramfs_last:', p.apply_change(sys.argv[2], name, edits))
PY
