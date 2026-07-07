# Skill: lit-review

## Description
Orchestrates a full literature review on a given topic, paper, or set of conclusions. Coordinates Searcher, Analyzer, and Synthesizer agents to produce a structured review report.

## Usage
```
/lit-review <topic or description>
/lit-review "LLM cheating behavior on cybersecurity benchmarks"
/lit-review "prompt-based mitigation of specification gaming in agent evaluations"
```

## Arguments
The argument is a free-text description of the topic to review. Can be:
- A research topic: "reward hacking in LLM agents"
- A paper title: "Every Model Cheats: Prompt-Level Mitigation..."
- A set of conclusions: "anti-cheat prompts reduce cheating but cause channel displacement"

## Orchestration Steps

### Step 1: Parse Input and Gather Paper Context
Read the user's topic description. Identify:
- Core concept and key terms
- Scope (narrow vs broad)
- Any specific papers, authors, or venues mentioned

Read project context to inform the review:
- Read `paper.yaml` for the paper's title, abstract summary, and section structure — this tells the Synthesizer what the paper is about and which sections exist for cross-section placement
- Read `bibliography.bib` to build an exclusion list of already-cited works — the Searcher should not return these
- Read `section/` files relevant to the topic (e.g., related work, introduction) for additional context on the paper's thesis

### Step 2: Read Guidance Docs
Read the following files to load workflow configuration:
- `capabilities/shared/workflow-config.md`
- `capabilities/shared/search-strategy.md`
- `capabilities/shared/evidence-standards.md`
- `capabilities/shared/output-formats.md`
- `capabilities/search-sources/agent.md`
- `capabilities/analyze-source/agent.md`
- `capabilities/shared/synthesizer.md`

### Step 3: Run Searchers (Parallel by Subtopic)
If the topic spans multiple distinct subtopics (e.g., a paper with 4 related work subsections), launch one Searcher agent per subtopic in parallel. This produces better coverage than a single broad search.

For each Searcher:
- Include the full Searcher agent instructions from `capabilities/search-sources/agent.md`
- Include relevant sections of search-strategy.md in the prompt
- Pass the subtopic description as input
- Pass the list of existing citations with instruction: "Do NOT return these — they are already cited"
- Request: "Find up to 15 relevant sources for this subtopic"

Collect all ranked source lists from the Searchers' responses.

### Step 3.5: Deduplicate Across Searchers
If multiple Searchers were used, merge their results and deduplicate:
- Same paper found by multiple searchers: keep one entry, note which subtopics it's relevant to
- Apply search-strategy.md deduplication rules (same paper at different URLs, updated versions, summaries of primary sources)
- Cap at 15 unique sources for analysis

### Step 4: Run Analyzers (Parallel)
For each source in the deduplicated list from Step 3.5, launch an agent using a flagship reasoning model:
- Include the full Analyzer agent instructions from `capabilities/analyze-source/agent.md`
- Include the source metadata (title, URL, type) from the Searcher
- Set analysis context to the original topic
- Request: "Deep-read this source and produce a source card"

Launch these in parallel (multiple Agent calls in a single message) to maximize throughput. Each agent handles one source.

**Batch size**: Launch up to 5 Analyzer agents at a time. If there are more than 5 sources, run in batches of 5.

### Step 5: Collect Source Cards
Gather all source cards from completed Analyzer agents. Note any sources that were inaccessible.

### Step 5.5: Verify Key Claims (Spot Check)
For sources likely to be cited, launch verification agents (one per source, in parallel) to spot-check the Analyzer's extracted claims against the actual source. Each verification agent should:
- Fetch the source directly (WebFetch or Read)
- Check specific numbers (counts, percentages, model names) against the source text
- Confirm author names are spelled correctly
- Confirm publication year from the arXiv ID or venue page
- Flag any claims where the Analyzer's framing differs from the source's own framing

This step catches errors that propagate into the final report if left unchecked. Priority: verify any source where the Analyzer reports specific quantitative findings, surprising claims, or findings that will be quoted in the paper. Skip verification for sources that are clearly nice-to-have or will not be cited.

### Step 6: Run Synthesizer
Launch a single agent using a flagship reasoning model (see capabilities/shared/workflow-config.md):
- Include the full Synthesizer agent instructions from `capabilities/shared/synthesizer.md`
- Include the output-formats.md template for Literature Review Report
- Include evidence-standards.md for quality assessment
- Pass all source cards as input
- Pass the original topic description
- Set mode to "literature review"
- If the review is for a specific paper, pass the paper's thesis and existing citations so the Synthesizer can assess contradiction, duplication, and cross-section placement
- Request: "Synthesize these source cards into a themed literature review. Assign priority tiers (must-cite / should-cite / nice-to-have). Flag any sources that contradict the paper's thesis or duplicate its contribution. Recommend cross-section placement. Write the report to `capabilities/reports/lit-review_<slug>_<YYYY-MM-DD>.md` and print a summary to stdout."

### Step 7: Output
Print the Synthesizer's stdout summary to the user. Report the file path of the written report.

## Error Handling
- If Searcher finds fewer than 3 sources, report this to the user and proceed with what was found
- If an Analyzer cannot access a source, skip it and note it in the report
- If any agent fails, report the failure and continue with remaining agents

## Model Requirement
ALL agent invocations in this skill MUST use a flagship reasoning model. See capabilities/shared/workflow-config.md for platform-specific model mapping.
