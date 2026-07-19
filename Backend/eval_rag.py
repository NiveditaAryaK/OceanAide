"""RAG evaluation for Ocean Node.

Offline (fast, no LLM needed):
    python Backend/eval_rag.py                 # BEIR-style retrieval metrics
                                               # + negative-set score separation
LLM required (LM Studio up):
    python Backend/eval_rag.py --generation    # output-contract eval per query
    python Backend/eval_rag.py --negative      # RGB negative rejection
    python Backend/eval_rag.py --rgb           # RGB noise robustness (subset)
    python Backend/eval_rag.py --judge         # RAGAS-style faithfulness +
                                               # answer relevance (implies
                                               # --generation; needs calibration
                                               # set to be trustworthy)

Gold sets in data/eval/:
    retrieval_queries.jsonl   {"query": ..., "expected": ["card.id", ...]}
    negative_queries.jsonl    {"query": ...}   out-of-scope; correct behavior
                                               is rejection, not an answer
    judge_calibration.jsonl   {"query": ..., "faithfulness": 1-5,
                               "relevance": 1-5}  human labels for judge check

Deliberately NOT measured: single aggregate score (masks failures),
BLEU/ROUGE (token overlap != correctness for open-ended replies).
"""
import argparse, json, math, pathlib, random, statistics

import retrieval

EVAL_DIR = pathlib.Path(__file__).resolve().parents[1] / "data" / "eval"
GOLD_PATH = EVAL_DIR / "retrieval_queries.jsonl"
NEG_PATH = EVAL_DIR / "negative_queries.jsonl"
CALIB_PATH = EVAL_DIR / "judge_calibration.jsonl"
K = 4  # same k the agent uses


def load_jsonl(path):
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


# ---------------------------------------------------------------- retrieval

def eval_retrieval(cards, gold, k=K, verbose=True):
    """BEIR-style: hit@1, hit@k, MRR, nDCG@k, precision@k, recall@k, and
    integration rate (multi-card queries with ALL expected cards in top-k)."""
    hits_at_1 = hits_at_k = 0
    rr_sum = ndcg_sum = prec_sum = rec_sum = 0.0
    multi = multi_ok = 0
    misses = []

    for item in gold:
        got = [c["id"] for c in retrieval.search(cards, item["query"], k=k)]
        expected = set(item["expected"])
        rank = next((i + 1 for i, cid in enumerate(got) if cid in expected), None)
        if rank == 1:
            hits_at_1 += 1
        if rank is not None:
            hits_at_k += 1
            rr_sum += 1.0 / rank
        else:
            misses.append((item["query"], item["expected"], got))

        rel = [1 if cid in expected else 0 for cid in got]
        dcg = sum(r / math.log2(i + 2) for i, r in enumerate(rel))
        idcg = sum(1 / math.log2(i + 2) for i in range(min(len(expected), k)))
        ndcg_sum += dcg / idcg if idcg else 0.0
        prec_sum += sum(rel) / k
        rec_sum += sum(rel) / len(expected)

        if len(expected) > 1:
            multi += 1
            multi_ok += expected.issubset(set(got))

    n = len(gold)
    print(f"Retrieval eval  ({n} queries, k={k})")
    print(f"  hit@1  : {hits_at_1 / n:6.1%}")
    print(f"  hit@{k}  : {hits_at_k / n:6.1%}")
    print(f"  MRR    : {rr_sum / n:6.3f}")
    print(f"  nDCG@{k} : {ndcg_sum / n:6.3f}")
    print(f"  prec@{k} : {prec_sum / n:6.3f}  (low is expected: 1-2 relevant cards vs k={k})")
    print(f"  recall@{k}: {rec_sum / n:6.3f}")
    if multi:
        print(f"  integration: {multi_ok}/{multi} multi-card queries had ALL expected cards in top-{k}")
    if verbose and misses:
        print("  misses:")
        for q, exp, got in misses:
            print(f"    {q!r}\n      wanted {exp}, got {got}")
    return {"hit@1": hits_at_1 / n, f"hit@{k}": hits_at_k / n, "mrr": rr_sum / n,
            "ndcg": ndcg_sum / n}


