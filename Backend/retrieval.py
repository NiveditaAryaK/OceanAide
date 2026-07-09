import json, pathlib
from typing import List, Dict
from rank_bm25 import BM25Okapi

IDX = pathlib.Path(__file__).resolve().parents[1] / "data" / "index.jsonl"
# retrieval.py (global)
_BM25 = None
_CORPUS = None
def _bm25_init(corpus):
    global _BM25, _CORPUS
    if _BM25 is None or _CORPUS is not corpus:
        _BM25 = BM25Okapi([_tokenize(c) for c in corpus])
        _CORPUS = corpus
    return _BM25

def load_cards():
    cards = []
    with open(IDX, "r", encoding="utf-8") as f:
        for line in f:
            cards.append(json.loads(line))
    return cards

def _tokenize(txt: str) -> List[str]:
    return [t for t in txt.lower().split() if t.isascii()]

def _bm25_init(corpus: List[str]) -> BM25Okapi:
    return BM25Okapi([_tokenize(c) for c in corpus])

# simple type coverage → ensure at least one of each voice if possible
VOICE_PREF = ("guardian", "explorer", "companion")

def search(cards: List[Dict], query: str, k: int = 5) -> List[Dict]:
    corpus = [c.get("text","") for c in cards]
    bm25 = _bm25_init(corpus)

    # top-N lexical hits
    N = max(30, k * 6)
    scores = bm25.get_scores(_tokenize(query))
    ranked = sorted(range(len(cards)), key=lambda i: scores[i], reverse=True)[:N]

    # prioritize diversity across 'type'
    picked_idx = []
    need = set(VOICE_PREF)
    for i in ranked:
        ctype = cards[i].get("type")
        if ctype in need:
            picked_idx.append(i)
            need.remove(ctype)
        if len(picked_idx) >= k:
            break

    # fill remaining slots by score
    if len(picked_idx) < k:
        for i in ranked:
            if i not in picked_idx:
                picked_idx.append(i)
            if len(picked_idx) >= k:
                break

    # light de-dup by title/id (MMR is overkill without vectors; keep it simple)
    seen = set()
    out = []
    for i in picked_idx:
        cid = cards[i].get("id")
        if cid in seen:
            continue
        seen.add(cid)
        out.append(cards[i])
    return out[:k]
