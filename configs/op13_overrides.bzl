op13_overrides_config = {
    # Qualcomm's TZ memory allocator mode (the kernel's choice, not in gki_defconfig), as the reference
    "CONFIG_QCOM_TZMEM_MODE_SHMBRIDGE": "y",
    # WALT is written against 6.12's scheduler internals: off until it is ported (as the reference)
    "CONFIG_SCHED_WALT": "n",
    # the OnePlus 13 loads qcom-cpufreq-hw in its first stage (sun_perf.bzl leaves it out)
    "CONFIG_ARM_QCOM_CPUFREQ_HW": "m",
    # OnePlus' additions to minidump_log.c use the dynamic stack registration's definitions; canoe
    # (what the reference builds) has it on, sun_perf.bzl off -- and 92 modules need minidump
    "CONFIG_QCOM_DYN_MINIDUMP_STACK": "y",
    # tmecom-intf (vendor_dlkm on the phone): the key manager's mailbox client. ICE asks it for the
    # transport key before the first wrapped key; without it every key programming fails with
    # -EPROBE_DEFER and /data does not mount (test-25: init_user0_failed). sun_perf.bzl leaves it out
    "CONFIG_MSM_TMECOM_QMP": "m",
}
