# Naming-validation protocol — the week-6 session script

**Purpose:** hand the device's name to braille readers — teach the mark, measure whether it works, and offer the rename pen. Implements the §1 naming rule (the mark is the name; the community holds naming authority) and answers the §11 open question (letter-mark vs non-letter signature). Runs inside the §7 week-6 usability pass — the reading tasks *are* the recall distractor. Section numbers refer to HAPTIC_COMPANION_PLAN.md.

**Status:** design research, not a claim set. n = 3–6 per session: directional, not statistical. The §9 no-clinical-claims rule applies everywhere, including the debrief and any follow-up. Publishable alongside the learnability protocol (§9 commits to publishing both).

**Length:** 45 minutes per participant. **Group:** 3–6 braille readers (recruit via HKNC regional reps / NFB chapters, per §9); mix daily and occasional readers and record which is which.

## 0 · Facilitator prep

- Communication access first: confirm each participant's preferred channel when scheduling (close vision, tactile sign, SSP support) and book an SSP/interpreter as needed. Participant-facing material exists in braille — embossed cards, braille consent form — not only in print.
- Hardware: prototype band loaded with the five marks (Ziv; Boaz; Razu; Buz; retired-Raz reference) — or the phone fallback, *haptic-name-marks.html* on Android Chrome (beat duration = 50 + 60 × dots ms, gap 420 ms — full timing spec: [HAPTIC_TIMING_SPEC.md](./HAPTIC_TIMING_SPEC.md)).
- Embossed braille cards: Z-I-V plus distractors Boaz / Razu / Buz. One logging sheet per participant.
- Quiet room, even lighting (many low-vision participants read close-vision).

## 1 · Welcome + consent (5 min)

Say, approximately: 'This device has no screen and no speaker, so its name is something you feel. A short vibration pattern plays when it starts up and before every message it sends on its own — it is how the device says who is talking. Today you will learn that pattern, tell us whether it works, and if it does not, you can help rename the device. This is not a medical or vision test — only the patterns are being tested. You can stop at any time.'

Consent: plain-language form (braille + large print); first name or initials only in all notes; recording only with separate explicit consent.

## 2 · Teach the mark (7 min)

The order is deliberate — braille first, rhythm second — so the mark anchors to a literacy the participant already owns:

1. Hand over the embossed Z-I-V card: 'Read this word.' Wait until they finish.
2. Play the mark once: 'That is the same word — Z, I, V. One buzz per cell, left to right; more dots means a longer buzz.'
3. Play it again, tapping their palm once per beat: 'Z… I… V.'
4. Hand over control: self-paced replays, minimum 5 exposures, stop at 10 or when they say 'got it'. **Log exposures-to-got-it** (working gate: median ≤ 5).

## 3 · Measure (15 min)

| # | Measure | How | Working pass line |
|---|---|---|---|
| M1 | Immediate recognition | 8 rounds, random order: the mark or a distractor (Boaz / Razu / Buz arc / attention patterns). 'Name, or not name?' Log seconds-to-answer. | ≥ 80% correct |
| M2 | Delayed recall | 4 options played once, after the §7 reading blocks: 'Which one is the device's name?' | ≥ 70% |
| M3 | Distinct from content | Confusions between the mark and the attention vocabulary (double-tap = new message, triple-pulse = reminder fired, long buzz = error), from M1 errors plus one direct question | zero confusions |
| M4 | Identity read | 'Did that feel like someone calling you, or like a message?' and 'Two of these devices in a room — would you know who is calling?' | majority describe identity, not content |

M3 + M4 answer the §11 question directly: if the mark reads as *content* or collides with the attention vocabulary, the fallback is a pure-rhythm signature that encodes no letters — the word then lives only on the box and the page.

## 4 · The word check (5 min, secondary)

- **Braille agreement:** 'Spell the name I just played.' Can a braille reader get Z-I-V back from the rhythm alone? The word on the box and the mark on the wrist should teach each other.
- **Sayability:** show the word Ziv in print and braille: 'Say it out loud. Could you tell a friend about this device?' Sighted-hearing buyers — family, caregivers, AT programs — will say this word daily.

## 5 · The rename conversation (10 min) — the community holds the pen

Open: 'The name is not ours to keep. In DeafBlind communities, name marks are given, not declared. Three options: A, keep it. B, keep the pattern and change the word. C, change both.'

- **A — keep:** Ziv and its mark, done.
- **B — new word, same mark:** any word whose letters spell to the heavy-light-heavy arc; check legal cleanliness first (the §1 ten-name sweep method) and braille agreement always. Pre-validated arc matches live in the timing spec's `rename_examples` ([HAPTIC_TIMING_SPEC.md](./HAPTIC_TIMING_SPEC.md)); the phone fallback's **Spell any word** box plays any candidate live so the room can feel option B before voting.
- **C — new mark and word:** pick a distractor arc from the cards or propose any rhythm; the facilitator plays any 3–5-letter spelling live on the band — or any word at all via the Spell any word box on the phone fallback.

Capture every preference and reason verbatim. **No vote in the room.** Across sessions: adopt an alternative only when a clear majority converges on the same one *and* it re-passes M1–M4; otherwise Ziv remains the working title and the question stays open. Any adopted rename is recorded in §1/§4 of the plan and the CHANGELOG — dated and attributed to the sessions, never to a founder.

## 6 · Debrief + close (5 min)

'What would you name it? What should we have asked and did not?' Record verbatim. Thank-you; compensation per the host chapter's norm [TBD per host org]; offer a follow-up contact.

## Data & ethics

- First names/initials only; notes under docs/sessions/ keyed by participant ID; recordings only with separate consent; deleted on request.
- n = 3–6 per group: this protocol catches obvious failure and hands over naming authority; it does not prove efficacy, and nothing it produces may be phrased as a clinical or efficacy claim (§9).
- Participants are told up front that results shape a hackathon prototype.

## Materials checklist

- Band charged, five marks loaded; fallback phone with *haptic-name-marks.html* — the page now also carries the attention vocabulary, an M1 session mode (8 randomized mark-vs-distractor rounds, tap-to-answer, per-round reaction times, downloadable CSV results), a blind A/B mode for arc recognition, and a spell-any-word box (full 26-letter vibro-braille + rename-candidate fills) for the §5 rename conversation
- Embossed cards: Z-I-V + Boaz / Razu / Buz; braille consent form + large-print copy
- Logging sheets (exposures, M1–M4, rename preference, verbatims); this script printed
- SSP/interpreter confirmed; quiet room, even lighting; compensation per host org
