# Skill: search-sources

## Description
Standalone source discovery skill. Finds relevant papers, preprints, and reports for a given topic or claim without performing deep analysis. Useful for quick reconnaissance before a full lit review.

## Usage
```
/search-sources <topic or query>
/search-sources "reward hacking in LLM agent evaluations"
/search-sources "benchmark score inflation from cheating"
```

## Arguments
Free-text description of the topic or query to search for.

## Orchestration Steps

### Step 1: Read Guidance
Read:
- `lit-review-and-claim-verifier/SEARCH_STRATEGY.md`
- `lit-review-and-claim-verifier/agents/searcher.md`

### Step 2: Run Searcher
Launch a single agent using a flagship reasoning model:
- Include the full Searcher agent instructions
- Include SEARCH_STRATEGY.md guidance
- Pass the user's topic/query
- Request: "Find up to 15 relevant sources. Return the ranked source list."

### Step 3: Output
Print the Searcher's ranked source list directly to stdout. Format as a numbered list with title, authors, date, URL, type, and relevance score for each source.

## Model Requirement
Agent invocation MUST use a flagship reasoning model. See WORKFLOW_CONFIG.md for platform-specific model mapping.
