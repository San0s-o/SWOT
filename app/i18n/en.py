"""English translations."""

STRINGS: dict[str, str] = {
    # -- Main Window ---------------------------------------------
    "main.title": "SW Team Optimizer",
    "main.import_btn": "Import JSON",
    "main.no_import": "No import loaded.",
    "main.import_label": "Import: {source}",
    "main.import_failed": "Import failed",
    "main.file_dialog_title": "Select Summoners War JSON",
    "main.file_dialog_filter": "JSON (*.json);;All files (*.*)",
    "main.search_placeholder": "Search monster...",
    "main.snapshot_title": "Load snapshot",
    "main.snapshot_failed": "Could not load snapshot:\n{exc}",
    "main.source_unknown": "Original name unknown",

    # -- Tabs ----------------------------------------------------
    "tab.overview": "Overview",
    "tab.siege_current": "Siege Defenses (current)",
    "tab.rta_current": "RTA (current)",
    "tab.siege_builder": "Siege Builder (Custom)",
    "tab.siege_saved": "Siege Optimizations (saved)",
    "tab.wgb_builder": "GWB Builder (Custom)",
    "tab.wgb_saved": "GWB Optimizations (saved)",
    "tab.rta_builder": "RTA Builder (Custom)",
    "tab.rta_saved": "RTA Optimizations (saved)",

    # -- Buttons -------------------------------------------------
    "btn.add": "Add",
    "btn.remove": "Remove",
    "btn.close": "Close",
    "btn.cancel": "Cancel",
    "btn.save": "Save",
    "btn.saved": "Saved",
    "btn.delete": "Delete",
    "btn.validate": "Validate",
    "btn.validate_pools": "Validate (Pools/Teams)",
    "btn.builds": "Builds (Sets+Mainstats)...",
    "btn.optimize": "Optimize",
    "btn.activate": "Activate",
    "btn.quit": "Quit",
    "btn.later": "Later",
    "btn.release_page": "Release Page",
    "btn.new_team": "New Team",
    "btn.edit_team": "Edit Team",
    "btn.delete_team": "Delete Team",
    "btn.optimize_team": "Optimize Team",
    "btn.take_siege": "Load current Siege Defenses",
    "btn.take_rta": "Load current RTA Monsters",

    # -- Labels --------------------------------------------------
    "label.passes": "Passes",
    "label.workers": "Cores",
    "label.saved_opt": "Saved Optimization:",
    "label.team": "Team",
    "label.team_name": "Team Name",
    "label.units": "units",
    "label.defense": "Defense {n}",
    "label.import_account_first": "Import an account first.",
    "label.no_teams": "No teams defined.",
    "label.no_team_selected": "No team selected.",
    "label.no_units": "No units.",
    "label.error": "Error",
    "label.spd_tick_short": "Tick",

    # -- Tooltips ------------------------------------------------
    "tooltip.set_multi": "Multi-select. After first selection only same-size sets (2-piece/4-piece).",
    "tooltip.set3": "Only active when Set 1 and Set 2 are both 2-piece sets.",
    "tooltip.mainstat_multi": "Multi-select possible. No selection = Any.",
    "tooltip.art_attr_focus": "Attribute artifact: HP/ATK/DEF (multi-select, empty = Any).",
    "tooltip.art_type_focus": "Type artifact: HP/ATK/DEF (multi-select, empty = Any).",
    "tooltip.art_sub": "{kind} artifact: Select substat (empty = Any).",
    "tooltip.passes": "Number of optimizer passes (1 = single pass only).",
    "tooltip.workers": "Number of CPU cores/threads used by the solver (max 90% of available cores).",
    "tooltip.spd_tick": "Optional SPD tick per monster. Enforces the corresponding SPD breakpoint.",

    # -- Group Boxes ---------------------------------------------
    "group.opt_order": "Optimization Order (Drag & Drop)",
    "group.turn_order": "Turn Order per Team (Drag & Drop)",
    "group.siege_select": "Select Siege Teams (up to 10 defenses x 3 monsters)",
    "group.wgb_select": "Select GWB Teams (5 defenses x 3 monsters)",
    "group.rta_select": "Select RTA Monsters (up to 15 - order via Drag & Drop)",

    # -- Table Headers -------------------------------------------
    "header.monster": "Monster",
    "header.set1": "Set 1",
    "header.set2": "Set 2",
    "header.set3": "Set 3",
    "header.slot2_main": "Slot 2 Main",
    "header.slot4_main": "Slot 4 Main",
    "header.slot6_main": "Slot 6 Main",
    "header.attr_main": "Attr Main",
    "header.attr_sub1": "Attr Sub 1",
    "header.attr_sub2": "Attr Sub 2",
    "header.type_main": "Type Main",
    "header.type_sub1": "Type Sub 1",
    "header.type_sub2": "Type Sub 2",
    "header.min_spd": "Min SPD",
    "header.min_cr": "Min CR",
    "header.min_cd": "Min CD",
    "header.min_res": "Min RES",
    "header.min_acc": "Min ACC",
    "header.stat": "Stat",
    "header.base": "Base",
    "header.runes": "Runes",
    "header.totem": "Totem",
    "header.leader": "Leader",
    "header.total": "Total",
    "header.value": "Value",

    # -- Status / Validation -------------------------------------
    "status.siege_ready": "Ready. Select/load Siege teams -> Validate -> Builds -> Optimize.",
    "status.wgb_ready": "Ready. (GWB) Select teams.",
    "status.siege_taken": "Current defenses loaded. Please validate.",
    "status.rta_taken": "{count} active RTA monsters loaded.",
    "status.pass_progress": "{prefix}: Pass {current}/{total}...",

    # -- Validation Messages -------------------------------------
    "val.incomplete_team": "{label}: Team {team} is incomplete ({have}/{need}).",
    "val.duplicate_in_team": "{label}: Team {team} contains '{name}' twice.",
    "val.no_teams": "{label}: No teams selected.",
    "val.ok": "{label}: OK ({count} units).",
    "val.no_account": "No account loaded.",
    "val.duplicate_monster_wgb": "Monster '{name}' appears multiple times (GWB allows each monster only once).",
    "val.title_siege": "Siege Validation",
    "val.title_siege_ok": "Siege Validation OK",
    "val.title_wgb": "GWB Validation",
    "val.title_wgb_ok": "GWB Validation OK",
    "val.title_rta": "RTA Validation",
    "val.title_rta_ok": "RTA Validation OK",
    "val.set_invalid": "Invalid set combo for {unit}: none of the set options fit in 6 slots.",

    # -- Dialog Messages -----------------------------------------
    "dlg.team_needs_units_title": "Team needs units",
    "dlg.team_needs_units": "Please add at least one monster.",
    "dlg.load_import_first": "Please load an import first.",
    "dlg.load_import_and_team": "Please load an import and select a team first.",
    "dlg.validate_first": "Please validate first.\n\n{msg}",
    "dlg.select_monsters_first": "Please select monsters first.",
    "dlg.duplicates_found": "Duplicates found. Please validate first.",
    "dlg.max_15_rta": "Maximum 15 monsters allowed.",
    "dlg.delete_confirm": "Really delete '{name}'?",
    "dlg.builds_saved_title": "Builds saved",
    "dlg.builds_saved": "Saved to {path}",
    "dlg.select_left": "Please select a monster on the left.",
    "dlg.no_result": "No result found.",

    # -- Optimization result display -----------------------------
    "result.title_team": "Team Optimization: {name}",
    "result.title_siege": "Greedy Optimization",
    "result.title_wgb": "GWB Greedy Optimization",
    "result.title_rta": "RTA Greedy Optimization",
    "result.opt_running": "{mode} optimization running",
    "result.team_opt_running": "Team '{name}' optimization running",
    "result.avg_rune_eff": "O Rune efficiency: <b>{eff}%</b>",
    "result.avg_rune_eff_none": "O Rune efficiency: <b>-</b>",
    "result.opt_name": "{mode} Optimization {ts}",

    # -- Saved optimization display names ------------------------
    "saved.opt_replace": " Optimization ",
    "saved.siege_opt": "SIEGE Optimization",
    "saved.wgb_opt": "GWB Optimization",
    "saved.rta_opt": "RTA Optimization",

    # -- Stat Labels ---------------------------------------------
    "stat.HP": "HP",
    "stat.ATK": "ATK",
    "stat.DEF": "DEF",
    "stat.SPD": "SPD",
    "stat.CR": "Crit. Rate",
    "stat.CD": "Crit. DMG",
    "stat.RES": "Resistance",
    "stat.ACC": "Accuracy",

    # -- Siege cards stat labels ---------------------------------
    "card_stat.HP": "HP",
    "card_stat.ATK": "ATK",
    "card_stat.DEF": "DEF",
    "card_stat.SPD": "SPD",
    "card_stat.CR": "Crit. Rate",
    "card_stat.CD": "Crit. DMG",
    "card_stat.RES": "RES",
    "card_stat.ACC": "ACC",

    # -- Artifact labels -----------------------------------------
    "artifact.attribute": "Attribute",
    "artifact.type": "Type",
    "artifact.no_rune": "No rune",
    "artifact.no_artifact": "No artifact",

    # -- Generic UI labels --------------------------------------
    "ui.artifact": "Artifact",
    "ui.artifacts_title": "Artifacts",
    "ui.rune_id": "Rune ID",
    "ui.artifact_id": "Artifact ID",
    "ui.focus": "Focus",
    "ui.current_on": "currently on: {owner}",
    "ui.slot": "Slot",
    "ui.main": "Main",
    "ui.prefix": "Prefix",
    "ui.subs": "Subs",
    "ui.rolls": "Rolls {n}",
    "ui.class_short": "Cls.",

    # -- Update dialog -------------------------------------------
    "update.title": "Update available",
    "update.text": "New version available: {latest}\nInstalled: {current}",
    "update.open_release": "Open GitHub release now?",

    # -- License dialog ------------------------------------------
    "license.title": "License Activation",
    "license.enter_key": "Please enter your serial key.",
    "license.trial_remaining": "Trial ({remaining} remaining)",
    "license.trial": "Trial",
    "license.days": "{n} days",
    "license.hours": "{n} hours",
    "license.minutes": "{n} minutes",
    "license.validating": "Validating license...",

    # -- Help dialog ---------------------------------------------
    "help.title": "Guide",
    "help.content": (
        "<h2>SW Team Optimizer - Quick Guide</h2>"

        "<h3>1. Import JSON</h3>"
        "<p>Click <b>Import JSON</b> and select your "
        "Summoners War JSON export. After importing you will see "
        "your account statistics, rune efficiency charts, and "
        "set distribution on the <b>Overview</b> tab.</p>"

        "<h3>2. View current setups</h3>"
        "<p><b>Siege Defenses (current)</b> - Shows your in-game "
        "siege defenses as cards with rune details.<br>"
        "<b>RTA (current)</b> - Shows your currently equipped RTA monsters.</p>"

        "<h3>3. Build teams</h3>"
        "<p>In the <b>Builder</b> tabs (Siege / GWB / RTA) you can "
        "create custom team compositions:</p>"
        "<ul>"
        "<li><b>Select monsters</b> - Via the dropdowns per defense (Siege/GWB) "
        "or the Add button (RTA).</li>"
        "<li><b>Load current</b> - Imports your in-game teams.</li>"
        "<li><b>Validate</b> - Checks for rune pool conflicts and shows warnings.</li>"
        "</ul>"

        "<h3>4. Define builds</h3>"
        "<p>Click <b>Builds (Sets+Mainstats)...</b> to set the desired "
        "rune sets and slot 2/4/6 main stats per monster. "
        "Multi-select is available for main stats (no selection = Any). "
        "Additionally, you can select up to two substats per artifact type "
        "(Attribute/Type; empty = Any). "
        "Set logic: Set 1 and Set 2 support multi-select. "
        "Only same-size sets are allowed per set slot (2-piece or 4-piece). "
        "Set 3 is only active when Set 1 and Set 2 are both 2-piece sets. "
        "You can also define minimum values (e.g. min SPD) here.</p>"

        "<h3>5. Optimize</h3>"
        "<p>Click <b>Optimize (Runes)</b> to start the automatic "
        "rune/artifact distribution. The optimizer distributes your runes "
        "and selects matching artifacts based on build constraints. "
        "When artifact substats are selected, matching artifacts with higher "
        "values are preferred. "
        "Turn order within teams is always enforced. "
        "In the Turn Order block you can set an SPD tick per monster. "
        "The optimizer then enforces that exact tick range "
        "(e.g. Tick 6 = SPD 239 to 285). "
        "With profile <b>Fast</b> it runs a quick greedy pass. "
        "<b>Balanced</b> uses greedy plus refinement from pass 2 onward. "
        "<b>Max Qualität</b> uses a global optimization over all selected monsters "
        "at once (efficiency-focused). "
        "Use <b>Passes</b> for 1-10 multi-pass runs in Fast/Balanced; "
        "if no further improvement is possible, the optimizer stops early. "
        "In Max Qualität, passes are not used as multi-pass. "
        "The app shows a progress dialog while optimization is running.</p>"

        "<h3>6. Save results</h3>"
        "<p>Optimizations are saved automatically and can be "
        "reviewed or deleted at any time in the "
        "<b>Optimizations (saved)</b> tabs.</p>"

        "<h3>Tips</h3>"
        "<ul>"
        "<li>In the rune chart you can use <b>Ctrl+Scroll</b> to change the "
        "number of displayed top runes.</li>"
        "<li>Hover over a data point in the chart to see "
        "rune details including subs and grinds.</li>"
        "<li>Subs that were swapped with a <span style='color:#1abc9c'><b>Gem</b></span> "
        "are highlighted in color.</li>"
        "</ul>"
    ),

    # -- Optimizer messages --------------------------------------
    "opt.slot_no_runes": "Slot {slot}: no runes in pool.",
    "opt.no_attr_artifact": "No attribute artifact (type 1) in pool.",
    "opt.no_type_artifact": "No type artifact (type 2) in pool.",
    "opt.no_builds": "No builds available.",
    "opt.feasible": "Build is fundamentally feasible with available runes/artifacts.",
    "opt.mainstat_missing": "Build '{name}': Slot {slot} mainstat {allowed} not available.",
    "opt.no_artifact_match": (
        "Build '{name}': no matching artifact for "
        "{kind} (Focus={focus}, Subs={subs})."
    ),
    "opt.set_too_many": "Build '{name}': Set option {opt} requires {pieces} pieces (>6).",
    "opt.set_not_enough": "Build '{name}': Set {set_id} needs {pieces}, available {avail}.",
    "opt.infeasible": "Infeasible: pool/build constraints are incompatible.",
    "opt.internal_no_rune": "Internal error: Slot {slot} no rune.",
    "opt.internal_no_artifact": "Internal error: Artifact type {art_type} missing.",
    "opt.no_units": "No units.",
    "opt.ok": "OK",
    "opt.cancelled": "Optimization cancelled.",
    "opt.partial_fail": "Done, but at least one monster could not be built.",
    "opt.stable_solution": "stable solution without further improvement",
    "opt.no_improvement": "no improvement in consecutive passes",
    "opt.multi_pass": (
        "{prefix} Multi-pass active: best result from {used} "
        "passes (pass {pass_idx})."
    ),
    "opt.multi_pass_early": (
        "{prefix} Multi-pass active: best result from {used} of {planned} "
        "planned passes (pass {pass_idx}); stopped early "
        "({reason})."
    ),

    # -- Update service messages ---------------------------------
    "svc.no_repo": "No GitHub repo configured (github_repo missing).",
    "svc.no_version": "No release-ready app_version value set.",
    "svc.check_failed": "Update check failed: {detail}",
    "svc.invalid_response": "Update check: invalid API response.",
    "svc.unexpected_format": "Update check: unexpected data format.",
    "svc.no_asset": "No suitable download asset found in release.",
    "svc.download_http_fail": "Download failed (HTTP {status}).",
    "svc.download_failed": "Download failed: {detail}",
    "svc.download_ok": "Update downloaded successfully.",

    # -- License service messages --------------------------------
    "lic.invalid_response": "Invalid server response ({status}).",
    "lic.server_error": "Server error ({status}).",
    "lic.activation_failed": "Activation failed.",
    "lic.activated": "License activated.",
    "lic.check_failed": "License check failed.",
    "lic.valid": "License valid.",
    "lic.valid_cached": "License temporarily verified from local cache.",
    "lic.no_key": "No key entered.",
    "lic.network_error": "Network error during license check: {detail}",
    "lic.not_configured": "License server not configured (license_config.json missing/incomplete).",

    # -- Overview widget -----------------------------------------
    "overview.monsters": "Monsters",
    "overview.runes": "Runes",
    "overview.artifacts": "Artifacts",
    "overview.rune_eff": "Rune Eff. (%)",
    "overview.attr_art_eff": "Attribute Artifact Eff. (%)",
    "overview.type_art_eff": "Type Artifact Eff. (%)",
    "overview.best_rune": "Best Rune",
    "overview.set_eff": "{name} Eff. (%)",
    "overview.chart_top_label": "Rune Chart Top:",
    "overview.rune_eff_chart": "Rune Efficiency (Top {n})",
    "overview.set_dist_chart": "Rune Set Distribution",
    "overview.set_eff_chart": "Important Sets Efficiency (Top {n})",
    "overview.art_eff_chart": "Artifact Efficiency (Top {n})",
    "overview.axis_count": "Count / Rank",
    "overview.axis_eff": "Efficiency (%)",
    "overview.series_current": "Current",
    "overview.series_hero_max": "Hero max",
    "overview.series_legend_max": "Legend max",
    "overview.series_attr_art": "Attribute Artifact",
    "overview.series_type_art": "Type Artifact",
    "overview.other": "Other ({count})",
    "overview.rank": "Rank #{idx}",
    "overview.efficiency": "Efficiency",
    "overview.quality": "Quality",
    "overview.current_eff": "Current: {eff}%",
    "overview.hero_max": "Hero max (Grind/Gem): {eff}%",
    "overview.legend_max": "Legend max (Grind/Gem): {eff}%",
    "overview.slot_left": "Left",
    "overview.slot_right": "Right",
    "overview.mainstat": "Main stat:",

    # -- RTA overview --------------------------------------------
    "rta.spd_lead": "<b>SPD Lead:</b>",
    "rta.no_lead": "No Lead (0%)",

    # -- Siege cards ---------------------------------------------
    "card.avg_rune_eff": "O Rune efficiency: <b>{eff}%</b>",
    "card.avg_rune_eff_none": "O Rune efficiency: <b>-</b>",
    "card.focus": "Focus:",
    "card.defense": "Defense {n}",

    # -- RTA validation messages ---------------------------------
    "rta.no_monsters": "RTA: No monsters selected.",
    "rta.duplicate": "RTA: '{name}' is selected twice.",
    "rta.ok": "RTA: OK ({count} monsters).",
}


