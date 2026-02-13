from __future__ import annotations

import argparse
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import requests


def _new_license_key() -> str:
    return f"SWOT-{secrets.token_urlsafe(24)}"


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Erstellt Lizenz-Einträge in Supabase.")
    parser.add_argument("--supabase-url", required=True, help="z. B. https://xyz.supabase.co")
    parser.add_argument("--service-role-key", required=True, help="Supabase service_role key")
    parser.add_argument("--app-id", default="SWOT", help="Produktkennung")
    parser.add_argument("--type", choices=["trial", "full"], required=True, help="Lizenztyp")
    parser.add_argument("--minutes", type=int, default=4320, help="Nur fuer trial (Standard: 3 Tage)")
    parser.add_argument("--max-devices", type=int, default=1, help="Maximal aktivierbare Geraete")
    args = parser.parse_args()

    key_plain = _new_license_key()
    key_hash = _sha256_hex(key_plain)
    expires_at = None
    if args.type == "trial":
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=int(args.minutes))).isoformat()

    payload = {
        "app_id": args.app_id,
        "license_key_hash": key_hash,
        "license_type": args.type,
        "status": "active",
        "expires_at": expires_at,
        "max_devices": int(args.max_devices),
    }
    base = args.supabase_url.rstrip("/")
    url = f"{base}/rest/v1/licenses"
    headers = {
        "apikey": args.service_role_key,
        "Authorization": f"Bearer {args.service_role_key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=15)
    if resp.status_code >= 400:
        raise SystemExit(f"Fehler beim Erstellen: {resp.status_code} {resp.text}")

    print("Lizenz erstellt.")
    print(f"Key: {key_plain}")
    print(f"Type: {args.type}")
    if expires_at:
        print(f"Expires At (UTC): {expires_at}")
    print(f"Max Devices: {args.max_devices}")


if __name__ == "__main__":
    main()
