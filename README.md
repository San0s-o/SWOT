# SW Team Optimizer (Desktop, Offline)

Minimaler Start (MVP-Skeleton):
- PySide6 GUI
- JSON Import (Summoners War Export)
- Anzeige der aktuellen Siege-Defense (aus `guildsiege_defense_unit_list`)
- Normalisierte Datenbasis (Units / Runen / Artefakte) als In-Memory Store

## Setup
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m app
```

## Hinweis
Dieses Projekt ist bewusst ein Skeleton. Die Optimierungs-Engine (CP-SAT) und Tick-Sim kommen als nächste Schritte.