def eval_negative_retrieval(cards, gold, negatives):
    """Score-separation analysis: can a BM25 score floor distinguish
    in-domain from out-of-scope queries? Informs a refusal threshold."""
    corpus = [c.get("text", "") for c in cards]
    bm25 = retrieval._bm25_init(corpus)

    def top_score(q):
        scores = bm25.get_scores(retrieval._tokenize(q))
        return max(scores) if len(scores) else 0.0

    pos = sorted(top_score(g["query"]) for g in gold)
    neg = sorted(top_score(n["query"]) for n in negatives)

    print(f"\nNegative-set score separation ({len(pos)} in-domain vs {len(neg)} out-of-scope)")
    print(f"  in-domain top-BM25   : min {pos[0]:.2f}  median {pos[len(pos)//2]:.2f}  max {pos[-1]:.2f}")
    print(f"  out-of-scope top-BM25: min {neg[0]:.2f}  median {neg[len(neg)//2]:.2f}  max {neg[-1]:.2f}")
    overlap = [s for s in neg if s >= pos[0]]
    if overlap:
        print(f"  overlap: {len(overlap)} out-of-scope queries score above the weakest in-domain query")
        print("  -> a pure score floor would misclassify these; combine with the LLM confidence signal")
    else:
        floor = (pos[0] + neg[-1]) / 2
        print(f"  clean separation -> a score floor around {floor:.2f} would reject all out-of-scope queries")


# --------------------------------------------------------------- generation

def eval_generation(cards, gold, label="Generation eval"):
    """Runs the full agent per query (fresh session each time) and checks the
    output contract: parseable control JSON, grounded reply, caution-line
    policy, and no disallowed voice sections."""
    from state import Agent

    ALLOWED_SECTIONS = {
        "Assess": {"Guardian"}, "Act": {"Guardian"}, "Plan": {"Explorer"},
        "Reflect": {"Companion"}, "Crisis": {"Guardian", "Companion"},
    }
    ALL_SECTIONS = {"Guardian", "Explorer", "Companion"}

    parse_ok_n = 0
    grounding_scores = []
    caution_ok_n = 0
    section_ok_n = 0
    results = []

    errors = []
    for item in gold:
        agent = Agent(cards)
        try:
            reply = agent.step(item["query"])
        except Exception as e:
            errors.append((item["query"], repr(e)))
            print(f"    [!] error on {item['query']!r}: {e}")
            continue
        dbg = agent.last_debug
        ctl = agent.last_control

        parse_ok_n += dbg["parse_ok"]
        grounding_scores.append(dbg["grounding"])

        from guardrails import CAUTION_LINE, GROUNDING_FLOOR
        needs_caution = (ctl.confidence < 0.5 or ctl.risk == "high"
                         or dbg["grounding"] < GROUNDING_FLOOR)
        caution_ok = (CAUTION_LINE in reply) if needs_caution else True
        caution_ok_n += caution_ok

        disallowed = ALL_SECTIONS - ALLOWED_SECTIONS[dbg["state_after"]]
        raw_reply = dbg["raw"].split("REPLY:", 1)[-1]
        section_ok = not any(
            line.strip().startswith(s)
            for line in raw_reply.splitlines() for s in disallowed
        )
        section_ok_n += section_ok

        results.append({
            "query": item["query"], "state": dbg["state_after"],
            "grounding": round(dbg["grounding"], 2),
            "parse_ok": dbg["parse_ok"], "caution_ok": caution_ok,
            "section_ok": section_ok, "reply": reply,
            "confidence": ctl.confidence,
            "cards_text": "\n".join(f"[{c['id']}] {c['text']}"
                                    for c in retrieval.search(cards, item["query"], k=K)),
        })

    n = len(gold) - len(errors)
    if n == 0:
        print(f"\n{label}: all {len(gold)} queries errored (is the model server up?)")
        return []
    if errors:
        print(f"\n  ({len(errors)} queries errored and were excluded)")
    print(f"\n{label} ({n} queries)")
    print(f"  control JSON parse ok : {parse_ok_n / n:6.1%}")
    print(f"  mean grounding score  : {statistics.mean(grounding_scores):6.3f}")
    print(f"  caution-line policy   : {caution_ok_n / n:6.1%}")
    print(f"  section discipline    : {section_ok_n / n:6.1%}  (raw output stayed in allowed voices)")
    worst = sorted(results, key=lambda r: r["grounding"])[:5]
    print("  worst grounding (hallucination risk lives here, not in the mean):")
    for r in worst:
        print(f"    g={r['grounding']:.2f} {r['state']:<8} {r['query']!r}")
    print("  per query:")
    for r in results:
        flags = "".join([
            "P" if r["parse_ok"] else "-",
            "C" if r["caution_ok"] else "-",
            "S" if r["section_ok"] else "-",
        ])
        print(f"    [{flags}] g={r['grounding']:.2f} {r['state']:<8} {r['query']!r}")
    return results


