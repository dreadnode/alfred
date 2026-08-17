# Skill: verify-claims

## Description
Orchestrates claim verification for a paper section. Auto-extracts claims from LaTeX or text, finds evidence for/against each, and produces a structured verification report with per-claim verdicts.

## Usage
```
/verify-claims <file path> [section]
/verify-claims section/01_introduction.tex
/verify-claims section/03_methodology.tex "Section 3.1"
```

## Arguments
- **Required**: File path to the LaTeX section or text file containing claims
- **Optional**: Specific section or line range to focus on (e.g., "Section 3.1", "lines 1-50")

## Orchestration Steps

### Step 1: Read Target Files and Paper Context
Use Read to load the target file(s). If a section filter was provided, extract only that section.

**Default to full-paper verification.** Prior-work characterizations — the most error-prone claim type — cluster in Related Work but also appear in the Introduction, Discussion, and Conclusion. Verifying a single section misses claims in other sections. When the user provides a paper directory or main file, read all sections. When the user provides a single section, still scan the full paper for prior-work claims, since these are the highest-yield verification targets regardless of which section the user asked about.

**Read `bibliography.bib`** to extract DOI and URL mappings for cited sources. Prior-work claims reference `\cite{key}` — match these keys against bibliography entries to get direct URLs/DOIs for source verification (Step 4). This is faster and more reliable than web search for verifying characterizations of prior work.

### Step 2: Read Guidance Docs
Read the following files to load workflow configuration:
- `capabilities/shared/workflow-config.md`
- `capabilities/shared/search-strategy.md`
- `capabilities/shared/evidence-standards.md`
- `capabilities/shared/output-formats.md`
- `capabilities/search-sources/agent.md`
- `capabilities/analyze-source/agent.md`
- `capabilities/shared/synthesizer.md`

### Step 3: Auto-Extract Claims
Parse the file content and extract verifiable claims. Use these heuristics:

**Characterizations of prior work** (HIGHEST PRIORITY — most error-prone):
Assertions about what other studies found. These are the claims most likely to contain inaccuracies because they paraphrase external sources.
- "NIST CAISI found cheating in approximately 0.3% of logs"
- "The Meerkat study audited nine benchmarks"
Verify these by fetching the cited source directly, not by web search.

**Superlatives or firsts** (HIGH PRIORITY — require adversarial search):
"the first to...", "the largest...", "the most..."
- "the first systematic test of whether system-prompt instructions suppress cheating"
These require specifically searching for prior work that would disprove the claim. The Searcher must be instructed to try to find counterexamples, not confirmations.

**Comparative claims** (MEDIUM PRIORITY — often verifiable arithmetically):
"more than...", "unlike prior work...", "an order of magnitude worse..."
- "an order of magnitude worse than prior estimates"
If both numbers are stated in the paper (e.g., 0.3-3.4% vs 37.1%), verify the math first. Only run a Searcher if the comparison references external data not already in the paper.

**Quantitative assertions** (LOWER PRIORITY for external verification):
Sentences with numbers + comparisons/metrics from the paper's own data.
- "37.1% of all passes involved cheating"
- "cheat propensity drops from 33.0% to 8.5%"
These come from the paper's own experiments and cannot be externally verified. Skip unless they reference external sources.

**Causal claims**: X causes/leads to/results in Y
- "anti-cheat prompts reduce cheating without degrading legitimate performance"

**Scope claims**: "all models...", "no model...", "every..."
- "21 of 22 models cheated under baseline"

Strip LaTeX formatting when extracting (remove `\cite{}`, `\ref{}`, `\textbf{}`, etc.) but preserve the file:line reference.

For each claim, record:
- Claim text (plain text, LaTeX stripped)
- Source location (file:line)
- Claim type (prior-work, superlative, comparative, quantitative, causal, scope)
- **All locations**: Search the entire paper for other instances of the same claim. Claims often appear in both the Introduction and Conclusion, or in both Related Work and Discussion. Record all file:line locations so fixes propagate consistently.

### Step 4: Triage Claims by Verification Strategy
Not all claims need web search. Route each claim to the appropriate verification method:

**Prior-work claims → Direct source verification (no Searcher needed)**
Fetch the cited source directly (via the URL or DOI in the bibliography) and compare the paper's characterization against the source text. This is faster and more reliable than web search. Launch one verification agent per cited source, in parallel.

**Superlative/first claims → Adversarial Searcher**
Launch a Searcher with explicit instructions to find counterexamples: "Search for any prior work that did X. If you find something, this claim is false." The Searcher must try to disprove the claim, not confirm it.

**Comparative claims → Arithmetic check first**
If both numbers are in the paper, verify the math (e.g., "order of magnitude" = 10x, check if 37.1/3.4 ≈ 10x). Only launch a Searcher if the comparison references external data.

**Own-data quantitative claims → Skip external verification**
Claims about the paper's own experimental results (e.g., "37.1% of passes involved cheating") cannot be externally verified. Flag them as "own-data, not externally verifiable" and move on.

**Causal/scope claims → Standard Searcher**
Generate 2-3 targeted search queries per claim (supporting + contradicting evidence).

Group similar claims to avoid redundant searches. If two claims reference the same prior work, combine their verification.

### Step 5: Run Verification Agents
Launch agents appropriate to each claim type (see Step 4):

**For prior-work claims**: Launch Analyzer agents that fetch the cited source directly and compare the paper's characterization against the source text. No Searcher needed.

**For superlative/first claims**: Launch Searcher agent(s) with adversarial framing.

**For remaining claims**: Launch standard Searcher agent(s) grouped by topic.

If the claim set is large (>10 externally verifiable claims), split into parallel batches.

### Step 6: Run Analyzers (Parallel)
For each unique source returned by the Searcher(s), launch an Agent using a flagship reasoning model (see capabilities/shared/workflow-config.md):
- Include the full Analyzer agent instructions from `capabilities/analyze-source/agent.md`
- Set analysis context to the specific claims this source is relevant to
- Request a source card focused on findings relevant to those claims

Launch in parallel, up to 5 at a time.

### Step 7: Run Synthesizer
Launch a single Agent using a flagship reasoning model (see capabilities/shared/workflow-config.md):
- Include the full Synthesizer agent instructions from `capabilities/shared/synthesizer.md`
- Include the output-formats.md template for Claim Verification Report
- Include evidence-standards.md for verdict criteria
- Pass all source cards
- Pass the extracted claims list with file:line references
- Set mode to "claim verification"
- Request: "Verify each claim against the evidence. Assign verdicts per evidence-standards.md. Write the report to `capabilities/reports/claim-verification_<slug>_<YYYY-MM-DD>.md` and print a summary to stdout."

### Step 8: Output
Print the Synthesizer's stdout summary to the user, including:
- Number of claims analyzed
- Verdict distribution (supported / partially / unsupported / contested / contradicted)
- Top finding or most notable result
- File path of the written report

## Error Handling
- If no verifiable claims are found in the file, report this and suggest the user provide a different section
- If Searcher finds no evidence for a claim, mark it as "Unsupported" with a note that the search may have missed relevant work
- If a source is inaccessible, skip it and proceed

## Model Requirement
ALL agent invocations in this skill MUST use a flagship reasoning model. See capabilities/shared/workflow-config.md for platform-specific model mapping.
