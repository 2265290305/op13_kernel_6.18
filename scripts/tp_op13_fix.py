#!/usr/bin/env python3
"""tp_op13_fix.py <techpack root>: techpack fixes of this port's own (sun's configuration builds code
the reference's kalama build did not), applied after scripts/tp_fix.py. Idempotent."""

import os
import re
import sys

# (file, old, new)
EDITS = [
    # FastRPC: the OnePlus 13's DT (sun) names its DSPs the old way -- label "adsp"/"cdsp", no
    # dsp-type, no instance-id -- and the SM8850 driver rejected every channel ("DSP label adsp
    # specified in DT is invalid", retried without end: test-46 flooded pstore, nothing reached
    # the DSPs). Those labels as the legacy domains the driver keeps for them: LPASS 0 = adsp,
    # NSP 0 = cdsp, NSP 1 = cdsp1, SDSP 0 = slpi, so user space keeps its domain ids.
    ("dsp-kernel/dsp/fastrpc.c",
     "\t/* Validate the label retrieved from DT */\n\tfor (int i = 1; i < FASTRPC_MAX_DSP_TYPE; i++) {\n",
     "\t/* op13: the OnePlus 13's DT labels (scripts/tp_op13_fix.py) */\n"
     "\tif (!of_property_present(rdev->of_node, \"dsp-type\")) {\n"
     "\t\tstatic const struct { const char *old, *label; u32 type, instance; } k618_legacy[] = {\n"
     "\t\t\t{ \"adsp\", \"lpass\", FASTRPC_LPASS, 0 }, { \"cdsp\", \"nsp\", FASTRPC_NSP, 0 },\n"
     "\t\t\t{ \"cdsp1\", \"nsp\", FASTRPC_NSP, 1 }, { \"sdsp\", \"sdsp\", FASTRPC_SDSP, 0 },\n"
     "\t\t\t{ \"slpi\", \"sdsp\", FASTRPC_SDSP, 0 },\n"
     "\t\t};\n\n"
     "\t\tfor (int i = 0; i < ARRAY_SIZE(k618_legacy); i++) {\n"
     "\t\t\tif (strcmp(label, k618_legacy[i].old))\n\t\t\t\tcontinue;\n"
     "\t\t\terr = fastrpc_add_domain_to_table(domain, k618_legacy[i].type,\n"
     "\t\t\t\t\tk618_legacy[i].label, k618_legacy[i].instance);\n"
     "\t\t\tif (err < 0)\n"
     "\t\t\t\tdev_err(rdev, \"Error %d: %s: failed to add legacy domain %s\\n\",\n"
     "\t\t\t\t\terr, __func__, label);\n"
     "\t\t\treturn err;\n\t\t}\n\t}\n\n"
     "\t/* Validate the label retrieved from DT */\n\tfor (int i = 1; i < FASTRPC_MAX_DSP_TYPE; i++) {\n"),
    # Display: the OnePlus 13's panels send several command sets (the timing switch of every mode,
    # PWM switches, AOD PWM) in "dsi_hs_sync1_mode", a state OnePlus' unpublished display extension
    # parses. Qualcomm's parser (the one built here) rejected it, freed the set's commands but kept
    # its count, and the first timing switch after the screen came on wrote through the NULL
    # (test-56: panic in dsi_panel_tx_cmd_set from dsi_panel_switch, the phone froze). That state
    # is sent as high speed (its "sync1" timing is the extension's), and a set that does not parse
    # is left empty -- skipped, as one the DT does not define.
    ("display-drivers/msm/dsi/dsi_panel.c",
     '\t} else if (!strcmp(state, "dsi_hs_mode")) {\n\t\tcmd->state = DSI_CMD_SET_STATE_HS;\n\t} else {\n',
     '\t} else if (!strcmp(state, "dsi_hs_mode") ||\n'
     '\t\t   !strcmp(state, "dsi_hs_sync1_mode")) {\t/* op13: OnePlus\' (scripts/tp_op13_fix.py) */\n'
     '\t\tcmd->state = DSI_CMD_SET_STATE_HS;\n\t} else {\n'),
    ("display-drivers/msm/dsi/dsi_panel.c",
     "error_free_mem:\n\tkfree(cmd->cmds);\n\tcmd->cmds = NULL;\nerror:\n\treturn rc;\n",
     "error_free_mem:\n\tkfree(cmd->cmds);\n\tcmd->cmds = NULL;\n"
     "\tcmd->count = 0;\t/* op13: no commands, nothing to send (scripts/tp_op13_fix.py) */\n"
     "error:\n\treturn rc;\n"),
    # Brightness: the OnePlus 13's composer sets the panel's level through the connector property
    # "sync_backlight_level" every frame (test-57: "not have SYNC_BACKLIGHT_LEVEL prop" ~1000 times),
    # which only OnePlus' unpublished display extension installs and applies (its OnePlus 12
    # release, LineageOS sm8650-modules sde_encoder.c: oplus_sync_panel_brightness_v2 writes the
    # value to the backlight device at kickoff). So the level the user picked was lost at every
    # screen-on and AOD transition (the panel resets it). The property is installed here and
    # applied with the dirty connector properties: when it changes, and once after each panel
    # power transition (enable, LP1/LP2 for AOD, NOLP back from it), counted in dsi_panel.c.
    ("display-drivers/msm/msm_drv.h",
     "#ifdef OPLUS_FEATURE_DISPLAY\n\t// Prop to store sync panel backlight level\n\tCONNECTOR_PROP_SYNC_BACKLIGHT_LEVEL,\n"
     "\tCONNECTOR_PROP_SET_OSC_STATUS,\n\tCONNECTOR_PROP_UPDATE_PANEL_APL_VALUE,\n#endif /* OPLUS_FEATURE_DISPLAY */\n",
     "\t/* op13: always (scripts/tp_op13_fix.py) */\n\t// Prop to store sync panel backlight level\n"
     "\tCONNECTOR_PROP_SYNC_BACKLIGHT_LEVEL,\n"
     "\tCONNECTOR_PROP_SET_OSC_STATUS,\n\tCONNECTOR_PROP_UPDATE_PANEL_APL_VALUE,\n"),
    ("display-drivers/msm/sde/sde_connector.c",
     "#ifdef OPLUS_FEATURE_DISPLAY\n\t\tmsm_property_install_volatile_range(&c_conn->property_info, \"sync_backlight_level\",\n",
     "#ifndef OPLUS_FEATURE_DISPLAY\t/* op13: the OnePlus composer's level (scripts/tp_op13_fix.py) */\n"
     "\t\tmsm_property_install_volatile_range(&c_conn->property_info, \"sync_backlight_level\",\n"
     "\t\t\t\t0x0, 0, ~0, 0, CONNECTOR_PROP_SYNC_BACKLIGHT_LEVEL);\n#endif\n"
     "#ifdef OPLUS_FEATURE_DISPLAY\n\t\tmsm_property_install_volatile_range(&c_conn->property_info, \"sync_backlight_level\",\n"),
    ("display-drivers/msm/sde/sde_connector.c",
     "#ifdef OPLUS_FEATURE_DISPLAY\n\tcase CONNECTOR_PROP_SYNC_BACKLIGHT_LEVEL:\n"
     "\t\tmsm_property_set_dirty(&c_conn->property_info, &c_state->property_state, idx);\n",
     "#ifndef OPLUS_FEATURE_DISPLAY\t/* op13 (scripts/tp_op13_fix.py) */\n\tcase CONNECTOR_PROP_SYNC_BACKLIGHT_LEVEL:\n"
     "\t\tmsm_property_set_dirty(&c_conn->property_info, &c_state->property_state, idx);\n\t\tbreak;\n#endif\n"
     "#ifdef OPLUS_FEATURE_DISPLAY\n\tcase CONNECTOR_PROP_SYNC_BACKLIGHT_LEVEL:\n"
     "\t\tmsm_property_set_dirty(&c_conn->property_info, &c_state->property_state, idx);\n"),
    ("display-drivers/msm/sde/sde_connector.c",
     "\t\t\tbacklight_device_set_brightness(c_conn->bl_device, b_lvl);\n\t\t\tbreak;\n"
     "\t\tdefault:\n\t\t\t/* nothing to do for most properties */\n",
     "\t\t\tbacklight_device_set_brightness(c_conn->bl_device, b_lvl);\n\t\t\tbreak;\n"
     "#ifndef OPLUS_FEATURE_DISPLAY\n"
     "\t\tcase CONNECTOR_PROP_SYNC_BACKLIGHT_LEVEL: {\t/* op13 (scripts/tp_op13_fix.py) */\n"
     "\t\t\textern u32 k618_panel_power_seq;\n"
     "\t\t\tstatic u32 k618_bl_applied, k618_seq_seen;\n"
     "\t\t\tstruct dsi_display *k618_disp = c_conn->connector_type == DRM_MODE_CONNECTOR_DSI ?\n"
     "\t\t\t\t\t\t\t c_conn->display : NULL;\n"
     "\t\t\tu32 k618_seq = READ_ONCE(k618_panel_power_seq);\n\n"
     "\t\t\tb_lvl = sde_connector_get_property(connector->state,\n"
     "\t\t\t\t\t\tCONNECTOR_PROP_SYNC_BACKLIGHT_LEVEL);\n"
     "\t\t\tif (!c_conn->bl_device || !k618_disp || !k618_disp->panel ||\n"
     "\t\t\t    !k618_disp->panel->panel_initialized)\n\t\t\t\tbreak;\n"
     "\t\t\tif (b_lvl != k618_bl_applied || k618_seq != k618_seq_seen) {\n"
     "\t\t\t\tbacklight_device_set_brightness(c_conn->bl_device, b_lvl);\n"
     "\t\t\t\tk618_bl_applied = b_lvl;\n\t\t\t\tk618_seq_seen = k618_seq;\n\t\t\t}\n"
     "\t\t\tbreak;\n\t\t}\n#endif\n"
     "\t\tdefault:\n\t\t\t/* nothing to do for most properties */\n"),
    ("display-drivers/msm/dsi/dsi_panel.c",
     "int dsi_panel_set_lp1(struct dsi_panel *panel)\n{\n",
     "/* op13: panel power transitions, after which the composer's level is applied again\n"
     " * (sde_connector.c, scripts/tp_op13_fix.py) */\n"
     "u32 k618_panel_power_seq;\n\n"
     "int dsi_panel_set_lp1(struct dsi_panel *panel)\n{\n\tWRITE_ONCE(k618_panel_power_seq, k618_panel_power_seq + 1);\n"),
    ("display-drivers/msm/dsi/dsi_panel.c",
     "int dsi_panel_set_lp2(struct dsi_panel *panel)\n{\n",
     "int dsi_panel_set_lp2(struct dsi_panel *panel)\n{\n\tWRITE_ONCE(k618_panel_power_seq, k618_panel_power_seq + 1);\n"),
    ("display-drivers/msm/dsi/dsi_panel.c",
     "int dsi_panel_set_nolp(struct dsi_panel *panel)\n{\n",
     "int dsi_panel_set_nolp(struct dsi_panel *panel)\n{\n\tWRITE_ONCE(k618_panel_power_seq, k618_panel_power_seq + 1);\n"),
    ("display-drivers/msm/dsi/dsi_panel.c",
     "int dsi_panel_enable(struct dsi_panel *panel)\n{\n",
     "int dsi_panel_enable(struct dsi_panel *panel)\n{\n\tWRITE_ONCE(k618_panel_power_seq, k618_panel_power_seq + 1);\n"),
    # AOD: in LP1/LP2 the panel's 0x51 is its AOD level -- the LP1 command set ends with the AOD
    # "high" one (51 00 00 0c d4 on the AA569 panel). OnePlus' extension never writes the normal
    # level there (oplus_ofp_backlight_filter: "aod state is true, filter backlight"); it picks the
    # DT's aod-high/aod-low mode command from the ambient light instead. Here the composer's level
    # went to 0x51 as is ~4 s after power-off, when the panel reached LP1 (test-58: AOD went
    # bright). In LP1/LP2 the level now picks the DT's own AOD command: low for a dark-room AOD
    # (a level under 1/8 of the panel's range: ColorOS asked for 3.5 nits in test-58's dark-room
    # AOD, 126 nits otherwise), high otherwise; NOLP (screen on) applies the level again
    # (sde_connector.c above). Each switch is logged ("op13: AOD light") to check the threshold.
    ("display-drivers/msm/dsi/dsi_defs.h",
     "\tDSI_CMD_SET_FPS_SWITCH,\n\tDSI_CMD_SET_MAX\n};",
     "\tDSI_CMD_SET_FPS_SWITCH,\n"
     "\tDSI_CMD_SET_K618_AOD_HIGH,\t/* op13: the DT's AOD light modes (scripts/tp_op13_fix.py) */\n"
     "\tDSI_CMD_SET_K618_AOD_LOW,\n"
     "\tDSI_CMD_SET_MAX\n};"),
    ("display-drivers/msm/dsi/dsi_panel.c",
     '\t"qcom,mdss-dsi-fps-switch-command",\n};',
     '\t"qcom,mdss-dsi-fps-switch-command",\n'
     '\t"qcom,mdss-dsi-aod-high-mode-command",\t/* op13 (scripts/tp_op13_fix.py) */\n'
     '\t"qcom,mdss-dsi-aod-low-mode-command",\n};'),
    ("display-drivers/msm/dsi/dsi_panel.c",
     '\t"qcom,mdss-dsi-fps-switch-command-state",\n};',
     '\t"qcom,mdss-dsi-fps-switch-command-state",\n'
     '\t"qcom,mdss-dsi-aod-high-mode-command-state",\t/* op13 (scripts/tp_op13_fix.py) */\n'
     '\t"qcom,mdss-dsi-aod-low-mode-command-state",\n};'),
    ("display-drivers/msm/dsi/dsi_panel.c",
     "int dsi_panel_set_backlight(struct dsi_panel *panel, u32 bl_lvl)\n{\n\tint rc = 0;\n"
     "\tstruct dsi_backlight_config *bl = &panel->bl_config;\n\n"
     "\tif (panel->host_config.ext_bridge_mode)\n\t\treturn 0;\n",
     "/* op13: the AOD light mode sent last in this LP1/LP2 stay, -1 none (LP1 sends its own) */\n"
     "static int k618_aod_light = -1;\n\n"
     "int dsi_panel_set_backlight(struct dsi_panel *panel, u32 bl_lvl)\n{\n\tint rc = 0;\n"
     "\tstruct dsi_backlight_config *bl = &panel->bl_config;\n\n"
     "\tif (panel->host_config.ext_bridge_mode)\n\t\treturn 0;\n\n"
     "\t/* op13: in AOD the level picks the panel's AOD light mode, it is not written as is\n"
     "\t * (scripts/tp_op13_fix.py) */\n"
     "\tif (panel->power_mode == SDE_MODE_DPMS_LP1 || panel->power_mode == SDE_MODE_DPMS_LP2) {\n"
     "\t\tint light = bl_lvl < max(bl->bl_max_level / 8, 1U) ?\n"
     "\t\t\t\tDSI_CMD_SET_K618_AOD_LOW : DSI_CMD_SET_K618_AOD_HIGH;\n\n"
     "\t\tif (!bl_lvl || light == k618_aod_light || !panel->cur_mode ||\n"
     "\t\t    !panel->cur_mode->priv_info ||\n"
     "\t\t    !panel->cur_mode->priv_info->cmd_sets[light].count)\n\t\t\treturn 0;\n"
     "\t\trc = dsi_panel_tx_cmd_set(panel, light, false);\n"
     "\t\tif (!rc)\n\t\t\tk618_aod_light = light;\n"
     "\t\tDSI_INFO(\"op13: AOD light %s (level %u), rc=%d\\n\",\n"
     "\t\t\t light == DSI_CMD_SET_K618_AOD_LOW ? \"low\" : \"high\", bl_lvl, rc);\n"
     "\t\treturn rc;\n\t}\n"
     "\tk618_aod_light = -1;\n"),
    ("display-drivers/msm/dsi/dsi_panel.c",
     "int dsi_panel_set_lp1(struct dsi_panel *panel)\n{\n\tWRITE_ONCE(k618_panel_power_seq, k618_panel_power_seq + 1);\n",
     "int dsi_panel_set_lp1(struct dsi_panel *panel)\n{\n\tWRITE_ONCE(k618_panel_power_seq, k618_panel_power_seq + 1);\n"
     "\tk618_aod_light = -1;\t/* op13: LP1's own commands set the AOD level */\n"),
    # sun_perf_gpuconf has KGSL_USE_SHMEM: android_rvh_shmem_get_folio passes the folio order since
    # 6.12.18 -- in 6.18 too, not only up to 6.13
    ("graphics-kernel/kgsl_sharedmem.c",
     "#if ((KERNEL_VERSION(6, 12, 18) <= LINUX_VERSION_CODE) && \\\n"
     "\t(KERNEL_VERSION(6, 13, 0) > LINUX_VERSION_CODE))\n"
     "static void kgsl_shmem_fill_page(",
     "#if (KERNEL_VERSION(6, 12, 18) <= LINUX_VERSION_CODE)\n"
     "static void kgsl_shmem_fill_page("),
    # display_modules.bzl lists msm/hdmi/hdmi_power.c and hdmi_parser.c among the HDMI sources
    # (sun's conf has HDMI on), the Kbuild does not (modpost: hdmi_power_put, hdmi_parser_put
    # undefined). The only other .bzl sources it lacks are behind options sun leaves off.
    ("display-drivers/msm/Kbuild",
     "\t\t\t\thdmi/hdmi_pll_snps.o \\\n",
     "\t\t\t\thdmi/hdmi_pll_snps.o \\\n\t\t\t\thdmi/hdmi_power.o \\\n\t\t\t\thdmi/hdmi_parser.o \\\n"),
    # The OnePlus 13's composer (6.6-era, OnePlus' SM8750 sde_drm.h) passes sde_drm_scaler_v2
    # without the eight fields the 6.12 release appends (edge_bleed_sup_en .. halo_suppress_coeff):
    # read what it sends, the rest zero (off), not 32 bytes of whatever follows in its memory
    ("display-drivers/msm/sde/sde_plane.c",
     "\tif (copy_from_user(&scale_v2, usr, sizeof(scale_v2))) {\n",
     "\t/* op13: the 6.6 composer's sde_drm_scaler_v2 ends before edge_bleed_sup_en */\n"
     "\tmemset(&scale_v2, 0, sizeof(scale_v2));\n"
     "\tif (copy_from_user(&scale_v2, usr, offsetof(struct sde_drm_scaler_v2, edge_bleed_sup_en))) {\n"),
    ("display-drivers/msm/sde/sde_crtc.c",
     "\t\t\tif (copy_from_user(&scaler_v2, scaler_v2_usr,\n"
     "\t\t\t\t\tsizeof(scaler_v2))) {\n",
     "\t\t\t/* op13: the 6.6 composer's sde_drm_scaler_v2 ends before edge_bleed_sup_en */\n"
     "\t\t\tmemset(&scaler_v2, 0, sizeof(scaler_v2));\n"
     "\t\t\tif (copy_from_user(&scaler_v2, scaler_v2_usr,\n"
     "\t\t\t\t\toffsetof(struct sde_drm_scaler_v2, edge_bleed_sup_en))) {\n"),
    # H2F_MSG_CONTEXT_POINTERS as the OnePlus 13's GMU firmware takes it: the SM8850 release appends
    # dcvs_profile_addr (its GMU DCVS profiles, which sun's GPU does not use), the SM8750 one ends at
    # gmu_context_queue_addr. test-43: the first GPU context surfaceflinger made got "HFI Error
    # Received: 8 1345 HandleHfiCommand" back, then a GMU fault and a snapshot.
    # The OnePlus 13's composer asks for the touch-down event as 0x80000014 (its sde_drm.h); the
    # SM8850 release put VM_RECLAIM there and moved TP_TOUCHDOWN to 0x80000015. test-43: "failed to
    # enable event 80000014". OnePlus 13's numbers.
    ("display-drivers/include/uapi/display/drm/sde_drm.h",
     "#define DRM_EVENT_VM_RECLAIM 0X80000014\n#ifdef OPLUS_FEATURE_DISPLAY\n"
     "#define DRM_EVENT_TP_TOUCHDOWN 0x80000015 /* tp touch down event */\n",
     "#define DRM_EVENT_VM_RECLAIM 0X80000015\t/* op13: TP_TOUCHDOWN's number in the 6.6 user space */\n"
     "#ifdef OPLUS_FEATURE_DISPLAY\n#define DRM_EVENT_TP_TOUCHDOWN 0x80000014 /* tp touch down event */\n"),
    # Colour-processing blobs from the 6.6 composer are shorter than the SM8850 structs: the demura
    # config without cfg0_param_7/8 (8 bytes), the dither config without the extended matrix (1028).
    # Take them zero-padded (the new fields' 0 is their default) instead of refusing them.
    # test-43: "invalid blob len 8560 exp 8568 feature 38".
    ("display-drivers/msm/sde/sde_color_processing.c",
     "\tif (blob->length != prop_node->prop_blob_sz) {\n"
     "\t\tDRM_ERROR(\"invalid blob len %zd exp %d feature %d\\n\",\n"
     "\t\t    blob->length, prop_node->prop_blob_sz, prop_node->feature);\n",
     "\t/* op13: the 6.6 composer's shorter demura (-8) and dither (-1028) configs, zero-padded */\n"
     "\tif (blob->length < prop_node->prop_blob_sz &&\n"
     "\t    (prop_node->prop_blob_sz - blob->length == 8 ||\n"
     "\t     prop_node->prop_blob_sz - blob->length == 1028)) {\n"
     "\t\tstruct drm_property_blob *nb = drm_property_create_blob(crtc->dev,\n"
     "\t\t\t\t\tprop_node->prop_blob_sz, NULL);\n\n"
     "\t\tif (!IS_ERR(nb)) {\n"
     "\t\t\tmemcpy(nb->data, blob->data, blob->length);\n"
     "\t\t\tdrm_property_blob_put(blob);\n"
     "\t\t\tblob = nb;\n"
     "\t\t}\n"
     "\t}\n"
     "\tif (blob->length != prop_node->prop_blob_sz) {\n"
     "\t\tDRM_ERROR(\"invalid blob len %zd exp %d feature %d\\n\",\n"
     "\t\t    blob->length, prop_node->prop_blob_sz, prop_node->feature);\n"),
    ("graphics-kernel/adreno_hfi.h",
     "\tu32 gmu_context_queue_addr;\n\tu32 dcvs_profile_addr;\n} __packed;",
     "\tu32 gmu_context_queue_addr;\n\t/* op13: no dcvs_profile_addr (SM8750 GMU firmware) */\n} __packed;"),
    ("graphics-kernel/adreno_gen8_hwsched_hfi.c",
     "\tcmd.version = 1;\n\tcmd.dcvs_profile_addr = GMU_BUF_ADDR(md);\n",
     "\t/* op13: version 0 and no dcvs_profile_addr, as the OnePlus 13's own KGSL sends it: version 1\n"
     "\t * announces the SM8850 layout with dcvs_profile_addr, which its GMU firmware does not have */\n"
     "\t(void)md;\n"),
]


