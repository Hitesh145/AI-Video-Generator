# Retrieval evaluation: findings

Plan: `docs/superpowers/plans/2026-11-03-retrieval-evaluation.md`. Spec: `docs/superpowers/specs/2026-11-01-paper-videos-design.md`.

**What was measured.** For three papers, 12 questions each that the paper can answer and 3 that it cannot, we asked: does the search put a passage containing the answer in the top few results? Three searches were compared: *vector* (meaning, Gemini embeddings), *keyword* (PostgreSQL full-text) and *hybrid* (both, merged by reciprocal rank fusion). A passage counts as the answer if its text contains one of the short phrases listed for the question; every phrase was checked against the stored text before scoring.

**Papers:** the owner's sample paper on AI (`sample`, local only, 5 pages), "Attention Is All You Need" (`attention`, 15 pages, tables and equations) and "Deep Residual Learning for Image Recognition" (`resnet`, 12 pages, figures and tables). Copies are stored under the account `evaluation@edugen.local` in the development database and are reused by later plans; they appear in nobody's library. The two arXiv PDFs are pinned by SHA-256 in `backend/evaluation/papers.json`.

## Headline

| (36 answerable questions, three papers pooled) | recall@1 | recall@5 | recall@8 | MRR (mean of 3 papers) |
|---|---|---|---|---|
| vector | 0.72 | 0.97 (35/36) | 0.97 | 0.83 |
| hybrid | 0.69 | 0.97 (35/36) | 0.97 | 0.81 |
| keyword | 0.61 | 0.83 (30/36) | 0.89 | 0.70 |

Recall@5 is the share of questions whose answer passage appears among the first five results. These pooled figures are averages of the per-paper tables below.

## Reading the numbers

**(a) Best mode.** Vector search, on every paper. Its recall@5 is 1.00, 1.00 and 0.92 (sample, attention, resnet) and it also puts the right passage first more often (recall@1 0.83, 0.75, 0.58). Hybrid matches it at recall@5 and recall@8 but is slightly lower at rank 1 and in MRR on two papers. Keyword alone is clearly the weakest (recall@5 0.92, 0.83, 0.75).

