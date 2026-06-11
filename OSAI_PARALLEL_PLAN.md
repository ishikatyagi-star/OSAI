# OSAI — Parallel Working Plan (two founders, side-by-side on GitHub)

**Purpose:** a step-by-step, dependency-ordered sequence so **Ishika (backend)** and **Co-founder (frontend + ops)** can both work and push to GitHub every day **without merge conflicts**, with work split roughly equally.

> Reads with: [`OSAI_EXECUTION_PLAN.md`](OSAI_EXECUTION_PLAN.md) (the *what/how* of each task, with `P#-T#` IDs) and [`OSAI_BUILD_ROADMAP.md`](OSAI_BUILD_ROADMAP.md) (summary). This file is the *who-does-what-when* layer.

---

## 1. Why merge conflicts will be rare (and how we keep it that way)

The repo splits cleanly by directory. **If we each stay in our lane, git never has to merge the same lines.**

| Path | Owner | Notes |
|---|---|---|
| `osai-backend/` | **Ishika** | All Python. Co-founder never edits. |
| `osai-web/` | **Co-founder** | All frontend. Ishika never edits. |
| `infra/`, `docker-compose.yml`, `*.env.example` | **Ishika** | Infra/devops config. |
| `osai-web/public/osai.html` (landing page) | **Co-founder** | The Vercel site. |
| `docs/api-contract.md` (NEW — see §3) | **Ishika writes, Co-founder reads** | The one true shared interface. |
| `OSAI_*.md` plan docs | **Ishika** edits; discuss first | Avoid both editing the same doc in the same hour. |

**Rules of the road:**
1. **One branch per task**, named `be/<task>` or `fe/<task>` (e.g. `be/p1-ask-endpoint`, `fe/p1-chat-ui`). Never commit straight to `main`.
2. **Pull before you start, PR when done.** `git checkout main && git pull` → branch → work → push → open PR → merge. Keep PRs small (a day or two of work max).
3. **Stay in your lane.** If you genuinely must touch the other person's directory, message first and do it in a tiny separate PR.
4. **Merge daily.** Long-lived branches are what cause conflicts. Short ones don't.
5. **If `main` moved while you worked:** `git fetch origin && git rebase origin/main` on your branch before opening the PR.

---

## 2. The git cheat-sheet (paste-ready)

```bash
# start a task
git checkout main && git pull
git checkout -b be/p1-ask-endpoint        # or fe/...

# ... do the work, commit in small chunks ...
git add osai-backend/...                  # only your lane
git commit -m "P1-T3: add /ask endpoint"

# before opening the PR, sync with main
git fetch origin && git rebase origin/main

git push -u origin be/p1-ask-endpoint
gh pr create --fill                       # then merge on GitHub
```

---

## 3. The trick that makes true parallelism work: **contract-first**

The only thing that blocks the frontend is *not knowing the API shape*. So we remove that block: **Ishika writes the API contract before implementing it.**

- Before building each endpoint, Ishika commits the request/response JSON shape to `docs/api-contract.md` (or an OpenAPI stub).
- The moment the contract is committed, **Co-founder can build the UI against it in parallel** — using mock data shaped exactly like the contract — without waiting for the backend to be finished.
- When Ishika's implementation lands, Co-founder swaps mock → live. Near-zero rework.

This is what lets us run both lanes at full speed instead of frontend waiting on backend.

---

## 4. The interleaved sequence (step by step, with handoff gates)

Three lanes run in parallel: **🟦 Backend (Ishika)**, **🟩 Frontend (Co-founder)**, **🟨 Ops/Shared (Co-founder when not blocked)**. A **🚩 Gate** means "the other lane can now pick up the dependent step."

### Round 0 — Foundation (both, day 1, ~1 hr together)
- **S0 (both):** agree on branch naming + lane rules above; set up GitHub branch protection on `main` (require PR). Co-founder installs the frontend toolchain; Ishika installs Docker/uv/Node.

