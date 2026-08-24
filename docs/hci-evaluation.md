# Human–Computer Interaction Evaluation

Witscraft treats HCI as an independent product-quality workflow. Functional tests prove that the system works; this workflow evaluates whether a player can understand, control, and recover from an AI-authored interactive novel without learning internal model or authoring terminology.

The method combines ISO 9241-210 human-centred design, Nielsen-style heuristic review, and WCAG 2.2 accessibility checks. The current references are [ISO 9241-210:2019](https://www.iso.org/standard/77520.html), the [Nielsen Norman Group heuristic workbook](https://media.nngroup.com/media/articles/attachments/Heuristic_Evaluation_Workbook_-_Nielsen_Norman_Group.pdf), and [WCAG 2.2](https://www.w3.org/TR/WCAG22/).

## Scoring rubric

Each dimension is rated from 0 to 4:

- `0` — absent, misleading, or blocks the core task;
- `1` — major recurring usability failure;
- `2` — usable with avoidable confusion or effort;
- `3` — clear and reliable for the intended audience;
- `4` — excellent, validated, and consistently applied.

The weighted score is `sum(rating / 4 × weight)`. Weights total 100.

| Dimension | Weight | Witscraft interpretation |
| --- | ---: | --- |
| Visibility and feedback | 10 | Generation, saving, quota, chapter transitions, and failure states are timely and understandable. |
| Match to the player's mental model | 10 | The product speaks in novels, scenes, characters, choices, and consequences—not model-routing or writing-workbench concepts. |
| Control and freedom | 10 | The player controls protagonist decisions; Continue grants AI authority only for that turn; regenerate, rewrite, branch, and cancel remain recoverable. |
| Error prevention | 10 | Destructive and canon-changing actions explain impact; invalid or impossible actions fail with a useful reason. |
| Accessibility | 10 | Keyboard, focus, labels, contrast, target size, responsive reflow, reduced motion, and status announcements meet the WCAG 2.2 AA intent. |
| AI trust and transparency | 10 | AI authority, uncertainty, truncation recovery, chapter decisions, and simulated versus real-provider behavior are not disguised. |
| Consistency and standards | 8 | Labels, icons, navigation, feedback, and interaction patterns remain consistent across creation, reading, and settings. |
| Recovery and resilience | 8 | Provider, stream, network, sync, and validation failures preserve work and offer an appropriate next action. |
| Recognition over recall | 7 | Current story, chapter, scene, choices, and available actions remain visible without requiring memory. |
| Reading focus and minimalism | 7 | Prose and the next player decision dominate; diagnostics and advanced tools use progressive disclosure. |
| Flexibility and efficiency | 5 | Suggested choices, free input, Continue, keyboard operation, and advanced editing serve different play styles. |
| Help and onboarding | 5 | Creation and first-scene entry explain the next step in context without a separate manual. |

An expert-review release gate requires an overall score of at least 85, every 10-point core dimension at least 3, all critical task scenarios to pass, and no severity 0 or 1 issue. Passing this gate does not replace participant research.

## Issue severity

- `0 blocker` — prevents a critical task, loses work, or creates unsafe AI authority.
- `1 severe` — likely to cause abandonment, an unintended story fact, or an unrecoverable mistake.
- `2 material` — creates recurring confusion, delay, or unnecessary cognitive load.
- `3 cosmetic` — noticeable polish issue with no meaningful task impact.

## Required scenarios

The deterministic expert walkthrough covers sign-in; first-story creation; first-scene entry; explicit player action; Continue; choice selection; custom choice; regeneration; rewrite; branch creation and switching; provider/stream recovery; chapter transition feedback; quota comprehension; and desktop/mobile navigation. Browser evidence must use the local application and deterministic data. Provider quality is evaluated separately with the approved live-provider capture workflow.

Participant validation is a separate gate: at least five target players, scenario completion and error rate, first-scene time-on-task, a post-task confidence question, and SUS. Results must never be inferred from expert review. The target is at least 90% critical-task completion, median first-scene entry under three minutes, no authority-boundary misunderstanding, and SUS at least 80.

## Current review

The versioned evidence is in `docs/evidence/hci-review-2026-08-24.json`. The first expert baseline scored 60.88. The revised expert pass scores 85.25 after making first-scene entry explicit, moving model routing out of the reading header, binding the visible world model to the current novel, collapsing optional style-reference input and advanced inspector data, aligning the product logo with the favicon, and verifying the core path at desktop and 390×844 mobile viewports.

Participant validation remains intentionally pending and must be run with real target users before claiming human-subject usability validation. The approved recruitment, facilitator, task, SUS, privacy, and acceptance protocol is defined in `docs/hci-participant-study.md`.
