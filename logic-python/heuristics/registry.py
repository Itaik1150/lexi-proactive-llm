"""
Which heuristics exist and which of them are ACTIVE (docs/REVIEW.md, owner decision of 26 Oct).

The study ("Lexi Takes the Lead") needs two proactive behaviours, Standard and Affective, plus
Reactive (no notification). The older research heuristics (temporal, behavioural gap, generic)
stay in the code base and stay registered, but are switched off: they can be drawn neither by the
weights of an experiment nor by the sender, and they must never build memory of their own
(the memory is built once, for everyone, by services/memory_pipeline.py).

To add a heuristic later: write the class, register it here, set active=True. Nothing else
needs to change. The dashboard should list this registry (docs/REVIEW.md, P9).
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Dict, Optional


@dataclass(frozen=True)
class HeuristicInfo:
    name: str          # key used in experiment weights and in proactive_logs
    module: str
    class_name: str
    active: bool
    note: str


REGISTRY: Dict[str, HeuristicInfo] = {
    "affective": HeuristicInfo(
        "affective", "heuristics.affective", "AffectiveHeuristic", True,
        "Warm check-in about a personal event or recent days (study condition)."),
    "temporal": HeuristicInfo(
        "temporal", "heuristics.temporal", "TemporalHeuristic", False,
        "Follow-up on upcoming plans. Dormant: not part of the study."),
    "behaviouralGap": HeuristicInfo(
        "behaviouralGap", "heuristics.behavioural_gap", "BehaviouralGapHeuristic", False,
        "Nudge about a stated intention. Dormant: not part of the study."),
    "generic": HeuristicInfo(
        "generic", "heuristics.generic", "GenericHeuristic", False,
        "Generic invitation written by the model. Dormant: replaced by the fixed Standard pool."),
}


def is_active(name: str) -> bool:
    info = REGISTRY.get(name)
    return bool(info and info.active)


def get_class(name: str) -> Optional[type]:
    """The class of an ACTIVE heuristic, else None."""
    info = REGISTRY.get(name)
    if not info or not info.active:
        return None
    return getattr(import_module(info.module), info.class_name)
