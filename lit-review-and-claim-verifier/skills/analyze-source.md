# Skill: analyze-source

## Description
Standalone deep-read skill for a single source. Fetches the full text, extracts structured findings, and returns a source card. Useful for examining a specific paper in detail without running a full review.

## Usage
```
/analyze-source <URL or file path> [context]
/analyze-source https://arxiv.org/abs/2506.12345 "LLM cheating on benchmarks"
/analyze-source docs/papers/meerkat-2026.pdf "cheating detection methodology"
```

## Arguments
- **Required**: URL or local file path of the source to analyze
- **Optional**: Context string describing what to focus the analysis on

## Orchestration Steps

### Step 1: Read Guidance
Read:
- `lit-review-and-claim-verifier/EVIDENCE_STANDARDS.md`
- `lit-review-and-claim-verifier/OUTPUT_FORMATS.md`
- `lit-review-and-claim-verifier/agents/analyzer.md`

### Step 2: Run Analyzer
Launch a single agent using a flagship reasoning model:
- Include the full Analyzer agent instructions
- Include EVIDENCE_STANDARDS.md for quality grading
- Include OUTPUT_FORMATS.md source card schema
- Pass the source URL/path and any context
- Request: "Deep-read this source and produce a structured source card."

### Step 3: Output
Print the full source card to stdout.

## Model Requirement
Agent invocation MUST use a flagship reasoning model. See WORKFLOW_CONFIG.md for platform-specific model mapping.