### Round 1 — Get it running + design in parallel
- 🟦 **S1 = P0-T1→T4** (Ishika): boot stack, real Gemini key, one real connector, prove extract→approve→push works. **🚩 Gate A** when the backend runs on real data.
- 🟩 **S2** (Co-founder, parallel, no dependency): **brand guidelines + design system** — colors, type, component library, mockups for the Ask-OSAI chat + dashboard. This is slow/wall-clock work; start it now.
- 🟨 **S3** (Co-founder, parallel): provision **hosting** (Render/Railway/Fly) for backend + Postgres + Qdrant + Redis, and a **Composio account** (free tier) → put the API key where Ishika can use it. (Ops work that balances the load.)

### Round 2 — "Ask OSAI" agent (the demo centerpiece)
- 🟦 **S4a = contract** (Ishika): commit the `/ask` request/response shape to `docs/api-contract.md`. **🚩 Gate B** — frontend can now build the chat UI against it.
- 🟦 **S4b = P1-T1→T3** (Ishika): tool registry → orchestrator → `/ask` endpoint.
- 🟩 **S5 = P0-T5 + P1-T4** (Co-founder, after Gate A/B): wire dashboard to live API; build the **Ask-OSAI chat UI** (citations, action-confirmation cards) — first against the contract mock, then live when S4b lands.

### Round 3 — Breadth (Composio)
- 🟦 **S6 = P2-T1→T3** (Ishika): Composio spike → adapter → enable pilot toolkits. Uses the account from S3.
- 🟩 **S7** (Co-founder): tools/integrations management screen + connect-an-app flow in the UI.

### Round 4 — Memory + knowledge graph
- 🟦 **S8 = P3** (Ishika): entity/edge schema + `org_memory` + wire into the agent. Commit any new read endpoints' contracts first. **🚩 Gate C** for graph endpoints.
- 🟦 **S9 = P4-T1→T3** (Ishika): stand up gbrain sidecar → ingestion → hybrid retrieval.
- 🟩 **S10 = P4-T4** (Co-founder, after Gate C): **org graph inspector** page; surface "what OSAI remembers" in the UI.
- 🟨 **S11 = P6-T2 fixtures** (Co-founder, parallel): author the **eval fixtures** — 10–20 real university scenarios + expected answers. This is domain/judgment work, not Python, so it balances nicely onto the frontend lane.

### Round 5 — Polish + self-improvement (ongoing)
- 🟦 **S12 = P5 + P6-T1/T3** (Ishika): UltraContext context versioning; full logging; run Hermes on one skill using S11's fixtures.
- 🟩 **S13** (Co-founder): eval/debug dashboards; demo polish; pilot onboarding flow.

---

## 5. Load balance check (is it ~equal?)

| Lane | Ishika | Co-founder |
|---|---|---|
| Code | All backend (Python, agent, memory, integrations) | All frontend (chat, dashboard, inspector, design system) |
| Non-code / ops | API contracts, infra config | Hosting/deploy, Composio account, **eval fixtures (domain)**, demo + pilot prep, brand/design |

Backend is heavier on raw code, so Co-founder absorbs **hosting/devops, Composio setup, eval-scenario authoring, and pilot/demo prep** to even it out. Adjust as you go — if one lane stalls, the other pulls a 🟨 shared item forward.

---

## 6. Sync points (the only times you must talk)

1. **Round 0** — agree on conventions.
2. **Each 🚩 Gate** — backend says "contract is committed / endpoint is live," frontend picks it up.
3. **End of each round** — 15-min check: what merged, what's next, any contract changes.

Keep these short. Everything else runs independently in your own directory and branch.

---

## 7. What to execute *first* (this week)

- **Ishika:** S1 (P0-T1→T4) — get the backend running on real data. This is the critical path; nothing impressive demos until it's done.
- **Co-founder:** S2 (design system) **and** S3 (hosting + Composio account) in parallel — both are unblocked and both take wall-clock time.

Then meet at **Gate A** and start Round 2.
