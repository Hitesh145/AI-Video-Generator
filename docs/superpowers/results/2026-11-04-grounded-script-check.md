# Grounded script check (real model, real stored papers)

Plan: `docs/superpowers/plans/2026-11-04-paper-videos-grounded.md`, Tasks 8 and 9. No video was rendered; this checks only the step that decides whether a video is true to the paper: the coverage popup logic and the script the model writes from the retrieved passages.

**Method.** The three evaluation papers (`sample`, `attention`, `resnet`, stored under the evaluation account), their 45 questions (36 answerable, 9 the paper cannot answer). For each question: vector search (12 passages), coverage level, and for a covered and a weak answerable question per paper the grounded script, read against its cited passages. Then the same for six questions the paper cannot answer that landed in the `weak` band. Model: the app's configured Gemini model; about 6-11 seconds per script.

## 1. Coverage levels (thresholds 0.75 / 0.60)

| | covered | weak | absent |
|---|---|---|---|
| answerable questions (36) | 20 | 16 | 0 |
| questions the paper cannot answer (9) | 0 | 7 | 2 |

- No answerable question was wrongly judged `absent`, so the popup never blocks a question the paper answers.
- But 7 of 9 unanswerable questions land in `weak`. Per paper: sample 2/3, attention 2/3, resnet 3/3. The `weak` popup says "the paper only touches this topic briefly", which is not true for them: the paper does not mention speech recognition, carbon, Cityscapes, ethics, a recommended programming language or self-attention (ResNet). Similarity alone cannot tell "mentioned briefly" from "not mentioned" (as the retrieval evaluation had already warned).
- The short sample paper is judged `weak` for 10 of its 12 answerable questions (its passages are short, so similarity is lower): the popup will appear often for that kind of paper.

## 2. What the model wrote (first version)

- **Faithful for the six answerable lessons.** Narration followed the cited passages; every number I traced was in the paper (for example 28.4 BLEU, 3.5 days on 8 P100 GPUs, 3.57%, 58.8% and 62.1% mAP, 6.0% and 28% on COCO). Citations were broad but pointed at real passages.
- **It never invented an answer to an unanswerable question** (no BERT description, no carbon figure, no Cityscapes result). But it still produced a video about other content, introduced as "the paper only touches this topic briefly" (or "briefly or not at all"). A viewer would believe the paper had something to say about the topic.
- **It wrote an equation that is not in the stored text.** In the ResNet passages the equation of the building block is a separate equation region with no text ("a building block defined as:" is followed by nothing). Twice (`resnet-02` and `resnet-14`) the narration said `y = F(x, {Wi}) + x`. That equation is correct in the real paper, but it was recalled by the model, not copied from the paper, which breaks the design rule that equations must be copied.

## 3. Fix (Task 9) and re-check

- The model must set `covers_topic` to false when the passages do not address the request; the job then ends with "The paper does not address this topic. <reason> You can still make a normal video that is not from the paper." instead of a video about something else.
- The lesson is rejected (one retry, then the job fails) when a section states a number, or an equation, that is not in the passages it cites; the introduction and conclusion are checked against all passages.
- The prompt forbids writing any formula not printed in the passages.

Re-run on the same questions: **all six unanswerable questions were refused** with a correct one-sentence reason (for example "The paper does not contain any information about Transformers or self-attention layers"); **all six answerable lessons were still produced** (none wrongly refused); the ResNet building-block narration now says "a building block is defined formally where x and y are the input and output vectors", without reciting the equation.

## 4. What this does not show

Six lessons read by hand, one run, one model; no rendering, so animations, narration audio and what appears on screen are unchecked. The number and equation guard only proves a number appears somewhere in the cited passages (a single digit such as `6` is easily found elsewhere), so a wrong small number can still pass; the sentence-by-sentence claim check (project 4) is still needed. Equations whose text was not extracted can still not be shown or checked (they will need the picture approach). Citations are broad: a section often cites several passages, so "supported by this passage" is not yet precise.

## 5. For the next steps

1. The popup should not promise "touches briefly" for the weak band; the honest messages are "the paper may only mention this" and, after generation, the refusal above. Consider making the weak-band wording neutral.
2. Measure how often the number guard rejects a faithful lesson on more topics (it rejected none of the six here).
3. Project 4: claim-level checking, using the stored `evidence.json` and `citations.json` of each video, and equation pictures.
