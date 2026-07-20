# LLM Writing Indicators

Reference taxonomy for detecting LLM-generated prose. Flag a document only when **3+ categories** show clear signals — single-category matches are weak evidence and produce false positives.

---

## 1. Telltale Vocabulary

Certain words appear with dramatically higher frequency in LLM output than in human writing.

### Tier 1 — Strongest signals (10x+ overrepresentation)

Any ONE in a prose paragraph is a weak signal; two or more in the same paragraph is strong.

- **"delve"** — 40x overrepresented in early GPT-4; dropped to ~8x by mid-2025
- **"tapestry"** — ~25x. Almost never in human technical writing
- **"testament"** — ~20x. "This is a testament to..." is near-certain LLM
- **"vibrant"** — ~15x. Humans use it for colors; LLMs for communities/ecosystems
- **"foster"** — ~12x. "Foster collaboration/innovation/growth" is signature LLM
- **"intricate"** — ~10x. Used by LLMs for anything with more than two moving parts

### Tier 2 — Strong signals (5-10x)

- **"crucial," "pivotal," "essential"** — LLMs over-qualify importance
- **"landscape"** (non-geographic) — ~7x overrepresented
- **"meticulous"** — ~6x. "Meticulous attention to detail" is stock LLM
- **"underscore," "enhance," "bolster"** — ~5-6x each

### Tier 3 — Moderate signals (3-5x)

Only count when clustered (2+ in a single paragraph).

- **Filler verbs**: "leverage," "unlock," "navigate," "harness," "embark," "utilize," "facilitate," "streamline," "spearhead"
- **Generic nouns**: "ecosystem," "framework," "dynamic," "interplay," "synergy," "paradigm"
- **Dramatic openers**: "unleash the power of," "at the forefront of," "pave the way for," "bridging the gap between," "in the realm of"

### Era-specific notes

- **2023 (early GPT-4)**: "delve," "tapestry," "testament," "vibrant" at peak
- **2024 (GPT-4-turbo, Claude 3)**: "delve" drops ~60%. "Crucial," "landscape," "foster" remain strong
- **2025 (GPT-4o, Claude 3.5/4)**: Most mocked words suppressed. "Foster," "enhance," "streamline" persist. New tells: "straightforward," "robust," "seamless"
- **2026**: Watch for: "comprehensive," "walkthrough," "hands-on," "step-by-step" in contexts where humans would just write instructions

---

## 2. Structural Patterns

- **Rule of Three**: AI defaults to triplet groupings with unnatural consistency. Threshold: 3+ triplet lists in a document, or triplets in >50% of bullet lists
- **"Not X, but Y" constructions**: ~12x overrepresented vs human writing
- **False ranges**: "From intimate gatherings to global movements" — implies spectrum where none exists
- **Uniform sentence length**: CV < 0.25 across 5+ sentences is suspicious. Human prose typically CV > 0.35
- **Formulaic section structure**: Every section follows: topic sentence → 3 bullets → concluding sentence
- **Balanced pros/cons**: LLMs produce exactly equal numbers; humans are usually biased

---

## 3. Punctuation and Formatting

- **Em dash overuse**: LLMs use em dashes (—) at 3-5x human rate. Threshold: >2 per 500 words elevated, >4 per 500 words strong signal
- **Markdown in non-Markdown contexts**: Fenced code blocks or Markdown syntax in plain text
- **Overly clean formatting**: Perfect consistency in bullet styles, heading levels, whitespace throughout
- **Exclamation mark avoidance**: LLMs in "professional" mode almost never use them

---

## 4. Tone and Register

- **HR-speak friendliness**: "It's understandable that...," "Great question!," gentle summarizing endings
- **Hedging padding**: "It's worth noting," "it's important to remember," "one might argue." Threshold: 3+ per 500 words (human baseline: 0-1)
- **Overemphasis**: Everything is "fascinating," "captivating," "remarkable," "pivotal"
- **Emotional flatness**: Polished but objective; no humor, frustration, or personality
- **Compulsive revision, no improvisation**: Every sentence grammatically perfect, no rough edges
- **Uniform register**: Same formality for critical security patch and minor whitespace fix

---

## 5. Transitional Phrases

**High-signal** (rare in human tech/academic writing, common in LLM output):
- "Moreover," "Furthermore," "Additionally," "Indeed," "Notably," "Consequently," "Subsequently," "Accordingly," "Conversely"

**Medium-signal** (used by humans too, but at lower density):
- "It is worth noting," "In terms of," "With regard to," "In light of," "As such," "To that end," "In particular"

**Threshold**: >2 high-signal transitions per 500 words is suspicious. >4 is strong signal. Count only prose paragraphs.

**Not a signal**: "However," "For example," "That said," "In practice"

---

## 6. Technical/Academic Documentation Tells

- **"Correct but useless" descriptions**: Restating what code/data does without explaining why
- **Missing business context**: Only the "what" is documented, never the "why" behind decisions
- **Knowledge-cutoff disclaimers**: "as of" a certain date, "at the time of writing"
- **Suspiciously complete boilerplate**: Perfect docstrings that add nothing beyond the type signature
- **Artificially comprehensive scope**: Covers every possible sub-topic even when only one was asked about
- **Generic prose under standard headers**: Standard headers (Introduction, Methods, Results) are fine — the signal is in the prose underneath them

---

## 7. Model-Specific Opening Patterns

- **ChatGPT**: "As," "Sure," "Certainly," "Here," "Creating," "To," "Let's"
- **Claude**: "I'd," "Based," "Here," "This," "How," "Looking." "I'd be happy to help" is a strong signal
- **Gemini**: "Absolutely," "Great," "Here," "That's a great question"
- **General LLM**: Starting with a meta-statement about what the section will cover ("In this section, we explore...") rather than just starting the content

---

## Calibration Notes

### False positive risks
- No single indicator is conclusive
- Academic writing naturally uses many flagged transitions and structures
- Non-native English speakers may trigger vocabulary and structure tells
- Prior exposure to LLM output causes humans to unconsciously adopt its style

### Detection accuracy
- Heavy LLM users detect AI text ~90% of the time
- 3+ category convergence approach: ~85% precision, ~70% recall
- Drops to ~40% recall on style-prompted or heavily edited text

### Temporal drift
- Tells evolve as models update — what screams "AI" today may not tomorrow
- The strongest long-term signal is: uniform cadence + absence of genuine opinion + suspiciously complete coverage
