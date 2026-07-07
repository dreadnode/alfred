# Search Strategy

This document guides the Searcher agent in constructing queries, selecting sources, and managing results.

## Query Construction

### From a topic
1. Identify the core concept and 2-3 synonyms or related terms
2. Generate 3-5 search queries using different angles:
   - **Direct**: the topic as stated (e.g., "LLM cheating on benchmarks")
   - **Synonym expansion**: alternate terminology (e.g., "specification gaming evaluation", "reward hacking benchmarks")
   - **Scoped**: site-restricted searches for high-quality sources (e.g., `site:arxiv.org LLM benchmark gaming`)
   - **Author-based**: if key authors are known, search by name + topic
   - **Recency-biased**: append year or "2025 2026" to find recent work

### From a claim
1. Extract the core assertion and key terms
2. Generate queries that would find both supporting AND contradicting evidence:
   - **Supporting**: search for the claim's key terms together
   - **Contradicting**: search for the opposite claim or known counterarguments
   - **Methodology**: search for studies using similar methods to assess comparability
3. Include the specific metric or number if the claim is quantitative (e.g., "benchmark cheating rate 3%" to find the source of that number)

### From a paper
1. Search for the paper by title to find citation context
2. Search for papers that cite it (use Google Scholar "cited by" or Semantic Scholar)
3. Search for papers in the same domain published after it
4. Search for the paper's key findings as standalone queries

## Query Syntax

- Use Google-style search syntax for WebSearch
- Boolean operators: `"exact phrase"`, `OR`, `-exclude`
- Site scoping: `site:arxiv.org`, `site:openreview.net`, `site:aclanthology.org`
- Filetype: `filetype:pdf` (use sparingly, prefer HTML-accessible versions)
- Recency: append year range when freshness matters

## Where to Search

Always include site-scoped queries against these domain-agnostic academic sources. They work for any research topic.

### Primary sources (always search)
| Source | URL | Use for |
|--------|-----|---------|
| arXiv | `site:arxiv.org` | Preprints — broadest coverage of recent research |
| Google Scholar | `scholar.google.com` | Citation graph, "cited by" discovery, cross-domain |
| Semantic Scholar | `semanticscholar.org` | API-friendly, related work recommendations |
| OpenReview | `site:openreview.net` | Conference submissions with peer reviews visible |

### Discovery tools (use for broadening)
| Source | URL | Use for |
|--------|-----|---------|
| Connected Papers | `connectedpapers.com` | Visual citation graph — find clusters of related work |
| Papers With Code | `paperswithcode.com` | Benchmarks, methods, and associated papers |

### Domain-specific venues
Do not hardcode domain-specific venues here. Instead, the Searcher should identify the relevant venues for the topic at hand and add site-scoped queries for them. For example, a security topic might warrant `site:usenix.org` or `site:ieee-security.org`, while a clinical topic might warrant `site:pubmed.ncbi.nlm.nih.gov` or `site:cochranelibrary.com`.

## Source Priority

Rank sources by quality tier (see EVIDENCE_STANDARDS.md for full definitions):

| Priority | Source Type | Examples |
|----------|------------|---------|
| 1 | Peer-reviewed publications | NeurIPS, ICML, USENIX, IEEE S&P, ACL |
| 2 | Preprints with institutional backing | arXiv papers from known research labs |
| 3 | Technical reports and system cards | Anthropic system cards, OpenAI technical reports |
| 4 | Workshop papers and extended abstracts | Conference workshop proceedings |
| 5 | Blog posts from research organizations | Anthropic blog, Google DeepMind blog, OpenAI blog |
| 6 | Independent blog posts and analyses | Well-sourced independent analysis |
| 7 | News articles | Tech journalism covering research findings |

Within the same tier, prefer:
- More recent over older
- Larger sample size over smaller
- More rigorous methodology over less
- Direct measurement over survey/opinion

## Deduplication Rules

1. **Same paper, different URLs**: Keep the highest-authority version (published > preprint > blog summary). Deduplicate by title + first author.
2. **Updated versions**: Keep the most recent version (v3 over v1 of same arXiv paper).
3. **Summaries of other work**: If source A summarizes source B and both are in the list, keep source B (the primary) unless source A adds original analysis.

## Result Limits

- **Per query**: Collect top 10 results
- **Per run**: Return at most 15 unique sources after deduplication and ranking
- **Minimum**: If fewer than 3 relevant sources are found, broaden search terms and try again (up to 2 broadening iterations)

## Broadening and Narrowing

### When to broaden
- Fewer than 3 relevant sources found
- All sources are from the same author or group
- Topic is very specific or niche

### How to broaden
- Remove specificity: "LLM cheating Cybench CTF" -> "LLM cheating benchmarks"
- Add synonyms: include "gaming", "shortcutting", "reward hacking"
- Expand time range: remove year constraints
- Search adjacent domains: if nothing in ML, try software engineering or security venues

### When to narrow
- More than 30 candidates before dedup
- Results are dominated by tangentially related work
- A specific sub-question needs targeted evidence

### How to narrow
- Add distinguishing terms from the specific claim
- Scope to specific venues or authors
- Add year constraints
- Use exact phrases for technical terms

## What the Searcher Returns

For each source, return:
```
- title: <paper/article title>
- authors: <first author et al. or full list if <= 3>
- date: <publication date, YYYY-MM or YYYY>
- url: <canonical URL>
- source_type: <peer-reviewed | preprint | tech-report | system-card | blog | news>
- abstract_snippet: <first 2-3 sentences of abstract or summary>
- relevance: <1-5 score with one-line justification>
- query_that_found_it: <which search query surfaced this>
```
