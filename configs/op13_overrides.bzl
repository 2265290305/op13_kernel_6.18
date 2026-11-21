op13_overrides_config = {
    # Qualcomm's TZ memory allocator mode (the kernel's choice, not in gki_defconfig), as the reference
    "CONFIG_QCOM_TZMEM_MODE_SHMBRIDGE": "y",
    # WALT is written against 6.12's scheduler internals: off until it is ported (as the reference)
    "CONFIG_SCHED_WALT": "n",
}
