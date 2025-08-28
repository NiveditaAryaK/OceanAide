import glob, os, re, json, yaml, hashlib, pathlib

KB_ROOT = pathlib.Path(__file__).resolve().parents[1] / "kb"
OUT = pathlib.Path(__file__).resolve().parents[1] / "data"
OUT.mkdir(parents=True, exist_ok=True)

def load_cards():
    cards = []
    for path in glob.glob(str(KB_ROOT / "**/*.md"), recursive=True):
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
        fm = re.findall(r"---(.*?)---", raw, re.S)
        meta = yaml.safe_load(fm[0]) if fm else {}
        body = raw.split("---", 2)[-1].strip()
        meta["text"] = body
        meta["type"] = pathlib.Path(path).parts[-2]  # guardian/explorer/companion/meta
        meta["id"] = meta.get("id") or os.path.splitext(os.path.basename(path))[0]
        meta["title"] = meta.get("title", meta["id"])
        meta["tags"] = meta.get("tags", [])
        meta["hash"] = hashlib.sha1((meta["id"]+meta["text"]).encode()).hexdigest()[:10]
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
