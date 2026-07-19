# ocean_agent/tools.py
import os, json
from datetime import datetime, timezone

def log_write(user_text: str, control: dict, reply: str, root="data/logs"):
    os.makedirs(root, exist_ok=True)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "user": user_text,
        "control": control,
        "reply": reply
    }
    with open(os.path.join(root, "session.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
