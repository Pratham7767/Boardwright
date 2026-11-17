"""The user's own choices, kept where only the user can change them (standard library only).

    .boardwright/choices.json   {"routing_plan": {"value": true, "how": "...", "at": "..."}, ...}

Written only by the plugin's hooks, from what the user typed (`/boardwright:pcb-plan on`) or the button
they clicked in a question Claude asked (see edit_hooks.py). Claude cannot write it: the edit hook refuses
any tool call that touches this file. Diagnostics consent has its own file (diagnostics.py), guarded the
same way.

The questions Claude asks for these choices use fixed headers and option labels, so the hook knows
what was chosen. They are listed in QUESTIONS and in the boardwright skill.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

# header -> the option labels Claude must offer (the hook matches on these)
QUESTIONS = {
    "Diagnostics": ["Yes, record everything", "Yes, but not my prompts", "No"],
    "Routing plan": ["Turn on", "Keep off"],
    "Approve routes": None,      # options are the corridors: "c1: /SDA, /SCL on F.Cu" (id before the colon)
}


def path(proj: Path) -> Path:
    return Path(proj) / ".boardwright" / "choices.json"


def load(proj: Path) -> dict:
    try:
        d = json.loads(path(proj).read_text("utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def get(proj: Path, key: str, default=None):
    v = load(proj).get(key)
    return v.get("value", default) if isinstance(v, dict) else default


def set_choice(proj: Path, key: str, value, how: str) -> None:
    from history import own_dir
    own_dir(Path(proj))
    d = load(proj)
    d[key] = {"value": value, "how": how[:200], "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    p = path(proj)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n", "utf-8")
    tmp.replace(p)
