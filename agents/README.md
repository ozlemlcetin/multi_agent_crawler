# Agent Definitions

This directory contains role definitions for the five development-workflow agents used
to design, build, and document the `multi_agent_crawler` project.

These are **not runtime agents**. The `multi_agent_crawler` application is a plain local
Python process with no LLM components at runtime. The agents described here operated
during development only — across separate chat sessions using a mix of AI tools — and
have no presence in the running application.

The human user is the final decision maker at every stage. No agent acts autonomously
or escalates decisions without human approval.

---

## Final Agent Roster

| Agent | Summary |
|---|---|
| [Architecture Agent](architecture_agent.md) | Defines system structure, module boundaries, data flow, and schema |
| [Implementation Agent](implementation_agent.md) | Writes all production Python code patch-by-patch |
| [Innovation Agent](innovation_agent.md) | Identifies risks, flags edge cases, and proposes improvements |
| [Documentation Agent](documentation_agent.md) | Produces all written project documentation |
| [Controller Agent](controller_agent.md) | Coordinates agent activity, enforces scope, routes work |

---

## Human Authority

The human user approves all architectural decisions, patch scope, documentation phrasing,
and conflict resolutions. Agents produce proposals and implementations; the human gates
every transition between stages.
