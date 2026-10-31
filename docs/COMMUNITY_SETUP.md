# Community tooling — setup notes

Setup is complete — this file is kept as the record of what was done and
where each piece lives. Everything below was executed between the
community-tooling merge and the templates landing on `main`:

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

## 4. What landed on `main` with the merge

- `.github/ISSUE_TEMPLATE/config.yml` — hides the blank-issue form, offers
  the "Tried it — feedback report" template, and routes questions/ideas to
  Discussions with the feel-tool and demo links surfaced in the chooser.
- `.github/ISSUE_TEMPLATE/feel-tool-feedback.yml` — the structured report
  form (entry point, platform incl. visual-only browsers, close/pacing
  answers, one-change question, device).
- The new near-top README section ("Try it / Talk to us") — the two
  one-click entry points above the fold.

## 5. Post-merge checks already verified via API

- The Discussions route resolves — welcome post
  [#1](https://github.com/razukc/ziv/discussions/1) is the pinned
  announcement, and the two purpose-built categories exist with the intended
  formats (`isAnswerable`: Tried it — experiences true, Design questions
  false).
- Both template files are served from `origin/main` and the served
  `config.yml` parses with `blank_issues_enabled: False` and the three
  contact links. The one check left to human eyes: open the issue chooser
  signed-in and confirm the "Tried it" form card renders as intended.
- File no test issue — post the announcement drafts first, and close the
  loop by replying to community feedback on the category it belongs in.
