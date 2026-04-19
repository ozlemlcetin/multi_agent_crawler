# Multi-Agent Development Workflow

## Purpose

This document describes the multi-agent workflow used to **design, build, and document**
the `multi_agent_crawler` project. The workflow governs how different AI agents collaborated
during development — not how the runtime application operates.

The runtime system is a plain local Python application. It has no LLM agents, no agent
orchestration, and no AI components at runtime. The multi-agent requirement for this course
assignment is fulfilled entirely at **development time**.

Agents were executed across separate chat sessions using a mix of Claude Code, ChatGPT, and
Gemini depending on the task. Tool choice was subordinate to role clarity, scope control, and
patch-by-patch verification.

---

## Why Development-Time Rather Than Runtime Multi-Agent

A runtime multi-agent architecture was considered and deliberately rejected for the following
reasons:

- **Scope fit** — the core deliverable is a local web crawler and search tool, not an AI
  orchestration platform. Embedding LLM agents into the runtime would add complexity without
  adding value to the crawl-index-search pipeline.
- **Simplicity constraint** — the project spec calls for stdlib-first, single-process,
  CLI-first design. Runtime agents would contradict all three constraints.
- **Reliability** — a synchronous Python pipeline is deterministic and easy to test.
  LLM-in-the-loop runtime systems introduce latency, cost, and non-determinism.
- **Honest scope** — using agents only for development is transparent and appropriate.
  The multi-agent requirement is met through verifiable design artifacts and patch history,
  not through hidden runtime components.

---

## Final Agent Roster

The workflow uses exactly five agents. Each agent has a defined role, input set, and
output set. No other agent roles exist in this project.

### 1. Architecture Agent

**Responsibility:** Define system structure, module boundaries, data flow, and schema design.
Produce durable technical decisions that downstream agents implement.

**Inputs:**
- Project requirements and constraints
- User feedback and correction on prior proposals

**Outputs:**
- Module decomposition and dependency graph
- SQLite schema definition
- Data model specifications (`models.py` types)
- Architectural rules (e.g., single writer path, bounded frontier, stdlib-only)

---

### 2. Implementation Agent

**Responsibility:** Write all production Python code patch-by-patch, following architecture
decisions exactly. Does not propose architectural changes.

**Inputs:**
- Architecture Agent output (schema, module specs, rules)
- Per-patch scope from the Controller Agent
- User correction and approval from prior patches

**Outputs:**
- Python source files (`fetcher.py`, `parser.py`, `storage.py`, `frontier.py`,
  `index_writer.py`, `search_service.py`, `coordinator.py`, `cli.py`, etc.)
- Patch-by-patch acceptance confirmation
- Terminal demo output as evidence of correctness

---

### 3. Innovation Agent

**Responsibility:** Identify improvements, flag risks, and propose alternatives before or
during implementation. Acts as a forward-looking reviewer of decisions — not a code author.

**Inputs:**
- Current architecture and implementation state
- Open design questions or flagged edge cases

**Outputs:**
- Risk assessments (e.g., frontier not persisted across sessions)
- Improvement proposals (e.g., min-depth upsert for discoveries)
- Alternative approaches for the human to evaluate

---

### 4. Documentation Agent

**Responsibility:** Produce all written documentation including `README.md`,
`multi_agent_workflow.md`, `product_prd.md`, and `recommendation.md`. Reflects only
what is actually implemented; does not invent features.

**Inputs:**
- Confirmed repository state (actual source files and CLI behavior)
- Architecture decisions and patch history
- Human-approved scope and phrasing corrections

**Outputs:**
- `README.md` — installation, usage, architecture summary, known limitations
- `multi_agent_workflow.md` — this document
- `product_prd.md` — requirements specification
- `recommendation.md` — design decisions and future recommendations

---

### 5. Controller Agent

**Responsibility:** Coordinate agent activity, define per-patch scope, enforce frozen
constraints, and route work to the correct agent. Does not implement code or write final docs.

**Inputs:**
- Project roadmap and patch plan
- Human user approvals and redirections
- Agent outputs that require routing or sequencing decisions

**Outputs:**
- Per-patch briefs with frozen constraints ("PATCH N ONLY")
- Scope boundaries enforced at each handoff
- Escalations to the human when proposals conflict

---

## Handoff Flow

```
Human User
    │
    ▼
Controller Agent  ──────────────────────────────────────┐
    │                                                    │
    ├──► Architecture Agent  ──► schema / module specs  │
    │                                                    │
    ├──► Implementation Agent ──► source code patches   │
    │           │                                        │
    │           └──► terminal demo / DB proof           │
    │                                                    │
    ├──► Innovation Agent  ──► risk flags / proposals   │
    │                                                    │
    └──► Documentation Agent ──► README / docs          │
                                                         │
    All agent outputs route back to Human User ◄────────┘
    for approval before the next step proceeds.
```

