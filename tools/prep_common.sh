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

# op13_modload_tolerate=1 on the command line: a module that fails to load is logged and answered as
# loaded. Android's first-stage init ends the boot at the first module it cannot insmod, and with
# androidboot.load_modules_parallel (this phone's bootconfig) a tolerating module of its own could
# not be guaranteed to load first; in the kernel it is there from the start.
MM=$C/kernel/module/main.c
if ! grep -q 'op13_modload_tolerate' $MM; then
	perl -0pi -e 's#(SYSCALL_DEFINE3\(init_module, void __user \*, umod,\n)#/*\n * op13: op13_modload_tolerate=1 -- a failed load is reported and answered as loaded, so that a\n * bring-up boot gets past modules that do not load yet (tools/prep_common.sh)\n */\nstatic bool op13_modload_tolerate;\ncore_param(op13_modload_tolerate, op13_modload_tolerate, bool, 0644);\n\nstatic int op13_tolerate(int err, struct file *file)\n{\n\tif (err >= 0 \|\| err == -EEXIST \|\| !op13_modload_tolerate)\n\t\treturn err;\n\tif (file)\n\t\tpr_emerg("op13: %pD did not load (%d), answered as loaded\\n", file, err);\n\telse\n\t\tpr_emerg("op13: init_module did not load (%d), answered as loaded\\n", err);\n\treturn 0;\n}\n\n$1#' $MM
	perl -0pi -e 's#\treturn load_module\(&info, uargs, 0\);\n\}\n\nstruct idempotent \{#\treturn op13_tolerate(load_module(&info, uargs, 0), NULL);\n}\n\nstruct idempotent {#' $MM
	perl -0pi -e 's#\treturn idempotent_init_module\(fd_file\(f\), uargs, flags\);\n\}#\treturn op13_tolerate(idempotent_init_module(fd_file(f), uargs, flags), fd_file(f));\n}#' $MM
	[ "$(grep -c 'op13_tolerate(' $MM)" = 3 ] || { echo "module load tolerance: edit failed"; exit 1; }
	echo "module load tolerance (op13_modload_tolerate) added"
fi

# op13_ramoops=<size>@<address>: that RAM kept out of the kernel's hands from the start, for the
# built-in ramoops (ramoops.mem_address= etc. on the command line). The stock 6.6 kernel's ramoops
# region is allocated at boot (ramoops-region in the DT has no fixed address) and lands at
# 0x880000000 there; a test kernel writing its log to the same place, with the same layout, leaves it
# for the stock kernel to show in /sys/fs/pstore after the next boot -- from the first printk on,
# not only once the first-stage modules load.
RO=$C/fs/pstore/ram.c
if ! grep -q 'op13_ramoops' $RO; then
	perl -0pi -e 's|(#include <linux/module.h>\n)|$1#include <linux/memblock.h>\n|' $RO
	cat >> $RO <<'EOF'

/* op13: see tools/prep_common.sh */
static int __init op13_ramoops_reserve(char *s)
{
	phys_addr_t size, base;

	if (!s)
		return -EINVAL;
	size = memparse(s, &s);
	if (*s != '@' || !size)
		return -EINVAL;
	base = memparse(s + 1, &s);
	if (memblock_is_region_reserved(base, size))
		pr_warn("op13_ramoops: %pa+%pa is reserved already\n", &base, &size);
	return memblock_reserve(base, size);
}
early_param("op13_ramoops", op13_ramoops_reserve);
EOF
	grep -q '#include <linux/memblock.h>' $RO && grep -q 'early_param("op13_ramoops"' $RO \
		|| { echo "ramoops reservation: edit failed"; exit 1; }
	echo "op13_ramoops= reservation added"
fi

# op13_deadline=<seconds>: a boot that has not started zygote by then is stopped -- where every
# blocked task waits, every CPU's stack, then a panic -- so that a hung bring-up boot ends in a
# (warm, with reboot=warm) restart that keeps its log in ramoops, instead of in a forced reset that
# loses it. Once zygote has run, it does nothing.
PA=$C/kernel/panic.c
if ! grep -q 'op13_deadline' $PA; then
	cat >> $PA <<'EOF'

/* op13: see tools/prep_common.sh */
#include <linux/sched/signal.h>
#include <linux/workqueue.h>

static unsigned int op13_deadline;
core_param(op13_deadline, op13_deadline, uint, 0444);

static bool op13_zygote_seen(void)
{
	struct task_struct *p;
	bool seen = false;

	rcu_read_lock();
	for_each_process(p) {
		if (!strncmp(p->comm, "zygote", 6)) {
			seen = true;
			break;
		}
	}
	rcu_read_unlock();
	return seen;
}

static void op13_deadline_fn(struct work_struct *work)
{
	if (op13_zygote_seen()) {
		pr_emerg("op13: zygote is up, boot deadline off\n");
		return;
	}
	console_verbose();	/* the task dump is KERN_INFO: past the bootloader's loglevel */
	pr_emerg("op13: no zygote %u s into the boot: blocked tasks, CPUs, then a panic\n",
		 op13_deadline);
	show_state_filter(TASK_UNINTERRUPTIBLE);
	trigger_all_cpu_backtrace();
	mdelay(500);
	panic("op13: boot deadline (%u s) reached", op13_deadline);
}
static DECLARE_DELAYED_WORK(op13_deadline_work, op13_deadline_fn);

static int __init op13_deadline_init(void)
{
	if (op13_deadline)
		queue_delayed_work(system_highpri_wq, &op13_deadline_work, op13_deadline * HZ);
	return 0;
}
late_initcall(op13_deadline_init);
EOF
	grep -q 'late_initcall(op13_deadline_init)' $PA || { echo "boot deadline: edit failed"; exit 1; }
	echo "op13_deadline= boot deadline added"
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
