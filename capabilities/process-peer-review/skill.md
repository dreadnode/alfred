# Skill: process-peer-review

## Description
Interactive peer-review response session. Takes an existing peer review record, summarizes it, then walks through each issue with the user. The user decides how to handle each item: address it (make paper changes), accept it, refute it, or skip it. All decisions are recorded in a peer review response file.

## Usage
```
/process-peer-review reviews/every-model-cheats-jane-doe-20260707-1430.md
/process-peer-review                    # Agent lists available reviews and asks which one
```

## Arguments
- **Optional**: Path to a peer review file in `reviews/`. If omitted, list all review files in `reviews/` and ask the user which one to process.

## Model Requirement
The agent handling this session MUST use a flagship reasoning model. See `capabilities/shared/workflow-config.md` for platform-specific model mapping.

## Session Lifecycle

### 1. Initialize

**If no review file is specified:**
- List all `.md` files in `reviews/` that have peer review frontmatter (contain `recommendation:` in their YAML)
- Exclude files that are already response records (contain `review_file:` in their frontmatter)
- Present the list with reviewer name, date, and recommendation
- Ask the user which review to process
- If only one review exists, offer to use it automatically

**Once a review file is selected:**
1. Read the review file fully
2. Read the paper context — `paper.yaml`, the section files referenced in the review, `bibliography.bib`
3. Create the response file at `reviews/<paper-slug>-response-<reviewer-slug>-<YYYYMMDD-HHMM>.md` using the same slugging rules as peer-review (see `capabilities/peer-review/skill.md` Step 1 for the slug algorithm). The timestamp is the current time (when processing begins), not the original review time.
4. Write the initial YAML frontmatter:

```yaml
---
paper: "<paper title>"
reviewer: "<reviewer name from the review>"
review_file: "<original review filename>"
date: "<YYYY-MM-DD HH:MM>"
status: in_progress
items_addressed: 0
items_accepted: 0
items_refuted: 0
items_skipped: 0
---

# Peer Review Response

Response to review by <reviewer name> (<date of original review>).
Recommendation: <recommendation from original review>.
```

5. Print a summary for the user:

```
=== PROCESSING PEER REVIEW ===
Review by: <reviewer name>
Date: <review date>
Recommendation: <recommendation>
Response file: reviews/<filename>.md

Issues:
  Major: <count> — <one-line summary of each>
  Minor: <count> — <one-line summary of each>
  Nit:   <count> — <one-line summary of each>

Strengths noted: <count>

Which item would you like to address first? (e.g., "R1" or "start with major issues")
```

### 2. Process Items

The user selects items to work on. For each item:

**Present the item:**
```
--- R<N>: <title> ---
Type: <type code> | Severity: <severity> | Location: <file:line>

<original reviewer comment>

How would you like to handle this?
  • address — make changes to the paper
  • accept — acknowledge without changes
  • refute — dispute with justification
  • skip — come back to it later
```

**Based on the user's decision:**

**Address:**
1. Discuss what changes are needed with the user
2. Make the requested changes to the paper using available tools (read_file, write_file, etc.)
3. After changes are made, ask the user to confirm they're satisfied
4. Record in the response file:
```markdown
## R<N>: <title>
**Decision**: Addressed
**Action**: <brief description of what was changed>
**Changes**: <list of files modified>
```
5. Increment `items_addressed` in the YAML frontmatter

**Accept:**
1. The user acknowledges the issue but may not make changes now, or the change is trivial enough they'll handle it themselves
2. Optionally the user can add a note
3. Record in the response file:
```markdown
## R<N>: <title>
**Decision**: Accepted
**Note**: <user's note, if any>
```
4. Increment `items_accepted` in the YAML frontmatter

**Refute:**
1. Ask the user for their justification
2. Help the user articulate the rebuttal if requested (e.g., point to evidence in the paper, find supporting sources)
3. Record in the response file:
```markdown
## R<N>: <title>
**Decision**: Refuted
**Justification**: <user's reasoning>
```
4. Increment `items_refuted` in the YAML frontmatter

**Skip:**
1. Move on to the next item — do not write anything to the response file body yet
2. If the user later comes back to a skipped item and makes a decision, record that decision normally

**After each item** (except skip), update the YAML frontmatter counts and ask:
```
R<N> recorded as <decision>. What's next? (<remaining count> items remaining)
```

### 3. Finalize

When the user says "done", "finalize", or all items have been processed:

1. Check for any items not yet recorded in the response file — remind the user: "You have N unhandled items (R2, R5). Would you like to address them now?"
2. If the user declines, these remain unhandled
3. Update the YAML frontmatter:
   - Set `status: complete`
   - Count decisions from the response body: `items_addressed`, `items_accepted`, `items_refuted`
   - Set `items_skipped` to the number of review items with no decision recorded
4. Print a summary:

```
=== PEER REVIEW RESPONSE COMPLETE ===
Response file: reviews/<filename>.md
  Addressed: <count>
  Accepted:  <count>
  Refuted:   <count>
  Skipped:   <count>
```

5. **Surface the response as an artifact**: Call `emit_file_artifact` with the response file path and label "Peer Review Response" so the user gets a clickable card in the chat to copy the full response.

## Response File Format

Response files use YAML frontmatter linking back to the original review via the `review_file` field. The body contains one section per processed item, in the order they were handled (not necessarily the original R-number order).

The `status` field is `in_progress` during the session and `complete` after finalization. This allows interrupted sessions to be identified and resumed.

## Error Handling
- If the review file doesn't exist, report the error and list available reviews
- If a referenced section file doesn't exist (e.g., sections were reorganized since the review), note this when presenting the item and ask the user how to proceed
- If the session is interrupted before finalization, the response file contains all decisions made so far with `status: in_progress`
- If a response file already exists for this review (detected by scanning `reviews/` for files whose `review_file` frontmatter matches), ask the user whether to continue or start fresh. If continuing, read the existing response file, identify which R-items already have decisions recorded, and skip those when presenting remaining items

## Integration with Other Capabilities
- When **addressing** an item, the agent uses its standard paper-editing tools (read_file, write_file, build_paper, sync_paper, etc.)
- When **refuting** a CLM or REF-type item, offer to run `/verify-claims` or `/search-sources` to gather supporting evidence for the rebuttal
- When the reviewer flagged missing references (REF type), offer to run `/search-sources` to find relevant papers

## Notes
- This capability is **conversational** — the core agent handles it directly, no subagents needed
- The agent should NOT make paper changes without the user's explicit approval
- The agent records the user's decisions faithfully — it does not override or editorialize
- Items are presented in the order the user requests, not forced sequentially
- The response file is written incrementally (each decision appended as it's made), not all at once
