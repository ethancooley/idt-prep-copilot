"""The brief the agent produces, and the structured outputs Claude returns at each step."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

CATEGORIES = [
    "fall", "hospital_or_ed", "medication_change", "weight_loss", "functional_status",
    "cognition", "psychosocial", "caregiver", "vitals", "care_plan_due", "other",
]
RECORD_CITATIONS = ["record:vitals", "record:encounters", "record:medications", "record:immunizations"]


class Verdict(str, Enum):
    supported = "supported"
    partially_supported = "partially_supported"
    unsupported = "unsupported"


class BriefItem(BaseModel):
    category: str
    severity: str = Field(description="high, medium, or low")
    statement: str
    citations: list[str] = Field(default_factory=list)
    verdict: Verdict | None = None
    verifier_note: str | None = None


class Brief(BaseModel):
    participant_id: str
    participant_name: str
    review_date: str
    window_start: str
    headline: str
    items: list[BriefItem]
    questions_for_team: list[str] = Field(default_factory=list)
    removed_claims: list[BriefItem] = Field(default_factory=list,
                                            description="Claims the verifier could not support, kept for audit")
    run: dict = Field(default_factory=dict, description="Models, tokens, cost, latency, tool calls")


# ------------------------------------------------------------ tool schemas Claude fills in

PLAN_TOOL = {
    "name": "submit_plan",
    "description": "Submit the checks to run before drafting the IDT brief.",
    "input_schema": {
        "type": "object",
        "properties": {"checks": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 10}},
        "required": ["checks"],
    },
}

BRIEF_TOOL = {
    "name": "submit_brief",
    "description": "Submit the IDT meeting brief. Every item must cite note ids or record citations.",
    "input_schema": {
        "type": "object",
        "properties": {
            "headline": {"type": "string", "description": "One sentence: the most important thing for the team."},
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string", "enum": CATEGORIES},
                        "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                        "statement": {"type": "string", "description": "One or two plain sentences with dates."},
                        "citations": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": f"Note ids (e.g. '1a2b3c4d-n007') and/or any of {RECORD_CITATIONS}.",
                        },
                    },
                    "required": ["category", "severity", "statement", "citations"],
                },
            },
            "questions_for_team": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
        },
        "required": ["headline", "items", "questions_for_team"],
    },
}

VERIFY_TOOL = {
    "name": "submit_verification",
    "description": "Submit a verdict for every brief item.",
    "input_schema": {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer"},
                        "verdict": {"type": "string", "enum": [v.value for v in Verdict]},
                        "reason": {"type": "string"},
                    },
                    "required": ["index", "verdict", "reason"],
                },
            }
        },
        "required": ["results"],
    },
}
