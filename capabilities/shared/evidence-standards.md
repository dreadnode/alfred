# Evidence Standards

This document defines how the Analyzer and Synthesizer agents assess source quality, grade evidence strength, and assign verdicts to claims.

## Source Quality Tiers

| Tier | Label | Description | Examples |
|------|-------|-------------|----------|
| A | **Peer-reviewed** | Published in a peer-reviewed venue (journal or top-tier conference) | NeurIPS, ICML, USENIX Security, IEEE S&P, ACL, EMNLP |
| B | **Institutional preprint** | arXiv/SSRN paper from a recognized research lab, not yet peer-reviewed | Papers from Anthropic, Google DeepMind, OpenAI, METR, university labs |
| C | **Technical report** | Official technical documentation from a vendor or standards body | System cards, model cards, NIST reports, safety evaluations |
| D | **Workshop/poster** | Workshop papers, extended abstracts, or poster presentations | NeurIPS workshops, ICML workshops |
| E | **Org blog post** | Blog posts from research organizations, typically summarizing internal work | Anthropic blog, OpenAI blog, Google AI blog |
| F | **Independent analysis** | Blog posts, analyses, or reports from independent researchers or journalists | Substacks, personal blogs with citations, tech journalism |

### Using tiers in analysis
- Tier alone does not determine truth. A well-designed preprint (B) can be stronger evidence than a poorly-designed published paper (A).
- Tier affects the **default credibility** before examining methodology. Higher-tier sources get benefit of the doubt; lower-tier sources need stronger internal evidence.
- When two sources conflict, tier is the tiebreaker only if methodology and sample size are comparable.

## Evidence Strength Grading

For each finding extracted from a source, the Analyzer assigns a strength grade:

| Grade | Label | Criteria |
|-------|-------|----------|
| **Strong** | Robust evidence | Large sample, controlled methodology, results are statistically significant or effect size is large, findings have been independently replicated |
| **Moderate** | Credible evidence | Reasonable sample, sound methodology, results are directionally clear but may lack statistical rigor or replication |
| **Weak** | Suggestive evidence | Small sample, limited methodology (case study, anecdotal), preliminary results, single data point |
| **Indirect** | Tangential evidence | Findings are from a related but not identical domain; supports the claim by analogy rather than direct measurement |

### Factors that strengthen evidence
- Large and representative sample
- Controlled experimental design (ablation, A/B, randomized)
- Clear operationalization of variables
- Statistical tests with reported significance levels
- Independent replication by different groups
- Open data and methodology

### Factors that weaken evidence
- Small or convenience sample
- No control condition or baseline
- Vague operationalization ("we observed that...")
- No statistical testing or unreported effect sizes
- Self-reported data without validation
- Conflicts of interest (vendor evaluating own model)

## Methodological Comparability

When comparing findings across sources, the Analyzer must flag methodological differences that affect comparability:

- **Different benchmarks**: Results from Cybench vs SWE-bench vs CTFusion are not directly comparable
- **Different metrics**: Pass rate vs solve rate vs success rate may measure different things
- **Different model versions**: GPT-4 (March 2023) vs GPT-4-turbo (April 2024) are different models
- **Different evaluation conditions**: With vs without internet access, sandboxed vs unsandboxed, with vs without system prompts
- **Different sample sizes**: 23 tasks vs 464 traces vs 89 tasks affect statistical power
- **Different cheating definitions**: Counting only successful cheating vs counting attempts, counting only web search vs including infrastructure probing

The Synthesizer must account for these differences when comparing findings. Two studies reporting different cheating rates may both be correct if their definitions or conditions differ.

## Claim Verdict Criteria

The Synthesizer assigns one of five verdicts to each claim:

| Verdict | Criteria | Symbol |
|---------|----------|--------|
| **Supported** | Multiple independent sources with moderate-to-strong evidence confirm the claim. No credible contradicting evidence. | **S** |
| **Partially Supported** | Some evidence supports the claim, but with caveats: limited sample, single source, or the evidence supports a weaker version of the claim. | **P** |
| **Unsupported** | No evidence found to confirm or deny the claim. The claim may be novel, or the search may have missed relevant work. | **U** |
| **Contested** | Credible evidence exists both for and against the claim. Sources disagree, and the disagreement is not explained by methodological differences alone. | **C** |
| **Contradicted** | Multiple independent sources with moderate-to-strong evidence directly contradict the claim. | **X** |

### Assigning verdicts
1. List all evidence for and against the claim
2. Weight evidence by source tier and strength grade
3. Account for methodological comparability (different conditions may explain different results)
4. Assign the verdict that best fits the evidence balance
5. State confidence level: **High** (clear evidence), **Medium** (some ambiguity), **Low** (limited evidence either way)

### Important principles
- **Absence of evidence is not evidence of absence.** "Unsupported" means the search found nothing, not that the claim is false.
- **Novelty is expected.** If the paper makes a genuinely new contribution, some claims SHOULD be unsupported by prior work. Flag these as "Novel claim — no prior evidence found" rather than implying the claim is weak.
- **Quantitative precision matters.** "37.1% of passes involved cheating" is a specific claim. If prior work found 3.4%, this is not a contradiction — it may reflect different methodology. Explain the difference rather than assigning "Contradicted."
- **Do not penalize scope.** A claim about "all benchmarks" requires broader evidence than a claim about "Cybench specifically." Match the evidence search to the claim's scope.
