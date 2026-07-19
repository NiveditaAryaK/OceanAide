import json, re
from schemas import Control
from retrieval import _tokenize

REQUIRED_FIELDS = {
    "mood": "neutral",
    "hazards": [],
    "goal": "stabilize",
    "plan": [],
    "risk": "medium",
    "confidence": 0.5,
    "next_state": "Reflect"
}

CAUTION_LINE = "Use judgment; conditions vary."

# A reply sentence counts as grounded if this fraction of its tokens
# appears in the selected cards.
SENTENCE_COVERAGE = 0.6
# Below this fraction of grounded sentences, the reply gets the caution line.
GROUNDING_FLOOR = 0.5


def split_and_parse(raw: str):
    """Returns (control, reply, parse_ok). parse_ok is False when the model
    broke the output contract and defaults were substituted."""
    cj_match = re.search(r"CONTROL_JSON:\s*(\{.*?\})\s*REPLY:", raw, re.S)
    rp_match = re.search(r"REPLY:\s*(.*)\Z", raw, re.S)

    if not cj_match or not rp_match:
        # fallback: return defaults + whole raw text as reply
        control = Control(**REQUIRED_FIELDS)
        return control, raw, False

    parse_ok = True
    try:
        parsed = json.loads(cj_match.group(1))
    except Exception:
        parsed = {}
        parse_ok = False

    # Fill in missing required fields with safe defaults
    for k, v in REQUIRED_FIELDS.items():
        parsed.setdefault(k, v)

    try:
        control = Control.model_validate(parsed)
    except Exception:
        control = Control(**REQUIRED_FIELDS)
        parse_ok = False

    reply = rp_match.group(1).strip()
    return control, reply, parse_ok


def grounding_score(reply: str, cards) -> float:
    """Fraction of substantive reply sentences whose vocabulary is covered
    by the selected cards. 1.0 = fully grounded, 0.0 = nothing traceable."""
    vocab = set()
    for c in cards:
        vocab.update(_tokenize(c.get("text", "")))
    if not vocab:
        return 0.0

    sentences = [s for s in re.split(r"[.!?\n]+", reply)]
    scored = 0
    grounded = 0
    for s in sentences:
        toks = _tokenize(s)
        if len(toks) < 3:  # skip headers/fragments
            continue
        scored += 1
        coverage = sum(t in vocab for t in toks) / len(toks)
        if coverage >= SENTENCE_COVERAGE:
            grounded += 1
    if scored == 0:
        return 1.0
    return grounded / scored


def apply_policies(reply: str, control: Control, grounding: float = 1.0):
    needs_caution = (
        control.confidence < 0.5
        or control.risk == "high"
        or grounding < GROUNDING_FLOOR
    )
    if needs_caution and CAUTION_LINE not in reply:
        reply += f"\n\n*{CAUTION_LINE}*"
    return reply
