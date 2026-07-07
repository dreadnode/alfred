# Skill: peer-review

## Description
Interactive peer-review session. The reviewer reads the paper and sends notes incrementally. The agent categorizes each note, maps it to the relevant section and line, and builds a structured feedback report. Optionally verifies reviewer concerns against sources using the verify-claims capability.

## Usage
```
/peer-review                           # Start session, reads all section/ files
/peer-review section/03_methodology.tex  # Start session focused on one section
```

## Arguments
- **Optional**: File path to focus on a specific section. Default: read all `section/*.tex` files.

## Session Lifecycle

### 1. Initialize
Read the paper to build context:
- Read `paper.yaml` for title, authors, abstract summary, section structure
- Read all `section/*.tex` files (or the specified section)
- Read `bibliography.bib` for citation context
- Create the report file at `capabilities/reports/peer-review_<slug>_<YYYY-MM-DD>.md` with the header populated (paper title, date, sections under review)

Print a short confirmation:
```
=== PEER REVIEW SESSION STARTED ===
Paper: <title from paper.yaml>
Sections loaded: <list>
Send notes as you read. Type /peer-review done to finalize.
```

### 2. Record Notes
The reviewer sends notes in natural language. For each note:

**Parse and categorize:**
- Identify the **feedback type** (see Feedback Types below)
- Identify the **severity**: major (blocks acceptance), minor (should fix), or nit (optional polish)
- Identify the **target**: which section file and line range the note refers to. If the reviewer specifies (e.g., "in the methodology, line 34..."), use that. If not, infer from context or ask.

**Record to the report:**
- Append the note to the appropriate section of the running report file
- Assign a sequential ID (R1, R2, R3, ...)
- Include the original note text, category, severity, and file:line reference

**Acknowledge briefly:**
After recording, confirm with one line:
```
R<N> recorded — <type>, <severity> → <section file>:<line>
```
Do not summarize the note back or add commentary unless the reviewer asks.

### 3. Finalize
When the reviewer says `/peer-review done` or "finalize the review":

1. Read the full report file
2. Write the **Summary** section — 3-5 sentences capturing the overall assessment
3. Count notes by type and severity, populate the **Statistics** table
4. Assign an overall **Recommendation** based on the balance of major/minor issues:
   - **Accept**: No major issues
   - **Minor Revision**: No major issues, multiple minor issues
   - **Major Revision**: 1-2 major issues that are addressable
   - **Reject**: Fundamental issues with methodology, claims, or contribution
5. Ask the reviewer if they want to adjust the recommendation before finalizing

**Optional — verify flagged claims:**
If any notes question the accuracy of specific claims (e.g., "I don't think this citation supports what they say it does"), offer to run `/verify-claims` on those specific claims. This launches the verify-claims capability to check them against sources.

Print a final summary:
```
=== PEER REVIEW COMPLETE ===
Report: <file path>
Notes recorded: <N>
  Major: <count>
  Minor: <count>
  Nit:   <count>
Recommendation: <recommendation>
```

## Feedback Types

| Type | Code | Description |
|------|------|-------------|
| **Clarity** | CLR | Writing is unclear, ambiguous, or hard to follow |
| **Methodology** | MTH | Issue with experimental design, evaluation, or approach |
| **Results** | RES | Issue with data analysis, interpretation, or presentation |
| **Claims** | CLM | A claim is unsupported, overstated, or inaccurate |
| **References** | REF | Missing citation, wrong citation, or mischaracterized prior work |
| **Presentation** | PRS | Figures, tables, formatting, or structural issues |
| **Novelty** | NOV | Concern about originality or overlap with existing work |
| **Scope** | SCP | Missing limitations, overgeneralization, or scope mismatch |
| **Positive** | POS | Strength worth noting — good methodology, clear writing, strong results |

The agent assigns the type automatically. If ambiguous, pick the closest match — the reviewer can correct it.

## Report Format

```markdown
# Peer Review Report

**Paper**: <title>
**Authors**: <authors from paper.yaml>
**Date**: <YYYY-MM-DD>
**Reviewer**: <anonymous unless stated>
**Sections reviewed**: <list>

## Summary
<3-5 sentence overall assessment — written during finalization>

## Recommendation
<Accept | Minor Revision | Major Revision | Reject>

## Statistics

| Severity | Count |
|----------|-------|
| Major    | <N>   |
| Minor    | <N>   |
| Nit      | <N>   |

| Type | Count |
|------|-------|
| CLR  | <N>   |
| MTH  | <N>   |
| ...  | ...   |

## Major Issues

### R<N>: <short title>
**Type**: <code> | **Severity**: Major | **Location**: `<file>:<line>`

<reviewer's note>

---

## Minor Issues

### R<N>: <short title>
**Type**: <code> | **Severity**: Minor | **Location**: `<file>:<line>`

<reviewer's note>

---

## Nits

### R<N>: <short title>
**Type**: <code> | **Severity**: Nit | **Location**: `<file>:<line>`

<reviewer's note>

---

## Strengths
<list of POS-type notes, if any>
```

## Integration with Other Capabilities

- **verify-claims**: When a reviewer flags a claim as suspect (CLM or REF type), offer to verify it. The verify-claims capability reads `bibliography.bib` for DOI lookups and can check the cited source directly.
- **search-sources**: When a reviewer says "there's prior work they missed on X," offer to run a source search. Results can be added as REF-type notes.

## Notes

- This capability is **conversational** — the core agent handles it directly, no subagents needed during the note-recording loop.
- Subagents are only spawned if the reviewer opts into claim verification or source search.
- The report file is written incrementally (notes appended as they arrive), not all at once at the end. This means the reviewer can stop at any time and still have a partial report.
- The agent should NOT editorialize or add its own opinions about the paper. It records the reviewer's feedback faithfully. The only agent-generated content is the summary (confirmed by the reviewer) and the categorization metadata.
