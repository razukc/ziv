# Community tooling — setup notes

One-time setup to run on GitHub when this branch lands on `main`. Everything
below is clicks in the web UI; the files in this branch provide the places
those clicks point to.

## 1. Enable Discussions

Done from the UI (Settings → **General** → Features → **Discussions**). The
API cannot create or edit categories — the GraphQL schema exposes only
`createDiscussion`/`updateDiscussion`, not `createDiscussionCategory` — so
categories are UI-only, which is why the create-a-category control feels
hard to find. The exact path:

**Discussions tab → left sidebar, to the right of the "Categories" heading →
the category icon → New category.** Set emoji, title, description and the
discussion format (open-ended / Q&A / announcement), then Create.

**Done.** With the six defaults GitHub seeded (Announcements, General, Ideas,
Polls, Q&A, Show and tell), create two purpose-built categories and reuse
one default:

| Category                | Format | What belongs here                                            |
|-------------------------|--------|----------------------------------------------------------------|
| Tried it — experiences  | Q&A    | What you felt or saw after trying the feel-tool or demo — first-hand reports, not predictions. The same content works as an issue too; Discussions if no filing, issue if you want it tracked. |
| Design questions        | Ideas  | The open design questions in the README's "Try it / Talk to us" section — timings, hardware, naming, audience. |
| Ideas (default, keep)   | Ideas  | "Have you considered…" threads — the default Ideas category already serves the speculations stream. |

Prefer the **Q&A** format for the first category so answers can be accepted;
Ideas format for the design categories so threads don't force a single
answer. Polls and Show and tell are not needed for this phase — delete the
ones you don't want via the category list (deleting asks where to move its
discussions, so nothing is lost).

## 2. Pin a welcome discussion

**Done.** [#1 — What Ziv is — and what feedback we are asking for](
https://github.com/razukc/ziv/discussions/1) is live **and pinned** in
Announcements, with the feel-tool and demo links, the two open design
questions, and both honesty rules — feedback on *experience*, not
predictions, and questions here rather than drive-by PRs
([CONTRIBUTING.md](https://github.com/razukc/ziv/blob/main/CONTRIBUTING.md)).

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
