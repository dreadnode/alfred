# Output Formats

Templates and schemas for all workflow outputs.

## Source Card (Analyzer output)

Each Analyzer invocation produces one source card:

```markdown
## Source Card: <short_id>

**Title**: <full title>
**Authors**: <author list>
**Date**: <YYYY-MM or YYYY>
**URL**: <canonical URL>
**Source Type**: <peer-reviewed | preprint | tech-report | system-card | blog | news>
**Quality Tier**: <A-F per capabilities/shared/evidence-standards.md>

### Summary
<2-4 sentence summary of the source's main contribution>

### Key Findings
1. <finding 1> [Strength: strong/moderate/weak/indirect]
2. <finding 2> [Strength: ...]
3. ...

### Methodology
- **Approach**: <experimental design, dataset, evaluation method>
- **Sample**: <number of models, tasks, trials, or data points>
- **Controls**: <what was controlled for, baselines used>
- **Limitations**: <stated or inferred limitations>

### Relevant Metrics
| Metric | Value | Context |
|--------|-------|---------|
| <metric name> | <value> | <conditions under which measured> |

### Relevance to Query
<1-3 sentences explaining how this source relates to the search topic or claim being verified>

### Methodological Notes
<any flags about comparability with other sources: different definitions, different benchmarks, different conditions>

### Accessibility
<full-text | abstract-only | paywalled | inaccessible>
```

## Literature Review Report

```markdown
# Literature Review: <topic>

**Date**: <YYYY-MM-DD>
**Sources analyzed**: <N>
**Search queries used**: <N>

## Executive Summary
<5-10 sentences: what the literature says about this topic, key areas of consensus and disagreement, notable gaps>

## Thematic Sections

### <Theme 1 name>
<synthesis of what sources say about this theme>

**Key sources**: [Author1 YYYY], [Author2 YYYY], ...
**Consensus level**: <strong agreement | moderate agreement | mixed | contested>

### <Theme 2 name>
...

## Source Summary Table

| # | Source | Date | Type | Tier | Key Finding | Priority | Sections |
|---|--------|------|------|------|-------------|----------|----------|
| 1 | Author et al. | YYYY | preprint | B | <one-line finding> | Must-cite | RW, Disc |
| 2 | ... | | | | | | |

**Priority**: Must-cite / Should-cite / Nice-to-have
**Sections**: Where to cite — RW (Related Work), Intro, Disc (Discussion), Meth (Methodology)

## Contradiction and Duplication Assessment
<For each source that could contradict the paper's thesis or duplicate its contribution, explain the relationship and whether it's a genuine conflict or an artifact of different methodology/scope>

## Gaps and Open Questions
<bulleted list of areas where evidence is thin, conflicting, or absent>

## Methodology Notes
<any cross-source comparability issues that affect interpretation>

## Full Source Cards
<include all source cards from Analyzer, in order of relevance>
```

## Claim Verification Report

```markdown
# Claim Verification Report

**Paper**: <paper title or file path>
**Section(s) analyzed**: <section names/numbers>
**Date**: <YYYY-MM-DD>
**Claims extracted**: <N>
**Sources consulted**: <N>

## Executive Summary
<5-10 sentences: overall assessment, how many claims supported/contested/unsupported, any red flags>

## Verdict Summary

| # | Claim | Verdict | Confidence | Sources |
|---|-------|---------|------------|---------|
| 1 | <claim text, abbreviated> | S/P/U/C/X | High/Med/Low | <N> |
| 2 | ... | | | |

**Legend**: S=Supported, P=Partially Supported, U=Unsupported, C=Contested, X=Contradicted

## Detailed Claim Analysis

### Claim 1: <claim text>
**Locations**: <all file:line references where this claim appears in the paper>
**Type**: <prior-work | superlative | comparative | causal | scope | quantitative>
**Verdict**: <verdict> | **Confidence**: <level>

#### Supporting Evidence
- <source short_id>: <what it says> [Strength: <grade>]

#### Contradicting Evidence
- <source short_id>: <what it says> [Strength: <grade>]

#### Methodological Considerations
<any comparability issues between the claim's context and the evidence sources>

#### Assessment
<2-3 sentences explaining the verdict>

---

### Claim 2: <claim text>
...

## Novel Claims
<list of claims that appear to be genuinely new contributions with no prior evidence either way>

## Full Source Cards
<include all source cards from Analyzer, in order of relevance>
```

