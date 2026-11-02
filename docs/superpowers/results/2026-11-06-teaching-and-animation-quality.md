# Teaching and animation quality: what changed and what was measured

Plan: `docs/superpowers/plans/2026-11-06-teaching-and-animation-quality.md`. The model was **not** changed (`gemini-3.5-flash-lite`); only the instructions given to it, the information passed between stages, and checks around its output.

## What changed

| Stage | Before | Now |
|---|---|---|
| Analyzer | guessed duration and depth, no rules | "detail" means about 8 minutes, nothing said means 4, quick means 2, never more than 12; depth limited to introductory / intermediate / advanced; lists the terms the learner named (`must_cover`) |
| Planner | "keep the structure generic and concept-independent"; only section titles | prerequisite-first order, about one section per minute, a purpose, terms to define and a worked example per section; retries once if a `must_cover` item is missing |
| Knowledge facts | produced, then only used for warnings | passed to the script writer as reference facts |
| Script writer | no rule to define terms; "keep concise"; length target ignored | defines every technical term where it first appears; completeness before brevity; a word budget per section; one rewrite at full length if the script is under 70% of the target |
| Term review (new) | none | a second pass lists terms used without explanation and fixes them once (keeps section titles and order, otherwise keeps the original); `must_cover` terms never mentioned are caught without the model |
| Paper videos | could not define a term the paper does not define | a section may carry up to two plain sentences of general-knowledge background, spoken with "Some background that is not from the paper:", free of numbers and equations, never given to the claim checker, and noted in the video's notes |
| Animation code | no layout rules, no layout feedback | layout rules in the prompt; after each beat the scene reports text that overlaps other text, leaves the screen or covers the subtitle strip, or is crossed by or touches a line, arrow or shape edge; problems go back to the model as a retry; if no attempt is clean the least flawed one is used with a warning |
| 3D | none | one 3D example scene (`three_d_layers.py`), a prompt rule, and a storyboard rule allowing 3D for spatial ideas |

## Baseline: what was actually wrong

Eight fixed topics (including the LR parsing request) were run through the old pipeline up to the finished script.
- The analyzer asked for **15 to 45 minute** lessons (even "binary search to a beginner" got 15), while the writer produced only **280 to 780 words**, which is 7% to 40% of its own length target. The length target in the prompt was simply ignored.
- On the LR request the baseline script did define "item" this time, so your miss is intermittent, not constant. Across the eight topics a judge found an average of about 5 unexplained terms per script.

## Teaching quality, before and after (8 topics, studio pipeline up to the script)

| Topic | requested min | words | unexplained terms (independent judge) |
|---|---|---|---|
| LR parsing (in detail) | 30 → 8 | 480 → 898 | 6 → 6 |
| Hash table (in detail) | 30 → 8 | 674 → 851 | 13 → 0 |
| Gradient descent (in detail) | 15 → 8 | 415 → 1279 | 2 → 2 |
| TCP three-way handshake | 15 → 4 | 387 → 437 | 3 → 3 |
| Binary search | 15 → 4 | 775 → 602 | 2 → 0 |
| Backpropagation (in detail) | 45 → 8 | 448 → 730 | 6 → 4 |
| RSA step by step | 15 → 4 | 458 → 657 | 3 → 1 |
| Photosynthesis (in detail) | 30 → 8 | 281 → 1358 | 4 → 3 |
| **Mean** | **24.4 → 6.5** | **490 → 852** | **4.9 → 2.4** |

- **Length now follows the request:** scripts reach 70% to 131% of their word target, against 7% to 40% before.
- **Unexplained terms roughly halved**, as judged by a larger model (`gemini-3.5-flash`) that did not write the scripts. The writer's own model family judged the same scripts at 4.8 → 0.0; that figure was inflated by self-grading and should not be quoted.
- **LR parsing:** the three terms the learner named (items, closure, the parsing table) are all defined in the new script (12, 2 and 3 sentences mention them, each first with a definition). What remains unexplained are other terms (stack, lookahead, accept), so the LR count did not fall.
- **Cost:** a script now takes about 116 s instead of 32 s on average (more calls: possible planner retry, length rewrite, review, fix; and scripts are 1.7 times longer).

## Paper videos: background definitions (live, real papers)

Three questions on the Attention and ResNet papers. Background appeared only where the passages did not define a term, was plain ("A softmax function turns numbers into probabilities that add up to one.") and contained no numbers. One definition ("An identity shortcut passes the input directly to the output without modification.") touches a term that is the paper's own; it is labelled as background, but it shows the line between general knowledge and the paper is not always sharp.

## Layout and 3D on real renders (3 sections, real model, real Manim)

| Section | Attempts | What the checker found | What the final frame shows |
|---|---|---|---|
| Text-heavy (LR definitions) | 1 | nothing | no overlaps, but a thin visual: one box with two short lines |
| Diagram (TCP handshake) | 2 | first attempt: "SYN" overlapped "ACK" text; the retry fixed it | the "ACK" label touches the SYN-ACK arrow |
| Spatial (network layers) | 2 | first attempt failed to render (Manim error), second was clean | the model chose a 3D scene by itself: three stacked layers, fixed title; no "input / hidden / output" labels, one colour |

**A gap the frames exposed, now fixed:** the first version of the check compared text with text only, and then ignored lines that merely grazed a label. The TCP scene's "ACK" label was missed. The check now also flags text that a line, arrow or shape edge crosses or comes within 0.05 units of; re-rendering that exact generated scene confirmed it flags "ACK", and the three example scenes (including the 3D one) still render with no false alarms. I did not re-run the full three-section test after this last change.

## What this does not show

- No complete video was produced end to end; teaching was measured at the script, layout on single sections.
- Eight topics, one run each, one judge model family (a larger model, but the same vendor); a person has not rated these.
- Scenes can still be visually thin (the LR frame) or unlabelled (the 3D frame): the check finds collisions, not poor content.
- The term review uses the same small model as the writer. Using a stronger model for just this pass (one or two short calls per video) is the obvious next experiment and would not change the writer.
- The result is not guaranteed to hold for a topic outside these eight.
