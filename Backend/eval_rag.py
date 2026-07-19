"""RAG evaluation for Ocean Node.

Retrieval eval (offline, always runs):
    python Backend/eval_rag.py
Generation eval (needs the local LLM server up):
    python Backend/eval_rag.py --generation

Gold set lives in data/eval/retrieval_queries.jsonl:
    {"query": "...", "expected": ["card.id", ...]}
A query counts as a hit if ANY expected card is retrieved.
"""
import argparse, json, pathlib, statistics

import retrieval

EVAL_PATH = pathlib.Path(__file__).resolve().parents[1] / "data" / "eval" / "retrieval_queries.jsonl"
K = 4  # same k the agent uses


def load_gold():
    gold = []
    with open(EVAL_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                gold.append(json.loads(line))
    return gold


def eval_retrieval(cards, gold, k=K, verbose=True):
    hits_at_1 = 0
    hits_at_k = 0
    rr_sum = 0.0
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

    n = len(gold)
    print(f"Retrieval eval  ({n} queries, k={k})")
    print(f"  hit@1 : {hits_at_1 / n:6.1%}")
    print(f"  hit@{k} : {hits_at_k / n:6.1%}")
    print(f"  MRR   : {rr_sum / n:6.3f}")
    if verbose and misses:
        print("  misses:")
        for q, exp, got in misses:
            print(f"    {q!r}\n      wanted {exp}, got {got}")
    return {"hit@1": hits_at_1 / n, f"hit@{k}": hits_at_k / n, "mrr": rr_sum / n}


def eval_generation(cards, gold):
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
            "section_ok": section_ok,
        })

    n = len(gold) - len(errors)
    if n == 0:
        print(f"\nGeneration eval: all {len(gold)} queries errored (is the model server up?)")
        return []
    if errors:
        print(f"\n  ({len(errors)} queries errored and were excluded)")
    print(f"\nGeneration eval ({n} queries)")
    print(f"  control JSON parse ok : {parse_ok_n / n:6.1%}")
    print(f"  mean grounding score  : {statistics.mean(grounding_scores):6.3f}")
    print(f"  caution-line policy   : {caution_ok_n / n:6.1%}")
    print(f"  section discipline    : {section_ok_n / n:6.1%}  (raw output stayed in allowed voices)")
    print("  per query:")
    for r in results:
        flags = "".join([
            "P" if r["parse_ok"] else "-",
            "C" if r["caution_ok"] else "-",
            "S" if r["section_ok"] else "-",
        ])
        print(f"    [{flags}] g={r['grounding']:.2f} {r['state']:<8} {r['query']!r}")
    return results


def main():
    ap = argparse.ArgumentParser(description="Evaluate Ocean Node RAG")
    ap.add_argument("--generation", action="store_true",
                    help="also run the LLM end-to-end (requires local model server)")
    ap.add_argument("-k", type=int, default=K)
    args = ap.parse_args()

    cards = retrieval.load_cards()
    gold = load_gold()
    eval_retrieval(cards, gold, k=args.k)
    if args.generation:
        eval_generation(cards, gold)


if __name__ == "__main__":
    main()
