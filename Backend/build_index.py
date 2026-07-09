import glob, os, re, json, yaml, hashlib, pathlib

KB_ROOT = pathlib.Path(__file__).resolve().parents[1] / "Kb"  # NOTE: capital Kb to match your tree
OUT = pathlib.Path(__file__).resolve().parents[1] / "data"
OUT.mkdir(parents=True, exist_ok=True)

def _render_card(meta: dict, body: str) -> str:
    """Deterministically render all useful fields into a compact plaintext block."""
    parts = []

    title = meta.get("title") or meta.get("id") or ""
    if title:
        parts.append(title)

    # Canonicalize common fields across your KB
    for key in ("fact", "why", "notes"):
        v = meta.get(key)
        if isinstance(v, str) and v.strip():
            parts.append(f"{key}: {v.strip()}")

    lists = {
        "steps": "Steps",
        "mission": "Mission",
        "missions": "Missions",
        "lines": "Lines",
        "snippets": "Snippets",
        "entries": "Entries",
    }
    for k, label in lists.items():
        v = meta.get(k)
        if isinstance(v, list) and v:
            items = "; ".join(x.strip() for x in v if isinstance(x, str) and x.strip())
            if items:
                parts.append(f"{label}: {items}")

    # add raw body from MD (if present)
    if isinstance(body, str) and body.strip():
        parts.append(body.strip())

    # tags help retrieval
    tags = meta.get("tags", [])
    if tags:
        parts.append("tags: " + " ".join(tags))

    # final compact text
    return " | ".join(p for p in parts if p)

def load_cards():
    cards = []
    # 1) Markdown with YAML front-matter
    for path in glob.glob(str(KB_ROOT / "**/*.md"), recursive=True):
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
        fm = re.findall(r"---(.*?)---", raw, re.S)
        meta = yaml.safe_load(fm[0]) if fm else {}
        body = raw.split("---", 2)[-1].strip()
        meta["type"] = pathlib.Path(path).parts[-2]  # guardian/explorer/companion/meta
        meta["id"] = meta.get("id") or os.path.splitext(os.path.basename(path))[0]
        meta["title"] = meta.get("title", meta["id"])
        meta["tags"] = meta.get("tags", [])
        meta["text"] = _render_card(meta, body)
        meta["hash"] = hashlib.sha1((meta["id"] + meta["text"]).encode()).hexdigest()[:10]
        cards.append(meta)

    # 2) JSONL cards (your sample shows JSON objects)
    for path in glob.glob(str(KB_ROOT / "**/*.jsonl"), recursive=True):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                meta = json.loads(line)
                # ensure required keys & render text from structured fields
                meta["type"] = meta.get("type") or "meta"
                meta["id"] = meta.get("id") or meta.get("title")
                meta["title"] = meta.get("title", meta["id"])
                meta["tags"] = meta.get("tags", [])
                body = meta.get("text", "")
                meta["text"] = _render_card(meta, body)
                meta["hash"] = hashlib.sha1((meta["id"] + meta["text"]).encode()).hexdigest()[:10]
                cards.append(meta)

    return cards

def main():
    cards = load_cards()
    with open(OUT / "index.jsonl", "w", encoding="utf-8") as f:
        for c in cards:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"Wrote {len(cards)} cards to data/index.jsonl")

if __name__ == "__main__":
    main()

