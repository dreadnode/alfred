# Literature Review & Claim Verification Workflow

A multi-agent workflow for two related tasks:

1. **Literature Review** — Given a topic, paper, or conclusions, find and synthesize relevant prior work
2. **Claim Verification** — Given claims from a paper, verify each against prior work and scientific evidence

## Architecture

Three specialized agents, each requiring a flagship reasoning model:

| Agent | Role | Tools |
|-------|------|-------|
| **Searcher** | Finds relevant sources via web search | WebSearch, WebFetch |
| **Analyzer** | Deep-reads a single source, extracts structured findings | WebFetch, Read |
| **Synthesizer** | Combines source cards into themed reviews or per-claim verdicts | Write, Read |

## Skills

### Orchestrators (full pipelines)

| Skill | Description |
|-------|-------------|
| `lit-review` | Full literature review: topic -> search -> analyze -> synthesize -> report |
| `verify-claims` | Claim verification: extract claims from LaTeX -> search -> analyze -> verdict report |

### Standalone (single-agent tasks)

| Skill | Description |
|-------|-------------|
| `search-sources` | Quick source discovery for a topic |
| `analyze-source` | Deep-read a single URL or file |

## Usage Examples

### Literature review on a topic
```
/lit-review "LLM cheating behavior on cybersecurity benchmarks"
```

### Verify claims in a paper section
```
/verify-claims section/01_introduction.tex
/verify-claims section/03_methodology.tex "Section 3.1"
```

### Quick source search
```
/search-sources "reward hacking in LLM agent evaluations"
```

### Deep-read a specific paper
```
/analyze-source https://arxiv.org/abs/2506.12345 "cheating detection methods"
```

## Output

Each full run produces:
- **Report file** in `reports/` — structured Markdown with source cards, thematic sections (lit review) or per-claim verdicts (verification)
- **Stdout summary** — 10-20 line digest with key findings

## Directory Structure

```
lit-review-and-claim-verifier/
  README.md                   # This file
  WORKFLOW_CONFIG.md          # Model requirements, agent roles, orchestration rules
  SEARCH_STRATEGY.md          # Query construction, source priorities, dedup
  EVIDENCE_STANDARDS.md       # Source quality tiers, evidence grading, verdict criteria
  OUTPUT_FORMATS.md           # Report templates, source card schema
  agents/
    searcher.md               # Searcher agent definition
    analyzer.md               # Analyzer agent definition
    synthesizer.md            # Synthesizer agent definition
  skills/
    lit-review.md             # Full literature review orchestrator
    verify-claims.md          # Claim verification orchestrator
    search-sources.md         # Standalone source discovery
    analyze-source.md         # Standalone source analysis
  reports/                    # Generated reports (gitignored)
```

## Model Requirements

All agents must run on a flagship reasoning model (the most capable model available on the orchestrating platform). These are high-knowledge tasks requiring deep reasoning, structured extraction from academic text, and cross-source synthesis. See WORKFLOW_CONFIG.md for platform-specific model mapping.
