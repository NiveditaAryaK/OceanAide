# OceanAide (Ocean Node)

An offline-first AI assistant for people at sea. Ocean Node answers safety, navigation, and morale questions using only a local knowledge base and a locally hosted LLM — no internet connection required.

## How it works

You type a log entry (e.g. "storm building, waves getting rough") into the CLI. The agent then:

1. **Retrieves** the most relevant knowledge-base cards using BM25 lexical search, with diversity across the three "voices" (`Backend/retrieval.py`).
2. **Prompts** a local LLM (LM Studio-compatible OpenAI API, default `http://127.0.0.1:1234`) with the selected cards as the only allowed source of facts (`Backend/models.py`, `Backend/prompts.py`).
3. **Validates** the response through guardrails — the model must emit a control JSON plus a reply, and only sections allowed for the current state are kept (`Backend/state.py`, `Backend/guardrails.py`).
4. **Logs** every interaction to `data/logs/`.

### Agent states and voices

The agent runs a small state machine — **Assess → Plan → Act → Reflect**, plus a **Crisis** state — and each state permits specific voices:

| Voice | Role | KB folder |
|---|---|---|
| **Guardian** | Immediate safety, heavy weather, first aid, distress signals | `Kb/guardian/` |
| **Explorer** | Ocean knowledge — tides, currents, sky clues, bioluminescence, micro-missions | `Kb/explorer/` |
| **Companion** | Morale, reframes, routines, mental first aid | `Kb/companion/` |

## Project layout

```
Backend/          # Agent loop, retrieval, prompts, guardrails, LLM client
Kb/               # Knowledge base cards (Markdown with YAML front-matter)
data/index.jsonl  # Built retrieval index
data/logs/        # Interaction logs
```

## Getting started

1. Install dependencies (Python 3.13, `requests`, `rank-bm25`, `pyyaml`) and start a local LLM server (e.g. LM Studio). Configure via env vars: `MODEL_BASE`, `MODEL_KEY`, `MODEL_NAME`.
2. Build the index from the knowledge base:
   ```
   python Backend/build_index.py
   ```
3. Run the agent:
   ```
   python Backend/app.py
   ```

> **Disclaimer:** Guidance is grounded in the bundled knowledge cards only and is not a substitute for professional maritime training or emergency services. Use judgment; conditions vary.
