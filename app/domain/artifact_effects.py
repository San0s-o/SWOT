from __future__ import annotations

from typing import Dict, List

# Source:
# Swarfarm repository, commit c78b7173 ("Added missing artifact effects")
# file: bestiary/models/artifacts.py (COM2US_EFFECT_MAP + EFFECT_STRINGS)


# Artifact main-focus mapping (primary effect id -> HP/ATK/DEF).
ARTIFACT_MAIN_FOCUS_BY_EFFECT_ID: Dict[int, str] = {
    1: "HP",
    2: "HP",
    3: "ATK",
    4: "ATK",
    5: "DEF",
    6: "DEF",
    100: "HP",
    101: "ATK",
    102: "DEF",
}


# Swarfarm templates keyed by Com2uS artifact effect id.
ARTIFACT_EFFECT_TEMPLATES: Dict[int, str] = {
    200: "ATK+ Proportional to Lost HP up to {}%",
    201: "DEF+ Proportional to Lost HP up to {}%",
    202: "SPD+ Proportional to Lost HP up to {}%",
    203: "SPD Under Inability +{}%",
    204: "ATK Increasing Effect +{}%",
    205: "DEF Increasing Effect +{}%",
    206: "SPD Increasing Effect +{}%",
    207: "CRIT Rate Increasing Effect +{}%",
    208: "Damage Dealt by Counterattack +{}%",
    209: "Damage Dealt by Attacking Together +{}%",
    210: "Bomb Damage +{}%",
    211: "Damage Dealt by Reflect DMG +{}%",
    212: "Crushing Hit DMG +{}%",
    213: "Damage Received Under Inability -{}%",
    214: "CRIT DMG Received -{}%",
    215: "Life Drain +{}%",
    216: "HP when Revived +{}%",
    217: "Attack Bar when Revived +{}%",
    218: "Additional Damage by {}% of HP",
    219: "Additional Damage by {}% of ATK",
    220: "Additional Damage by {}% of DEF",
    221: "Additional Damage by {}% of SPD",
    222: "CRIT DMG+ up to {}% as the enemy's HP condition is good",
    223: "CRIT DMG+ up to {}% as the enemy's HP condition is bad",
    224: "Single-target skill CRIT DMG +{}% on your turn",
    225: "Damage Dealt by Counterattack/Attacking Together +{}%",
    226: "ATK/DEF Increasing Effect +{}%",
    300: "Damage Dealt on Fire +{}%",
    301: "Damage Dealt on Water +{}%",
    302: "Damage Dealt on Wind +{}%",
    303: "Damage Dealt on Light +{}%",
    304: "Damage Dealt on Dark +{}%",
    305: "Damage Received from Fire -{}%",
    306: "Damage Received from Water -{}%",
    307: "Damage Received from Wind -{}%",
    308: "Damage Received from Light -{}%",
    309: "Damage Received from Dark -{}%",
    400: "[Skill 1] CRIT DMG +{}%",
    401: "[Skill 2] CRIT DMG +{}%",
    402: "[Skill 3] CRIT DMG +{}%",
    403: "[Skill 4] CRIT DMG +{}%",
    404: "[Skill 1] Recovery +{}%",
    405: "[Skill 2] Recovery +{}%",
    406: "[Skill 3] Recovery +{}%",
    407: "[Skill 1] Accuracy +{}%",
    408: "[Skill 2] Accuracy +{}%",
    409: "[Skill 3] Accuracy +{}%",
    410: "[Skill 3/4] CRIT DMG +{}%",
    411: "First Attack CRIT DMG +{}%",
}


def _template_to_label(template: str) -> str:
    # Convert value-templates into selector labels.
    return (
        template
        .replace("+{}%", "")
        .replace("-{}%", "")
        .replace("{}%", "N%")
        .replace("  ", " ")
        .strip()
    )


# Effect labels for dropdowns/filters (without concrete values).
ARTIFACT_EFFECT_LABELS: Dict[int, str] = {
    effect_id: _template_to_label(template)
    for effect_id, template in ARTIFACT_EFFECT_TEMPLATES.items()
}


# Optimizer artifact type ids in this project:
# 1 = Attribute artifact (Element), 2 = Type artifact (Archetype/Type).
ARTIFACT_EFFECT_IDS_BY_ARTIFACT_TYPE: Dict[int, List[int]] = {
    1: [
        200, 201, 202, 203,
        204, 205, 206, 207,
        208, 209, 210, 211, 212, 213, 214, 215, 216, 217,
        218, 219, 220, 221, 222, 223, 224, 225, 226,
        300, 301, 302, 303, 304,
        305, 306, 307, 308, 309,
    ],
    2: [
        200, 201, 202, 203,
        204, 205, 206, 207,
        208, 209, 210, 211, 212, 213, 214, 215, 216, 217,
        218, 219, 220, 221, 222, 223, 224, 225, 226,
        400, 401, 402, 403,
        404, 405, 406,
        407, 408, 409,
        410, 411,
    ],
}


ARTIFACT_RANK_LABELS: Dict[int, str] = {
    1: "Normal",
    2: "Magic",
    3: "Rare",
    4: "Hero",
    5: "Legend",
}

# Legacy effects no longer obtainable on new artifacts.
ARTIFACT_LEGACY_EFFECT_IDS = {
    200, 201, 202, 203, 204, 205, 207, 208, 209,
    211, 212, 213, 216, 217,
}


def artifact_effect_label(effect_id: int, fallback_prefix: str = "Effect") -> str:
    eid = int(effect_id or 0)
    base = ARTIFACT_EFFECT_LABELS.get(eid, f"{fallback_prefix} {eid}")
    if eid in ARTIFACT_LEGACY_EFFECT_IDS:
        return f"{base} [Legacy]"
    return base


def artifact_effect_text(effect_id: int, value: int | float | str, fallback_prefix: str = "Effect") -> str:
    eid = int(effect_id or 0)
    template = ARTIFACT_EFFECT_TEMPLATES.get(eid)
    if not template:
        base = f"{artifact_effect_label(eid, fallback_prefix)} {value}"
        return base

    try:
        if isinstance(value, str):
            raw = float(value) if "." in value else int(value)
        else:
            raw = value
        if isinstance(raw, (int, float)):
            rendered_value: int | float = abs(raw)
            if isinstance(rendered_value, float) and rendered_value.is_integer():
                rendered_value = int(rendered_value)
        else:
            rendered_value = raw
    except Exception:
        rendered_value = value

    try:
        rendered = template.format(rendered_value)
        if eid in ARTIFACT_LEGACY_EFFECT_IDS:
            return f"{rendered} [Legacy]"
        return rendered
    except Exception:
        return f"{artifact_effect_label(eid, fallback_prefix)} {value}"


def artifact_effect_artifact_type(effect_id: int) -> int:
    eid = int(effect_id or 0)
    in_attr = eid in ARTIFACT_EFFECT_IDS_BY_ARTIFACT_TYPE[1]
    in_type = eid in ARTIFACT_EFFECT_IDS_BY_ARTIFACT_TYPE[2]
    if in_attr and in_type:
        return 0
    if in_attr:
        return 1
    if in_type:
        return 2
    return 0


def artifact_rank_label(rank: int, fallback_prefix: str = "Rank") -> str:
    r = int(rank or 0)
    return ARTIFACT_RANK_LABELS.get(r, f"{fallback_prefix} {r}")


def artifact_effect_is_legacy(effect_id: int) -> bool:
    return int(effect_id or 0) in ARTIFACT_LEGACY_EFFECT_IDS
