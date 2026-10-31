# Community tooling — setup notes

One-time setup to run on GitHub when this branch lands on `main`. Everything
below is clicks in the web UI; the files in this branch provide the places
those clicks point to.

## 1. Enable Discussions

Settings → **General** → Features → check **Discussions**.

Then create these categories under Settings → Discussions (keep the default
categories named General and Announcements, add the three below):

| Category                    | Type         | What belongs here                                            |
|-----------------------------|--------------|--------------------------------------------------------------|
| Tried it — experiences      | Q&A          | What you felt or saw after trying the feel-tool or demo. The same content works as an issue too; Discussions if no filing, issue if you want it tracked. |
| Design questions            | Ideas        | The open design questions in the README's "Try it / Talk to us" section — timings, hardware, naming, audience. |
| Speculations and thoughts   | Ideas        | "Have you considered…" threads. Not a task list.            |

Prefer **Q&A** for the first category so answers can be accepted; prefer
**Ideas** for the two design categories so threads don't force a single
answer.

## 2. Pin a welcome discussion

New Discussion → _Pinned category (or Announcements)_. Title:
**What Ziv is — and what feedback we're asking for.** Body: link the
[feel-tool](https://site-5505fea77ec84b4f8e1a5d70c82d5877.freebuff.page) and
the [76 s demo](https://youtu.be/t9ovgEjm8i8), then list the concrete open
questions. Two honesty rules to keep from the repo docs: nothing here is yet
validated with deaf-blind readers (feedback on *experience*, not predictions),
and this repository is the hackathon submission artifact — it is not an
active open-source project, so questions go here rather than drive-by PRs
([CONTRIBUTING.md](../CONTRIBUTING.md) already says the commit rules).

## 3. Feedback route for non-GitHub visitors

Community members who found the project via Devpost or a shared link and
don't have a GitHub account can file the same kind of report by posting in
the *Tried it — experiences* category — no issue needed. Link them straight
to the Discussions tab in the Devpost description.

## 4. What already exists in this branch

- `.github/ISSUE_TEMPLATE/config.yml` — hides the blank-issue form, offers
  the "Tried it — feedback report" template, and routes questions/ideas to
  Discussions with the feel-tool and demo links surfaced in the chooser.
- `.github/ISSUE_TEMPLATE/feel-tool-feedback.yml` — the structured report
  form (entry point, platform incl. visual-only browsers, close/pacing
  answers, one-change question, device).
- The new near-top README section ("Try it / Talk to us") — the two
  one-click entry points above the fold.

## 5. After enabling

- Verify [this Discussions link](https://github.com/razukc/ziv/discussions)
  resolves (the config.yml and README links point at it).
- Verify the issue chooser at
  [new issue](https://github.com/razukc/ziv/issues/new/choose) shows the
  "Tried it" form and the three contact links, and the blank form is hidden.
- File no test issue — open the pinned welcome discussion instead and close
  the loop by posting the first real update when the first feedback lands.
