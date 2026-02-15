"""German translations (default language)."""

STRINGS: dict[str, str] = {
    # ── Main Window ─────────────────────────────────────────────
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

    # ── Tabs ────────────────────────────────────────────────────
    "tab.overview": "Übersicht",
    "tab.siege_current": "Siege Verteidigungen (aktuell)",
    "tab.rta_current": "RTA (aktuell)",
    "tab.siege_builder": "Siege Builder (Custom)",
    "tab.siege_saved": "Siege Optimierungen (gespeichert)",
    "tab.wgb_builder": "WGB Builder (Custom)",
    "tab.wgb_saved": "WGB Optimierungen (gespeichert)",
    "tab.rta_builder": "RTA Builder (Custom)",
    "tab.rta_saved": "RTA Optimierungen (gespeichert)",

    # ── Buttons ─────────────────────────────────────────────────
    "btn.add": "Hinzufügen",
    "btn.remove": "Entfernen",
    "btn.close": "Schließen",
    "btn.save": "Speichern",
    "btn.saved": "Gespeichert",
    "btn.delete": "Löschen",
    "btn.validate": "Validieren",
    "btn.validate_pools": "Validieren (Pools/Teams)",
    "btn.builds": "Builds (Sets+Mainstats)…",
    "btn.optimize": "Optimieren (Runen)",
    "btn.activate": "Aktivieren",
    "btn.quit": "Beenden",
    "btn.later": "Spaeter",
    "btn.release_page": "Release-Seite",
    "btn.new_team": "Neues Team",
    "btn.edit_team": "Team bearbeiten",
    "btn.delete_team": "Team löschen",
    "btn.optimize_team": "Team optimieren",
    "btn.take_siege": "Aktuelle Siege-Verteidigungen übernehmen",
    "btn.take_rta": "Aktuelle RTA Monster übernehmen",

    # ── Labels ──────────────────────────────────────────────────
    "label.passes": "Durchläufe",
    "label.saved_opt": "Gespeicherte Optimierung:",
    "label.team": "Team",
    "label.team_name": "Team-Name",
    "label.defense": "Verteidigung {n}",
    "label.import_account_first": "Importiere zuerst ein Konto.",
    "label.no_teams": "Keine Teams definiert.",
    "label.no_team_selected": "Kein Team ausgewählt.",
    "label.no_units": "Keine Units.",
    "label.error": "Fehler",

    # ── Tooltips ────────────────────────────────────────────────
    "tooltip.set_multi": "Mehrfachauswahl. Nach erster Auswahl nur gleich große Sets (2er/4er).",
    "tooltip.set3": "Nur aktiv, wenn Set 1 und Set 2 jeweils 2er-Sets sind.",
    "tooltip.mainstat_multi": "Mehrfachauswahl möglich. Keine Auswahl = Any.",
    "tooltip.art_attr_focus": "Attribut-Artefakt: HP/ATK/DEF (Mehrfachauswahl, leer = Any).",
    "tooltip.art_type_focus": "Typ-Artefakt: HP/ATK/DEF (Mehrfachauswahl, leer = Any).",
    "tooltip.art_sub": "{kind}-Artefakt: Substat auswählen (leer = Any).",
    "tooltip.passes": "Anzahl Optimizer-Durchläufe (1 = nur ein Durchlauf).",

    # ── Group Boxes ─────────────────────────────────────────────
    "group.opt_order": "Optimierungsreihenfolge (Drag & Drop)",
    "group.turn_order": "Turn Order pro Team (Drag & Drop)",
    "group.siege_select": "Siege-Teams auswählen (bis zu 10 Verteidigungen × 3 Monster)",
    "group.wgb_select": "WGB-Teams auswählen (5 Verteidigungen × 3 Monster)",
    "group.rta_select": "RTA Monster auswählen (bis zu 15 – Reihenfolge per Drag & Drop)",

    # ── Table Headers ───────────────────────────────────────────
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
    "header.min_cr": "Min CR",
    "header.min_cd": "Min CD",
    "header.min_res": "Min RES",
    "header.min_acc": "Min ACC",
    "header.stat": "Stat",
    "header.base": "Basis",
    "header.runes": "Runen",
    "header.leader": "Leader",
    "header.total": "Gesamt",
    "header.value": "Wert",

    # ── Status / Validation ─────────────────────────────────────
    "status.siege_ready": "Bereit. Siege auswählen/übernehmen -> Validieren -> Builds -> Optimieren.",
    "status.wgb_ready": "Bereit. (WGB) Teams auswählen.",
    "status.siege_taken": "Aktuelle Verteidigungen übernommen. Bitte validieren.",
    "status.rta_taken": "{count} aktive RTA Monster übernommen.",
    "status.pass_progress": "{prefix}: Durchlauf {current}/{total}...",

    # ── Validation Messages ─────────────────────────────────────
    "val.incomplete_team": "{label}: Team {team} ist unvollständig ({have}/{need}).",
    "val.duplicate_in_team": "{label}: Team {team} enthält '{name}' doppelt.",
    "val.no_teams": "{label}: Keine Teams ausgewählt.",
    "val.ok": "{label}: OK ({count} Units).",
    "val.no_account": "Kein Account geladen.",
    "val.duplicate_monster_wgb": "Monster '{name}' kommt mehrfach vor (WGB erlaubt jedes Monster nur 1×).",
    "val.title_siege": "Siege Validierung",
    "val.title_siege_ok": "Siege Validierung OK",
    "val.title_wgb": "WGB Validierung",
    "val.title_wgb_ok": "WGB Validierung OK",
    "val.title_rta": "RTA Validierung",
    "val.title_rta_ok": "RTA Validierung OK",
    "val.set_invalid": "Ungültige Set-Kombi für {unit}: keine der Set-Optionen passt in 6 Slots.",

    # ── Dialog Messages ─────────────────────────────────────────
    "dlg.team_needs_units_title": "Team braucht Units",
    "dlg.team_needs_units": "Bitte füge mindestens ein Monster hinzu.",
    "dlg.load_import_first": "Bitte zuerst einen Import laden.",
    "dlg.load_import_and_team": "Bitte zuerst einen Import laden und ein Team auswählen.",
    "dlg.validate_first": "Bitte erst validieren.\n\n{msg}",
    "dlg.select_monsters_first": "Bitte erst Monster auswählen.",
    "dlg.duplicates_found": "Duplikate gefunden. Bitte erst validieren.",
    "dlg.max_15_rta": "Maximal 15 Monster erlaubt.",
    "dlg.delete_confirm": "'{name}' wirklich löschen?",
    "dlg.builds_saved_title": "Builds gespeichert",
    "dlg.builds_saved": "Gespeichert in {path}",
    "dlg.select_left": "Bitte links ein Monster auswählen.",
    "dlg.no_result": "Kein Ergebnis gefunden.",

    # ── Optimization result display ─────────────────────────────
    "result.title_team": "Team Optimierung: {name}",
    "result.title_siege": "Greedy Optimierung",
    "result.title_wgb": "WGB Greedy Optimierung",
    "result.title_rta": "RTA Greedy Optimierung",
    "result.opt_running": "{mode} Optimierung läuft",
    "result.team_opt_running": "Team '{name}' Optimierung läuft",
    "result.avg_rune_eff": "Ø Rune-Effizienz: <b>{eff}%</b>",
    "result.avg_rune_eff_none": "Ø Rune-Effizienz: <b>—</b>",
    "result.opt_name": "{mode} Optimierung {ts}",

    # ── Saved optimization display names ────────────────────────
    "saved.opt_replace": " Optimierung ",
    "saved.siege_opt": "SIEGE Optimierung",
    "saved.wgb_opt": "WGB Optimierung",
    "saved.rta_opt": "RTA Optimierung",

    # ── Stat Labels ─────────────────────────────────────────────
    "stat.HP": "LP",
    "stat.ATK": "Angriff",
    "stat.DEF": "Verteidigung",
    "stat.SPD": "Tempo",
    "stat.CR": "Krit.-Rate",
    "stat.CD": "Krit.-Schaden",
    "stat.RES": "Widerstand",
    "stat.ACC": "Präzision",

    # ── Siege cards stat labels ─────────────────────────────────
    "card_stat.HP": "HP",
    "card_stat.ATK": "ATK",
    "card_stat.DEF": "DEF",
    "card_stat.SPD": "SPD",
    "card_stat.CR": "Krit. Rate",
    "card_stat.CD": "Krit. Schdn",
    "card_stat.RES": "RES",
    "card_stat.ACC": "ACC",

    # ── Artifact labels ─────────────────────────────────────────
    "artifact.attribute": "Attribut",
    "artifact.type": "Typ",
    "artifact.no_rune": "Kein Rune",
    "artifact.no_artifact": "Kein Artefakt",

    # ── Update dialog ───────────────────────────────────────────
    "update.title": "Update verfuegbar",
    "update.text": "Neue Version verfuegbar: {latest}\nInstalliert: {current}",
    "update.open_release": "GitHub-Release jetzt oeffnen?",

    # ── License dialog ──────────────────────────────────────────
    "license.title": "Lizenz Aktivierung",
    "license.enter_key": "Bitte gib deinen Serial Key ein.",
    "license.trial_remaining": "Trial ({remaining} gültig)",
    "license.trial": "Trial",
    "license.days": "{n} Tage",
    "license.hours": "{n} Stunden",
    "license.minutes": "{n} Minuten",

    # ── Help dialog ─────────────────────────────────────────────
    "help.title": "Anleitung",
    "help.content": (
        "<h2>SW Team Optimizer – Kurzanleitung</h2>"

        "<h3>1. JSON importieren</h3>"
        "<p>Klicke auf <b>JSON importieren</b> und wähle deinen "
        "Summoners War JSON-Export aus. Nach dem Import siehst du "
        "auf dem <b>Übersicht</b>-Tab deine Account-Statistiken, "
        "Runen-Effizienz-Charts und die Set-Verteilung.</p>"

        "<h3>2. Aktuelle Aufstellungen ansehen</h3>"
        "<p><b>Siege Verteidigungen (aktuell)</b> – Zeigt deine im Spiel "
        "eingestellten Siege-Verteidigungen als Karten mit Runen-Details.<br>"
        "<b>RTA (aktuell)</b> – Zeigt deine aktuell für RTA gerüsteten Monster.</p>"

        "<h3>3. Teams zusammenstellen</h3>"
        "<p>In den <b>Builder</b>-Tabs (Siege / WGB / RTA) kannst du "
        "eigene Team-Aufstellungen erstellen:</p>"
        "<ul>"
        "<li><b>Monster wählen</b> – Über die Dropdowns je Verteidigung (Siege/WGB) "
        "oder per Hinzufügen-Button (RTA).</li>"
        "<li><b>Aktuelle übernehmen</b> – Übernimmt die im Spiel eingestellten Teams.</li>"
        "<li><b>Validieren</b> – Prüft ob Runen-Pools kollidieren und zeigt Warnungen.</li>"
        "</ul>"

        "<h3>4. Builds definieren</h3>"
        "<p>Klicke auf <b>Builds (Sets+Mainstats)…</b> um je Monster "
        "die gewünschten Runen-Sets und Slot-2/4/6-Hauptstats festzulegen. "
        "Bei Mainstats ist Mehrfachauswahl möglich (keine Auswahl = Any). "
        "Set-Logik: In Set 1 und Set 2 ist Mehrfachauswahl möglich. "
        "Pro Set-Slot sind nur gleich große Sets erlaubt (2er oder 4er). "
        "Set 3 ist nur aktiv, wenn Set 1 und Set 2 jeweils 2er-Sets sind. "
        "Hier kannst du auch Mindest-Werte (z.B. min SPD) definieren.</p>"

        "<h3>5. Optimieren</h3>"
        "<p>Klicke auf <b>Optimieren (Runen)</b> um die automatische "
        "Runen-Verteilung zu starten. Der Optimizer verteilt deine Runen "
        "so, dass die Vorgaben möglichst effizient erfüllt werden. "
        "Die Turn-Order innerhalb von Teams wird dabei immer erzwungen. "
        "Über <b>Durchläufe</b> kannst du 1-10 Multi-Pass-Runs wählen; "
        "wenn keine Verbesserung mehr möglich ist, stoppt der Optimizer vorzeitig. "
        "Das Ergebnis kannst du als Karten mit allen Stats und Runen-Details sehen.</p>"

        "<h3>6. Ergebnisse speichern</h3>"
        "<p>Optimierungen werden automatisch gespeichert und können "
        "in den <b>Optimierungen (gespeichert)</b>-Tabs jederzeit "
        "wieder aufgerufen oder gelöscht werden.</p>"

        "<h3>Tipps</h3>"
        "<ul>"
        "<li>Im Runen-Chart kannst du mit <b>Strg+Mausrad</b> die Anzahl "
        "der angezeigten Top-Runen ändern.</li>"
        "<li>Fahre mit der Maus über einen Datenpunkt im Chart, um "
        "Runen-Details inkl. Subs und Grinds zu sehen.</li>"
        "<li>Subs die mit einem <span style='color:#1abc9c'><b>Gem</b></span> "
        "getauscht wurden, werden farblich hervorgehoben.</li>"
        "</ul>"
    ),

    # ── Optimizer messages ──────────────────────────────────────
    "opt.slot_no_runes": "Slot {slot}: keine Runen im Pool.",
    "opt.no_attr_artifact": "Kein Attribut-Artefakt (Typ 1) im Pool.",
    "opt.no_type_artifact": "Kein Typ-Artefakt (Typ 2) im Pool.",
    "opt.no_builds": "Keine Builds vorhanden.",
    "opt.feasible": "Build ist bzgl. Runen/Artefakten grundsätzlich machbar.",
    "opt.mainstat_missing": "Build '{name}': Slot {slot} Mainstat {allowed} nicht verfügbar.",
    "opt.no_artifact_match": (
        "Build '{name}': kein passendes Artefakt für "
        "{kind} (Focus={focus}, Subs={subs})."
    ),
    "opt.set_too_many": "Build '{name}': Set-Option {opt} verlangt {pieces} Teile (>6).",
    "opt.set_not_enough": "Build '{name}': Set {set_id} braucht {pieces}, verfügbar {avail}.",
    "opt.infeasible": "Infeasible: Pool/Build-Constraints passen nicht zusammen.",
    "opt.internal_no_rune": "interner Fehler: Slot {slot} keine Rune.",
    "opt.internal_no_artifact": "interner Fehler: Artefakt Typ {art_type} fehlt.",
    "opt.no_units": "Keine Units.",
    "opt.ok": "OK",
    "opt.partial_fail": "Fertig, aber mindestens ein Monster konnte nicht gebaut werden.",
    "opt.stable_solution": "stabile Lösung ohne weiteren Gewinn",
    "opt.no_improvement": "keine Verbesserung in aufeinanderfolgenden Durchläufen",
    "opt.multi_pass": (
        "{prefix} Multi-Pass aktiv: bestes Ergebnis aus {used} "
        "Durchläufen (Pass {pass_idx})."
    ),
    "opt.multi_pass_early": (
        "{prefix} Multi-Pass aktiv: bestes Ergebnis aus {used} von {planned} "
        "geplanten Durchläufen (Pass {pass_idx}); vorzeitig gestoppt "
        "({reason})."
    ),

    # ── Update service messages ─────────────────────────────────
    "svc.no_repo": "Kein GitHub-Repo konfiguriert (github_repo fehlt).",
    "svc.no_version": "Kein releasefaehiger app_version-Wert gesetzt.",
    "svc.check_failed": "Update-Check fehlgeschlagen: {detail}",
    "svc.invalid_response": "Update-Check: ungueltige API-Antwort.",
    "svc.unexpected_format": "Update-Check: unerwartetes Datenformat.",
    "svc.no_asset": "Kein passendes Download-Asset im Release gefunden.",
    "svc.download_http_fail": "Download fehlgeschlagen (HTTP {status}).",
    "svc.download_failed": "Download fehlgeschlagen: {detail}",
    "svc.download_ok": "Update erfolgreich heruntergeladen.",

    # ── License service messages ────────────────────────────────
    "lic.invalid_response": "Ungültige Serverantwort ({status}).",
    "lic.server_error": "Serverfehler ({status}).",
    "lic.activation_failed": "Aktivierung fehlgeschlagen.",
    "lic.activated": "Lizenz aktiviert.",
    "lic.check_failed": "Lizenzprüfung fehlgeschlagen.",
    "lic.valid": "Lizenz gültig.",
    "lic.no_key": "Kein Key eingegeben.",
    "lic.not_configured": "Lizenz-Server nicht konfiguriert (license_config.json fehlt/ist unvollständig).",

    # ── Overview widget ─────────────────────────────────────────
    "overview.monsters": "Monster",
    "overview.runes": "Runen",
    "overview.artifacts": "Artefakte",
    "overview.rune_eff": "Runen Eff. (%)",
    "overview.attr_art_eff": "Attribut-Artefakt Eff. (%)",
    "overview.type_art_eff": "Typ-Artefakt Eff. (%)",
    "overview.best_rune": "Beste Rune",
    "overview.set_eff": "{name} Eff. (%)",
    "overview.chart_top_label": "Runen-Chart Top:",
    "overview.rune_eff_chart": "Runen Effizienz (Top {n})",
    "overview.set_dist_chart": "Runen Set Verteilung",
    "overview.set_eff_chart": "Wichtige Sets Effizienz (Top {n})",
    "overview.art_eff_chart": "Artefakt Effizienz (Top {n})",
    "overview.axis_count": "Anzahl / Rank",
    "overview.axis_eff": "Effizienz (%)",
    "overview.series_current": "Aktuell",
    "overview.series_attr_art": "Attribut-Artefakt",
    "overview.series_type_art": "Typ-Artefakt",
    "overview.other": "Andere ({count})",
    "overview.rank": "Rank #{idx}",
    "overview.efficiency": "Effizienz",
    "overview.quality": "Qualität",
    "overview.current_eff": "Aktuell: {eff}%",
    "overview.hero_max": "Hero max (Grind/Gem): {eff}%",
    "overview.legend_max": "Legend max (Grind/Gem): {eff}%",
    "overview.slot_left": "Links",
    "overview.slot_right": "Rechts",
    "overview.mainstat": "Hauptstat:",

    # ── RTA overview ────────────────────────────────────────────
    "rta.spd_lead": "<b>SPD Lead:</b>",
    "rta.no_lead": "Kein Lead (0%)",

    # ── Siege cards ─────────────────────────────────────────────
    "card.avg_rune_eff": "Ø Rune-Effizienz: <b>{eff}%</b>",
    "card.avg_rune_eff_none": "Ø Rune-Effizienz: <b>—</b>",
    "card.focus": "Fokus:",
    "card.defense": "Verteidigung {n}",

    # ── RTA validation messages ─────────────────────────────────
    "rta.no_monsters": "RTA: Keine Monster ausgewählt.",
    "rta.duplicate": "RTA: '{name}' ist doppelt ausgewählt.",
    "rta.ok": "RTA: OK ({count} Monster).",
}
