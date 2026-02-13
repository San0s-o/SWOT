# SWOT - Summoners War Optimization Tool

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
| **Set-Optionen** | Erlaubte Runen-Set-Kombinationen (z.B. Despair+Will, Swift+Will) |
| **Mainstats** | Erlaubte Mainstats pro Slot (2, 4, 6) |
| **Min-Stats** | Mindest-Werte (z.B. min. 200 SPD) |
| **Priorität** | Niedrigere Zahl = bekommt zuerst die besten Runen |
| **Turn-Order** | Erzwingt Speed-Reihenfolge innerhalb eines Teams |

### 6. Validieren

Klicke auf **Validieren (Pools/Teams)** bevor du optimierst. Die Validierung prüft:
- Keine Monster doppelt vergeben
- Alle Slots besetzt
- Genügend Runen der benötigten Sets vorhanden
- Benötigte Mainstats im Pool verfügbar

### 7. Optimieren

Klicke auf **Optimieren (Runen)**. Der Optimizer:
1. Weist Runen in Prioritäts-Reihenfolge zu (wichtigste Monster zuerst)
2. Beachtet alle Set- und Mainstat-Vorgaben
3. Maximiert Runen-Effizienz und Stat-Gewichtung
4. Berücksichtigt optional die Turn-Order innerhalb von Teams

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