def eval_negative_generation(cards, negatives):
    """RGB negative rejection: out-of-scope queries must be rejected
    (low confidence and/or caution line), never answered with invented
    facts. Replies are printed for manual review — automated checks can't
    prove non-fabrication."""
    from state import Agent
    from guardrails import CAUTION_LINE

    rejected_n = 0
    rows = []
    for item in negatives:
        agent = Agent(cards)
        try:
            reply = agent.step(item["query"])
        except Exception as e:
            print(f"    [!] error on {item['query']!r}: {e}")
            continue
        ctl = agent.last_control
        rejected = ctl.confidence < 0.5 or CAUTION_LINE in reply
        rejected_n += rejected
        rows.append((rejected, ctl.confidence, item["query"], reply))

    n = len(rows)
    if n == 0:
        print("\nNegative rejection: no queries completed (is the model server up?)")
        return
    print(f"\nNegative rejection ({n} out-of-scope queries)")
    print(f"  rejection rate: {rejected_n / n:6.1%}  (confidence < 0.5 or caution line)")
    print("  review replies below — a 'rejected' reply that still invents facts is a fail:")
    for rejected, conf, q, reply in rows:
        mark = "REJ" if rejected else "ANS"
        head = " ".join(reply.split())[:110]
        print(f"    [{mark}] conf={conf:.2f} {q!r}")
        print(f"          -> {head}")


