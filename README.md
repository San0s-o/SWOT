# SWTO - Summoners War Team Optimizer

Runen-Optimierer und Team-Builder für Summoners War. Verteilt Runen automatisch optimal auf deine Monster – für Siege, WGB und RTA.

## Features

- **Account-Import** – Lade deinen Summoners War JSON-Export und sieh sofort alle Monster, Runen und Artefakte
- **Runen-Optimierung** – Automatische Zuweisung der besten Runen pro Monster (powered by OR-Tools Constraint Solver)
- **Siege Builder** – Stelle bis zu 10 Verteidigungsteams (je 3 Monster) zusammen und optimiere sie
- **WGB Builder** – 5 Verteidigungsteams für World Guild Battle
- **RTA Builder** – Bis zu 15 Monster mit frei definierbarer Reihenfolge
- **Team Builder** – Eigene Teams für PvE oder sonstige Planung
- **Build-Presets** – Definiere pro Monster erlaubte Sets, Mainstats, Min-Stats und Priorität
- **Validierung** – Prüft vor der Optimierung ob Runen-Pool, Sets und Mainstats ausreichen
- **Optimierungen speichern** – Ergebnisse werden gespeichert und können später verglichen werden

## Kurzanleitung

### 1. Account importieren

Exportiere deinen Summoners War Account als JSON (z.B. via SWEX) und importiere die Datei über **Datei → Import**.

### 2. Übersicht prüfen

Im Tab **Übersicht** siehst du:
- Anzahl Monster, Runen und Artefakte
- Runen-Verteilung nach Set und Qualität (Normal/Magic/Rare/Hero/Legend)
- Effizienz-Analyse deiner Runen
- Artefakt-Übersicht

### 3. Aktuelle Aufstellung ansehen

- **Siege Verteidigungen (aktuell)** – Zeigt deine aktuell gerunten Siege-Defs als Karten
- **RTA (aktuell)** – Zeigt deine RTA-Monster mit Speed-Lead-Umschalter für Turn-Order-Vergleiche

### 4. Teams zusammenstellen

Wechsle zum gewünschten Builder-Tab (Siege / WGB / RTA) und stelle deine Teams zusammen.

**Siege Builder:** Wähle bis zu 10 Verteidigungen mit je 3 Monstern.
**WGB Builder:** Wähle bis zu 5 Verteidigungen mit je 3 Monstern.
**RTA Builder:** Wähle bis zu 15 Monster und ordne sie per Drag & Drop.

### 5. Builds konfigurieren

Klicke auf **Builds (Sets+Mainstats)** um pro Monster festzulegen:

| Einstellung | Beschreibung |
|---|---|
| **Set-Optionen** | Set 1 und Set 2 erlauben Mehrfachauswahl. Pro Set-Slot sind nur gleich große Sets (2er/4er) erlaubt. Set 3 ist nur aktiv, wenn Set 1 und Set 2 jeweils 2er-Sets sind. |
| **Mainstats** | Erlaubte Mainstats pro Slot (2, 4, 6), Mehrfachauswahl möglich |
| **Min-Stats** | Mindest-Werte (z.B. min. 200 SPD) |
| **Priorität** | Niedrigere Zahl = bekommt zuerst die besten Runen |
| **Turn-Order** | Reihenfolge pro Team (wird bei der Optimierung immer erzwungen) |
| **Durchläufe** | Anzahl Multi-Pass-Durchläufe (1–10), mit vorzeitigem Stop bei keiner Verbesserung |
| **Qualitätsprofil** | `Fast` (schnell), `Balanced` (ausgewogen), `Max Qualität` (globale Qualitätsoptimierung), `GPU Search` (GPU-gestuetztes Varianten-Screening + CPU-Feinpruefung) |

### 6. Validieren

Klicke auf **Validieren (Pools/Teams)** bevor du optimierst. Die Validierung prüft:
- Keine Monster doppelt vergeben
- Alle Slots besetzt
- Genügend Runen der benötigten Sets vorhanden
- Benötigte Mainstats im Pool verfügbar

### 7. Optimieren

Klicke auf **Optimieren (Runen)**. Der Optimizer:
1. Beachtet alle Set-, Mainstat-, Min-Stat- und Tick/Turn-Order-Vorgaben
2. Verwendet das gewählte **Qualitätsprofil**:
   - `Fast`: schneller Greedy-Lauf (geringerer Suchraum)
   - `Balanced`: Greedy + Refinement ab Lauf 2 (Effizienz wichtiger, solange Constraints eingehalten sind)
   - `Max Qualität`: globales OR-Tools-Modell über alle ausgewählten Monster gleichzeitig (effizienzfokussiert)
   - `GPU Search`: sehr viele Varianten werden auf der GPU vorgerankt; die besten Kandidaten werden danach mit dem Solver auf CPU feinoptimiert
