# Announcement drafts

Two ready-to-paste copies for the post-submission community push. Both point
at the same three entry points — the feel-tool, the demo, and the feedback
form — and both carry the asking rule. Post the long one on Devpost (project
updates are open there after submission), the short one in the hackathon
Discord.

These resolve for anyone signed into GitHub *once Discussions is enabled
(see [COMMUNITY_SETUP.md](COMMUNITY_SETUP.md))* only for the Discussions link
mentions; the issue-chooser link (`/issues/new/choose`) works as soon as the
issue templates from this branch are merged to `main`. The short version does
not depend on Discussions at all — it can be posted today.

## Long version — Devpost / project update

---

**Ziv needs your fingers, not just your eyeballs — feedback requested**

Ziv is our hackathon submission: a haptic message channel. An open NVIDIA
model writes the line; your Android phone plays it as vibro-braille you feel —
no audio, no spoken reply, no scrolling. Every turn is framed by an attention
vocabulary: an arrival cue, working ticks, Grade-1 braille cells, and a
descending close so "message over" is *felt*, not guessed from silence. If
the queue is busy, the next message waits politely instead of barging in; a
full queue answers the sender with a loud 429. All of it is proven in tests
and a live repro — [JUDGE_REPRO.md](https://github.com/razukc/ziv/blob/main/JUDGE_REPRO.md)
maps every claim to its proof.

**Try it first (no install, no key):**

- 🤲 The **feel-tool** — plays the timing vocabulary, name marks and any word
  you spell. Android Chrome vibrates; desktop/iOS show the rhythm visually:
  https://site-5505fea77ec84b4f8e1a5d70c82d5877.freebuff.page
- 🎬 The **76-second demo** — the whole loop on the phone: scheduled intent →
  model-written line → gate → queue → close: https://youtu.be/t9ovgEjm8i8

**Two design questions we're actively deciding on — tell us:**

1. The close (200→140→90→50 ms buzzes): did it land as "this message is
   over," or just as quiet?
2. Letter pacing (530–770 ms per character): bearable, dragging, or rushed?

**Where to reply:** questions and ideas →
[Discussions](https://github.com/razukc/ziv/discussions). A proper "Tried it"
report → the structured issue form at
https://github.com/razukc/ziv/issues/new/choose.

**One asking rule:** describe what *you* actually felt or saw — not what you
predict "users" would feel. Nothing here is validated with deaf-blind readers
yet; first-hand experience beats speculation, and it's the input we can
actually act on. The repo is the submission artifact, not an active
open-source project — so questions, not drive-by PRs. Thank you 🙏

---

## Short version — Discord

---

**Ziv — feedback requested 🤲** Messages you can *feel*: our hackathon build
turns what an open model writes into vibro-braille on your Android phone —
no audio, no spoken reply, and messages that queue politely instead of
barging in. **Try it in one click, no install:** the feel-tool plays the
timing vocabulary, name marks and any word you spell (Android Chrome
vibrates; desktop/iOS show visual rhythm only) →
https://site-5505fea77ec84b4f8e1a5d70c82d5877.freebuff.page · 76-second
demo: https://youtu.be/t9ovgEjm8i8

Two things we're actively deciding — after trying it, please tell us:
**1)** does the ending close (200→140→90→50 ms) *feel* like "message over",
or just quiet? **2)** at 530–770 ms per letter, does the spelling pace read
as bearable, dragging or rushed? Drop your experience in the "Tried it —
feedback report" form → https://github.com/razukc/ziv/issues/new/choose
(and describe what *you* felt, not what you predict "users" would —
first-hand reports are the ones we can act on).

---

Tuning notes: the links first, numbers in the questions so answers stay
actionable, and the honesty rule framed as an asking rule rather than a
disclaimer. People without a GitHub account are invited to reply in-thread;
transcribe anything useful into the same "Tried it" form yourself.
