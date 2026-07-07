# Skill: peer-review

## Description
Interactive peer-review session. The reviewer reads the paper and sends notes incrementally. The agent categorizes each note, maps it to the relevant section and line, and builds a structured review record. Optionally verifies reviewer concerns against sources using the verify-claims capability.

## Usage
```
/peer-review                                      # Start session, agent asks for reviewer name
/peer-review --reviewer "Alice Chen"               # Start session with reviewer name
/peer-review section/03_methodology.tex            # Focus on one section
/peer-review --reviewer "Alice Chen" section/03_methodology.tex  # Both
```

## Arguments
- **--reviewer "Name"**: Reviewer's name for the review record. If omitted, the agent asks during initialization.
- **Optional**: File path to focus on a specific section. Default: read all `section/*.tex` files.

## Model Requirement
The agent handling the peer-review session MUST use a flagship reasoning model. Accurate categorization and context-aware mapping of reviewer feedback to paper locations requires deep reasoning. See `capabilities/shared/workflow-config.md` for platform-specific model mapping.

## Guidance Documents
Before starting a session, read:
- `capabilities/shared/workflow-config.md` — model requirements
- `capabilities/shared/output-formats.md` — peer review record template
- `capabilities/shared/evidence-standards.md` — useful when evaluating CLM/REF-type notes for verify-claims handoff

## Session Lifecycle

### 1. Initialize
Read the paper to build context:
- Read `paper.yaml` for title, authors, abstract summary, section structure
- Read all `section/*.tex` files (or the specified section)
- Read `bibliography.bib` for citation context
- **Ask for the reviewer's name** if not provided as an argument. This is required for the review record filename.
- Create the review record at `reviews/<paper-slug>-<reviewer-slug>-<YYYYMMDD-HHMM>.md` (timestamp in UTC) with the header populated. Generate each slug independently as follows:
  1. Lowercase the string
  2. Strip accents/diacritics (e.g., "é" → "e")
  3. Replace any non-alphanumeric character with a hyphen
  4. Collapse consecutive hyphens into one
  5. Trim leading/trailing hyphens
  6. Truncate to 40 characters per slug (at a word boundary if possible)
  
  Apply these steps separately to the paper title and reviewer name, then join with a hyphen.
  Example: paper "Every Model Cheats: A Study", reviewer "Alice Chen" → `every-model-cheats-a-study-alice-chen-20260707-1430.md`

During initialization, build a **section index** — a mapping of section names/topics to file paths and line ranges. This is used to resolve vague reviewer references like "in the results" to specific files. Example:
```
"abstract"      → section/00_abstract.tex
"introduction"  → section/01_introduction.tex
"background"    → section/02_background.tex
"methodology"   → section/03_methodology.tex
"results"       → section/04_results.tex
"discussion"    → section/05_discussion.tex
"conclusion"    → section/06_conclusion.tex
```

Print a short confirmation:
```
=== PEER REVIEW SESSION STARTED ===
Paper: <title from paper.yaml>
Reviewer: <name>
Sections loaded: <list>
Review record: reviews/<filename>.md
Send notes as you read. Say "done with review" or /peer-review done to finalize.
```

### 2. Record Notes
The reviewer sends notes in natural language. For each note:

**Parse and categorize:**
- Identify the **feedback type** (see Feedback Types below)
- Identify the **severity**: major (blocks acceptance), minor (should fix), or nit (optional polish)
- Identify the **target** using these rules, in order:
  1. **Explicit reference**: The reviewer says "line 34 in methodology" or "section 3.2" → use that file:line directly
  2. **Section mention**: The reviewer says "in the results" or "the introduction claims..." → resolve via the section index to the file path, then search that file for the relevant passage to get a line number
  3. **Quote or paraphrase**: The reviewer quotes text from the paper → grep section files for the quote to find file:line
  4. **Context from prior notes**: If the reviewer's last few notes were about a specific section, assume this note is about the same section unless they indicate otherwise
  5. **Cannot determine**: If none of the above resolves a target, ask the reviewer: "Which section does this note apply to?"

**Multi-section notes:** If a note spans multiple sections (e.g., "the methodology is underdescribed and this makes the results hard to interpret"), record it as a single note with multiple locations: `section/03_methodology.tex, section/04_results.tex`. Use the primary section (where the fix should happen) as the sort key.

**Questions from the reviewer:** Treat questions as feedback. "Why did you choose this baseline?" is a CLR note — the reviewer is saying the choice isn't adequately justified. Record it as-is; the question format IS the feedback.

