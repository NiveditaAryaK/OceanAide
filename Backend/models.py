import os, requests

BASE = os.environ.get("MODEL_BASE", "http://127.0.0.1:1234/v1")  # LM Studio default
API_KEY = os.environ.get("MODEL_KEY", "offline-key")
MODEL = os.environ.get("MODEL_NAME", "gpt-oss-20b")

def generate(prompt: str) -> str:
    r = requests.post(
        f"{BASE}/chat/completions",
        headers={"Authorization": f"Bearer {API_KEY}"},
        json={
            "model": MODEL,
            "messages": [
                {"role":"system","content":"You are Ocean Node."},
                {"role":"user","content": prompt}
            ],
            "temperature": 0,
            "stream": False
        },
        timeout=300
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]
