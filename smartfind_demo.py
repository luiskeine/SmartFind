"""Synthetic, in-memory scenarios for demonstrating SmartFind."""
from copy import deepcopy


_BASE = {
    "type": "Lost",
    "item": "Black Smartphone",
    "category": "Smartphone",
    "color": "Black",
    "location": "Library",
    "date": "2026-10-08",
    "description": "cracked screen with black case",
    "brand": "",
    "photo": None,
    "status": "Searching",
    "user_email": "demo-lost@example.invalid",
}

_SCENARIOS = {
    "Strong evidence": {
        "description": "Two reports share the key details and earn a high score.",
        "lost": {},
        "found": {
            "id": "DEMO-F-001",
            "type": "Found",
            "status": "Reported",
            "user_email": "demo-found@example.invalid",
        },
    },
    "Partial evidence": {
        "description": "Some details align, while location, color, and date earn partial credit.",
        "lost": {
            "id": "DEMO-L-002",
            "color": "Navy Blue",
            "location": "Library 2nd Floor",
            "date": "2026-10-08",
            "description": "silver case with star sticker",
        },
        "found": {
            "id": "DEMO-F-002",
            "type": "Found",
            "item": "Blue Smartphone",
            "color": "Blue",
            "location": "Library",
            "date": "2026-10-10",
            "description": "silver case",
            "status": "Reported",
            "user_email": "demo-found@example.invalid",
        },
    },
    "Conflicting details": {
        "description": "Conflicting reports fall below the Possible Matches display threshold.",
        "lost": {
            "id": "DEMO-L-003",
            "item": "Red Keys",
            "category": "Keys",
            "color": "Red",
            "location": "Gymnasium",
            "date": "2026-10-01",
            "description": "red keychain with a bell",
        },
        "found": {
            "id": "DEMO-F-003",
            "type": "Found",
            "item": "Black Smartphone",
            "color": "Black",
            "location": "Library",
            "date": "2026-10-15",
            "description": "cracked screen with black case",
            "status": "Reported",
            "user_email": "demo-found@example.invalid",
        },
    },
}


def demo_scenario_names():
    return tuple(_SCENARIOS)


def get_demo_scenario(name):
    """Return fresh sample reports without exposing mutable fixture state."""
    try:
        scenario = deepcopy(_SCENARIOS[name])
    except KeyError as exc:
        raise ValueError(f"Unknown SmartFind demo scenario: {name}") from exc

    lost = {**_BASE, **scenario.pop("lost")}
    lost.setdefault("id", "DEMO-L-001")
    found = {**_BASE, **scenario.pop("found"), "type": "Found"}
    found.setdefault("id", "DEMO-F-001")
    found["status"] = "Reported"
    return {**scenario, "lost": lost, "found": found}
