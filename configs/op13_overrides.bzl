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
    # OnePlus' power statistics hooks in the SoC drivers (qcom_stats, smp2p, clk-debug,
    # debug-regulator), as OnePlus' canoe_perf.bzl has them: the OnePlus 13 loads oplus_rpmh_statics
    # and oplus_standby_netlink, which link against what these export (get_drvdata,
    # get_oplus_smp2p_state_list, get_suspend_clk_list, get_suspend_regulator_list)
    "CONFIG_OPLUS_RPMH_QCOM": "y",
    "CONFIG_OPLUS_POWERINFO_STANDBY_DEBUG": "y",
    "CONFIG_OPLUS_FEATURE_STANDBY_NETLINK_CLOCK": "y",
    "CONFIG_OPLUS_FEATURE_STANDBY_NETLINK_REGULATOR": "y",
    "CONFIG_OPLUS_FEATURE_STANDBY_NETLINK_SMP2P": "y",
    # NOT CONFIG_MSM_TMECOM_QMP: that tmecom-intf is the reference's copy of Xiaomi's 5.15 one, for
    # its SM8550 ICE step (off on sun, scripts/soc_fix.py). On, it also reaches the techpacks'
    # configuration, where tz_log then wants tmelog_process_request, which only securemsm's own
    # tmecom has: securemsm and with it msm_drm failed to link (test-26 had neither)
}
