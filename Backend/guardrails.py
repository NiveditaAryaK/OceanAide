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


def _extract_json_object(text: str):
    """Return the first balanced {...} block in text, or None. A non-greedy
    regex breaks on nested objects (the Control schema nests PlanStep dicts
    inside 'plan'), so walk the braces, ignoring ones inside strings."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if escaped:
            escaped = False
            continue
        if ch == "\\" and in_str:
            escaped = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def split_and_parse(raw: str):
    """Returns (control, reply, parse_ok). parse_ok is False when the model
    broke the output contract and defaults were substituted."""
    cj_match = re.search(r"CONTROL_JSON:\s*(.*?)\s*REPLY:", raw, re.S)
    rp_match = re.search(r"REPLY:\s*(.*)\Z", raw, re.S)

    if not cj_match or not rp_match:
        # fallback: return defaults + whole raw text as reply
        control = Control(**REQUIRED_FIELDS)
        return control, raw, False

    parse_ok = True
    json_block = _extract_json_object(cj_match.group(1))
    try:
        parsed = json.loads(json_block) if json_block else {}
        if not json_block:
            parse_ok = False
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
        # Nothing substantive to check (empty or fragment-only reply):
        # treat as ungrounded so the caution policy kicks in, instead of
        # letting a blank reply pass with a perfect score.
        return 0.0
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