**Record to the report:**
- Append the note to the appropriate severity section (Major Issues / Minor Issues / Nits / Strengths) in the review record
- Assign a sequential ID (R1, R2, R3, ...)
- Include the original note text, category, severity, and file:line reference
- The Summary section remains blank until finalization — the rest of the file is valid markdown at all times
- The YAML frontmatter fields (`recommendation`, `issues`, `types`) stay zeroed until finalization

**Acknowledge briefly:**
After recording, confirm with one line:
```
R<N> recorded — <type>, <severity> → <section file>:<line>
```
Do not summarize the note back or add commentary unless the reviewer asks.

**Editing previous notes:**
The reviewer can modify prior notes at any time:
- "Change R3 to major" → update severity, move to correct section in report
- "Delete R5" → remove from report, do not reuse the ID
- "R7 should be MTH not CLR" → update the type code
Acknowledge edits with: `R<N> updated — <what changed>`

### 3. Finalize
When the reviewer says `/peer-review done`, "done with review", or "finalize the review":

1. Read the full review record
2. Write the **Summary** section — 3-5 sentences capturing the overall assessment, derived from the notes
3. Count notes by type and severity, update the YAML frontmatter `issues:` fields (major, minor, nit, positive) and `types:` fields with final counts
4. Propose an overall **Recommendation** with justification (also update the `recommendation:` field in frontmatter):
   - **Accept**: No major issues, few or no minor issues
   - **Minor Revision**: No major issues, but several minor issues that need attention
   - **Major Revision**: Major issues present, but they appear addressable with additional work
   - **Reject**: Fundamental issues that undermine the paper's core contribution

   State the reasoning: "You raised N major issues (focused on methodology and claims) and M minor issues. This suggests Major Revision. Does that match your assessment, or would you like to adjust?"
5. The reviewer confirms or overrides. Their decision is final — record it as-is.

**Optional — verify flagged claims:**
If any CLM or REF-type notes question the accuracy of specific claims, offer to verify them. To do this:
1. Extract the specific claim text from the section file at the note's file:line location
2. Read `bibliography.bib` to resolve any `\cite{key}` references in that passage to DOIs/URLs
3. Run `/verify-claims` targeting just that passage, or launch a single Analyzer agent (from `capabilities/analyze-source/agent.md`) to fetch and check the cited source directly
4. Append the verification result to the note in the review record as a sub-section: "**Verification**: <result>"

For REF-type notes where the reviewer says "there's prior work they missed," run `/search-sources` with the topic and append discovered sources to the note.

Print a final summary:
```
=== PEER REVIEW COMPLETE ===
Review record: <file path>
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

The agent assigns the type automatically. If ambiguous, pick the closest match — the reviewer can correct it (see "Editing previous notes" above).

## Report Format

Review records use YAML frontmatter for machine-readable metadata (paper, reviewer, date, recommendation, issue/type counts). The frontmatter fields `recommendation`, `issues`, and `types` are zeroed at creation and populated during finalization.

See `capabilities/shared/output-formats.md` for the full template.

## Integration with Other Capabilities

- **verify-claims**: When a reviewer flags a claim as suspect (CLM or REF type), extract the claim text from the paper at the note's file:line, resolve cited sources via `bibliography.bib`, and run verification. See Step 3 (Finalize) for the detailed workflow.
- **search-sources**: When a reviewer says "there's prior work they missed on X," run `/search-sources` with the topic. Append results to the note.
- **analyze-source**: If the reviewer provides a URL to a paper they think is missing, run `/analyze-source` to produce a source card and add it as evidence to the note.

## Error Handling
- If no section files are found, report this and ask the reviewer to provide a file path
- If a note cannot be mapped to any section after asking the reviewer, record it with location "general" rather than blocking the session
- If verify-claims or search-sources fails during finalization, note the failure in the review record and continue
- If the session is interrupted before finalization, the review record contains all recorded notes in valid markdown — the reviewer can resume by starting a new session and referencing the partial report

## Notes

- This capability is **conversational** — the core agent handles it directly, no subagents needed during the note-recording loop.
- Subagents are only spawned if the reviewer opts into claim verification or source search.
- The review record is written incrementally (notes appended as they arrive), not all at once at the end. This means the reviewer can stop at any time and still have a partial report.
- The agent should NOT editorialize or add its own opinions about the paper. It records the reviewer's feedback faithfully. The only agent-generated content is the summary (confirmed by the reviewer) and the categorization metadata.
- Use `python3 scripts/reviews.py` to list all past reviews, filter by reviewer, or get detail on a specific review.
