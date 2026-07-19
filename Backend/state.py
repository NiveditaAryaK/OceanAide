import retrieval, prompts, models, guardrails
from tools import log_write

# Which states may follow which. The model proposes next_state, but the
# agent only accepts transitions listed here; anything else keeps the
# current state. Crisis is reachable from everywhere.
TRANSITIONS = {
    "Assess":  {"Assess", "Plan", "Act", "Crisis"},
    "Plan":    {"Plan", "Act", "Crisis"},
    "Act":     {"Act", "Reflect", "Crisis"},
    "Reflect": {"Reflect", "Assess", "Plan", "Crisis"},
    "Crisis":  {"Crisis", "Assess"},
}

MAX_HISTORY = 3


class Agent:
    def __init__(self, cards):
        self.cards = cards
        self.state = "Assess"
        self.history = []      # last few turns: user text + control summary
        self.last_control = None
        self.last_debug = None

    def step(self, user_text: str):
        selected = retrieval.search(self.cards, user_text, k=4)
        cards_text = "\n\n".join(f"[{c['id']}] {c['text']}" for c in selected)
        prompt = prompts.SYSTEM + "\n\n" + prompts.USER_TEMPLATE.format(
            current_state=self.state,
            allowed_next=", ".join(sorted(TRANSITIONS[self.state])),
            history_text=self._history_text(),
            user_text=user_text,
            cards_text=cards_text,
        )
        raw = models.generate(prompt)
        control, reply, parse_ok = guardrails.split_and_parse(raw)
        next_state = self._advance(control)
        control.next_state = next_state

        grounding = guardrails.grounding_score(reply, selected)
        # filter first: apply_policies appends the caution line, which the
        # section filter would otherwise strip as an unlabeled line.
        reply = self.filter_sections(reply, next_state)
        reply = guardrails.apply_policies(reply, control, grounding)

        log_write(user_text, {**control.model_dump(),
                              "state": self.state,
                              "grounding": round(grounding, 3),
                              "parse_ok": parse_ok}, reply)

        self.last_control = control
        self.last_debug = {
            "state_before": self.state,
            "state_after": next_state,
            "selected_ids": [c["id"] for c in selected],
            "grounding": grounding,
            "parse_ok": parse_ok,
            "raw": raw,
        }
        self.history.append({
            "user": user_text,
            "state": next_state,
            "goal": control.goal,
            "risk": control.risk,
        })
        self.history = self.history[-MAX_HISTORY:]
        self.state = next_state
        return reply

    def _advance(self, control) -> str:
        # Safety override: high risk or panic always escalates to Crisis.
        if control.risk == "high" or control.mood == "panic":
            return "Crisis"
        proposed = control.next_state
        if proposed in TRANSITIONS[self.state]:
            return proposed
        return self.state

    def _history_text(self) -> str:
        if not self.history:
            return "(first entry this session)"
        return "\n".join(
            f"- [{h['state']}] user said: {h['user']!r} | goal: {h['goal']} | risk: {h['risk']}"
            for h in self.history
        )

    def filter_sections(self, reply: str, next_state: str) -> str:
        lines = reply.splitlines()
        keep = []
        allowed = []

        if next_state in ["Assess", "Act"]:
            allowed = ["Guardian"]
        elif next_state == "Plan":
            allowed = ["Explorer"]
        elif next_state == "Reflect":
            allowed = ["Companion"]
        elif next_state == "Crisis":
            allowed = ["Guardian", "Companion"]

        current_section = None
        for line in lines:
            if any(line.strip().startswith(s) for s in allowed):
                current_section = [s for s in allowed if line.strip().startswith(s)][0]
                keep.append(line)
            elif current_section and line.strip() != "":
                keep.append(line)
            elif current_section and line.strip() == "":
                current_section = None
        return "\n".join(keep).strip()
