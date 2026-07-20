# Skill: detect-llm-writing

## Description
Analyzes prose in the paper (or a specific section) for indicators that it was written by an LLM rather than a human. Scores text against vocabulary tells, structural patterns, punctuation habits, tone, transitions, and documentation-specific signals. Produces a per-section report with a final verdict.

## Usage
```
/detect-llm-writing
/detect-llm-writing section/03_methodology.tex
/detect-llm-writing "check the introduction and related work"
```

## Arguments
- **Optional**: File path or section name to analyze. If omitted, analyzes all section files in `section/`.

## Orchestration Steps

### Step 1: Identify Target Files
If the user specified a file or section, use that. Otherwise, read `paper.yaml` to get the section list and read all `section/*.tex` files.

### Step 2: Read Detection Reference
Read `capabilities/detect-llm-writing/indicators.md` — this contains the full indicator taxonomy with thresholds and examples.

### Step 3: Analyze Each Section
For each target file:

1. Read the file content with Read.
2. Walk through each indicator category from `indicators.md` and tally hits with `file:line` citations.
3. Only count prose content — skip LaTeX commands, `\begin{}`/`\end{}` blocks, citations, labels, comments, and math environments.
4. Record per-category hit counts and specific examples.

### Step 4: Generate Report
Write the report to `capabilities/reports/llm-detection_<YYYY-MM-DD>.md` using this format:

```markdown
# LLM Writing Detection Report

**Paper**: <title from paper.yaml>
**Date**: <YYYY-MM-DD>
**Scope**: <files analyzed>

## Summary

| Section | Verdict | Categories Triggered |
|---------|---------|---------------------|
| ... | Likely human / Mixed / Likely LLM | N of 7 |

## Per-Section Analysis

### <section name> (`<file>`)

**Verdict**: <verdict>
**Categories triggered**: N of 7

#### Category Hits
1. **Vocabulary** — <hit count> | examples: `file:line` "phrase"
2. **Structure** — <hit count> | examples: ...
3. **Punctuation** — <hit count> | examples: ...
4. **Tone** — <hit count> | examples: ...
5. **Transitions** — <hit count> | examples: ...
6. **Doc-specific** — <hit count> | examples: ...
7. **Opening words** — <hit count> | examples: ...

#### Notes
<caveats, false-positive risks, context>

## Overall Assessment
<summary of findings, sections of concern, recommendations>
```

### Step 5: Output
Print a summary to stdout:
- Per-section verdicts
- Total categories triggered across all sections
- Sections flagged as "Likely LLM" (if any)
- File path of the written report

## Verdict Criteria
- **Likely human**: 0–2 categories with clear signals
- **Mixed/uncertain**: 3 categories with signals, or 2 with very strong signals
- **Likely LLM**: 3+ categories with clear signals

A single-category match is weak evidence. Never flag a section based on one category alone.

## Caveats
- Academic and formal writing naturally uses some of these patterns — context matters
- Non-native English speakers may trigger vocabulary and structure tells
- Text prompted with specific style instructions or heavily edited post-generation may not trigger tells
- The strongest long-term signal is the combination of: uniform cadence + absence of genuine opinion + suspiciously complete topic coverage