**(b) Does adding keyword search help?** Not on these papers. Hybrid ties vector at recall@5/@8 and is a little worse at the very top (MRR 0.85 vs 0.88 on attention, 0.66 vs 0.69 on resnet; one question's rank each, which is within noise for 12 questions). The weaker keyword list pulls good vector results down a place or two. It does not hurt where it matters for generation (the top 5-8), so keeping hybrid available costs little, but there is no evidence yet that it earns its place. Keyword search is where exact tokens such as numbers or identifiers should matter; the numeric questions here (BLEU 28.4, 3.57%, 20000 engineers) were all found by vector search too.

**(c) What fails.** Only one question is missed by every mode in the top 8: **resnet-11**, "What went wrong with the network that had more than a thousand layers?" The answer passage says "1202-layer network ... overfitting"; the question says "more than a thousand layers". The words do not match ("thousand" vs "1202"), and ResNet's many other passages about depth outrank it. This is a vocabulary and vagueness failure, not a format failure. Keyword search alone also fails the whole "future work" category on attention (0.00) and "results" on resnet (0.33); there the question uses different words than the paper ("do next" vs "plan to extend"), which meaning-based search bridges and word matching cannot.
Equations were **not** tested: in the stored text the formula regions carry no text at all (for example "We compute the matrix of outputs as:" is followed by nothing), so no phrase from an equation can be validated. This matches the design (equations are shown as pictures), but it means retrieval can currently find the sentence around an equation, never the equation itself.
Answers spread over more than one section (attention-07, attention-10, resnet-10, sample-10, sample-12) were all found at recall@5 by vector and hybrid, because the phrases accept either section; this does not prove the generator would see both halves.

**(d) The "not in this paper" threshold.** The suggested cut-offs on the best-passage similarity (vector) are 0.613 (sample), 0.623 (attention) and 0.707 (resnet), with accuracy 0.93, 0.87 and 0.93 in separating answerable from absent questions. The two groups overlap in every paper: absent questions were deliberately about a nearby topic, so a related passage still matches (for example attention: absent questions reach 0.73, answerable ones start at 0.65). The suggested value also moves by about 0.1 between papers. Keyword scores do not separate the groups reliably (accuracy 0.80-0.93, thresholds 0.10 to 1.10). **Confidence is low**: 9 absent questions in total, the cut-off is fitted on the same questions it is scored on (optimistic), and the figures are paper-dependent. A single fixed number should not decide alone whether a question is "not in this paper". It is useful as a warning signal: a low best-match similarity should trigger the claim check of the next project, not a silent answer.

**(e) Recommendation for the next plan.**
1. Use **vector search** as the default evidence retriever and pass the top 5-8 passages on; keep hybrid switchable for the comparison below rather than the default.
2. **Neighbouring-passage expansion looks worth testing**: the one miss, the split tables and the reading-order break (see below) are all cases where the right text sits next to the retrieved text. **Reranking does not look worth adding yet**: recall@5 is already 0.97, and the generator receives 5-8 passages anyway.
3. The **whole-paper-in-prompt comparison** should be run before building more retrieval. These papers are 35-50 thousand characters (roughly 10-15 thousand tokens) and fit in one prompt. Measure, on the same questions plus the absent ones: whether the answer is correct and grounded (judged against the paper, not a phrase match), whether absent questions are refused, whether equation and table answers are right, and cost and time per answer. Retrieval is only worth its complexity if it beats this, or if papers get long.
4. Fix extraction problems 1 and 2 below before relying on any stored paper for teaching claims.

## What these numbers do not show

Three papers; 45 questions, all written by the assistant after reading the stored text, so they reflect what the parser managed to extract (anything it silently dropped could not become a question: see problem 1, which would have been invisible); relevance is "the passage contains a phrase", not "a person judged it sufficient"; retrieval only, no generated answers, so nothing here says the final explanations are correct; one run, one embedding model (`gemini-embedding-2`, 1536 dimensions); no equation questions; differences of one question (about 0.08) are noise.

## Extraction problems found on the way (the stored text is what retrieval can find)

1. **A partly failed parse is stored as a normal paper.** The first copy of the Attention paper was stored while the OCR step (RapidOCR/onnxruntime) was failing with "bad allocation" under memory pressure. Docling logged the errors and carried on; our parser turns `result.errors` into warnings only, so the paper was stored as if complete, missing its Introduction, Background, section 4 and parts of sections 3-6 (29 of 41 passages). Nothing in the product would have told a user. Re-parsing the same file cleanly gave all 41 passages. Evaluation numbers above are from the clean copy. **This directly conflicts with the design's rule that unreadable content must be reported, never guessed.** It predates this plan and is not fixed here; it needs its own test-first change (treat a conversion with errors as a failed or flagged paper).
2. **Native crashes take the process down.** One ingestion run ended in a segmentation fault inside the OCR library. In the app, parsing runs in the backend process, so the same crash would kill the server. Running the parser in a subprocess would contain it. The evaluation parsed on the CPU (`DOCLING_DEVICE=cpu`) because the running backend already held the GPU memory.
3. **Reading order breaks on two-column first pages.** In `resnet`, a sentence on page 1 is cut in two and its second half ends up in a later passage ("solutions that" ... "are comparably good or better than the constructed solution").
4. **Tables can be split across passages.** Table 3 of `attention` is cut mid-row over several passages; each piece is meaningless alone.
5. **Equations have no text** (see (c)); figures contribute only their captions.
6. **No document title** was detected for `attention` and `resnet` (the title appears only as a section name).
7. The attention PDF's author block becomes its own passage, and one stray licence sentence becomes passage 0.

## Report as produced

The tables below are the unedited output of `python -m evaluation.run` (also written to `backend/evaluation/results/latest.md`, which is git-ignored).



### sample

12 answerable questions, 3 that the paper cannot answer.

| mode | recall@1 | recall@3 | recall@5 | recall@8 | MRR |
|---|---|---|---|---|---|
| vector | 0.83 | 1.00 | 1.00 | 1.00 | 0.92 |
| keyword | 0.83 | 0.83 | 0.92 | 1.00 | 0.86 |
| hybrid | 0.83 | 1.00 | 1.00 | 1.00 | 0.92 |

Recall@5 by question category:

| category | vector | keyword | hybrid |
|---|---|---|---|
| applications | 1.00 | 0.50 | 1.00 |
| comparison | 1.00 | 1.00 | 1.00 |
| definition | 1.00 | 1.00 | 1.00 |
| limitations | 1.00 | 1.00 | 1.00 |
| method | 1.00 | 1.00 | 1.00 |
| numbers | 1.00 | 1.00 | 1.00 |

How strongly the best passage matches (min / median / max), and the suggested "covered by the paper" threshold:

| mode | answerable questions | questions the paper cannot answer | suggested threshold | accuracy |
|---|---|---|---|---|
| vector | 0.62 / 0.73 / 0.79 | 0.60 / 0.61 / 0.70 | 0.613 | 0.93 |
| keyword | 0.60 / 1.10 / 2.60 | 0.10 / 0.30 / 1.40 | 0.450 | 0.93 |
| hybrid | 0.62 / 0.73 / 0.79 | 0.60 / 0.61 / 0.70 | 0.613 | 0.93 |

Answerable questions no mode found in the top 8:

- none

### attention

12 answerable questions, 3 that the paper cannot answer.

| mode | recall@1 | recall@3 | recall@5 | recall@8 | MRR |
|---|---|---|---|---|---|
| vector | 0.75 | 1.00 | 1.00 | 1.00 | 0.88 |
| keyword | 0.67 | 0.83 | 0.83 | 0.92 | 0.75 |
| hybrid | 0.75 | 1.00 | 1.00 | 1.00 | 0.85 |

Recall@5 by question category:

| category | vector | keyword | hybrid |
|---|---|---|---|
| comparison | 1.00 | 1.00 | 1.00 |
| definition | 1.00 | 0.50 | 1.00 |
| future work | 1.00 | 0.00 | 1.00 |
| method | 1.00 | 1.00 | 1.00 |
| motivation | 1.00 | 1.00 | 1.00 |
| results | 1.00 | 1.00 | 1.00 |
| tables | 1.00 | 1.00 | 1.00 |

How strongly the best passage matches (min / median / max), and the suggested "covered by the paper" threshold:

| mode | answerable questions | questions the paper cannot answer | suggested threshold | accuracy |
|---|---|---|---|---|
| vector | 0.65 / 0.78 / 0.82 | 0.60 / 0.70 / 0.73 | 0.623 | 0.87 |
| keyword | 0.10 / 2.20 / 3.40 | 0.50 / 1.00 / 1.50 | 0.100 | 0.80 |
| hybrid | 0.65 / 0.78 / 0.82 | 0.59 / 0.70 / 0.73 | 0.619 | 0.87 |

Answerable questions no mode found in the top 8:

- none

### resnet

12 answerable questions, 3 that the paper cannot answer.

| mode | recall@1 | recall@3 | recall@5 | recall@8 | MRR |
|---|---|---|---|---|---|
| vector | 0.58 | 0.92 | 0.92 | 0.92 | 0.69 |
| keyword | 0.33 | 0.58 | 0.75 | 0.75 | 0.50 |
| hybrid | 0.50 | 0.83 | 0.92 | 0.92 | 0.66 |

Recall@5 by question category:

| category | vector | keyword | hybrid |
|---|---|---|---|
| comparison | 1.00 | 1.00 | 1.00 |
| definition | 1.00 | 1.00 | 1.00 |
| limitations | 0.00 | 0.00 | 0.00 |
| method | 1.00 | 1.00 | 1.00 |
| motivation | 1.00 | 1.00 | 1.00 |
| results | 1.00 | 0.33 | 1.00 |
| tables | 1.00 | 1.00 | 1.00 |

How strongly the best passage matches (min / median / max), and the suggested "covered by the paper" threshold:

| mode | answerable questions | questions the paper cannot answer | suggested threshold | accuracy |
|---|---|---|---|---|
| vector | 0.71 / 0.78 / 0.85 | 0.67 / 0.71 / 0.73 | 0.707 | 0.93 |
| keyword | 1.10 / 2.00 / 2.80 | 1.30 / 2.10 / 2.20 | 1.100 | 0.80 |
| hybrid | 0.71 / 0.78 / 0.85 | 0.67 / 0.71 / 0.71 | 0.707 | 0.93 |

Answerable questions no mode found in the top 8:

- resnet-11 (limitations): What went wrong with the network that had more than a thousand layers?
