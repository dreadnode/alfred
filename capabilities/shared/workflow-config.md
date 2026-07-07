# Workflow Configuration

## Model Requirements

All agents in this workflow MUST run on a **flagship reasoning model** — the most capable model available in whatever platform is orchestrating the workflow. These are high-knowledge tasks requiring deep reasoning, structured extraction from dense academic text, and cross-source synthesis. Lighter or faster models produce shallow, unreliable analyses.

| Agent | Model Tier | Rationale |
|-------|-----------|-----------|
| Searcher | Flagship reasoning | Query construction requires understanding research domains, anticipating terminology variations, and judging source relevance from abstracts |
| Analyzer | Flagship reasoning | Deep reading of academic papers demands precise extraction of methodology, metrics, sample sizes, and limitations without hallucination |
| Synthesizer | Flagship reasoning | Cross-source reasoning, conflict resolution, evidence weighing, and structured argumentation require flagship reasoning |

### Platform-specific model mapping

| Platform | Flagship model parameter |
|----------|--------------------------|
| Claude Code | `model: "opus"` in Agent tool |
| OpenAI | `model: "o3"` or latest reasoning model |
| Google | `model: "gemini-2.5-pro"` or latest |
| Custom orchestrator | Set via config; must be the provider's top-tier reasoning model |

The orchestrator is responsible for mapping "flagship reasoning" to the correct model identifier for its platform.

## Agent Roles

### Searcher
- **Purpose**: Find relevant papers, preprints, tech reports, and blog posts
- **Tools**: `WebSearch`, `WebFetch` (abstracts/metadata only)
- **Input**: Search queries (generated from topic or claims)
- **Output**: Ranked source list with URLs, titles, authors, dates, abstracts, and relevance scores
- **Constraints**: Does NOT deep-read full papers. Fetches only enough to assess relevance (title, abstract, introduction). Deduplicates by DOI/URL.

### Analyzer
- **Purpose**: Deep-read a single source and extract structured findings
- **Tools**: `WebFetch`, `Read`
- **Input**: A source URL (or local file path) + context about what to look for
- **Output**: A structured source card (see capabilities/shared/output-formats.md)
- **Constraints**: One source per invocation. Extracts facts, does not editorialize. Flags when a source is paywalled or inaccessible.

### Synthesizer
- **Purpose**: Combine source cards with user input to produce final reports
- **Tools**: `Write`, `Read`
- **Input**: Source cards from Analyzer + original user input (topic or claims)
- **Output**: Structured report file + stdout summary
- **Constraints**: Must cite every factual assertion back to a specific source card. Must use verdict criteria from capabilities/shared/evidence-standards.md.

## Orchestration Rules

1. **Searcher runs first.** No analysis without sources.
2. **Analyzer runs in parallel** across sources. Each source is an independent agent invocation.
3. **Synthesizer runs last.** It needs all source cards before producing the report.
4. **Max sources per run**: 15 (to keep analysis tractable). Searcher should return top 15 ranked by relevance.
5. **Timeout**: If a source is inaccessible after WebFetch, skip it and note it in the report as "inaccessible."
6. **Report output**: Write to `capabilities/reports/<mode>_<slug>_<YYYY-MM-DD>.md`. Print a 10-20 line summary to stdout after writing.

## Directory Structure

```
capabilities/
  shared/
    workflow-config.md          # This file
    search-strategy.md          # How to find sources
    evidence-standards.md       # How to grade evidence
    output-formats.md           # Report and source card templates
    synthesizer.md              # Shared synthesis agent
  search-sources/
    agent.md                    # Searcher agent definition
    skill.md                    # /search-sources orchestration
  analyze-source/
    agent.md                    # Analyzer agent definition
    skill.md                    # /analyze-source orchestration
  lit-review/
    skill.md                    # /lit-review orchestration
  verify-claims/
    skill.md                    # /verify-claims orchestration
  reports/                      # Output directory for generated reports
```
