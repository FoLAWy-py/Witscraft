# Target-Player HCI Participant Study

**Status:** Protocol ready; participant results pending

This protocol validates whether target players—not authors or developers—can understand and control Witscraft as an AI-authored interactive novel. Expert review and automated checks cannot satisfy this gate, and no participant result may be inferred or fabricated.

## Participants and ethics

Recruit at least five adults who read fiction and have used at least one interactive story, narrative game, or conversational AI product. Exclude current Witscraft contributors and anyone who has seen the task script. Record only a random participant code, broad prior-experience band, task metrics, ratings, and observation notes.

Before the session, explain that the build is experimental, AI output may be unexpected, participation is voluntary, the participant may stop at any time, and no sensitive personal information or private writing should be entered. Obtain explicit consent for observation and screen/audio recording separately. If recording is declined, use timestamped facilitator notes. Store consent separately from study data and follow `docs/data-privacy.md` for deletion and retention.

## Environment

Use the isolated LAN staging candidate described in `docs/staging-release-candidate.md`, a synthetic test account, and a clean browser profile at a supported desktop or mobile viewport. Trust only the staging certificate on the test device. Confirm readiness immediately before each session. Do not use the public deployment, recovered user data, or participant-owned reference text.

The facilitator must not teach the interface. Use the neutral prompt “Please continue as you normally would” when the participant pauses. Assistance beyond that is recorded as a task error.

## Task script

1. Sign in and identify what the product lets the player do.
2. Create a new interactive novel with a chosen premise, 3–120 planned chapters, and a preferred chapter-development minimum. Leave reference text collapsed.
3. Enter the opening scene and explain whose decisions the AI may make.
4. Submit one explicit protagonist action and identify what changed in the story.
5. Use **Continue**, then explain how its authority differs from a normal action.
6. Choose a suggested option, then use the custom-action path.
7. Cancel a generation or respond to a staged recoverable provider failure; confirm whether accepted prose was preserved and identify the recovery action.
8. Regenerate or rewrite a turn, create a branch, switch branches, and identify which events remain true on each branch.
9. Find the current chapter and explain whether reaching the displayed minimum forces a chapter ending.
10. Find weekly AI usage and explain what the percentage covers without seeing raw token counts.

The facilitator records task start/end, success without help, recoverable and unrecoverable errors, requests for help, backtracking, authority-boundary statements, and notable confusion. Do not interpret literary preference as an interface error unless it prevents a decision or recovery.

## Measures

Primary measures:

- critical-task completion rate across tasks 2–7;
- median time from sign-in to visible first scene;
- error rate per critical task;
- number of authority-boundary misunderstandings;
- successful recovery after cancel/provider failure;
- post-task confidence from 1 (not confident) to 5 (fully confident);
- System Usability Scale (SUS) using the standard ten alternating items.

For SUS, subtract 1 from each odd-item response, subtract each even-item response from 5, sum the ten contributions, and multiply by 2.5. Report individual scores, median, range, and arithmetic mean. Do not remove an unfavorable valid session. Mark missing or interrupted questionnaires explicitly rather than imputing values.

Secondary observations map to the weighted HCI principles in `docs/hci-evaluation.md`: visibility and feedback, player mental-model match, control and freedom, error prevention, accessibility, AI trust, consistency, recovery, recognition, reading focus, flexibility, and onboarding.

## Acceptance criteria

The participant gate passes only when all of the following are true:

- at least five valid target-player sessions are complete;
- critical-task completion is at least 90%;
- median first-scene entry is under three minutes;
- no participant believes the AI may make protagonist decisions on a normal action turn;
- every participant can explain that Continue delegates only the current turn;
- recoverable failure/cancel recovery succeeds in at least 90% of attempts;
- median post-task confidence is at least 4/5;
- mean SUS is at least 80;
- no severity 0 or 1 issue remains open.

A failed criterion produces a versioned issue list and another participant round after remediation. The same participant may verify a specific fix, but a full gate rerun should include at least three people who did not take part in the failed round.

## Evidence template

Store a sanitized, versioned report under `docs/evidence/` containing the tested Git revision, staging candidate schema, session dates, device/viewport classes, aggregate task metrics, de-identified per-participant SUS scores, severity-ranked findings, remediation decisions, and protocol deviations. Never include names, email addresses, raw story prose, recordings, IP addresses, cookies, provider prompts, or credentials.
