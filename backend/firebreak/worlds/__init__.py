"""Synthetic worlds: pure data modules with an identical interface.

A world is a company's operational graph encoded as data. The engine (simulator,
RCA, agents, memory) never imports a specific world, so a new domain is a new
module here plus a registry entry.

Each module exposes: MIN, HOUR, DAY, TEAMS, PEOPLE, ON_CALL, COMPONENTS,
DEPENDS_ON, FAILS_OVER_TO, RUNS_ON_B, BASELINE, PRODUCTS, CUSTOMERS, DECISIONS,
RUNBOOKS, THREADS, EXPERT_IN, INCIDENTS, BACKGROUND_CHANGE_COUNT, CHANGE_KINDS.
"""

from . import meridian, nimbuspay

WORLDS = {"nimbuspay": nimbuspay, "meridian": meridian}


def register(name: str, module) -> None:
    WORLDS[name] = module


def get(name: str):
    if name not in WORLDS:
        raise KeyError(f"unknown world {name!r}; have {sorted(WORLDS)}")
    return WORLDS[name]
