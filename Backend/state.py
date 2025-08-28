import retrieval, prompts, models, guardrails
from tools import log_write

class Agent:
    def __init__(self, cards):
        self.cards = cards
        self.last_control = None

    def step(self, user_text: str):
        selected = retrieval.search(self.cards, user_text, k=5)
        cards_text = "\n\n".join(c["text"] for c in selected)
        prompt = prompts.SYSTEM + "\n\n" + prompts.USER_TEMPLATE.format(
            user_text=user_text, cards_text=cards_text
        )
        raw = models.generate(prompt)
        control, reply = guardrails.split_and_parse(raw)
        reply = guardrails.apply_policies(reply, control)
        reply = self.filter_sections(reply, control.next_state)  # Add self.
        log_write(user_text, control.model_dump(), reply)
        self.last_control = control
        return reply
    
    def filter_sections(self, reply: str, next_state: str) -> str:  # Add self parameter
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

        current_section = None  # Fix typo
        for line in lines:
            if any(line.strip().startswith(s) for s in allowed):
                current_section = [s for s in allowed if line.strip().startswith(s)][0]
                keep.append(line)
            elif current_section and line.strip() != "":
                keep.append(line)
            elif current_section and line.strip() == "":
                current_section = None
        return "\n".join(keep).strip()