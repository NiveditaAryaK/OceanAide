# ocean_agent/schemas.py
from pydantic import BaseModel, Field
from typing import List, Literal, Optional

Mood = Literal["panic", "worried", "neutral", "curious", "calm"]
Risk = Literal["low", "medium", "high"]

class PlanStep(BaseModel):
    type: Literal["checklist", "mission", "reframe"]
    card_id: Optional[str] = None
    note: Optional[str] = None

class Control(BaseModel):
    mood: Mood
    hazards: List[str] = Field(default_factory=list)
    goal: str
    plan: List[PlanStep]
    risk: Risk
    confidence: float
    next_state: Literal["Assess", "Plan", "Act", "Reflect", "Crisis"]
