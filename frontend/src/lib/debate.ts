/**
 * Debate transcripts. Live runs stream one `debate` event per turn; finished
 * runs (or a missed stream) only have the transcript text stored on RunOut,
 * which the agent core writes as "\nBull Analyst: ...\nBear Analyst: ...".
 */

export type DebateSide = 'bull' | 'bear' | 'aggressive' | 'conservative' | 'neutral' | 'judge' | 'other'

export interface DebateTurn {
  speaker: string
  side: DebateSide
  content: string
}

// Speaker names may come in English or Chinese; the CJK alternatives below are
// match patterns for agent output, not UI text.
const SIDE_PATTERNS: ReadonlyArray<[DebateSide, RegExp]> = [
  ['bull', /bull|多/i],
  ['bear', /bear|空/i],
  ['aggressive', /aggressive|risky|激进/i],
  ['conservative', /conservative|safe|保守/i],
  ['neutral', /neutral|中立/i],
  ['judge', /judge|manager|经理/i],
]

export function speakerSide(speaker: string): DebateSide {
  for (const [side, re] of SIDE_PATTERNS) if (re.test(speaker)) return side
  return 'other'
}

const SPEAKERS =
  'Bull Analyst|Bear Analyst|Bull Researcher|Bear Researcher|Aggressive Analyst|Risky Analyst|Conservative Analyst|Safe Analyst|Neutral Analyst'
const SPEAKER_RE = new RegExp(`^(${SPEAKERS})\\s*[:：]\\s*`, 'gm')
const LEADING_SPEAKER_RE = new RegExp(`^\\s*(${SPEAKERS})\\s*[:：]\\s*`)

/** Drop the "Bull Analyst:" prefix agents put on each turn (the bubble already names the speaker). */
export function stripSpeaker(content: string): string {
  return content.replace(LEADING_SPEAKER_RE, '')
}

/** Split a stored transcript into turns by its "Speaker:" prefixes. */
export function parseDebate(text: string | null | undefined): DebateTurn[] {
  if (!text?.trim()) return []
  const matches = [...text.matchAll(SPEAKER_RE)]
  if (matches.length === 0) return [{ speaker: '', side: 'other', content: text.trim() }]

  const turns: DebateTurn[] = []
  matches.forEach((m, i) => {
    const start = (m.index ?? 0) + m[0].length
    const end = i + 1 < matches.length ? (matches[i + 1]?.index ?? text.length) : text.length
    const content = text.slice(start, end).trim()
    const speaker = m[1] ?? ''
    if (content) turns.push({ speaker, side: speakerSide(speaker), content })
  })
  return turns
}
