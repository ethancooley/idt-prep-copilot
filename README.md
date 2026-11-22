# IDT Prep Copilot

**Know what changed before the IDT meeting.**

IDT Prep Copilot gets PACE care teams ready for their interdisciplinary team meetings. For each
participant up for review, it reads everything in the chart since the last review, writes a one-page brief of
what changed and what the team should discuss, and links every line to the note it came from. A clinician
checks each line and approves the brief before the meeting.

**[Try it at idt.ethancooley.com](https://idt.ethancooley.com)**

<!-- Add a 30-second screen recording of a live run here, e.g. docs/images/live-run.gif -->

> Every participant in this project is synthetic. No real patient data is used anywhere.

## The problem

PACE (Program of All-Inclusive Care for the Elderly) cares for older adults who could qualify for a nursing
home but still live in their community. One interdisciplinary team covers everything for each person: the
physician, nurses, therapists, social workers, dietitians, day center staff, and home care aides. That team
has to reassess every participant at least every six months, and more often when their condition changes.

Getting ready for each of those reviews means reading every note written since the last one, by every
discipline. Months of notes, for every participant on the agenda. It's slow, and it's easy to miss things: a
fall mentioned only in an aide's note, weight slipping across a few vitals checks, a caregiver who has stopped
coping. Then the team spends meeting time rebuilding the picture when it could be spent deciding what to do.

## What it does

For each participant due for review, IDT Prep Copilot:

- **Reads the whole chart for the review period**: notes from every discipline, vitals, ED visits and hospital
  stays, medication changes, and immunizations
- **Writes a one-page brief**: a headline, then each change or concern, ranked high, medium, or low, plus
  questions for the team to settle
- **Cites its source for every line.** Click any citation to read the note it came from, with the relevant
  sentences highlighted
- **Leaves the decision to a clinician**, who approves, edits, or rejects each line, then approves the brief.
  Every decision is logged, and the approved brief exports as a PDF for the meeting

## Why a team can trust it

A wrong brief is worse than no brief, so the product is designed around five rules.

1. **No line without a source.** Every line must point to the note or record that supports it.
2. **A second check on every line.** Before anyone sees the brief, a separate pass reads each line next to
   only the sources it cites. Lines the sources don't support are removed and listed for audit, never shown
   as fact.
3. **It reads, it never writes.** The agent can only look things up, and only in the chart of the participant
   it's working on.
4. **A clinician makes the final call.** Nothing reaches the team until a person has approved it.
5. **Nothing is hidden.** For every brief you can see the chart it read, replay each step it took, and see how
   much it cost.

## How it works

Two Claude models share the work, coordinated as an agent:

| Step | What happens | Who does it |
| --- | --- | --- |
| Plan | Reads who the participant is and writes a checklist of what to look for | Claude Haiku, a fast and inexpensive model |
| Read the chart | Looks up the chart one piece at a time: notes, vitals, encounters, medications. Code makes sure the essential lookups always happen | Claude Haiku |
| Write | Drafts the brief from what it found, citing a source for every line | Claude Sonnet, a stronger model |
| Check | Checks each line against its sources. If any fail, the agent goes back to the chart once for evidence and rewrites | Code and Claude Sonnet |
| Approve | Reviews, edits, and approves the brief | A clinician |

On the demo site, every participant's page walks through four steps: **the chart** the agent read, **what
the agent did** (a replay of every step), **the brief** it wrote, and **the answer key** it was graded
against. With an access code, you can also watch the agent build a new brief live, one step at a time.

## How well it works

Every synthetic participant was generated with planted events (a fall, an ED visit, weight loss, new
confusion, a missed flu vaccine) and an **answer key** recording exactly what a good brief must catch. Some
charts also include an older event from before the review period, which the brief should leave out because
the team already discussed it. The agent never sees the key.

Scoring is strict. A brief only gets credit for an event when one of its lines **cites a note that proves
it**, so a line that just sounds right doesn't count.

Across 40 participants:

| | First run | After fixing the prompt |
| --- | --- | --- |
| Planted events caught | 94.7% | 100% |
| High-severity events caught | 100% | 100% |
| Briefs that caught everything | 32 of 40 | 40 of 40 |
| Older events reported as new | 3 | 0 |
| Lines not tied to a planted event | 12.2% | 1.0% |
| Cost per brief | $0.049 | $0.041 |
| Time per brief (median) | 36 s | 35 s |

The first run found two patterns: the agent treated a missing flu vaccine as routine, and it mentioned older
events as background. A two-line change to the instructions fixed both without hurting anything else. The
full reports are in [evals/reports](evals/reports).

**Being honest about the numbers:** the instructions were tuned on these same 40 participants. The next
step is scoring a fresh set of charts the agent has never seen.

## What it isn't

- **Not tested on real charts.** Real notes are messier, longer, and more varied than these synthetic ones.
- **Not a medical device,** and not a substitute for clinical judgment. It prepares a draft for a clinician.
- **Not connected to an EHR.** A real deployment would read from the PACE organization's records system and
  keep the review log on a server, not in the browser.

## How it's built

I built every layer, from the data to the interface:

| Layer | What it is | Built with |
| --- | --- | --- |
| Data | EHR-style records for each participant: notes from every discipline, vitals, ED visits and hospital stays, medications, immunizations | Postgres, pgvector, Synthea plus a custom generator for notes and answer keys |
| Tools | Read-only lookups into one participant's chart, with keyword and semantic search over notes | Model Context Protocol (MCP) server in Python |
| Agent | Plans, gathers, drafts, and verifies, going back to the chart once when a claim fails | LangGraph, Claude Haiku and Claude Sonnet via the Anthropic API, with prompt caching and structured tool outputs |
| Evaluation | Scores every brief against planted answer keys: recall, high-severity recall, old events reported as new, unsupported lines, cost, latency | Python eval harness, rerunnable in CI on saved briefs |
| Interface | Review queue, cited brief with evidence pane, line-by-line approval, audit log, PDF export, and a live view of the agent working | React, TypeScript, Vite |
| Infrastructure | Static site, a streaming API for live runs gated by an access code and daily limits, secrets kept out of code | AWS (CloudFront, S3, Lambda, Parameter Store) defined as infrastructure as code, GitHub Actions for testing and deployment on every push |

## For developers

How it's built, how to run it, and how to deploy your own copy: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)
and [deploy/README.md](deploy/README.md).

## About

Built by [Ethan Cooley](https://ethancooley.com), a machine learning engineer working on AI for clinical
decision-making. Want an access code to watch the agent work live, or have questions? Reach out through
[ethancooley.com](https://ethancooley.com).