## Stdout Summary Format

After writing the report file, print this to stdout:

```
=== <MODE> COMPLETE ===
Topic/Paper: <input description>
Report: <file path>
Sources found: <N searched> -> <N analyzed> -> <N cited>

[For lit-review]
Themes identified: <N>
Priority breakdown: <N> must-cite, <N> should-cite, <N> nice-to-have
Contradictions found: <N or "none">
Key consensus: <1-2 sentence>
Key gap: <1-2 sentence>

[For verify-claims]
Claims analyzed: <N>
  Supported:           <count>
  Partially supported: <count>
  Unsupported:         <count>
  Contested:           <count>
  Contradicted:        <count>

Top finding: <most notable result in 1-2 sentences>
```

## Citation Format

Within reports, cite sources as `[Author YYYY]` inline. Full bibliographic details are in the source cards at the end of the report. Do not use numeric citation styles — author-year is more readable in Markdown reports.

When referencing specific findings, include the page or section if available:
`[Author YYYY, Section 3.2]` or `[Author YYYY, Table 2]`

## Peer Review Record

```markdown
---
paper: <title from paper.yaml>
authors: <authors from paper.yaml>
reviewer: <reviewer name>
date: <YYYY-MM-DD HH:MM UTC>
sections_reviewed:
  - <section file 1>
  - <section file 2>
recommendation:     # filled during finalization
issues:
  major: 0          # updated during finalization
  minor: 0
  nit: 0
  positive: 0
types:
  CLR: 0            # updated during finalization
  MTH: 0
  RES: 0
  CLM: 0
  REF: 0
  PRS: 0
  NOV: 0
  SCP: 0
  POS: 0
---

# Peer Review Record

## Summary
<3-5 sentence overall assessment — written during finalization, left blank until then>

## Recommendation
<Accept | Minor Revision | Major Revision | Reject — with 1-2 sentence justification. Written during finalization, left blank until then. The short verdict (e.g., "Major Revision") is also stored in the frontmatter `recommendation` field — keep them in sync.>

## Major Issues

### R<N>: <short title>
**Type**: <code> | **Severity**: Major | **Location**: `<file>:<line>`

<reviewer's note>

## Minor Issues

### R<N>: <short title>
**Type**: <code> | **Severity**: Minor | **Location**: `<file>:<line>`

<reviewer's note>

## Nits

### R<N>: <short title>
**Type**: <code> | **Severity**: Nit | **Location**: `<file>:<line>`

<reviewer's note>

## Strengths

### R<N>: <short title>
**Location**: `<file>:<line>`

<reviewer's note>
```

Notes are appended incrementally to the appropriate severity section as they arrive. The YAML frontmatter fields (`recommendation`, `issues`, `types`) are zeroed at creation and updated during finalization. The file is valid markdown at all times.

The frontmatter `recommendation` field must use one of the four exact values: `Accept`, `Minor Revision`, `Major Revision`, `Reject`. The body Recommendation section contains the same value plus a justification sentence.

Review records are saved to `reviews/` (not `capabilities/reports/`). Use `python3 scripts/reviews.py` to list and summarize all reviews.

## Adding Discovered Sources to the Paper

After a lit review identifies must-cite or should-cite sources, add them to the paper's bibliography using the existing citation tool:

```bash
# Add by Semantic Scholar ID, DOI, or arXiv ID
python3 scripts/cite.py add arXiv:1706.03762
python3 scripts/cite.py add DOI:10.1234/example

# Search and add by title
python3 scripts/cite.py search --add "paper title"
```

This fetches real BibTeX from Semantic Scholar and appends it to `bibliography.bib`. Use `\cite{key}` in section files to reference the new entry.
