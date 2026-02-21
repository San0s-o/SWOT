# SWTO – Summoners War Team Optimizer

Runen-Optimierer und Team-Builder für Summoners War. Verteilt Runen und Artefakte automatisch optimal auf deine Monster – für Siege, WGB, RTA und Arena Rush.

---

## Inhaltsverzeichnis

1. [Features](#features)
2. [Tab-Übersicht](#tab-übersicht)
3. [Kurzanleitung](#kurzanleitung)
4. [Build-Konfiguration](#build-konfiguration)
5. [Qualitätsprofile](#qualitätsprofile)
6. [Systemanforderungen](#systemanforderungen)
7. [Lizenz](#lizenz)
8. [Technisches](#technisches)

---

## Features

| Bereich | Beschreibung |
|---|---|
| **Account-Import** | Summoners War JSON-Export laden (z.B. via SWEX) – alle Monster, Runen und Artefakte sofort verfügbar |
| **Übersicht** | Account-Statistiken, Runen-Effizienz-Diagramme, Set-Verteilung, Artefakt-Übersicht |
| **Siege Builder** | Bis zu 10 Verteidigungsteams (je 3 Monster) auswählen, konfigurieren und optimieren |
| **WGB Builder** | 5 Verteidigungsteams (je 3 Monster) für World Guild Battle |
| **RTA Builder** | Bis zu 15 Monster per Drag & Drop in beliebiger Reihenfolge – mit aktuellem RTA-Snapshot |
| **Arena Rush Builder** | 1 Arena-Defense (4 Monster) + bis zu 15 Offense-Teams (je 4 Monster) |
| **Runen & Artefakte** | Tabellenansicht aller Runen (ab +12) und Artefakte mit Filter und Effizienz-Werten |
| **Team Builder** | Eigene Teams für PvE oder sonstige Planung |
| **Build-Presets** | Pro Monster: erlaubte Sets, Mainstats, Artefakt-Substats, Min-Stats, Priorität, Turn-Order |
| **Runen-Optimierung** | Automatische Zuweisung via OR-Tools Constraint Solver, inkl. Artefakt-Zuweisung |
| **Optimierungen speichern** | Ergebnisse werden gespeichert und können jederzeit eingesehen und verglichen werden |

---

## Tab-Übersicht

Die App ist in Gruppen-Tabs organisiert. Viele Tabs haben Unter-Tabs (Aktuell / Builder / Gespeichert):

| Gruppen-Tab | Unter-Tabs | Inhalt |
|---|---|---|
| **Übersicht** | – | Statistiken, Diagramme, Set-Verteilung |
| **Siege** | Aktuell · Builder · Gespeichert | Ingame-Siege-Defs anzeigen, eigene konfigurieren, Ergebnisse ansehen |
| **World Guild Battle** | Builder · Gespeichert | WGB-Teams konfigurieren und Ergebnisse ansehen |
| **RTA** | Aktuell · Builder · Gespeichert | RTA-Monster anzeigen, eigene Liste erstellen, Ergebnisse ansehen |
| **Arena Rush** | Builder · Gespeichert | Defense + Offense-Teams konfigurieren, Ergebnisse ansehen |
| **Runen & Artefakte** | Runen · Artefakte | Filterbare Tabellen mit Effizienz-Werten |
| **Einstellungen** | – | Import, Lizenz, Sprache, Datenverwaltung, Updates |

---

## Kurzanleitung

### 1. Account importieren

Exportiere deinen Summoners War Account als JSON (z.B. via SWEX) und importiere die Datei über den **Einstellungen**-Tab oder direkt über den Import-Button.

### 2. Übersicht prüfen

Im Tab **Übersicht** siehst du:
- Anzahl Monster, Runen und Artefakte
- Runen-Effizienz-Diagramm mit Hover-Details (Strg+Scrollen ändert die Top-N-Anzeige)
- Runen-Verteilung nach Set und Qualität
- Artefakt-Effizienz

### 3. Aktuelle Aufstellungen ansehen

- **Siege → Aktuell** – Deine aktuell angelegten Siege-Defs als Karten mit Runen-Details
- **RTA → Aktuell** – Deine aktuell ausgerüsteten RTA-Monster mit Speed-Lead-Umschalter

### 4. Teams zusammenstellen

Wechsle zum **Builder**-Unter-Tab des gewünschten Modus:

**Siege Builder** (`Siege → Builder`)
- Bis zu 10 Verteidigungen mit je 3 Monstern
- Slot 1 bestimmt den Leader-Skill des Teams
- **Aktuelle Siege-Verteidigungen übernehmen** – lädt die Ingame-Aufstellung
- Checkbox **Runen/Artefakte nicht-optimierter Defs sperren** – sperrt Runen von Verteidigungen, die per Checkbox deaktiviert sind

**WGB Builder** (`World Guild Battle → Builder`)
- 5 Verteidigungen mit je 3 Monstern
- Slot 1 bestimmt den Leader-Skill

**RTA Builder** (`RTA → Builder`)
- Bis zu 15 Monster, Reihenfolge per Drag & Drop
- **Aktuelle RTA Monster übernehmen** – lädt die Ingame-Aufstellung

**Arena Rush Builder** (`Arena Rush → Builder`)
- **Arena Defense** – 1 Team mit 4 Monstern (deine zu verteidigende Aufstellung)
- **Arena Offense Teams** – bis zu 15 Teams mit je 4 Monstern (Checkbox „Aktiv" pro Team)
- **Aktuelle Arena-Def übernehmen** / **Arena-Offense Decks übernehmen** – lädt Ingame-Daten

### 5. Builds konfigurieren

Klicke auf **Builds (Sets+Mainstats)...** um pro Monster festzulegen:

| Einstellung | Beschreibung |
|---|---|
| **Set 1 / Set 2** | Erlaubte Runen-Sets, Mehrfachauswahl. Nur gleichgroße Sets pro Slot (2er oder 4er). |
| **Set 3** | Nur aktiv wenn Set 1 und Set 2 beide 2er-Sets sind. |
| **Mainstats** | Erlaubte Mainstats für Slot 2, 4, 6. Mehrfachauswahl möglich, leer = beliebig. |
| **Artefakte** | Attribut- und Typ-Artefakt: Fokus (HP/ATK/DEF) und bis zu 2 Substats, leer = beliebig. |
| **Min-Stats** | Mindestwerte (z.B. Min SPD 200). Optional mit Base-Stats-Modus. |
| **Priorität** | Niedrigere Zahl = bekommt zuerst die besten Runen aus dem Pool. |
| **Turn-Order** | Reihenfolge pro Team (Drag & Drop). Optional SPD-Tick pro Monster für exakte Breakpoints. |
| **Durchläufe** | Anzahl Multi-Pass-Durchläufe (1–10), stoppt vorzeitig bei keiner Verbesserung. |
| **Qualitätsprofil** | Siehe [Qualitätsprofile](#qualitätsprofile). |

### 6. Optimieren

Klicke auf **Optimieren**. Der Optimizer:
1. Beachtet alle Set-, Mainstat-, Min-Stat- und Turn-Order-Vorgaben
2. Weist passende Artefakte basierend auf Artefakt-Build-Vorgaben zu
3. Zeigt während der Berechnung einen Fortschrittsdialog

Das Ergebnis zeigt pro Monster:
- Zugewiesene Runen (Slot 1–6) mit allen Stats
- Zugewiesene Artefakte
- Berechnete Endwerte (HP, ATK, DEF, SPD, CR, CD, RES, ACC)
- Leader-Skill-Boni

### 7. Ergebnis speichern & vergleichen

Klicke auf **Speichern** im Ergebnis-Dialog. Unter dem jeweiligen **Gespeichert**-Unter-Tab kannst du frühere Optimierungen laden, ansehen und löschen.

---

## Build-Konfiguration

### Optimierungsreihenfolge

Bei `Fast` und `Balanced` ist die **Drag & Drop Reihenfolge** in der Monsterliste entscheidend: Monster weiter oben wählen zuerst aus dem gemeinsamen Runen-Pool. Bei `Max Qualität` wird global über alle Monster gleichzeitig optimiert.

### Arena Rush Besonderheiten

- Kein Multi-Pass (Durchläufe-Steuerung ist ausgeblendet)
- Nur Profile **Max Qualität** und **Ultra (langsam)** verfügbar
- Optimiert alle Offense-Teams gleichzeitig gegen die definierte Defense

---

## Qualitätsprofile

### CPU-Profile

| Profil | Beschreibung | Durchläufe | Laufzeit (Richtwert) |
|---|---|---|---|
| `Fast` | Schnelle Suche, geringer Suchraum | 1 | ~5 s × Monsteranzahl |
| `Balanced` | Breitere Suche mit Verfeinerung | 1–10 mit Early-Stop | ~5 s × Monster × Durchläufe |
| `Max Qualität` | Globale Optimierung über alle Monster gleichzeitig | kein Multi-Pass | ~7,5 s × Monsteranzahl |

### Arena Rush Profile

| Profil | Beschreibung |
|---|---|
| `Max Qualität` | Globale OR-Tools-Optimierung über alle Offense-Teams |
| `Ultra (langsam)` | Erweiterter Suchraum, höhere Qualität, längere Laufzeit |

---

## Systemanforderungen

- **Betriebssystem:** Windows 10/11
- **Summoners War JSON-Export:** z.B. via [SWEX](https://github.com/frostq/swex)

---

## Lizenz

Die App erfordert einen gültigen Lizenz-Key. Beim ersten Start wirst du zur Eingabe aufgefordert. Der Key wird einmalig online aktiviert und an dein Gerät gebunden. Lizenz und Key sind im **Einstellungen**-Tab einsehbar und verwaltbar.

---

## Technisches

### Offline-Metadaten für EXE-Builds

Die App nutzt zur Laufzeit nur lokale Metadaten. Für Releases können die Metadaten vorab per Script aktualisiert und mit der EXE ausgeliefert werden:

```bash
python -m app.tools.update_monster_db
```

Aktualisiert:
- `app/assets/monsters.json` (inkl. Leader Skill, Archetype, Turn-Effect-Caps)
- `app/config/monster_turn_effect_capabilities.json`
- `app/config/arena_speed_lead_cache.json`
- `app/config/arena_archetype_cache.json`

Zur Laufzeit findet kein Online-Nachladen/Scraping statt.

### Tests

```bash
pytest -q tests/test_license_service.py tests/test_update_service.py tests/test_import.py
```

### Benchmark

```bash
python benchmark_optimizer.py --mode rta --units 15 --passes 3 --runs 5 --time-limit 1.5 --quality-profile balanced --multi-pass-strategy greedy_refine --speed-slack 1 --rune-top-per-set 200 --out-json benchmark/latest.json
```

Relevante Flags: `--quality-profile (fast|balanced|max_quality)`, `--rune-top-per-set`, `--speed-slack`, `--multi-pass-strategy`. Ohne `--snapshot` wird automatisch der aktive gespeicherte Snapshot verwendet.
