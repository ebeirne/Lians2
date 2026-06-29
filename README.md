<p align="center">
  <a href="https://github.com/Lians-ai/Lians">
    <img src="docs/images/banner.png" width="800px" alt="Lians — Financial-Grade Agent Memory">
  </a>
</p>

<p align="center">
  <a href="https://github.com/Lians-ai/Lians">Learn more</a>
  ·
  <a href="https://github.com/Lians-ai/Lians/tree/main/docs">Docs</a>
  ·
  <a href="https://github.com/Lians-ai/Lians#self-hosted-quickstart">Quickstart</a>
</p>

<p align="center">
  <a href="https://pypi.org/project/lians-sdk">
    <img src="https://img.shields.io/pypi/v/lians-sdk?color=%2334D058&label=pypi%20package" alt="PyPI version">
  </a>
  <a href="https://pypi.org/project/lians-sdk">
    <img src="https://img.shields.io/pypi/dm/lians-sdk?label=pypi%20downloads" alt="PyPI downloads">
  </a>
  <a href="https://github.com/Lians-ai/Lians">
    <img src="https://img.shields.io/github/commit-activity/m/Lians-ai/Lians/master?style=flat-square" alt="GitHub commit activity">
  </a>
  <a href="https://www.npmjs.com/package/@ebeirne/lians">
    <img src="https://img.shields.io/npm/v/%40ebeirne%2Flians?label=npm" alt="npm version">
  </a>
  <a href="https://registry.modelcontextprotocol.io/servers/io.github.ebeirne/lians">
    <img src="https://img.shields.io/badge/MCP-Official%20Registry-blueviolet" alt="MCP Official Registry">
  </a>
  <a href="LICENSE">
    <img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg" alt="License: Apache 2.0">
  </a>
</p>

<p align="center">
  <a href="docs/benchmark.md"><strong> Benchmark: 0 stale facts in top-5 vs mem0's 4/4 — and 100% supersession accuracy →</strong></a>
</p>

---

