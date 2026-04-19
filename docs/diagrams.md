# Project Diagrams

Diagrams for the `multi_agent_crawler` project.
The runtime is a plain local Python application — there are no LLM agents at runtime.
The multi-agent system described in Diagram 3 operated during **development only**.

---

## 1. Runtime Architecture

The main runtime modules and data flow of the local Python application.

```mermaid
flowchart TD
    User(["User (terminal)"])
    CLI["cli.py\nInteractive Shell"]
    Coord["coordinator.py\nCoordinator"]
    Frontier["frontier.py\nBounded Queue"]
    Fetcher["fetcher.py\nHTTP Fetch"]
    Parser["parser.py\nHTML Parse"]
    Writer["index_writer.py\nPersistence"]
    DB[("crawler.db\nSQLite WAL")]
    Search["search_service.py\nSearch"]
    Status["status()\nCounts & Frontier Snapshot"]

    User -->|"index / step / search\n jobs / status / quit"| CLI
    CLI --> Coord
    Coord --> Frontier
    Frontier -->|"FrontierItem"| Fetcher
    Fetcher -->|"FetchResult"| Parser
    Parser -->|"ParsedResult"| Writer
    Writer -->|"pages / links\nterms / postings\ndiscoveries"| DB
    Coord -->|"search query"| Search
    Search -->|"reads committed state"| DB
    Search -->|"(relevant_url, origin_url, depth)"| CLI
    Coord --> Status
    Status -->|"reads counts"| DB
    Status --> CLI
```

---

## 2. Indexing and Search Flow

Step-by-step flow from job submission through to search result output.

```mermaid
flowchart TD
    A(["User: index &lt;url&gt; &lt;depth&gt;"])
    B["Canonicalize origin URL\nurl_normalizer.py"]
    C["Insert crawl_jobs row\nstorage.py"]
    D["Get or create pages row\n(fetch_state = unfetched)"]
    E["Insert discoveries row\n(depth = 0, parent = NULL)"]
    F{"Page already\nqueued or fetched?"}
    G["Admit FrontierItem\nset fetch_state = queued"]
    H(["User: step"])
    I["Pop FrontierItem\nfrom Frontier"]
    J["fetch_url()\nfetcher.py"]
    K{"HTML\nsuccess?"}
    L["parse_html()\nparser.py"]
    M["persist_page()\nindex_writer.py"]
    N["Update pages metadata\ntitle / hash / http_status"]
    O["Replace page_links\nfor source page"]
    P["Replace terms + postings\nterm frequencies"]
    Q["Admit eligible children\nat depth + 1"]
    R["Record non-HTML\nor error outcome"]
    S(["User: search &lt;query&gt;"])
    T["Tokenize query\nsearch_service.py"]
    U["JOIN postings → terms\n→ pages → discoveries\n→ crawl_jobs"]
    V["Rank: matched terms\nthen summed TF"]
    W(["Output: relevant_url\norigin_url, depth"])

    A --> B --> C --> D --> E --> F
    F -->|"No"| G
    F -->|"Yes — skip admission"| H
    G --> H
    H --> I --> J --> K
    K -->|"Yes"| L --> M
    M --> N
    M --> O
    M --> P
    M --> Q
    K -->|"No"| R
    S --> T --> U --> V --> W
```

---

## 3. Multi-Agent Development Workflow

The five agents that collaborated to design, build, and document this project.
These are **development-time agents only** — they have no presence in the running application.
The human user is the final decision maker at every stage.

```mermaid
flowchart TD
    Human(["👤 Human User\n(final decision maker)"])

    Controller["Controller Agent\nScope, sequencing,\nfrozen constraints"]
    Arch["Architecture Agent\nModule design, schema,\ndata model, rules"]
    Impl["Implementation Agent\nPython source code,\npatch-by-patch"]
    Innov["Innovation Agent\nRisk flags, proposals,\nalternatives"]
    Docs["Documentation Agent\nREADME, PRD, workflow,\nrecommendation, agents/"]

    Human <-->|"Approve / redirect"| Controller
    Controller -->|"Patch briefs +\nfrozen constraints"| Impl
    Controller -->|"Structural questions"| Arch
    Controller -->|"Design questions"| Innov
    Controller -->|"Doc phase trigger"| Docs

    Arch -->|"Schema, module specs,\nrules"| Impl
    Arch -->|"Architecture summary"| Docs

    Impl -->|"Patch output +\ndemo evidence"| Human
    Impl -->|"Edge case flags"| Innov
    Impl -->|"Confirmed state\nto document"| Docs

    Innov -->|"Risk assessments +\nproposals"| Human
    Innov -->|"Accepted improvements"| Controller

    Docs -->|"Drafts for review"| Human
```
