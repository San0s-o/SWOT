from __future__ import annotations

import argparse

def main() -> None:
    parser = argparse.ArgumentParser(description="Legacy-Tool (offline keygen, nicht mehr verwendet).")
    parser.parse_args()
    raise SystemExit(
        "Offline-Keygen ist deaktiviert. Nutze stattdessen:\n"
        "python -m app.tools.license_admin --help"
    )


if __name__ == "__main__":
    main()
