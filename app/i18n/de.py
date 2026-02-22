"""German translations (default language)."""

STRINGS: dict[str, str] = {
    # -- Main Window ---------------------------------------------
    "main.title": "SW Team Optimizer",
    "main.import_btn": "JSON importieren",
    "main.no_import": "Kein Import geladen.",
    "main.import_label": "Import: {source}",
    "main.import_failed": "Import fehlgeschlagen",
    "main.file_dialog_title": "Summoners War JSON auswählen",
    "main.file_dialog_filter": "JSON (*.json);;Alle Dateien (*.*)",
    "main.search_placeholder": "Monster suchen...",
    "main.snapshot_title": "Snapshot laden",
    "main.snapshot_failed": "Snapshot konnte nicht geladen werden:\n{exc}",
    "main.source_unknown": "Originalname unbekannt",
    "main.import_outdated_title": "Import veraltet",
    "main.import_outdated_msg": "Der aktuelle Import \"{source}\" ist vom {date} und somit älter als 1 Monat.\n\nBitte importiere eine aktuelle JSON-Datei, damit die Daten auf dem neuesten Stand sind.",

    # -- Tabs (Gruppen-Tabs) -------------------------------------
    "tab.overview": "Übersicht",
    "tab.siege_group": "Siege",
    "tab.wgb_group": "World Guild Battle",
    "tab.rta_group": "RTA",
    "tab.arena_rush_group": "Arena Rush",
    "tab.rune_optimization": "Runen && Artefakte",
    # -- Sub-Tabs (innerhalb Gruppen) ----------------------------
    "tab.subtab_current": "Aktuell",
    "tab.subtab_builder": "Builder",
    "tab.subtab_saved": "Gespeichert",
    "rune_opt.subtab_runes": "Runen",
    "rune_opt.subtab_artifacts": "Artefakte",
    # -- Alte Tab-Keys (für Kompatibilität) ----------------------
    "tab.siege_current": "Siege Verteidigungen (aktuell)",
    "tab.rta_current": "RTA (aktuell)",
    "tab.siege_builder": "Siege Builder (Custom)",
    "tab.siege_saved": "Siege Optimierungen (gespeichert)",
    "tab.wgb_builder": "WGB Builder (Custom)",
    "tab.wgb_saved": "WGB Optimierungen (gespeichert)",
    "tab.rta_builder": "RTA Builder (Custom)",
    "tab.rta_saved": "RTA Optimierungen (gespeichert)",
    "tab.arena_rush_builder": "Arena Rush Builder",
    "tab.arena_rush_saved": "Arena Rush Optimierungen (gespeichert)",

    # -- Buttons -------------------------------------------------
    "btn.add": "Hinzufügen",
    "btn.remove": "Entfernen",
    "btn.close": "Schließen",
    "btn.cancel": "Abbrechen",
    "btn.save": "Speichern",
    "btn.saved": "Gespeichert",
    "btn.delete": "Löschen",
    "btn.validate": "Validieren",
    "btn.validate_pools": "Validieren (Pools/Teams)",
    "btn.builds": "Builds...",
    "btn.optimize": "Optimieren",
    "btn.activate": "Aktivieren",
    "btn.quit": "Beenden",
    "btn.later": "Später",
    "btn.release_page": "Release-Seite",
    "btn.install_update": "Update",
    "btn.new_team": "Neues Team",
    "btn.edit_team": "Team bearbeiten",
    "btn.delete_team": "Team löschen",
    "btn.optimize_team": "Team optimieren",
    "btn.take_siege": "Aktuelle Siege-Verteidigungen übernehmen",
    "btn.take_rta": "Aktuelle RTA Monster übernehmen",
    "btn.take_arena_def": "Aktuelle Arena-Def übernehmen",
    "btn.take_arena_off": "Arena-Offense Decks übernehmen",
    "btn.load_current_runes": "Aktuelle Runen übernehmen",
    "btn.restore_saved_preset": "Gespeichertes Preset laden",
    "btn.load_preferred_runes": "Bevorzugte Runen laden",
    "btn.load_preferred_runes_all": "Bevorzugte Runen für alle laden",
    "btn.save_preferred_runes": "Bevorzugte Runen speichern",

    # -- Labels --------------------------------------------------
    "label.passes": "Durchläufe",
    "label.workers": "Kerne",
    "label.saved_opt": "Gespeicherte Optimierung:",
    "label.team": "Team",
    "label.team_name": "Team-Name",
    "label.units": "Monster",
    "label.defense": "Verteidigung {n}",
    "label.team_slot_1_leader": "Slot 1 (Leader)",
    "label.team_slot_2": "Slot 2",
    "label.team_slot_3": "Slot 3",
    "label.team_leader_hint": "Hinweis: Slot 1 bestimmt den Leader-Skill des Teams.",
    "label.arena_defense": "Arena Defense",
    "label.arena_offense": "Arena Offense {n}",
    "label.offense": "Offense {n}",
    "label.active": "Aktiv",
    "label.import_account_first": "Importiere zuerst ein Konto.",
    "label.no_teams": "Keine Teams definiert.",
    "label.no_team_selected": "Kein Team ausgewählt.",
    "label.no_units": "Keine Units.",
    "label.error": "Fehler",
    "label.spd_tick_short": "Tick",
    "label.effect_spd_buff": "SPD+",
    "label.effect_atb_boost": "ATB",
    "label.min_mode": "Berechnung",
    "label.min_mode_hint": "Mit Base-Stats: Eingabewerte sind Runen-Bonus.",
    "label.min_base_prefix": "{value} +",
    "label.min_base_values": "Basiswerte: SPD {spd} | HP {hp} | ATK {atk} | DEF {defense}",

    # -- Tooltips ------------------------------------------------
    "tooltip.load_current_runes": "Übernimmt die aktuell angelegten Runen-Sets und Mainstats für alle Monster.",
    "tooltip.restore_saved_preset": "Stellt die beim Öffnen gespeicherten Build-Einstellungen wieder her.",
    "tooltip.load_preferred_runes": "Lädt bevorzugte Runen-Kombis und Mainstats aus monster_rune_set_preferences.json für dieses Monster.",
    "tooltip.load_preferred_runes_all": "Lädt bevorzugte Runen-Kombis und Mainstats aus monster_rune_set_preferences.json für alle Monster.",
    "tooltip.load_preferred_runes_missing": "Keine Runen-Prefs für dieses Monster in monster_rune_set_preferences.json gefunden.",
    "tooltip.save_preferred_runes": "Speichert die aktuell gewählten Runen-Sets und Mainstats als Monster-Prefs in monster_rune_set_preferences.json.",
    "tooltip.set_multi": "Mehrfachauswahl. Nach erster Auswahl nur gleich große Sets (2er/4er).",
    "tooltip.set3": "Nur aktiv, wenn Set 1 und Set 2 jeweils 2er-Sets sind.",
    "tooltip.mainstat_multi": "Mehrfachauswahl möglich. Keine Auswahl = Any.",
    "tooltip.art_attr_focus": "Attribut-Artefakt: HP/ATK/DEF (Mehrfachauswahl, leer = Any).",
    "tooltip.art_type_focus": "Typ-Artefakt: HP/ATK/DEF (Mehrfachauswahl, leer = Any).",
    "tooltip.art_sub": "{kind}-Artefakt: Substat auswählen (leer = Any).",
    "tooltip.passes": "Anzahl Optimizer-Durchläufe (1 = nur ein Durchlauf).",
    "tooltip.workers": "Anzahl CPU-Kerne/Threads für den Solver (max. 90% der verfügbaren Kerne).",
    "tooltip.spd_tick": "Optionaler SPD-Tick pro Monster. Erzwingt den passenden SPD-Breakpoint.",
    "tooltip.effect_spd_buff": "Wenn aktiv, wird nach diesem Zug ein SPD-Buff beruecksichtigt.",
    "tooltip.effect_atb_boost": "Wenn aktiv, wird ein Angriffsbalken-Push in % beruecksichtigt.",
    "tooltip.team_slot_leader": "Bei Siege/WGB bestimmt das erste Monster (Slot 1) die Leader-Fertigkeit des Teams.",
    "tooltip.siege_optimize_check": "Wenn aktiviert, wird diese Verteidigung optimiert. Deaktivieren, um sie zu überspringen.",
    "tooltip.clear_slot": "Diesen Slot leeren",
    "tooltip.clear_defense": "Gesamte Verteidigung leeren",
    "tooltip.builds": "Build-Presets bearbeiten (Runen-Sets, Mainstats, Substats)",
    "tooltip.siege_block_excluded": "Runen und Artefakte von Monstern in nicht-optimierten Verteidigungen werden für die Optimierung gesperrt (nicht verfügbar).",
    "chk.siege_block_excluded": "Runen/Artefakte nicht-optimierter Defs sperren",
    "tooltip.optimize_order_priority": (
        "Drag & Drop Reihenfolge = Optimierungsreihenfolge. "
        "Bei Fast/Balanced besonders wichtig, weil vordere Monster zuerst "
        "aus dem gemeinsamen Runen-/Artefaktpool waehlen."
    ),

    # -- Group Boxes ---------------------------------------------
    "group.opt_order": "Optimierungsreihenfolge (Drag & Drop)",
    "group.turn_order": "Turn Order pro Team (Drag & Drop)",
    "group.siege_select": "Siege-Teams auswählen (bis zu 10 Verteidigungen x 3 Monster)",
    "group.wgb_select": "WGB-Teams auswählen (5 Verteidigungen x 3 Monster)",
    "group.rta_select": "RTA Monster auswählen (bis zu 15 - Reihenfolge per Drag & Drop)",
    "group.arena_def_select": "Arena Defense (4 Monster)",
    "group.arena_off_select": "Arena Offense Teams (bis zu 15 Teams x 4 Monster)",
    "group.build_monster_list": "Monster (Optimierungsreihenfolge)",
    "group.build_editor": "Build-Editor",
    "group.build_rune_sets": "Runen-Sets",
    "group.build_mainstats": "Mainstats (Slots 2/4/6)",
    "group.build_artifacts": "Artefakte",
    "group.build_min_stats": "Mindestwerte",

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
    "header.type_main": "Typ Main",
    "header.type_sub1": "Typ Sub 1",
    "header.type_sub2": "Typ Sub 2",
    "header.min_spd": "Min SPD",
    "header.min_hp": "Min HP",
    "header.min_atk": "Min ATK",
    "header.min_def": "Min DEF",
    "header.min_cr": "Min CR",
    "header.min_cd": "Min CD",
    "header.min_res": "Min RES",
    "header.min_acc": "Min ACC",
    "min.mode.with_base": "Mit Base-Stats",
    "min.mode.without_base": "Ohne Base-Stats",
    "header.stat": "Stat",
    "header.base": "Basis",
    "header.runes": "Runen",
    "header.totem": "Totem",
    "header.leader": "Leader",
    "header.total": "Gesamt",
    "header.value": "Wert",
    "header.before": "Vorher",
    "header.after": "Nachher",
    "header.delta": "Delta",
    "rune_opt.col.symbol": "Rune",
    "rune_opt.col.set": "Set",
    "rune_opt.col.quality": "Quali / Ancient",
    "rune_opt.col.slot": "Slot",
    "rune_opt.col.upgrade": "+",
    "rune_opt.col.substats": "Substats",
    "rune_opt.col.gem_grind": "Gem/Grind",
    "rune_opt.col.monster": "Monster",
    "rune_opt.col.current_eff": "Aktuelle Eff",
    "rune_opt.col.hero_max_eff": "Max Hero Eff",
    "rune_opt.col.legend_max_eff": "Max Legend Eff",
    "rune_opt.col.hero_potential": "Hero Potenzial",
    "rune_opt.col.legend_potential": "Legend Potenzial",
    "rune_opt.gem_grind_status": "Gems: {gems} | Grinds: {grinds}",
    "rune_opt.quality_ancient": "{quality} (Ancient)",
    "rune_opt.filter_set": "Set:",
    "rune_opt.filter_slot": "Slot:",
    "rune_opt.filter_monster": "Monster:",
    "rune_opt.filter_all": "Alle",
    "rune_opt.filter_reset": "Zurücksetzen",
    "rune_opt.hint_no_import": "Bitte zuerst einen Import laden.",
    "rune_opt.hint_no_rows": "Keine Runen ab +12 gefunden.",
    "rune_opt.hint_no_filter_rows": "Keine Runen für den gewählten Set-/Slot-/Monster-Filter gefunden.",
    "rune_opt.count": "Runen ab +12: {n}",
    "rune_opt.count_filtered": "Runen ab +12: {shown} / {total}",

    # -- Artefakt-Übersicht --------------------------------------
    "art_opt.col.type": "Typ",
    "art_opt.col.quality": "Qualität",
    "art_opt.col.level": "Level",
    "art_opt.col.slot": "Slot",
    "art_opt.col.mainstat": "Hauptstat",
    "art_opt.col.substats": "Substats",
    "art_opt.col.monster": "Monster",
    "art_opt.col.efficiency": "Effizienz",
    "art_opt.filter_type": "Typ:",
    "art_opt.filter_monster": "Monster:",
    "art_opt.filter_all": "Alle",
    "art_opt.filter_reset": "Zurücksetzen",
    "art_opt.type_attribute": "Attribut",
    "art_opt.type_type": "Typ",
    "art_opt.hint_no_import": "Bitte zuerst einen Import laden.",
    "art_opt.hint_no_rows": "Keine Artefakte gefunden.",
    "art_opt.hint_no_filter_rows": "Keine Artefakte für den gewählten Filter gefunden.",
    "art_opt.count": "Artefakte: {n}",
    "art_opt.count_filtered": "Artefakte: {shown} / {total}",

    # -- Status / Validation -------------------------------------
    "status.siege_ready": "Bereit. Siege auswählen/übernehmen -> Validieren -> Builds -> Optimieren.",
    "status.wgb_ready": "Bereit. (WGB) Teams auswählen.",
    "status.siege_taken": "Aktuelle Verteidigungen übernommen. Bitte validieren.",
    "status.rta_taken": "{count} aktive RTA Monster übernommen.",
    "status.arena_rush_ready": "Bereit. Arena-Def/Off laden -> Validieren -> Builds -> Optimieren.",
    "status.arena_def_taken": "Arena-Defense aus Snapshot geladen.",
    "status.arena_off_taken": "{count} Arena-Offense-Decks geladen.",
    "status.arena_off_taken_limited": "{count}/{total} Arena-Offense-Decks geladen (UI-Limit erreicht).",
    "status.arena_caps_loading": "Lade Monster-Skilldaten fuer Effekt-Filter...",
    "status.pass_progress": "{prefix}: Durchlauf {current}/{total}...",

    # -- Validation Messages -------------------------------------
    "val.incomplete_team": "{label}: Team {team} ist unvollständig ({have}/{need}).",
    "val.duplicate_in_team": "{label}: Team {team} enthält '{name}' doppelt.",
    "val.no_teams": "{label}: Keine Teams ausgewählt.",
    "val.ok": "{label}: OK ({count} Units).",
    "val.no_account": "Kein Account geladen.",
    "val.duplicate_monster_wgb": "Monster '{name}' kommt mehrfach vor (WGB erlaubt jedes Monster nur 1x).",
    "val.title_siege": "Siege Validierung",
    "val.title_siege_ok": "Siege Validierung OK",
    "val.title_wgb": "WGB Validierung",
    "val.title_wgb_ok": "WGB Validierung OK",
    "val.title_rta": "RTA Validierung",
    "val.title_rta_ok": "RTA Validierung OK",
    "val.title_arena": "Arena Rush Validierung",
    "val.title_arena_ok": "Arena Rush Validierung OK",
    "val.arena_def_need_4": "Arena Defense muss genau 4 Monster haben (aktuell {have}).",
    "val.arena_def_duplicate": "Arena Defense enthält Duplikate.",
    "val.arena_off_need_4": "Offense-Team {team} muss genau 4 Monster haben (aktuell {have}).",
    "val.arena_off_duplicate": "Offense-Team {team} enthält Duplikate.",
    "val.arena_need_off": "Mindestens ein vollständiges Offense-Team erforderlich.",
    "val.arena_turn_conflict": "Turnorder-Konflikt zwischen Teams erkannt:\n{details}",
    "val.arena_turn_conflict_line": "{unit}: Teams [{teams}] verwenden unterschiedliche Slots [{slots}]",
    "val.arena_ok": "Arena Rush: OK ({off_count} Offense-Teams).",
    "val.set_invalid": "Ungültige Set-Kombi für {unit}: keine der Set-Optionen passt in 6 Slots.",

    # -- Dialog Messages -----------------------------------------
    "dlg.team_needs_units_title": "Team braucht Monster",
    "dlg.team_needs_units": "Bitte füge mindestens ein Monster hinzu.",
    "dlg.load_import_first": "Bitte zuerst einen Import laden.",
    "dlg.load_import_and_team": "Bitte zuerst einen Import laden und ein Team auswählen.",
    "dlg.validate_first": "Bitte erst validieren.\n\n{msg}",
    "dlg.select_monsters_first": "Bitte erst Monster auswählen.",
    "dlg.duplicates_found": "Duplikate gefunden. Bitte erst validieren.",
    "dlg.max_15_rta": "Maximal 15 Monster erlaubt.",
    "dlg.arena_builds": "Arena Rush Builds",
    "dlg.delete_confirm": "'{name}' wirklich löschen?",
    "dlg.builds_saved_title": "Builds gespeichert",
    "dlg.builds_saved": "Gespeichert in {path}",
    "dlg.select_left": "Bitte links ein Monster auswählen.",
    "dlg.no_result": "Kein Ergebnis gefunden.",

    # -- Optimization result display -----------------------------
    "result.title_team": "Team Optimierung: {name}",
    "result.title_siege": "Optimizer",
    "result.title_wgb": "WGB Optimizer",
    "result.title_rta": "RTA Optimizer",
    "result.title_arena_def": "Arena Rush - Defense",
    "result.title_arena_off": "Arena Rush - Offense {n}",
    "result.opt_running": "{mode} Optimierung läuft",
    "result.team_opt_running": "Team '{name}' Optimierung läuft",
    "result.avg_rune_eff": "Ø Rune-Effizienz: <b>{eff}%</b>",
    "result.avg_rune_eff_none": "Ø Rune-Effizienz: <b>-</b>",
    "result.compare_before_after": "Vorher/Nachher anzeigen",
    "result.rune_changes": "Geänderte Runen-Slots: {changes}",
    "result.rune_changes_none": "Keine Rune-Slot-Änderungen.",
    "result.opt_name": "{mode} Optimierung {ts}",

    # -- Saved optimization display names ------------------------
    "saved.opt_replace": " Optimierung ",
    "saved.siege_opt": "SIEGE Optimierung",
    "saved.wgb_opt": "WGB Optimierung",
    "saved.rta_opt": "RTA Optimierung",
    "saved.arena_rush_opt": "Arena Rush Optimierung",

    # -- Stat Labels ---------------------------------------------
    "stat.HP": "LP",
    "stat.ATK": "Angriff",
    "stat.DEF": "Verteidigung",
    "stat.SPD": "Tempo",
    "stat.CR": "Krit.-Rate",
    "stat.CD": "Krit.-Schaden",
    "stat.RES": "Widerstand",
    "stat.ACC": "Präzision",

    # -- Siege cards stat labels ---------------------------------
    "card_stat.HP": "LP",
    "card_stat.ATK": "ANG",
    "card_stat.DEF": "VER",
    "card_stat.SPD": "Tempo",
    "card_stat.CR": "Krit. Rate",
    "card_stat.CD": "Krit. Schdn",
    "card_stat.RES": "RES",
    "card_stat.ACC": "ACC",

    # -- Card labels ---------------------------------------------
    "card.avg_rune_eff": "Ø Runen-Effizienz: <b>{eff}%</b>",
    "card.avg_rune_eff_none": "Ø Runen-Effizienz: <b>-</b>",
    "card.focus": "Fokus:",
    "card.defense": "Verteidigung {n}",

    # -- Artifact labels -----------------------------------------
    "artifact.attribute": "Attribut",
    "artifact.type": "Typ",
    "artifact.no_rune": "Keine Rune",
    "artifact.no_artifact": "Kein Artefakt",

    # -- Generische UI-Labels -----------------------------------
    "ui.artifact": "Artefakt",
    "ui.artifacts_title": "Artefakte",
    "ui.rune_id": "Rune ID",
    "ui.artifact_id": "Artefakt ID",
    "ui.focus": "Fokus",
    "ui.current_on": "aktuell auf: {owner}",
    "ui.slot": "Slot",
    "ui.main": "Main",
    "ui.prefix": "Prefix",
    "ui.subs": "Subs",
    "ui.rolls": "Rolls {n}",
    "ui.class_short": "Kl.",

    # -- Update dialog -------------------------------------------
    "update.title": "Update verfügbar",
    "update.text": "Neue Version verfügbar: {latest}\nInstalliert: {current}",
    "update.open_release": "GitHub-Release jetzt öffnen?",
    "update.auto_failed": "Update fehlgeschlagen.",
    "update.wizard.step_info": "Info",
    "update.wizard.step_download": "Download",
    "update.wizard.step_done": "Fertig",
    "update.wizard.new_version": "Neue Version: {latest}  (aktuell: {current})",
    "update.wizard.release_notes": "Release Notes:",
    "update.wizard.downloading": "Wird heruntergeladen...",
    "update.wizard.installing": "Wird installiert...",

    # -- License dialog ------------------------------------------
    "license.title": "Lizenz Aktivierung",
    "license.enter_key": "Bitte gib deinen Serial Key ein.",
    "license.trial_remaining": "Trial ({remaining} gültig)",
    "license.trial": "Trial",
    "license.days": "{n} Tage",
    "license.hours": "{n} Stunden",
    "license.minutes": "{n} Minuten",
    "license.validating": "Lizenz wird geprüft...",

    # -- Help dialog ---------------------------------------------
    "help.title": "Anleitung",
    "help.content": (
        "<h2>SW Team Optimizer – Kurzanleitung</h2>"

        "<h3>1. JSON importieren</h3>"
        "<p>Öffne den <b>Einstellungen</b>-Tab und klicke auf <b>JSON importieren</b>. "
        "Wähle deinen Summoners War JSON-Export (z.B. via SWEX). "
        "Nach dem Import zeigt der <b>Übersicht</b>-Tab deine Account-Statistiken, "
        "Runen-Effizienz-Diagramme und Artefakt-Übersicht.</p>"

        "<h3>2. Aktuelle Aufstellungen ansehen</h3>"
        "<p><b>Siege → Aktuell</b> – Zeigt deine Ingame-Siege-Verteidigungen "
        "als Karten mit allen Runen-Details.<br>"
        "<b>RTA → Aktuell</b> – Zeigt deine aktuell ausgerüsteten RTA-Monster "
        "mit Speed-Lead-Umschalter für Turn-Order-Vergleiche.</p>"

        "<h3>3. Teams im Builder zusammenstellen</h3>"
        "<p>Wechsle zum <b>Builder</b>-Unter-Tab des gewünschten Modus:</p>"
        "<ul>"
        "<li><b>Siege</b> – Bis zu 10 Verteidigungen × 3 Monster. "
        "Slot 1 bestimmt den Leader-Skill. "
        "<b>Aktuelle Siege-Verteidigungen übernehmen</b> lädt deine Ingame-Defs.</li>"
        "<li><b>WGB</b> – 5 Verteidigungen × 3 Monster.</li>"
        "<li><b>RTA</b> – Bis zu 15 Monster per Hinzufügen-Button, "
        "Reihenfolge per Drag &amp; Drop.</li>"
        "<li><b>Arena Rush</b> – 1 Arena-Defense (4 Monster) + bis zu 15 "
        "Offense-Teams (je 4 Monster, Checkbox <b>Aktiv</b> pro Team). "
        "<b>Aktuelle Arena-Def übernehmen</b> und <b>Arena-Offense Decks übernehmen</b> "
        "laden deine Ingame-Daten.</li>"
        "</ul>"

        "<h3>4. Builds definieren</h3>"
        "<p>Klicke auf <b>Builds (Sets+Mainstats)...</b> um pro Monster festzulegen:</p>"
        "<ul>"
        "<li><b>Sets</b> – Set 1 und Set 2 unterstützen Mehrfachauswahl. "
        "Nur gleichgroße Sets pro Slot (2er oder 4er). "
        "Set 3 ist nur aktiv wenn Set 1 und Set 2 beide 2er-Sets sind.</li>"
        "<li><b>Mainstats</b> – Slot 2, 4, 6; Mehrfachauswahl möglich (leer = beliebig).</li>"
        "<li><b>Artefakte</b> – Attribut- und Typ-Artefakt: Fokus und bis zu "
        "2 Substats wählbar (leer = beliebig).</li>"
        "<li><b>Min-Stats</b> – Mindestwerte (z.B. Min SPD 200).</li>"
        "<li><b>Priorität</b> – Niedrigere Zahl = erhält zuerst die besten Runen.</li>"
        "<li><b>Turn-Order</b> – Reihenfolge per Drag &amp; Drop; optionaler "
        "SPD-Tick erzwingt den exakten Breakpoint-Bereich (z.B. Tick 6 = SPD 239–285).</li>"
        "</ul>"

        "<h3>5. Optimieren</h3>"
        "<p>Klicke auf <b>Optimieren</b>. Verfügbare Profile:</p>"
        "<ul>"
        "<li><b>Fast</b> – Schnelle Suche mit geringem Suchraum.</li>"
        "<li><b>Balanced</b> – Breitere Suche mit Verfeinerung; "
        "1–10 Durchläufe, stoppt früh wenn keine Verbesserung mehr möglich ist.</li>"
        "<li><b>Max Qualität</b> – Globale Optimierung über alle Monster gleichzeitig.</li>"
        "</ul>"
        "<p>Bei <b>Fast</b> und <b>Balanced</b> ist die Drag &amp; Drop "
        "Reihenfolge in der Monsterliste wichtig – Monster weiter oben "
        "wählen zuerst aus dem gemeinsamen Runen-Pool.<br>"
        "Für <b>Arena Rush</b> stehen die Profile <b>Max Qualität</b> und "
        "<b>Ultra (langsam)</b> zur Verfügung.</p>"

        "<h3>6. Ergebnisse speichern</h3>"
        "<p>Optimierungen werden nach dem Speichern im jeweiligen "
        "<b>Gespeichert</b>-Unter-Tab angezeigt und können dort "
        "geladen oder gelöscht werden.</p>"

        "<h3>Tipps</h3>"
        "<ul>"
        "<li>Im Runen-Diagramm mit <b>Strg+Scrollen</b> die Anzahl der "
        "angezeigten Top-Runen anpassen.</li>"
        "<li>Maus über einen Datenpunkt im Diagramm → Runen-Details "
        "inkl. Subs und Grinds.</li>"
        "<li>Substats die per <span style='color:#1abc9c'><b>Gem</b></span> "
        "getauscht wurden, sind farblich hervorgehoben.</li>"
        "<li>Tabs lassen sich per Drag &amp; Drop in der Tab-Leiste "
        "umsortieren.</li>"
        "</ul>"
    ),

    # -- Optimizer messages --------------------------------------
    "opt.slot_no_runes": "Slot {slot}: keine Runen im Pool.",
    "opt.no_attr_artifact": "Kein Attribut-Artefakt (Typ 1) im Pool.",
    "opt.no_type_artifact": "Kein Typ-Artefakt (Typ 2) im Pool.",
    "opt.no_builds": "Keine Builds vorhanden.",
    "opt.feasible": "Build ist bzgl. Runen/Artefakten grundsätzlich machbar.",
    "opt.mainstat_missing": "Build '{name}': Slot {slot} Mainstat {allowed} nicht verfügbar.",
    "opt.no_artifact_match": (
        "Build '{name}': kein passendes Artefakt für "
        "{kind} (Fokus={focus}, Subs={subs})."
    ),
    "opt.set_too_many": "Build '{name}': Set-Option {opt} benötigt {pieces} Teile (>6).",
    "opt.set_not_enough": "Build '{name}': Set {set_id} braucht {pieces}, verfügbar {avail}.",
    "opt.infeasible": "Nicht erfuellbar: Pool/Build-Constraints passen nicht zusammen.",
    "opt.not_feasible": "Nicht erfuellbar: {detail}",
    "opt.internal_no_rune": "Interner Fehler: Slot {slot} keine Rune.",
    "opt.internal_no_artifact": "Interner Fehler: Artefakt-Typ {art_type} fehlt.",
    "opt.no_units": "Keine Units.",
    "opt.ok": "OK",
    "opt.cancelled": "Optimierung abgebrochen.",
    "opt.partial_fail": "Fertig, aber mindestens ein Monster konnte nicht gebaut werden.",
    "opt.stable_solution": "stabile Lösung ohne weitere Verbesserung",
    "opt.no_improvement": "keine Verbesserung in aufeinanderfolgenden Passes",
    "opt.multi_pass": (
        "{prefix} Multi-Pass aktiv: bestes Ergebnis aus {used} "
        "Durchläufen (Pass {pass_idx})."
    ),
    "opt.multi_pass_early": (
        "{prefix} Multi-Pass aktiv: bestes Ergebnis aus {used} von {planned} "
        "geplanten Durchläufen (Pass {pass_idx}); vorzeitig gestoppt "
        "({reason})."
    ),

    # -- Update service messages ---------------------------------
    "svc.no_repo": "Kein GitHub-Repo konfiguriert (github_repo fehlt).",
    "svc.no_version": "Kein release-fähiger app_version-Wert gesetzt.",
    "svc.check_failed": "Update-Prüfung fehlgeschlagen: {detail}",
    "svc.invalid_response": "Update-Prüfung: ungültige API-Antwort.",
    "svc.unexpected_format": "Update-Prüfung: unerwartetes Datenformat.",
    "svc.no_asset": "Kein passendes Download-Asset im Release gefunden.",
    "svc.download_http_fail": "Download fehlgeschlagen (HTTP {status}).",
    "svc.download_failed": "Download fehlgeschlagen: {detail}",
    "svc.download_ok": "Update erfolgreich heruntergeladen.",
    "svc.auto_zip_only_frozen": "Update per ZIP ist nur in der EXE-Version verfügbar.",
    "svc.auto_install_dir_missing": "Installationsordner nicht gefunden.",
    "svc.auto_exe_missing": "Aktuelle EXE wurde nicht gefunden.",
    "svc.auto_install_failed": "Automatische Installation fehlgeschlagen: {detail}",
    "svc.auto_relaunch_failed": "Update installiert, aber Neustart fehlgeschlagen: {detail}",
    "svc.auto_zip_installed": "Update installiert. App wird neu gestartet.",
    "svc.auto_installer_failed": "Installer konnte nicht gestartet werden: {detail}",
    "svc.auto_installer_started": "Installer gestartet. Bitte Installation abschließen.",
    "svc.auto_updater_launch_failed": "Updater konnte nicht gestartet werden: {detail}",
    "svc.auto_updater_state_invalid": "Updater-Start fehlgeschlagen: {detail}",

    # -- License service messages --------------------------------
    "lic.invalid_response": "Ungültige Server-Antwort ({status}).",
    "lic.server_error": "Server-Fehler ({status}).",
    "lic.activation_failed": "Aktivierung fehlgeschlagen.",
    "lic.activated": "Lizenz aktiviert.",
    "lic.check_failed": "Lizenzprüfung fehlgeschlagen.",
    "lic.valid": "Lizenz gültig.",
    "lic.valid_cached": "Lizenz temporär aus lokalem Cache verifiziert.",
    "lic.no_key": "Kein Key eingegeben.",
    "lic.network_error": "Netzwerkfehler bei Lizenzprüfung: {detail}",
    "lic.not_configured": "Lizenz-Server nicht konfiguriert (license_config.json fehlt/unvollständig).",

    # -- Overview widget -----------------------------------------
    "overview.monsters": "Monster",
    "overview.runes": "Runen",
    "overview.artifacts": "Artefakte",
    "overview.rune_eff": "Runen-Eff. (%)",
    "overview.attr_art_eff": "Attribut-Artefakt-Eff. (%)",
    "overview.type_art_eff": "Typ-Artefakt-Eff. (%)",
    "overview.best_rune": "Beste Rune",
    "overview.set_eff": "{name} Eff. (%)",
    "overview.chart_top_label": "Runen-Chart Top:",
    "overview.rune_set_filter_label": "Set-Filter:",
    "overview.filter_all_sets": "Alle Sets",
    "overview.rune_eff_chart": "Runen-Effizienz (Top {n})",
    "overview.set_dist_chart": "Runen-Set-Verteilung",
    "overview.set_eff_chart": "Wichtige Sets Effizienz (Top {n})",
    "overview.art_eff_chart": "Artefakt-Effizienz (Top {n})",
    "overview.axis_count": "Anzahl / Rang",
    "overview.axis_eff": "Effizienz (%)",
    "overview.series_current": "Aktuell",
    "overview.series_hero_max": "Hero max",
    "overview.series_legend_max": "Legend max",
    "overview.series_attr_art": "Attribut-Artefakt",
    "overview.series_type_art": "Typ-Artefakt",
    "overview.other": "Andere ({count})",
    "overview.rank": "Rang #{idx}",
    "overview.efficiency": "Effizienz",
    "overview.quality": "Qualität",
    "overview.current_eff": "Aktuell: {eff}%",
    "overview.hero_max": "Hero max (Grind/Gem): {eff}%",
    "overview.legend_max": "Legend max (Grind/Gem): {eff}%",
    "overview.slot_left": "Links",
    "overview.slot_right": "Rechts",
    "overview.mainstat": "Hauptstat:",

    # -- RTA overview --------------------------------------------
    "rta.spd_lead": "<b>SPD Lead:</b>",
    "rta.no_lead": "Kein Lead (0%)",

    # -- RTA validation messages ---------------------------------
    "rta.no_monsters": "RTA: Keine Monster ausgewählt.",
    "rta.duplicate": "RTA: '{name}' ist doppelt ausgewählt.",
    "rta.ok": "RTA: OK ({count} Monster).",
    "arena_rush.mode": "Arena Rush",

    # -- Tabs (Einstellungen) ------------------------------------
    "tab.settings": "Einstellungen",

    # -- Settings tab --------------------------------------------
    "settings.group_account": "Account / JSON Import",
    "settings.group_license": "Lizenzverwaltung",
    "settings.group_language": "Sprache",
    "settings.group_data": "Datenverwaltung",
    "settings.group_updates": "Updates",
    "settings.group_about": "Über",

    "settings.btn_import": "JSON importieren...",
    "settings.btn_clear_snapshot": "Snapshot löschen",
    "settings.label_import_status": "Aktuell: {source}",
    "settings.label_import_date": "Importiert: {date}",
    "settings.label_no_import": "Kein Import geladen.",

    "settings.label_license_type": "Lizenz: {type}",
    "settings.label_license_type_trial": "Trial ({remaining} verbleibend)",
    "settings.label_license_type_full": "Vollversion",
    "settings.label_license_key": "Key: {license_key}",
    "settings.label_no_license": "Keine Lizenz aktiv.",
    "settings.license_activated": "Lizenz erfolgreich aktiviert.",
    "settings.license_activation_failed": "Aktivierung fehlgeschlagen: {message}",

    "settings.label_language": "Sprache:",

    "settings.btn_reset_presets": "Build-Presets zurücksetzen",
    "settings.btn_clear_optimizations": "Gespeicherte Optimierungen löschen",
    "settings.btn_clear_teams": "Teams löschen",
    "settings.confirm_reset_presets": "Wirklich alle Build-Presets auf Standard zurücksetzen?",
    "settings.confirm_clear_optimizations": "Wirklich alle gespeicherten Optimierungen löschen?",
    "settings.confirm_clear_teams": "Wirklich alle Teams löschen?",
    "settings.confirm_clear_snapshot": "Wirklich den importierten Account-Snapshot löschen?",
    "settings.confirm_title": "Bestätigen",
    "settings.data_cleared": "{name} gelöscht.",

    "settings.btn_check_update": "Nach Updates suchen",
    "settings.label_version": "Version: {version}",
    "settings.update_checking": "Suche nach Updates...",
    "settings.update_no_update": "Du verwendest die neueste Version ({version}).",
    "settings.update_error": "Update-Prüfung fehlgeschlagen.",

    "settings.about_version": "App-Version: {version}",
    "settings.about_license": "Lizenz: {type}",
    "settings.about_creator": "Ersteller: {name}",
    "settings.about_discord": "Discord: {handle}",
    "settings.btn_open_discord_dm": "Discord-DM öffnen",
    "settings.discord_opened": "Discord wurde geöffnet. Schreibe {handle} eine DM.",
    "settings.discord_open_failed": "Discord konnte nicht geöffnet werden. Kontakt: {handle}",
    "settings.about_open_source": (
        "Open Source: "
        "<a href='https://www.qt.io/'>PySide6 (Qt)</a>, "
        "<a href='https://developers.google.com/optimization'>OR-Tools</a>, "
        "<a href='https://requests.readthedocs.io/'>Requests</a>"
    ),
    "settings.about_data_sources": (
        "Datenquellen: "
        "<a href='https://swarfarm.com/api/'>Swarfarm API</a> "
        "(Monster, Skills, Skill-Icons)."
    ),
    "settings.about_data_dir": "Datenverzeichnis: {path}",
}