def eval_noise(cards, gold, sample=10, seed=7):
    """RGB noise robustness: replace half the retrieved context with
    irrelevant cards and compare contract metrics against the clean run
    on the same query subset."""
    from state import Agent

    rng = random.Random(seed)
    subset = gold[::max(1, len(gold) // sample)][:sample]

    import guardrails

    def run(noisy):
        parse_n, ground = 0, []
        for item in subset:
            agent = Agent(cards)
            clean_selected = retrieval.search(cards, item["query"], k=K)
            selected = clean_selected
            if noisy:
                top_ids = {c["id"] for c in clean_selected}
                pool = [c for c in cards if c["id"] not in top_ids]
                selected = clean_selected[:K // 2] + rng.sample(pool, K - K // 2)
            try:
                reply = agent.step(item["query"], selected=selected)
            except Exception as e:
                print(f"    [!] error on {item['query']!r}: {e}")
                continue
            parse_n += agent.last_debug["parse_ok"]
            # Always score against the CLEAN cards: scoring against the
            # noisy context would inflate grounding (bigger vocab = easier
            # coverage). A reply that leans on the noise cards drops here.
            ground.append(guardrails.grounding_score(reply, clean_selected))
        n = len(ground)
        return (parse_n / n if n else 0.0,
                statistics.mean(ground) if ground else 0.0, n)

    clean_parse, clean_ground, n1 = run(noisy=False)
    noisy_parse, noisy_ground, n2 = run(noisy=True)
    print(f"\nNoise robustness ({len(subset)} queries, {K // 2}/{K} context cards replaced with noise)")
    print(f"  parse ok  : clean {clean_parse:6.1%}  noisy {noisy_parse:6.1%}")
    print(f"  grounding : clean {clean_ground:6.3f}  noisy {noisy_ground:6.3f}")
    print("  (both scored against the clean relevant cards; a big noisy drop"
          " means the model leaned on the irrelevant cards)")


# -------------------------------------------------------------------- judge

_FAITH_PROMPT = """CONTEXT:
{cards}

ANSWER:
{reply}

Rate how faithful the ANSWER is to the CONTEXT on a 1-5 scale:
5 = every claim in the ANSWER is supported by the CONTEXT
3 = mostly supported, minor unsupported additions
1 = key claims are not in the CONTEXT
Reply with ONLY the number."""

_REL_PROMPT = """QUESTION: {query}

ANSWER:
{reply}

Rate how directly the ANSWER addresses the QUESTION on a 1-5 scale:
5 = fully addresses it, 3 = partially, 1 = off-topic or non-answer.
Reply with ONLY the number."""


def _judge_score(prompt):
    import models, re
    try:
        out = models.generate(prompt)
    except models.ModelError:
        return None
    m = re.search(r"[1-5]", out)
    return int(m.group()) if m else None


def eval_judge(results):
    """RAGAS-style faithfulness + answer relevance via the local LLM as
    judge. Reported separately, never averaged together. Trust requires the
    human calibration set (ARES); without it the numbers are directional."""
    faith, rel = {}, {}
    for r in results:
        f = _judge_score(_FAITH_PROMPT.format(cards=r["cards_text"], reply=r["reply"]))
        a = _judge_score(_REL_PROMPT.format(query=r["query"], reply=r["reply"]))
        if f is not None:
            faith[r["query"]] = f
        if a is not None:
            rel[r["query"]] = a

    print(f"\nLLM-judge eval ({len(faith)} queries scored)")
    if faith:
        print(f"  faithfulness    : mean {statistics.mean(faith.values()):.2f}/5"
              f"   worst: {min(faith.values())}")
    if rel:
        print(f"  answer relevance: mean {statistics.mean(rel.values()):.2f}/5"
              f"   worst: {min(rel.values())}")
    low = [q for q, s in faith.items() if s <= 3]
    if low:
        print("  faithfulness <= 3 (inspect these):")
        for q in low:
            print(f"    {q!r}")

    if CALIB_PATH.exists():
        calib = {c["query"]: c for c in load_jsonl(CALIB_PATH)}
        fd = [abs(faith[q] - calib[q]["faithfulness"]) for q in faith if q in calib]
        rd = [abs(rel[q] - calib[q]["relevance"]) for q in rel if q in calib]
        if fd or rd:
            print(f"  calibration vs human labels ({len(fd)} overlapping queries):")
            if fd:
                print(f"    faithfulness MAE: {statistics.mean(fd):.2f} points")
            if rd:
                print(f"    relevance MAE   : {statistics.mean(rd):.2f} points")
        else:
            print("  calibration file present but no overlapping queries")
    else:
        print("  WARNING: judge is UNCALIBRATED — no human labels in "
              f"{CALIB_PATH.name}. Treat scores as directional only. To "
              "calibrate: copy ~15 (query, faithfulness, relevance) rows "
              "with your own 1-5 labels into that file.")


# --------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="Evaluate Ocean Node RAG")
    ap.add_argument("--generation", action="store_true",
                    help="run the LLM end-to-end on the gold set")
    ap.add_argument("--negative", action="store_true",
                    help="RGB negative rejection on out-of-scope queries (LLM)")
    ap.add_argument("--rgb", action="store_true",
                    help="RGB noise robustness on a query subset (LLM, 2x calls)")
    ap.add_argument("--judge", action="store_true",
                    help="LLM-judge faithfulness + relevance (implies --generation)")
    ap.add_argument("-k", type=int, default=K)
    args = ap.parse_args()

    cards = retrieval.load_cards()
    gold = load_jsonl(GOLD_PATH)
    negatives = load_jsonl(NEG_PATH) if NEG_PATH.exists() else []

    eval_retrieval(cards, gold, k=args.k)
    if negatives:
        eval_negative_retrieval(cards, gold, negatives)

    results = []
    if args.generation or args.judge:
        results = eval_generation(cards, gold)
    if args.negative and negatives:
        eval_negative_generation(cards, negatives)
    if args.rgb:
        eval_noise(cards, gold)
    if args.judge and results:
        eval_judge(results)


if __name__ == "__main__":
    main()
