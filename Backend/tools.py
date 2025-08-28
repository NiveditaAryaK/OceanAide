# ocean_agent/tools.py
import os, json
from datetime import datetime

def log_write(user_text: str, control: dict, reply: str, root="data/logs"):
    os.makedirs(root, exist_ok=True)
    entry = {
        "ts": datetime.utcnow().isoformat() + "Z",
        "user": user_text,
        "control": control,
        "reply": reply
    }
    with open(os.path.join(root, "session.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

def timer_set(minutes: int):
    return {"timer": f"{minutes}m", "status": "scheduled"}

def estimate_drift(heading_deg: int, speed_kn: float, hours: float):
    return {
        "nm": round(speed_kn * hours, 2),
        "heading_deg": heading_deg
    }
