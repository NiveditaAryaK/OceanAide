
import os, requests

BASE = os.environ.get("MODEL_BASE", "http://127.0.0.1:1234/v1")  # LM Studio default
API_KEY = os.environ.get("MODEL_KEY", "offline-key")
MODEL = os.environ.get("MODEL_NAME", "gpt-oss-20b")
TIMEOUT = int(os.environ.get("MODEL_TIMEOUT", "120"))
# gpt-oss spends most of its budget on the reasoning channel before emitting
# content; 512 caused finish_reason=length with empty replies.
MAX_TOKENS = int(os.environ.get("MODEL_MAX_TOKENS", "2048"))

class ModelError(Exception):
    """Local LLM server unreachable or returned an unusable response.
    Callers should degrade gracefully (the agent falls back to verbatim
    card content) instead of crashing."""


def _request(prompt: str) -> str:
    r = requests.post(
        f"{BASE}/chat/completions",
        headers={"Authorization": f"Bearer {API_KEY}"},
        json={
            "model": MODEL,
            "messages": [
                {"role":"system","content":"You are Ocean Node."},
                {"role":"user","content": prompt}
            ],
            "temperature": 0.0,
            "top_p": 1.0,
            "max_tokens": MAX_TOKENS,
            "stream": False,
            "stop": ["</END>"]  # You can add "</END>" at end of prompt if you like
        },
        timeout=TIMEOUT
    )
    r.raise_for_status()
    choice = r.json()["choices"][0]
    if choice.get("finish_reason") == "length":
        print("[models] warning: reply truncated at max_tokens "
              f"({MAX_TOKENS}); consider raising MODEL_MAX_TOKENS")
    return choice["message"].get("content") or ""


def generate(prompt: str) -> str:
    last_err = None
    for _ in range(2):
        try:
            return _request(prompt)
        except (requests.exceptions.RequestException, KeyError, ValueError) as e:
            last_err = e
    raise ModelError(f"model server at {BASE} failed after retry: {last_err}") from last_err
