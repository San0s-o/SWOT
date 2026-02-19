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
    "main.import_outdated_title": "Import outdated",
    "main.import_outdated_msg": "The current import \"{source}\" is from {date} and older than 1 month.\n\nPlease import a current JSON file to keep your data up to date.",

    # -- Tabs ----------------------------------------------------
    "tab.overview": "Overview",
    "tab.siege_current": "Siege Defenses (current)",
    "tab.rta_current": "RTA (current)",
    "tab.rune_optimization": "Runes & Artifacts",
    "rune_opt.subtab_runes": "Runes",
    "rune_opt.subtab_artifacts": "Artifacts",
    "tab.siege_builder": "Siege Builder (Custom)",
    "tab.siege_saved": "Siege Optimizations (saved)",
    "tab.wgb_builder": "GWB Builder (Custom)",
    "tab.wgb_saved": "GWB Optimizations (saved)",
    "tab.rta_builder": "RTA Builder (Custom)",
    "tab.rta_saved": "RTA Optimizations (saved)",
    "tab.arena_rush_builder": "Arena Rush Builder",
    "tab.arena_rush_saved": "Arena Rush Optimizations (saved)",

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
    "btn.take_arena_def": "Load current Arena Defense",
    "btn.take_arena_off": "Load Arena Offense Decks",
    "btn.load_current_runes": "Load current runes",

    # -- Labels --------------------------------------------------
    "label.passes": "Passes",
    "label.workers": "Cores",
    "label.saved_opt": "Saved Optimization:",
    "label.team": "Team",
    "label.team_name": "Team Name",
    "label.units": "units",
    "label.defense": "Defense {n}",
    "label.team_slot_1_leader": "Slot 1 (Leader)",
    "label.team_slot_2": "Slot 2",
    "label.team_slot_3": "Slot 3",
    "label.team_leader_hint": "Note: Slot 1 defines the team's leader skill.",
    "label.arena_defense": "Arena Defense",
    "label.arena_offense": "Arena Offense {n}",
    "label.offense": "Offense {n}",
    "label.active": "Active",
    "label.import_account_first": "Import an account first.",
    "label.no_teams": "No teams defined.",
    "label.no_team_selected": "No team selected.",
    "label.no_units": "No units.",
    "label.error": "Error",
    "label.spd_tick_short": "Tick",
    "label.effect_spd_buff": "SPD+",
    "label.effect_atb_boost": "ATB",
    "label.min_mode": "Calculation",
    "label.min_mode_hint": "With base stats: entered values are rune bonus.",
    "label.min_base_prefix": "{value} +",
    "label.min_base_values": "Base stats: SPD {spd} | HP {hp} | ATK {atk} | DEF {defense}",

    # -- Tooltips ------------------------------------------------
    "tooltip.load_current_runes": "Load currently equipped rune sets and mainstats for all monsters.",
    "tooltip.set_multi": "Multi-select. After first selection only same-size sets (2-piece/4-piece).",
    "tooltip.set3": "Only active when Set 1 and Set 2 are both 2-piece sets.",
    "tooltip.mainstat_multi": "Multi-select possible. No selection = Any.",
    "tooltip.art_attr_focus": "Attribute artifact: HP/ATK/DEF (multi-select, empty = Any).",
    "tooltip.art_type_focus": "Type artifact: HP/ATK/DEF (multi-select, empty = Any).",
    "tooltip.art_sub": "{kind} artifact: Select substat (empty = Any).",
    "tooltip.passes": "Number of optimizer passes (1 = single pass only).",
    "tooltip.workers": "Number of CPU cores/threads used by the solver (max 90% of available cores).",
    "tooltip.spd_tick": "Optional SPD tick per monster. Enforces the corresponding SPD breakpoint.",
    "tooltip.effect_spd_buff": "When enabled, an SPD buff after this unit's turn is considered.",
    "tooltip.effect_atb_boost": "When enabled, an attack bar push in % is considered.",
    "tooltip.team_slot_leader": "In Siege/GWB, the first monster (slot 1) defines the team's leader skill.",
    "tooltip.optimize_order_priority": (
        "Drag & Drop order = optimization order. "
        "Especially important for Fast/Balanced, because earlier monsters "
        "pick first from the shared rune/artifact pool."
    ),

    # -- Group Boxes ---------------------------------------------
    "group.opt_order": "Optimization Order (Drag & Drop)",
    "group.turn_order": "Turn Order per Team (Drag & Drop)",
    "group.siege_select": "Select Siege Teams (up to 10 defenses x 3 monsters)",
    "group.wgb_select": "Select GWB Teams (5 defenses x 3 monsters)",
    "group.rta_select": "Select RTA Monsters (up to 15 - order via Drag & Drop)",
    "group.arena_def_select": "Arena Defense (4 monsters)",
    "group.arena_off_select": "Arena Offense Teams (up to 15 teams x 4 monsters)",
    "group.build_monster_list": "Monsters",
    "group.build_editor": "Build Editor",
    "group.build_rune_sets": "Rune Sets",
    "group.build_mainstats": "Mainstats (Slots 2/4/6)",
    "group.build_artifacts": "Artifacts",
    "group.build_min_stats": "Minimum Stats",

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
    "header.min_hp": "Min HP",
    "header.min_atk": "Min ATK",
    "header.min_def": "Min DEF",
    "header.min_cr": "Min CR",
    "header.min_cd": "Min CD",
    "header.min_res": "Min RES",
    "header.min_acc": "Min ACC",
    "min.mode.with_base": "With base stats",
    "min.mode.without_base": "Without base stats",
    "header.stat": "Stat",
    "header.base": "Base",
    "header.runes": "Runes",
    "header.totem": "Totem",
    "header.leader": "Leader",
    "header.total": "Total",
    "header.value": "Value",
    "header.before": "Before",
    "header.after": "After",
    "header.delta": "Delta",
    "rune_opt.col.symbol": "Rune",
    "rune_opt.col.set": "Set",
    "rune_opt.col.quality": "Quality / Ancient",
    "rune_opt.col.slot": "Slot",
    "rune_opt.col.upgrade": "+",
    "rune_opt.col.substats": "Substats",
    "rune_opt.col.gem_grind": "Gem/Grind",
    "rune_opt.col.monster": "Monster",
    "rune_opt.col.current_eff": "Current Eff",
    "rune_opt.col.hero_max_eff": "Max Hero Eff",
    "rune_opt.col.legend_max_eff": "Max Legend Eff",
    "rune_opt.col.hero_potential": "Hero Potential",
    "rune_opt.col.legend_potential": "Legend Potential",
    "rune_opt.gem_grind_status": "Gems: {gems} | Grinds: {grinds}",
    "rune_opt.quality_ancient": "{quality} (Ancient)",
    "rune_opt.filter_set": "Set:",
    "rune_opt.filter_slot": "Slot:",
    "rune_opt.filter_monster": "Monster:",
    "rune_opt.filter_all": "All",
    "rune_opt.filter_reset": "Reset",
    "rune_opt.hint_no_import": "Please import an account first.",
    "rune_opt.hint_no_rows": "No runes at +12 or higher found.",
    "rune_opt.hint_no_filter_rows": "No runes match the selected set/slot/monster filter.",
    "rune_opt.count": "Runes at +12 or higher: {n}",
    "rune_opt.count_filtered": "Runes at +12 or higher: {shown} / {total}",

    # -- Artifact overview ---------------------------------------
    "art_opt.col.type": "Type",
    "art_opt.col.quality": "Quality",
    "art_opt.col.level": "Level",
    "art_opt.col.slot": "Slot",
    "art_opt.col.mainstat": "Main Stat",
    "art_opt.col.substats": "Substats",
    "art_opt.col.monster": "Monster",
    "art_opt.col.efficiency": "Efficiency",
    "art_opt.filter_type": "Type:",
    "art_opt.filter_monster": "Monster:",
    "art_opt.filter_all": "All",
    "art_opt.filter_reset": "Reset",
    "art_opt.type_attribute": "Attribute",
    "art_opt.type_type": "Type",
    "art_opt.hint_no_import": "Please import an account first.",
    "art_opt.hint_no_rows": "No artifacts found.",
    "art_opt.hint_no_filter_rows": "No artifacts match the selected filter.",
    "art_opt.count": "Artifacts: {n}",
    "art_opt.count_filtered": "Artifacts: {shown} / {total}",

    # -- Status / Validation -------------------------------------
    "status.siege_ready": "Ready. Select/load Siege teams -> Validate -> Builds -> Optimize.",
    "status.wgb_ready": "Ready. (GWB) Select teams.",
    "status.siege_taken": "Current defenses loaded. Please validate.",
    "status.rta_taken": "{count} active RTA monsters loaded.",
    "status.arena_rush_ready": "Ready. Load Arena def/off -> Validate -> Builds -> Optimize.",
    "status.arena_def_taken": "Arena defense loaded from snapshot.",
    "status.arena_off_taken": "{count} Arena offense decks loaded.",
    "status.arena_off_taken_limited": "{count}/{total} Arena offense decks loaded (UI limit reached).",
    "status.arena_caps_loading": "Loading monster skill data for effect filters...",
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
    "val.title_arena": "Arena Rush Validation",
    "val.title_arena_ok": "Arena Rush Validation OK",
    "val.arena_def_need_4": "Arena defense must contain exactly 4 monsters (currently {have}).",
    "val.arena_def_duplicate": "Arena defense contains duplicates.",
    "val.arena_off_need_4": "Offense team {team} must contain exactly 4 monsters (currently {have}).",
    "val.arena_off_duplicate": "Offense team {team} contains duplicates.",
    "val.arena_need_off": "At least one complete offense team is required.",
    "val.arena_turn_conflict": "Turn-order conflict between teams detected:\n{details}",
    "val.arena_turn_conflict_line": "{unit}: teams [{teams}] use different slots [{slots}]",
    "val.arena_ok": "Arena Rush: OK ({off_count} offense teams).",
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
    "dlg.arena_builds": "Arena Rush Builds",
    "dlg.delete_confirm": "Really delete '{name}'?",
    "dlg.builds_saved_title": "Builds saved",
    "dlg.builds_saved": "Saved to {path}",
    "dlg.select_left": "Please select a monster on the left.",
    "dlg.no_result": "No result found.",

    # -- Optimization result display -----------------------------
    "result.title_team": "Team Optimization: {name}",
    "result.title_siege": "Optimizer",
    "result.title_wgb": "GWB Optimizer",
    "result.title_rta": "RTA Optimizer",
    "result.title_arena_def": "Arena Rush - Defense",
    "result.title_arena_off": "Arena Rush - Offense {n}",
    "result.opt_running": "{mode} optimization running",
    "result.team_opt_running": "Team '{name}' optimization running",
    "result.avg_rune_eff": "O Rune efficiency: <b>{eff}%</b>",
    "result.avg_rune_eff_none": "O Rune efficiency: <b>-</b>",
    "result.compare_before_after": "Show before/after",
    "result.rune_changes": "Changed rune slots: {changes}",
    "result.rune_changes_none": "No rune-slot changes.",
    "result.opt_name": "{mode} Optimization {ts}",

    # -- Saved optimization display names ------------------------
    "saved.opt_replace": " Optimization ",
    "saved.siege_opt": "SIEGE Optimization",
    "saved.wgb_opt": "GWB Optimization",
    "saved.rta_opt": "RTA Optimization",
    "saved.arena_rush_opt": "Arena Rush Optimization",

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
        "For <b>Fast</b>/<b>Balanced</b>, optimization order "
        "(Drag & Drop in the monster list) is especially important, because "
        "earlier monsters pick first from the shared pool. "
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
    "overview.rune_set_filter_label": "Set Filter:",
    "overview.filter_all_sets": "All Sets",
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
    "arena_rush.mode": "Arena Rush",

    # -- Tabs (Settings) -----------------------------------------
    "tab.settings": "Settings",

    # -- Settings tab --------------------------------------------
    "settings.group_account": "Account / JSON Import",
    "settings.group_license": "License Management",
    "settings.group_language": "Language",
    "settings.group_data": "Data Management",
    "settings.group_updates": "Updates",
    "settings.group_about": "About",

    "settings.btn_import": "Import JSON...",
    "settings.btn_clear_snapshot": "Clear Snapshot",
    "settings.label_import_status": "Current: {source}",
    "settings.label_import_date": "Imported: {date}",
    "settings.label_no_import": "No import loaded.",

    "settings.label_license_type": "License: {type}",
    "settings.label_license_type_trial": "Trial ({remaining} remaining)",
    "settings.label_license_type_full": "Full",
    "settings.label_license_key": "Key: {license_key}",
    "settings.label_no_license": "No license active.",
    "settings.license_activated": "License activated successfully.",
    "settings.license_activation_failed": "Activation failed: {message}",

    "settings.label_language": "Language:",

    "settings.btn_reset_presets": "Reset Build Presets",
    "settings.btn_clear_optimizations": "Clear Saved Optimizations",
    "settings.btn_clear_teams": "Clear Teams",
    "settings.confirm_reset_presets": "Really reset all build presets to defaults?",
    "settings.confirm_clear_optimizations": "Really delete all saved optimizations?",
    "settings.confirm_clear_teams": "Really delete all teams?",
    "settings.confirm_clear_snapshot": "Really delete the imported account snapshot?",
    "settings.confirm_title": "Confirm",
    "settings.data_cleared": "{name} cleared.",

    "settings.btn_check_update": "Check for Updates",
    "settings.label_version": "Version: {version}",
    "settings.update_checking": "Checking for updates...",
    "settings.update_no_update": "You are on the latest version ({version}).",
    "settings.update_error": "Update check failed.",

    "settings.about_version": "App Version: {version}",
    "settings.about_license": "License: {type}",
    "settings.about_data_dir": "Data Directory: {path}",
}
