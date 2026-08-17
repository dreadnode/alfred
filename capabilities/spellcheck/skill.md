# Skill: spellcheck

## Description
Full spelling and grammar check of the paper. Reads all section files (or a specific file), identifies errors, and reports them with locations and suggested fixes.

## Usage
```
/spellcheck                          # Check all section files
/spellcheck section/01_introduction.tex   # Check a specific section
```

## Arguments
- **Optional**: File path to a specific section. If omitted, check all `section/*.tex` files.

## Workflow

### 1. Identify target files
- If a file path is provided, use that file only
- Otherwise, read `paper.yaml` to get the section list, then read each `section/*.tex` file

### 2. Check each file
For each file, carefully read the text and identify:

**Spelling errors:**
- Misspelled words (not LaTeX commands, labels, or citation keys)
- Skip words inside `\cite{}`, `\ref{}`, `\label{}`, `\url{}`, `\texttt{}`, and math environments
- Skip content inside `\begin{equation}...\end{equation}`, `$...$`, `$$...$$`

**Grammar issues:**
- Subject-verb agreement
- Article usage (a/an/the)
- Sentence fragments
- Run-on sentences
- Tense consistency within paragraphs
- Dangling modifiers

**Style issues (report separately, lower priority):**
- Passive voice overuse
- Overly long sentences (>40 words)
- Repeated words in close proximity

### 3. Report findings
For each issue found, report:
```
<file>:<line> — <type> — "<problematic text>" → "<suggested fix>"
```

Group by file, then by type (spelling, grammar, style). At the end, print a summary:
```
=== SPELLCHECK COMPLETE ===
Files checked: <count>
Spelling errors: <count>
Grammar issues: <count>
Style suggestions: <count>
```

## Notes
- This is a text-level check — the agent reads the raw LaTeX source and ignores markup
- Do NOT modify any files — report only. The user decides what to fix.
- Be conservative: if unsure whether something is an error (e.g., domain-specific terminology, proper nouns), skip it rather than flagging a false positive
- LaTeX-specific terms (e.g., "biblatex", "natbib") are not spelling errors
