# Capabilities

Extended AI-agent capabilities beyond core document authoring. Each capability is a prompt-based multi-agent workflow that composes specialized agents.

## Available Capabilities

### Standalone

| Capability | Skill | Description |
|------------|-------|-------------|
| [search-sources](search-sources/) | `/search-sources "query"` | Find relevant papers, preprints, and reports for a topic |
| [analyze-source](analyze-source/) | `/analyze-source <URL> "context"` | Deep-read a single source, extract structured findings |

### Orchestrators

| Capability | Skill | Description |
|------------|-------|-------------|
| [lit-review](lit-review/) | `/lit-review "topic"` | Full literature review: search → analyze → synthesize → report |
| [verify-claims](verify-claims/) | `/verify-claims section/01_intro.tex` | Extract claims from LaTeX, verify against evidence |

## Architecture

Three specialized agents, each requiring a flagship reasoning model:

| Agent | Location | Role |
|-------|----------|------|
| Searcher | `search-sources/agent.md` | Finds relevant sources via web search |
| Analyzer | `analyze-source/agent.md` | Deep-reads a single source, extracts structured findings |
| Synthesizer | `shared/synthesizer.md` | Combines source cards into themed reviews or per-claim verdicts |

The standalone capabilities (search-sources, analyze-source) use a single agent each. The orchestrators (lit-review, verify-claims) compose all three agents into multi-step pipelines.

## Shared Resources

| File | Purpose |
|------|---------|
| `shared/workflow-config.md` | Model requirements, agent roles, orchestration rules |
| `shared/search-strategy.md` | Query construction, source priorities, deduplication |
| `shared/evidence-standards.md` | Source quality tiers, evidence grading, verdict criteria |
| `shared/output-formats.md` | Report templates, source card schema, cite.py integration |
| `shared/synthesizer.md` | Shared synthesis agent used by lit-review and verify-claims |

## Output

Reports are written to `capabilities/reports/` and gitignored. Each run also prints a 10-20 line summary to stdout.

## Adding New Capabilities

Create a new directory under `capabilities/` with:
- `agent.md` — agent definition (if the capability introduces a new agent)
- `skill.md` — orchestration steps for the `/skill-name` command

Reference shared resources from `capabilities/shared/` rather than duplicating them.
