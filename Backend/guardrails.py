import json, re
from schemas import Control

REQUIRED_FIELDS = {
    "mood": "neutral",
    "hazards": [],
    "goal": "stabilize",
    "plan": [],
    "risk": "medium",
    "confidence": 0.5,
    "next_state": "Reflect"
}

def split_and_parse(raw: str):
    # Extract CONTROL_JSON and REPLY using regex
    cj_match = re.search(r"CONTROL_JSON:\s*(\{.*?\})\s*REPLY:", raw, re.S)
    rp_match = re.search(r"REPLY:\s*(.*)\Z", raw, re.S)

    if not cj_match or not rp_match:
        # fallback: return defaults + whole raw text as reply
        control = Control(**REQUIRED_FIELDS)
        return control, raw

    try:
        parsed = json.loads(cj_match.group(1))
    except Exception:
        # If invalid JSON, fallback to defaults
        parsed = {}

    # Fill in missing required fields with safe defaults
    for k, v in REQUIRED_FIELDS.items():
        parsed.setdefault(k, v)

    try:
        control = Control.model_validate(parsed)
    except Exception:
        # If still invalid, force schema with defaults
        control = Control(**REQUIRED_FIELDS)

    reply = rp_match.group(1).strip()
    return control, reply

def apply_policies(reply: str, control: Control):
    if control.confidence < 0.5 or control.risk == "high":
        if "Use judgment; conditions vary." not in reply:
            reply += "\n\n*Use judgment; conditions vary.*"
    return reply
