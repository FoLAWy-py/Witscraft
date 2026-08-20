# Interactive Fiction Product Contract

**Status:** Approved implementation baseline

**Last updated:** 21 August 2026

## 1. Product Boundary

Witscraft is a player-led interactive novel. The AI is the author and narrator; the user plays the protagonist and determines the plot through actions and choices. It is not an authoring workbench and does not assume that the user wants to draft or edit prose manually.

The system may describe the world, supporting characters, consequences, and information that the protagonist can perceive. It must preserve player authority over the protagonist unless the player deliberately delegates that authority for one turn.

## 2. Player Agency

### 2.1 Default turns

On a normal action or selected choice, the AI must not invent consequential speech, decisions, commitments, or private thoughts for the protagonist. It may narrate involuntary perception and immediate physical reaction when those details do not imply a choice.

A submitted action is an attempted intent, not a guaranteed fact. The world model determines the outcome. Once resolved, the attempt and its observable consequences become story history; an option label alone never becomes canon before resolution.

### 2.2 Continue delegation

Selecting **Continue** grants the AI authority over the protagonist for exactly one narrative turn. During that turn, the AI may choose ordinary speech, thoughts, and actions that are consistent with established characterization and the current objective. The delegation ends when the response completes and must not carry into the next turn.

Even under delegation, the AI must stop before an avoidable irreversible commitment, identity-defining decision, major relationship commitment, permanent sacrifice, or branch-ending choice. It should end the chapter at that decision point and return control to the player.

### 2.3 Invalid actions

An action that is impossible under established facts or violates an explicit world rule must be rejected before narrative generation. The rejection must:

- identify the conflicting fact or rule in player-facing language;
- avoid adding the attempted action to canon or advancing the chapter;
- preserve weekly allowance by using deterministic validation where the conflict is already known; and
- offer feasible alternatives when they can be derived without changing the player's intent.

Plausible but difficult actions are not invalid. They should produce uncertain, partial, costly, or failed outcomes inside the narrative.

## 3. Chapter Model

Each successful narrative turn produces one titled novel chapter and then returns control to the player. Story creation requires a planned chapter count from 3 through 120, with 12 as the default.

The player selects a target length for each chapter:

| Preset | Target |
| --- | ---: |
| Concise | 800 |
| Standard | 1,800 |
| Detailed | 3,000 |
| Custom | 500–5,000 |

For Chinese, Japanese, and Korean prose, the target unit is visible characters after whitespace normalization. For whitespace-delimited languages, the target unit is words. The generation acceptance band is ±15%. UI copy must name the active unit; token estimates remain an internal cost-control concern and are not presented as exact prose length.

A normal chapter should resolve one meaningful scene movement and establish the next decision. It may advance minutes or hours. Longer travel, recovery, training, or waiting may be summarized only when the player's instruction or **Continue** delegation makes that transition reasonable. It must not skip an unresolved high-stakes decision or compress multiple irreversible events into one turn.

## 4. Roadmap and Endings

Story creation generates a branch-local roadmap containing all planned chapter numbers, provisional chapter titles, provisional objectives, and at least one provisional ending title. Future titles and objectives are planning aids and are hidden behind a spoiler control by default.

Completed chapters are immutable history on their branch. The active and future roadmap is revised after each accepted chapter to reflect player choices, established facts, unresolved threads, and remaining chapter budget. Revisions must not silently change the configured chapter count.

The player may change the planned count while the story is active, provided that the new value is between the number of completed chapters and 120 and never below 3. A branch normally reaches its ending in the configured final chapter. An earlier terminal failure is allowed only as a fair consequence of an established, irreversible risk; ordinary users must be able to regenerate, rewrite, or branch before that outcome.

Ending titles are branch-specific and may change with the roadmap. A final title becomes immutable only when its ending is committed.

## 5. Ordinary-Player Revision Controls

Regenerate, rewrite, branch, and canon correction are ordinary-player features rather than an expert mode.

