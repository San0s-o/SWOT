# Lizenz mit Supabase (Online)

Diese Datei bleibt im Projekt-Root und wird nicht in die EXE gepackt.

## 1) Supabase vorbereiten

1. SQL ausfuehren:
```powershell
# Inhalt von supabase/sql/license_schema.sql im Supabase SQL Editor ausfuehren
```
2. Edge Functions deployen:
```powershell
supabase functions deploy activate
supabase functions deploy validate
```
3. Function-Secrets setzen:
```powershell
supabase secrets set SUPABASE_URL="https://YOUR-PROJECT.supabase.co"
supabase secrets set SUPABASE_SERVICE_ROLE_KEY="YOUR_SERVICE_ROLE_KEY"
supabase secrets set LICENSE_SESSION_TTL_HOURS="24"
```

## 2) Lokale App-Konfiguration anlegen

`license_config.json.example` nach `license_config.json` kopieren und Werte eintragen:
- `supabase_url`
- `supabase_anon_key`
- `app_id` (z. B. `SWOT`)
- `app_version` (z. B. `1.0.0`)

## 3) Lizenz erzeugen (Admin, lokal)

```powershell
python -m app.tools.license_admin --supabase-url "https://YOUR-PROJECT.supabase.co" --service-role-key "YOUR_SERVICE_ROLE_KEY" --app-id SWOT --type trial --minutes 4320 --max-devices 1
python -m app.tools.license_admin --supabase-url "https://YOUR-PROJECT.supabase.co" --service-role-key "YOUR_SERVICE_ROLE_KEY" --app-id SWOT --type full --max-devices 1
```

Der ausgegebene `Key` wird an den Nutzer verteilt.

## 4) EXE bauen

```powershell
cd "D:\Projekte\SWOT"
Copy-Item .\license_config.json .\dist\license_config.json -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe -m PyInstaller .\app\__main__.py --onedir --noconsole --name SWOT --clean --add-data "app/assets;app/assets"
Copy-Item .\license_config.json .\dist\SWOT\license_config.json -Force
```

## 5) Runtime-Pfade

- EXE-Lizenzcache: `%APPDATA%\SWOT\license.json`
- Dev-Lizenzcache (`python -m app`): `%APPDATA%\SWOT-dev\license.json`

Hinweise:
- `service_role` niemals in die EXE.
- In die EXE darf nur `supabase_url` + `anon_key`.