def gpu_as_op13(root):
    """The OnePlus 13's GPU (Adreno 830: gen8_0_1, Sun v2's DT; gen8_0_0 for v1) as the OnePlus 13's
    own KGSL sets it up: without the GMU thermal mitigation, the thermal profile and the
    no-fault-tolerance timeout the SM8850 release sends its GMU (OnePlus took them out for SM8750:
    "bug:8274887"), and without the CLX table: OnePlus' SM8750 KGSL builds the same table in code,
    but here the GMU firmware answers it with error 115 every boot (test-40 and test-44 sent it and
    hung; test-43 left it out and its GPU came up). test-40: the phone's GMU firmware answered the boot handshake with HFI error 115
    (ResMgrCalibrate) and stopped acking, the GPU never came up, surfaceflinger kept dying."""
    path = os.path.join(root, "graphics-kernel/adreno-gpulist.h")
    if not os.path.exists(path):
        return 0
    text = open(path, encoding="utf-8", errors="surrogateescape").read()
    n = 0

    def fix(m):
        nonlocal n
        b = m.group(0)
        b2 = b.replace("ADRENO_ACD | ADRENO_CLX | ADRENO_GMU_THERMAL_MITIGATION,", "ADRENO_ACD | ADRENO_CLX,")
        b2 = re.sub(r"\n\t\.(cl_no_ft_timeout_ms|therm_profile|clx_tbl) =[^\n]*,", "", b2)
        if b2 != b:
            n += 1
        return b2
    text = re.sub(r"static const struct adreno_gen8_core adreno_gpu_core_gen8_0_[01] = \{.*?\n\};", fix, text,
                  flags=re.S)
    if n:
        open(path, "w", encoding="utf-8", errors="surrogateescape", newline="").write(text)
    return n


def main(argv):
    root = argv[1]
    n = gpu_as_op13(root)
    for rel, old, new in EDITS:
        path = os.path.join(root, rel)
        if not os.path.exists(path):
            continue
        text = open(path, encoding="utf-8", errors="surrogateescape").read()
        if new in text:
            continue
        if old in text:
            open(path, "w", encoding="utf-8", errors="surrogateescape", newline="").write(text.replace(old, new))
            n += 1
        else:
            print(f"tp_op13_fix: {rel}: text to change not found", file=sys.stderr)
            return 1
    print(f"tp_op13_fix: {n} changes")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