[Lians](https://github.com/Lians-ai/Lians) is a **financial-grade memory layer** for AI agents — built for regulated environments where stale facts contaminate decisions, auditors demand point-in-time reconstruction, and data-subject erasure must be cryptographically provable.

| | Library | Self-Hosted Server | Cloud |
|---|---|---|---|
| **Best for** | Testing, prototyping | Teams, compliance deployments | Zero-ops production |
| **Setup** | `pip install lians-sdk[local]` | `docker compose up --build` | `pip install lians-sdk` + API key |
| **Database** | SQLite (zero setup) | Postgres 16 + pgvector | Managed |
| **Audit chain** | ✓ | ✓ | ✓ |
| **GDPR erasure** | ✓ | ✓ | ✓ |

---

## MCP — Native tool in any AI client

Lians is listed on the [official MCP Registry](https://registry.modelcontextprotocol.io/servers/io.github.ebeirne/lians). Any MCP-compatible host — Claude Desktop, Cursor, VS Code, Windsurf, and others — can connect to your Lians server as a native tool with a one-time config. No SDK code, no custom adapter, no wrapper.

Your agents get eight tools automatically:

| Tool | What it does |
|------|-------------|
| `remember` | Store a fact with event time and metadata |
| `recall` | Retrieve current (non-stale) facts by semantic query |
| `recall_at` | Point-in-time recall — what did we know on date X? |
| `reconstruct` | Full audit reconstruction for regulatory submissions |
| `list_conflicts` | Surface facts where two sources disagree |
| `memory_lineage` | Full supersession history of any fact |
| `fact_history` | Time-series view of a ticker+metric (e.g. AAPL EPS) |
| `backtest_check` | Detect lookahead bias before a backtest runs |

### Claude Desktop / Cursor / Windsurf

Add to your `claude_desktop_config.json` (or equivalent MCP config):

```json
{
  "mcpServers": {
    "lians": {
      "command": "uvx",
      "args": ["--from", "lians-sdk[mcp]", "lians-mcp"],
      "env": {
        "LIANS_URL": "https://your-lians-server.internal",
        "LIANS_API_KEY": "lians_...",
        "LIANS_AGENT_ID": "trading-desk-1"
      }
    }
  }
}
```

Restart your client and Lians memory tools appear immediately — no install step for your users beyond setting the three env vars.

### Any other MCP host

```bash
uvx --from 'lians-sdk[mcp]' lians-mcp
```

Set `LIANS_URL`, `LIANS_API_KEY`, and optionally `LIANS_AGENT_ID` in the environment.

---

## Quickstart

```bash
pip install lians-sdk[local]   # zero-setup local mode (SQLite, no Docker)
```

```python
from lians import LocalLiansClient
from datetime import datetime, timezone

mem = LocalLiansClient()

mem.add(
    agent_id="analyst-1",
    content="NVDA FY2026 revenue guidance raised to $40B",
    event_time=datetime(2025, 11, 19, 16, tzinfo=timezone.utc),
    metadata={"ticker": "NVDA", "metric": "revenue_guidance"},
)

# Superseded facts are excluded at the DB layer — never reach the LLM
results = mem.recall(agent_id="analyst-1", query="NVDA revenue guidance")

# Point-in-time: what did we know on March 1? (compliance-grade answer)
results = mem.recall_at(
    agent_id="analyst-1",
    query="NVDA revenue guidance",
    as_of=datetime(2025, 3, 1, tzinfo=timezone.utc),
)
```

Switch to the hosted server with one line: `from lians import LiansClient as LocalLiansClient`

---

## Agent harness — drop-in memory loop

`LiansMemoryHarness` wraps the two operations every memory-augmented agent needs —
recall-before and remember-after — into one object, with the compliance scoping
(subject, source, event-time, information barrier) regulated deployments require.
Works with any sync client (`LiansClient` or `LocalLiansClient`) and any model.

```python
from lians import LiansClient, LiansMemoryHarness

harness = LiansMemoryHarness(mem, agent_id="research-desk", domain="finance")

# One call: recall context, run your model, persist the response.
answer = harness.run_turn(
    "What is NVDA's current revenue guidance?",
    generate=lambda context, query: call_model(f"{context}\n\nUser: {query}"),
)

# Or control each step:
context = harness.recall_context("NVDA revenue guidance")   # ready to inject
harness.remember("Desk note: guidance now $40B")            # write after the turn
```

Regulated scoping ties every write to one data subject and an information barrier:

```python
harness = LiansMemoryHarness(
    mem, agent_id="care-team-3",
    subject_id="MRN-00042",       # per-subject key — the crypto-shred target
    barrier_group="oncology",     # information-barrier tag
    domain="healthcare",
)
```

Runnable end-to-end demo: [`agentmem/examples/harness_demo.py`](agentmem/examples/harness_demo.py).

---

## Relationship graph — compliance questions that are inherently relational

Some compliance checks *are* graph queries. Lians stores **bitemporal relationship
edges** alongside facts — same audit chain, same information barriers, no graph
database — so you can answer them point-in-time:

- **Legal** — conflict-of-interest reachability (ABA 1.7/1.9): is an attorney
  connected to an adverse party?
- **Finance** — related-party / beneficial-ownership (SEC, AML/KYC): is a
  counterparty within N hops of a restricted entity?
- **Healthcare** — care-network / referral-pattern (anti-kickback) analysis.

```python
mem.relate("analyst-1", src_entity="Attorney", rel_type="represented",
           dst_entity="ClientX", event_time=datetime(2026, 1, 1, tzinfo=timezone.utc))
mem.relate("analyst-1", src_entity="ClientX", rel_type="adverse_to",
           dst_entity="PartyY", event_time=datetime(2026, 1, 1, tzinfo=timezone.utc))

# Conflict-of-interest check — is there a connection, and through what?
path = mem.path("analyst-1", src_entity="Attorney", dst_entity="PartyY")
# → {"connected": True, "hops": 2, "path": [...]}

# Point-in-time: who was connected on the day of the trade?
mem.neighbors("analyst-1", entity="FundA", depth=2, as_of=datetime(2025, 6, 1, tzinfo=timezone.utc))

# Graph-proximity reranking — boost recalls about entities near an anchor
mem.recall_near("analyst-1", query="earnings", near_entity="FundA", near_key="ticker")
```

Endpoints: `POST /v1/graph/relate` · `/v1/graph/unrelate` · `GET /v1/graph/neighbors` · `/v1/graph/path` (all `as_of`-capable). Inspired by [Zep/Graphiti](docs/compare-zep.md), built on our compliance spine.

---

## Agent integrations — Claude Code, Codex, MCP

Give any coding agent persistent, compliance-grade memory:

| Host | How |
|------|-----|
| **Claude Code** | Plugin with slash commands (`/lians-remember`, `/lians-recall`, `/lians-audit`, `/lians-integrate`) and a compliance subagent — [`integrations/lians-plugin`](integrations/lians-plugin) |
| **Codex** | Drop-in `AGENTS.md` + MCP config — [`integrations/codex`](integrations/codex) |
| **Skills standard** | `npx skills add https://github.com/Lians-ai/Lians --skill lians` — works in Claude Code, Codex, Cursor — [`skills/`](skills) |
| **Any MCP host** | One-time config; eight native memory tools — see [MCP section](#mcp--native-tool-in-any-ai-client) above |

---

## Why Lians

Financial AI agents accumulate facts that **change over time**: rate decisions supersede prior ones, guidance gets revised, price targets change. Systems like mem0 return all versions with equal rank — your LLM gets contaminated context.

Lians fixes this with a bitemporal model:
- **event_time** — when the fact happened (business time)
- **valid_from / valid_to** — when it was known (system time)

Superseded facts are excluded at the database layer. Every write is recorded in a tamper-evident SHA-256 hash chain (SEC 17a-4). Per-subject keys can be destroyed for GDPR erasure while the audit trail survives. Information barriers are enforced at PostgreSQL RLS, not the application layer.

| | Lians | mem0 | Graphiti/Zep |
|---|---|---|---|
| Stale facts in top-5 (5-revision chain) | **0 / 4** | 4 / 4 | N/T |
| Supersession accuracy (22-pair benchmark) | **100%** | N/A | No benchmark |
| Point-in-time recall (4 quarterly queries) | **4 / 4** | 0 / 4 | Partial |
| SEC 17a-4 audit hash chain | ✓ | ✗ | ✗ |
| GDPR crypto-shred with audit survival | ✓ | ✗ | ✗ |
| Information barriers (DB-layer RLS) | ✓ | ✗ | ✗ |

→ Full benchmark numbers: [docs/benchmark.md](docs/benchmark.md) · Feature-by-feature breakdown: [vs mem0](docs/compare-mem0.md) · [vs Zep/Graphiti](docs/compare-zep.md)

---

## Framework integrations

| Framework | Install | Import |
|-----------|---------|--------|
| **LangChain** | `pip install lians-sdk[langchain]` | `from lians.langchain_integration import LiansChatHistory, build_tools` |
| **LangGraph** | `pip install lians-sdk[langgraph]` | `from lians.langgraph_integration import create_recall_node, create_remember_node` |
| **CrewAI** | `pip install lians-sdk[crewai]` | `from lians.crewai_integration import build_crewai_tools` |
| **OpenAI Agents SDK** | `pip install lians-sdk[openai-agents]` | `from lians.openai_agents_integration import build_openai_agent_tools` |
| **AutoGen v0.4** | `pip install lians-sdk[autogen]` | `from lians.autogen_integration import build_autogen_tools` |
| **TypeScript / Node** | `npm install @ebeirne/lians` | `import { LiansClient } from "@ebeirne/lians"` |

---

## Self-hosted quickstart

```bash
git clone https://github.com/Lians-ai/Lians.git && cd Lians/agentmem
cp .env.demo .env
docker compose up --build -d
python scripts/seed_demo.py   # prints a demo API key; open demo/index.html
```

Deploy to Fly.io, Kubernetes, or bare Docker: [docs/deploy.md](docs/deploy.md)

---

## SDK reference

```python
# All three clients share the same API surface
from lians import LiansClient          # sync, connects to hosted/self-hosted server
from lians import AsyncLiansClient     # async, for FastAPI / async frameworks
from lians import LocalLiansClient     # local SQLite, no server needed

client.add(agent_id, content, event_time, metadata={}, importance=0.5)
client.add_from_messages(agent_id, messages=[{"role": "user", "content": "..."}])
client.recall(agent_id, query, k=5)
client.recall_at(agent_id, query, as_of=datetime(...))   # point-in-time
client.snapshot(agent_id, as_of=datetime(...))           # full state export
client.backtest_check(agent_id, simulation_as_of=...)    # lookahead-bias detection
client.erase(subject_id, request_ref)                    # GDPR crypto-shred
```

---

## Architecture

```
                    ┌──────────────┐
                    │  LLM / Agent │
                    └──────┬───────┘
                           │  REST / MCP
               ┌───────────▼────────────┐
               │        Lians API        │   FastAPI · rate-limit · OTEL
               └──┬────────────────┬────┘
          ┌───────▼──────┐  ┌──────▼───────┐
          │   memories    │  │  event_log   │
          │  (encrypted)  │  │ (hash chain) │
          │  bitemporal   │  │  append-only │
          └───────┬───────┘  └──────────────┘
                  │
          ┌───────▼───────┐
          │  subject_keys  │   AES-256-GCM per subject
          │  (crypto-shred)│   destroy key = content unrecoverable
          └───────────────┘

  Postgres 16 + pgvector (HNSW)      Redis (recall hot cache)
```

**Recall pipeline:** BM25 + cosine (Voyage Finance-2) → recency decay → validity gate (`valid_to IS NULL` for present; `valid_from ≤ as_of < valid_to` for point-in-time)

**Supersession pipeline:** Stage 1 (metadata key overlap) → Stage 2 (deterministic: SUPERSEDES / CONFIRMS / ADDS) → Stage 3 (optional LLM adjudication for paraphrase detection)

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `EMBEDDING_PROVIDER` | `local` | `voyage` · `openai` · `sentence-transformers` · `local` |
| `VOYAGE_API_KEY` | — | Required when `EMBEDDING_PROVIDER=voyage` |
| `MASTER_ENCRYPTION_KEY` | — | Base64 32-byte key; blank disables PII encryption |
| `KMS_PROVIDER` | `env` | `env` · `aws` · `azure` · `vault` |
| `ADMIN_SECRET` | — | Protects `/v1/admin/*` — **change in production** |
| `SUPERSESSION_LLM_STAGE` | `false` | Enables Stage 3 LLM adjudication (Claude Haiku) |
| `AIRGAP_MODE` | `false` | Hard-fails at startup if any config would send data externally |
| `STRIPE_API_KEY` | — | Enables per-namespace usage metering |

Full reference: [agentmem/.env.example](agentmem/.env.example)

---

## Key endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/memories` | Add a memory (triggers supersession check) |
| `POST` | `/v1/memories/batch` | Batch ingest |
| `POST` | `/v1/recall` | Hybrid BM25+cosine recall; optional `as_of` |
| `POST` | `/v1/erase` | GDPR crypto-shred by `subject_id` |
| `GET`  | `/v1/audit/reconstruct` | Reconstruct agent state at any past date |
| `GET`  | `/v1/admin/audit/verify` | Verify SHA-256 hash chain integrity |
| `GET`  | `/v1/admin/audit/export` | Export audit log (SEC/FINRA/CFTC) |
| `GET`  | `/health` | Deep health check (DB + Redis) |

Interactive docs: `http://localhost:8000/docs`

---

## Running tests

```bash
cd agentmem
pip install -e ".[dev]"
pytest -v

# Benchmarks only (no API keys required)
pytest tests/test_supersession_benchmark.py tests/test_recall_quality.py -v
```

See [docs/testing.md](docs/testing.md) for the six named invariants (temporal soundness, audit immutability, erasure, etc.).

---

## Compliance

| Requirement | Feature |
|-------------|---------|
| SEC 17a-4 tamper-evidence | SHA-256 hash chain on every audit row |
| FINRA 4511 recordkeeping | Append-only `event_log` |
| GDPR Art. 17 erasure | AES-256-GCM per-subject keys; crypto-shred |
| MiFID II point-in-time | Bitemporal: `event_time` + `valid_from/valid_to` |
| Information barriers | `barrier_group` column; PostgreSQL RLS |
| HIPAA §164.312 | Per-subject encryption, audit controls, transmission security |

Full documentation: [docs/compliance.md](docs/compliance.md) · [docs/hipaa.md](docs/hipaa.md)

---

## Cloud & Pricing

Lians is open-source and fully self-hostable. A managed cloud is also available at **[api.lians.dev](https://api.lians.dev)** — no infrastructure to run.

| Tier | Price | Memories / mo | Recalls / mo | Features |
|------|-------|---------------|--------------|----------|
| **Free** | $0 | 10,000 | 1,000 | Memory writes · recalls · semantic search |
| **Starter** | $15 | 100,000 | 10,000 | + Domain adapters (finance, healthcare, legal) · Audit log |
| **Growth** | $70 | 1,000,000 | 100,000 | + Conflict detection · Webhooks · Compliance reports · Merkle audit chain |
| **Pro** | $200 | 10,000,000 | 1,000,000 | + Information barriers · HIPAA encryption · GDPR erasure certs · Backtest · Prometheus metrics |
| **Enterprise** | Custom | Unlimited | Unlimited | + Air-gap mode · Custom KMS (AWS / Azure / Vault) · Dedicated onboarding · SLA |

The Free tier never expires and requires no credit card. Use `pip install lians-sdk` and point `LIANS_URL` at `https://api.lians.dev` with your free API key.

Full pricing and billing documentation: [docs/pricing-tiers.md](docs/pricing-tiers.md) · [docs/billing.md](docs/billing.md)

**Switching from another system?** [Migrate from mem0 →](docs/migrate-from-mem0.md) · [Migrate from Zep CE →](docs/migrate-from-zep.md)

---

## License

Apache 2.0 — see [LICENSE](LICENSE).

<!-- mcp-name: io.github.ebeirne/lians -->