Agents do not hand off directly to each other without passing through human review.
The human user is the final authority at every gate.

---

## Decision Authority and Approval Model

| Decision type | Who decides |
|---|---|
| Architectural changes | Human user (after Architecture Agent proposal) |
| Patch scope and frozen constraints | Controller Agent, confirmed by human |
| Code correctness within a patch | Implementation Agent, verified by human review of output |
| Risk acceptance | Human user (after Innovation Agent flag) |
| Documentation phrasing | Human user (targeted corrections applied by Documentation Agent) |

No agent has autonomous authority to change frozen constraints or expand scope.
If the Controller Agent detects a constraint violation in a proposal, it escalates
to the human before proceeding.

---

## How Conflicting Proposals Were Resolved

When agents produced conflicting proposals (for example, Implementation Agent code that
diverged from Architecture Agent schema, or Innovation Agent suggestions that would expand
patch scope), the resolution process was:

1. The Controller Agent surfaced the conflict explicitly to the human.
2. The human issued a ruling — either adopting one position, requesting a revised proposal,
   or accepting a compromise.
3. The chosen resolution was recorded as a frozen constraint for subsequent patches.
4. No silent reconciliation occurred between agents.

---

## How the Workflow Supported Code Patches and Documentation

### Code patches

Each patch followed a fixed structure:
- **Scope brief** (Controller Agent): exact files to create or modify, explicit list of what
  NOT to implement, frozen constraints, acceptance criteria.
- **Implementation** (Implementation Agent): code written strictly within scope.
- **Verification** (human review): terminal demo output and DB proof provided with each patch.
- **Gate**: next patch did not begin until the human confirmed the current patch passed.

Patches were numbered P1–P9 and built sequentially:

| Patch | Deliverable |
|---|---|
| P1 | Package skeleton + interactive CLI shell |
| P2 | SQLite schema, WAL mode, storage helpers |
| P3 | URL canonicalization |
| P4 | Crawl job creation + frontier admission |
| P5 | Synchronous HTTP fetcher |
| P6 | HTML parser (title, text, links, tokens) |
| P7 | Write path: persistence, `step` pipeline |
| P8 | Search service wired to CLI |
| P9 | CLI/UX polish |

### Documentation

Documentation was produced after implementation was stable. The Documentation Agent
was instructed to inspect actual source files rather than rely on memory, and the human
issued targeted correction passes (for example, neutralising agent-specific wording,
correcting limitation descriptions) before any document was written to disk.

---

## Boundaries and Non-Goals

This workflow document does **not** describe:

- Runtime behavior of `multi_agent_crawler` — that is covered in `README.md`.
- LLM API calls at crawl time — there are none.
- Any agent framework (LangChain, AutoGen, CrewAI, etc.) — none were used.
- Continuous integration or automated testing pipelines.
- Deployment or hosting — the project runs only on localhost.

---

## Example Workflow: Adding the Search Feature (Patch 8)

1. **Controller Agent** issued a patch brief:
   - Scope: `search_service.py`, `coordinator.py`, `cli.py`, `storage.py`
   - Constraint: read committed DB state only; no external search library; no TF-IDF complexity
   - Output shape required: `(relevant_url, origin_url, depth)`

2. **Architecture Agent** confirmed the query plan:
   - join `postings → terms → pages → discoveries → crawl_jobs`
   - rank by matched-term count then summed term frequency

3. **Implementation Agent** produced:
   - `search_service.py` with `tokenize_query()` and `search()`
   - updated `coordinator.py` and `cli.py`

4. **Human** reviewed terminal output and confirmed search returned correct rows.

5. **Innovation Agent** noted no ranking limitations were hidden — the MVP boundary was
   documented explicitly in `README.md` Known Limitations.

6. **Documentation Agent** recorded the search behavior in `README.md` under CLI Commands
   and Known Limitations.

---

## Supporting Evidence

The following artifacts provide evidence that the multi-agent development workflow was
followed:

| Artifact | Evidence |
|---|---|
| `README.md` | Documents the implemented system truthfully, including MVP limitations |
| `product_prd.md` | Requirements produced before implementation, traceable to patches |
| `recommendation.md` | Design decisions and future recommendations, separated from runtime docs |
| `/agents/*.md` | Per-agent role definitions, inputs, outputs, and constraints |
| Patch history (P1–P9) | Sequential scope briefs and acceptance demos in the conversation transcript |
| Source code | Module boundaries and naming consistent with Architecture Agent decisions |
| DB schema | Matches Architecture Agent schema spec exactly (`crawl_jobs`, `pages`, `discoveries`, `page_links`, `terms`, `postings`) |
