/** Flavour text for the "Agent …" indicator while a turn is in flight.
 *
 * Present participles, so each drops into the same slot "working" occupied.
 * Drawn from what ALFRED actually does: composing prose, typesetting the paper,
 * working the literature, analysing data, and checking claims.
 *
 * Deliberately excludes anything that reads as a regression or a loss —
 * "regressing" is a fine statistics pun and a terrible status line, because
 * "Agent regressing" reads as the agent getting worse at its job.
 */
export const AGENT_VERBS = [
  // Composing
  'drafting',
  'composing',
  'penning',
  'wordsmithing',
  'redrafting',
  'revising',
  'rephrasing',
  'burnishing',
  // Typesetting
  'typesetting',
  'kerning',
  'paginating',
  'justifying',
  'copyediting',
  'proofing',
  'footnoting',
  // Literature
  'surveying',
  'combing',
  'sifting',
  'canvassing',
  'cataloging',
  'indexing',
  'citing',
  'annotating',
  // Analysis
  'tabulating',
  'computing',
  'extrapolating',
  'plotting',
  'correlating',
  'quantifying',
  'modeling',
  'triangulating',
  // Verification
  'corroborating',
  'scrutinizing',
  'adjudicating',
  'vetting',
  'interrogating',
  // Deliberation
  'synthesizing',
  'ruminating',
  'cogitating',
  'collating',
] as const

/**
 * Pick a verb from a seed.
 *
 * Pure, so the caller controls exactly when a new word is drawn. That matters:
 * the indicator re-renders while a turn runs, so choosing during render would
 * reshuffle the word continuously instead of once a turn. TerminalChat calls
 * this once on the turn's leading edge and holds the result for its duration.
 *
 * The seeds of consecutive turns are near-adjacent integers, which a plain
 * modulo would map to adjacent list entries and march through the list in
 * order. Hashing first scatters them.
 */
export function agentVerb(seed: number | null | undefined): string {
  let h = (seed ?? 0) | 0
  h = Math.imul(h ^ (h >>> 15), 0x2c1b3c6d)
  h = Math.imul(h ^ (h >>> 12), 0x297a2d39)
  h ^= h >>> 15
  // >>> 0 rather than Math.abs: the hash can land on -2^31, whose absolute
  // value is not representable as a positive int32 and stays negative.
  return AGENT_VERBS[(h >>> 0) % AGENT_VERBS.length]
}
