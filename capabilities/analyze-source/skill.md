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
- `capabilities/shared/workflow-config.md`
- `capabilities/shared/evidence-standards.md`
- `capabilities/shared/output-formats.md`
- `capabilities/analyze-source/agent.md`

### Step 2: Run Analyzer
Launch a single agent using a flagship reasoning model:
- Include the full Analyzer agent instructions
- Include evidence-standards.md for quality grading
- Include output-formats.md source card schema
- Pass the source URL/path and any context
- Request: "Deep-read this source and produce a structured source card."

### Step 3: Output
Print the full source card to stdout.

## Model Requirement
Agent invocation MUST use a flagship reasoning model. See capabilities/shared/workflow-config.md for platform-specific model mapping.
