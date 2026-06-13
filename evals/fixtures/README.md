# OSAI Eval Fixtures

Golden Q&A scenarios for automated regression testing of the "Ask OSAI" agent.

## Structure

Each `.json` file contains an array of test cases:

```jsonc
{
  "id": "own-01",              // unique, prefixed by category
  "category": "ownership",     // ownership | ticket_triage | routing | qa | action
  "question": "Who owns the VPC security setup?",
  "expected": "Yash",          // the core expected fact in the answer
  "match_mode": "contains",    // contains | exact | regex
  "tags": ["person", "infra"], // optional tags for filtering
  "notes": null                // optional human notes
}
```

## Categories

| Category | Tests | What it evaluates |
|---|---|---|
| `ownership` | Who owns/is responsible for X? | Entity resolution, graph traversal |
| `ticket_triage` | SLA status, priority, assignment | Freshdesk retrieval + reasoning |
| `routing` | Where should X be logged/posted? | Knowledge of org conventions |
| `qa` | Factual recall from indexed docs | RAG retrieval accuracy |
| `action` | "Do X for me" — does it propose the right action? | Tool selection + parameter extraction |

## Running evals

```bash
cd osai-backend
uv run python evals/run_evals.py          # scores all fixtures
uv run python evals/run_evals.py --category ownership  # one category
```

## Adding fixtures

1. Add cases to the relevant `.json` file (or create a new one).
2. Keep `expected` short — it's what we grep for in the agent's answer.
3. Use `match_mode: "contains"` unless exact match is critical.
4. Run the eval suite to establish a baseline before changing the agent.

## Authoring guidelines

- Each scenario should be answerable from the indexed data (Notion, Slack,
  Freshdesk, Google Drive, Zoom transcripts).
- For `action` category, `expected` is the tool+action that should be proposed
  (e.g. `freshdesk:create_ticket`).
- Keep scenarios representative of the university pilot use cases.