3. Nutzt bei `Fast`/`Balanced` mehrere Durchläufe (1–10) und stoppt vorzeitig bei stabiler Lösung ohne Verbesserung
4. Führt bei `Max Qualität` eine globale Optimierung statt Multi-Pass aus (Durchläufe werden dafür nicht verwendet)
5. Zeigt während der Berechnung einen Fortschrittsdialog, damit die App sichtbar weiterarbeitet

Das Ergebnis zeigt pro Monster:
- Zugewiesene Runen (Slot 1–6) mit allen Stats
- Berechnete Endwerte (HP, ATK, DEF, SPD, CR, CD, RES, ACC)
- Leader-Skill-Boni

### 8. Ergebnis speichern & vergleichen

Klicke **Speichern** um die Optimierung zu archivieren. Unter den jeweiligen **Optimierungen (gespeichert)** Tabs kannst du frühere Ergebnisse laden, ansehen und vergleichen.

## Lizenz

Die App erfordert einen gültigen Lizenz-Key. Beim ersten Start wirst du zur Eingabe aufgefordert. Der Key wird einmalig online aktiviert und an dein Gerät gebunden.

## Systemanforderungen

- Windows 10/11
- Summoners War JSON-Export (z.B. via SWEX)

### GPU Search Voraussetzungen

`GPU Search` wird nur angezeigt, wenn PyTorch mit CUDA in der aktiven Python-Umgebung verfügbar ist.

Benötigt:
- NVIDIA GPU mit aktuellem Treiber
- PyTorch CUDA Build (nicht CPU-only), z.B.:

```bash
python -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
```

Prüfen:

```bash
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'n/a')"
```

Wenn `True` ausgegeben wird, ist GPU Search aktivierbar.

### GPU Profile (Fast/Balanced/Max) - Laufzeit und Suchumfang

Die GPU-Profile unterscheiden sich in Suchintensität und Laufzeit.
Dabei gilt:
- **GPU-Screening** = viele Varianten werden auf der GPU vorgerankt
- **CPU-Evals** = Top-Kandidaten werden mit dem Solver feinoptimiert

Ungefaehre Laufzeit mit UI-Default `time_limit_per_unit_s = 5.0`:
- `Fast` (Greedy): ca. `5s * Monsteranzahl` (1 Pass, kleiner Suchraum)
- `Balanced` (Greedy + Refine): ca. `5s * Monsteranzahl * Durchlaeufe` (mit Early-Stop)
- `Max Qualität` (CPU global): ca. `7.5s * Monsteranzahl`
- `GPU Fast`: ca. `10s * Monsteranzahl`
- `GPU Balanced`: ca. `20s * Monsteranzahl`
- `GPU Max`: ca. `30s * Monsteranzahl`

CPU-Profil-Verhalten:

| Profil | Suchansatz | Durchlaeufe |
|---|---|---|
| `Fast` | Greedy-only | effektiv 1 (auch wenn mehr gesetzt ist, stoppt sehr frueh) |
| `Balanced` | Greedy + Refine ab Lauf 2 | 1-10, mit Early-Stop bei stabiler Loesung |
| `Max Qualität` | globales OR-Tools Modell (alle Monster gleichzeitig) | keine Multi-Pass-Durchlaeufe |

Aktuelle Profil-Parameter (bei CUDA):

| Profil | GPU batch size | GPU batches/cycle | Max CPU-Evals |
|---|---:|---:|---:|
| `GPU Fast` | `units * 2048` (max 262144) | `min(20, units/2 + 2)` | `units * 10` (max 720) |
| `GPU Balanced` | `units * 8192` (max 262144) | `min(20, units/2 + 8)` | `units * 20` (max 720) |
| `GPU Max` | `units * 12288` (max 262144) | `min(20, units/2 + 12)` | `units * 26` (max 720) |

Hinweis:
- Reale Laufzeit kann kuerzer sein (Early-Stop bei keiner Verbesserung, Zeitlimit, manueller Abbruch).
- Hohe GPU-Auslastung ist nicht dauerhaft garantiert, weil die finale Feinauswahl weiterhin CPU-Solver nutzt.

## Tests

Folgende automatisierte Tests sind jetzt enthalten:
- `tests/test_license_service.py`
- `tests/test_update_service.py`
- `tests/test_import.py` (Smoke-Test)

Ausfuehren:

```bash
pytest -q tests/test_license_service.py tests/test_update_service.py tests/test_import.py
```

## Benchmark

Runtime- und Qualitaetsvergleich des Greedy-Optimizers:

```bash
python benchmark_optimizer.py --mode rta --units 15 --passes 3 --runs 5 --time-limit 1.5 --quality-profile balanced --multi-pass-strategy greedy_refine --speed-slack 1 --rune-top-per-set 200 --out-json benchmark/latest.json
```

Hinweis:
- Ohne `--snapshot` nimmt das Script automatisch den aktiven gespeicherten Snapshot (inkl. Legacy-Fallback).
- Relevante Flags: `--quality-profile (fast|balanced|max_quality)`, `--rune-top-per-set`, `--speed-slack`, `--multi-pass-strategy`.
