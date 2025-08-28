import json, pathlib

IDX = pathlib.Path(__file__).resolve().parents[1] / "data" / "index.jsonl"

def load_cards():
    cards = []
    with open(IDX, "r", encoding="utf-8") as f:
        for line in f:
            cards.append(json.loads(line))
    return cards

def search(cards, query: str, k=5):
    q = query.lower()
    scored = []
    for c in cards:
        hay = (c.get("title","")+" "+c.get("text","")+" "+" ".join(c.get("tags",[]))).lower()
        score = sum(1 for w in set(q.split()) if w in hay)
        if c["type"] in ("guardian","explorer","companion"): score += 1  # bias
        scored.append((score, c))
    scored.sort(key=lambda x: x[0], reverse=True)

    out, need = [], set(["guardian","explorer","companion"])
    for _, c in scored:
        if c["type"] in need:
            out.append(c); need.remove(c["type"])
        if not need: break
    for _, c in scored:
        if c not in out and len(out) < k: out.append(c)
    return out