- **Regenerate** replaces an unaccepted model response from the same player intent and does not duplicate the intent.
- **Rewrite** accepts a bounded player instruction and produces a replacement chapter while preserving facts the player did not explicitly change.
- **Branch** retains the source history and creates an independent future from the selected point.
- **Canon correction** proposes an explicit before/after change, shows affected facts, and requires confirmation before invalidating dependent future material.

Every operation must remain idempotent, branch-scoped, authorized, and auditable without storing provider credentials or unrestricted prompt/response bodies in operational logs.

## 6. Optional Reference Text

The creation flow may accept pasted text or UTF-8 `.txt` and `.md` files. Import is optional and requires the player to attest that they own the text, have permission to use it, or that it is in the public domain.

Reference processing extracts an abstract style profile such as sentence-length distribution, paragraph rhythm, dialogue ratio, viewpoint, tense, descriptive density, figurative-language density, and pacing. It must not create a named-author imitation mode or instruct the model to reproduce distinctive passages.

The raw text is transient by default. After a profile is accepted, the service stores the profile, a normalized content hash, provenance category, and analysis version, then deletes the raw reference unless a later, explicit retention feature is approved. The content hash prevents repeated analysis or embedding when neither the text nor the analysis version changed.

Reference text is not added to long-term story memory and does not trigger embedding merely because it was imported. An embedding is permitted only for a separately approved retrieval requirement with cache invalidation evidence.

## 7. Style Safety and Evaluation

Generated prose must pass deterministic non-reproduction checks before it is accepted. The first gate compares normalized character and word n-grams against the reference and rejects suspiciously long or dense overlap. Thresholds and normalization rules must be versioned and covered by adversarial tests.

Style quality is measured against the abstract profile, not against author identity. A scored evaluation must include:

- profile adherence;
- narrative quality and coherence;
- player-agency compliance;
- world-rule and canon compliance;
- roadmap and chapter-length compliance; and
- reference-overlap safety.

Model quality scores must come from bounded real-provider captures. Deterministic fixtures validate parsers, policies, and scorers but cannot be reported as provider quality. A capture is reusable while the provider/model, prompt version, evaluation corpus, style-analysis version, and post-processing contract remain unchanged. Generation and judging should use independent model routes where practical, and provider traffic must be sequential, capped, sanitized, and explicitly recorded without secrets.

Initial style evaluation must use reviewed public-domain reference text with documented provenance. It must not use private user stories, living-author samples selected for imitation, or text with uncertain rights.

## 8. Acceptance Invariants

The implementation is not complete until automated tests demonstrate all of the following:

1. Chapter counts below 3 or above 120 and custom lengths outside 500–5,000 are rejected.
2. A normal turn cannot assign consequential protagonist speech, thought, or choice.
3. **Continue** delegates exactly one turn and stops before an irreversible decision.
4. A known impossible action creates no chapter, canon, usage-bearing model call, or branch-version advance.
5. A valid attempt may fail without being treated as invalid input.
6. Completed roadmap entries remain stable while future entries can change on the active branch.
7. Regeneration and rewrite do not duplicate accepted chapters or provider charges under request replay.
8. Raw reference text is deleted after successful profiling and is absent from account logs, memory embeddings, and model-call audit metadata.
9. Re-importing unchanged text reuses the version-compatible profile without another provider or embedding call.
10. Non-reproduction checks block seeded overlap cases before persistence.
11. Player-visible quota remains percentage-only, while administrator policy retains token totals and the deterministic word estimate.
12. Any published model score identifies a real-provider capture and cannot fall back to synthetic evidence.

## 9. Delivery Order

Implementation proceeds through an auditable development-data reset, schema and migration changes, creation UX, generation enforcement, reference profiling, player revision controls, and bounded provider evaluation. Destructive development cleanup requires a verified backup and an explicit target summary before execution. Production data is never included in that authorization.
