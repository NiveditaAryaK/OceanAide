# OceanAide (Ocean Node)

An offline-first AI assistant for people at sea. Ocean Node answers safety, ocean-knowledge, and morale questions using only a local knowledge base and a locally hosted LLM — no internet connection required. Every answer is grounded in the bundled knowledge cards; when the model can't produce a grounded reply, the assistant falls back to verbatim card content rather than improvising.

## How it works

You type a log entry (e.g. "storm building, waves getting rough") into the CLI. The agent then:

1. **Retrieves** the most relevant knowledge-base cards using BM25 lexical search, with diversity across the three "voices" (`Backend/retrieval.py`). Cards carry query-language `aliases` in their front-matter so real user phrasings ("went over the side", "skin is blistering") match the right card.
2. **Prompts** a local LLM (LM Studio-compatible OpenAI API, default `http://127.0.0.1:1234`) with the selected cards as the only allowed source of facts (`Backend/models.py`, `Backend/prompts.py`).
3. **Validates** the response through guardrails (`Backend/state.py`, `Backend/guardrails.py`):
   - the model must emit a control JSON (brace-balanced parse; safe defaults on any violation) plus a reply;
   - only voice sections allowed for the current state are kept (markdown-tolerant matching);
   - a grounding score checks reply sentences against the retrieved cards — low grounding, low confidence, or high risk appends a fixed caution line.
4. **Degrades safely**: if the model server is down, times out, or returns nothing usable, the agent answers with the top retrieved card verbatim plus the caution line — never silence, never invention.
5. **Logs** every interaction to `data/logs/` (gitignored).

### Agent states and voices

The agent runs a small state machine — **Assess → Plan → Act → Reflect**, plus a **Crisis** state — and each state permits specific voices:

| Voice | Role | KB folder |
|---|---|---|
| **Guardian** | Immediate safety, heavy weather, first aid, distress signals | `Kb/guardian/` |
| **Explorer** | Ocean knowledge — tides, currents, sky clues, bioluminescence, micro-missions | `Kb/explorer/` |
| **Companion** | Morale, reframes, routines, mental first aid | `Kb/companion/` |

## Project layout

```
Backend/          # Agent loop, retrieval, prompts, guardrails, LLM client, eval
Kb/               # Knowledge base cards (Markdown with YAML front-matter)
data/index.jsonl  # Built retrieval index
data/eval/        # Gold query set for the eval harness
data/logs/        # Interaction logs (gitignored)
```

## Getting started

1. Install dependencies (Python 3.13) and start a local LLM server (e.g. LM Studio):
   ```
   pip install -r requirements.txt
   ```
   Configure via env vars: `MODEL_BASE`, `MODEL_KEY`, `MODEL_NAME`, `MODEL_TIMEOUT`, `MODEL_MAX_TOKENS` (default 2048 — reasoning models like gpt-oss spend most of their budget thinking before they answer).
2. Build the index from the knowledge base:
   ```
   python Backend/build_index.py
   ```
3. Run the agent:
   ```
   python Backend/app.py
   ```

## Evaluation

A gold set of 30 real-phrasing queries lives in `data/eval/retrieval_queries.jsonl` (`{"query": ..., "expected": [card ids]}`).

```
python Backend/eval_rag.py               # retrieval only: hit@1, hit@k, MRR (offline, fast)
python Backend/eval_rag.py --generation  # full agent per query (needs the LLM server up)
```

The generation mode checks the output contract end to end: control-JSON parse rate, grounding score, caution-line policy, and voice-section discipline. Further modes (all need the LLM server up):

| Flag | Axis | What it measures |
|---|---|---|
| `--negative` | Negative rejection (RGB) | Out-of-scope queries (`negative_queries.jsonl`) must be refused, never answered from general knowledge; replies printed for fabrication review |
| `--rgb` | Noise robustness (RGB) | Half the context replaced with irrelevant cards; parse rate and grounding vs the clean cards compared |
| `--counterfactual` | Counterfactual robustness (RGB) | A retrieved card is poisoned with a planted falsehood (`counterfactual.jsonl`); replies classified ACCEPTED / ECHOED+FLAGGED / REJECTED / AVOIDED. The system trusts its curated KB by design, so this quantifies the blast radius of index corruption |
| `--integration` | Information integration | On multi-card queries, does the final reply draw sentences from *every* expected card, not just retrieve them |
| `--multiturn` | Agent behavior | Scripted 3-turn scenarios (`scenarios.jsonl`) run in one session: escalation to Crisis, de-escalation, reflection — asserting accepted states and legal transitions per turn |
| `--judge` | Faithfulness + relevance (RAGAS-style) | Local-LLM judge, scores reported separately; add ~15 human labels to `judge_calibration.jsonl` to get an error bar (uncalibrated warning otherwise) |

Current scores (gpt-oss-20b): retrieval **hit@1 100%, hit@4 100%, MRR 1.0, nDCG@4 0.98** (30 queries); generation **parse 100%, caution policy 100%, section discipline 100%, mean grounding 0.98, worst-case 0.83**; **negative rejection 100%** (10 out-of-scope queries, no fabricated answers); noise robustness **parse 100%** with grounding 1.00 → 0.81 when half the context is replaced with irrelevant cards.

To improve retrieval, add `aliases` (phrases users would actually type, including inflected forms — the stemmer only handles plurals) to a card's front-matter, rebuild the index, and re-run the eval. Grow the gold set with fresh phrasings before trusting the numbers.

> **Disclaimer:** Guidance is grounded in the bundled knowledge cards only and is not a substitute for professional maritime training or emergency services. Use judgment; conditions vary.
