import json, pathlib, re, unicodedata
from typing import List, Dict
from rank_bm25 import BM25Okapi

IDX = pathlib.Path(__file__).resolve().parents[1] / "data" / "index.jsonl"

_BM25 = None
_CORPUS_KEY = None

# Words too common to carry signal in a 20-card corpus.
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "get", "has", "have", "how", "if", "in", "is", "it", "its", "my", "no",
    "not", "of", "on", "or", "our", "so", "than", "that", "the", "their",
    "them", "then", "there", "they", "this", "to", "was", "we", "were",
    "what", "when", "where", "which", "while", "will", "with", "you", "your",
}

_WORD_RE = re.compile(r"[a-z0-9']+")

# Map typographic punctuation to ASCII before tokenizing, so "ocean's"
# (curly apostrophe) doesn't vanish from the index.
_PUNCT_MAP = str.maketrans({
    "’": "'", "‘": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", " ": " ",
})


def _stem(tok: str) -> str:
    """Very light stemming: possessives and simple plurals only.
    Plain 's' stripping keeps waves/wave and tides/tide aligned; a broader
    'es' rule would map waves->wav and break the match."""
    if tok.endswith("'s"):
        tok = tok[:-2]
    if len(tok) > 3 and tok.endswith("ies"):
        return tok[:-3] + "y"
    if len(tok) > 3 and tok.endswith(("xes", "ches", "shes", "zes")):
        return tok[:-2]
    if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
        return tok[:-1]
    return tok


def _tokenize(txt: str) -> List[str]:
    txt = unicodedata.normalize("NFKD", txt).translate(_PUNCT_MAP).lower()
    toks = []
    for m in _WORD_RE.finditer(txt):
        tok = _stem(m.group().strip("'"))
        if tok and tok not in STOPWORDS:
            toks.append(tok)
    return toks


def _bm25_init(corpus: List[str]) -> BM25Okapi:
    global _BM25, _CORPUS_KEY
    # Key on content, not id(): the corpus list is rebuilt every call, so a
    # recycled id could serve a stale index after the cards change.
    key = hash(tuple(corpus))
    if _BM25 is None or _CORPUS_KEY != key:
        _BM25 = BM25Okapi([_tokenize(c) or ["<empty>"] for c in corpus])
        _CORPUS_KEY = key
    return _BM25


def load_cards():
    cards = []
    with open(IDX, "r", encoding="utf-8") as f:
        for line in f:
            cards.append(json.loads(line))
    return cards


# simple type coverage → ensure at least one of each voice if possible
VOICE_PREF = ("guardian", "explorer", "companion")


def search(cards: List[Dict], query: str, k: int = 5) -> List[Dict]:
    corpus = [c.get("text", "") for c in cards]
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
