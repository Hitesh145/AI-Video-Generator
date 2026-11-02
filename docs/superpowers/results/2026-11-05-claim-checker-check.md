# Claim checker: live check (real model, real stored papers)

Plan: `docs/superpowers/plans/2026-11-05-claim-checker.md`, Task 4. The checker reads each sentence of a paper video's script against the passages that sentence cites and must give an exact quote from them for every sentence it passes. This note measures whether it catches wrong sentences and how often it wrongly rejects right ones. No video was rendered.

**Method.** The same six lessons as the previous live check (a covered and a weak question on each of the sample, Attention and ResNet papers), written by the grounded writer and checked. Then errors were planted by hand into each script and the checker run again. Separately, six number-rich lessons had every figure altered by one digit.

## 1. Planted errors

| planted into the first section of each of the 6 scripts | caught |
|---|---|
| a sentence reversing what the paper says (for example "supervised learning does not use labelled data") | 6 of 6 |
| a true statement from outside the paper (for example "AI was founded as a field at the Dartmouth workshop in 1956") | 6 of 6 |
| a figure the paper does not give, or (once) a changed figure | 6 of 6 |
| **Total** | **18 of 18** |

Subtle number changes, measured separately on lessons with real figures (last digit changed by one: 28.4 to 28.5 style): **10 of 10 caught** (WMT 2014 to 2015, 8 GPUs to 9, step time 1.0 to 1.1 s, 3.57% to 3.58%, 152 layers to 153, VGG-16 to VGG-17, encoder N = 6 to 7 in both the encoder and decoder sentence, and two table numbers).

## 2. False alarms: the real cost

Across the six untouched scripts the checker rejected **8 of 57 sentences (14%)**; with the planted-error scripts 5 of 52 untouched sentences were rejected (the checker is not perfectly repeatable). Reading them:
- Some rejections were right and are the writer's own embellishments, for example "convolutional layers have a path length of O(logk(n)) **or higher depending on the kernel setup**" (the paper does not say the last part).
- Some are true statements of the paper that the section did not cite precisely (for example the path-length comparison from Table 1 when the section cited other passages). The checker only sees the cited passages, so imprecise citations turn into rejections.
- Summary sentences in a conclusion that combine several facts were sometimes rejected.

What happens to them in the pipeline: one rewrite with the rejected sentences named, then removal of what still fails. The viewer gets a shorter but fully checked script, and the note says how many sentences were removed. With 14% rejection a typical video loses roughly one sentence in seven or triggers a rewrite; that is the price of the strict "when unsure, unsupported" rule.

## 3. Cost

The check adds about 3 to 5 model calls and roughly 20 seconds per script (write plus check took 25 to 32 seconds against about 7 for writing alone). A rewrite adds a lesson call and another check.

## 4. What this does not show

- The planted errors were chosen by me; the three kinds are blatant except the number changes. A subtle false paraphrase (a claim that is almost what the paper says, with a changed qualifier) was not systematically tested.
- The checker uses the same model as the writer; a different model would give a more independent second opinion.
- It only judges what is in the script; it does not notice a key result that is missing (the design's second anti-goal).
- Checks are against the passages the section cites, so a faithful sentence with a wrong citation is rejected, and a sentence supported only by a passage that was not retrieved is also rejected.
- Equation pictures, on-screen text and narration audio are outside this check.
- Six lessons, three papers, one run each.

## 5. Next

1. Make citations more precise (ask the writer for the passage per sentence) to cut false alarms.
2. Test subtle paraphrase errors and try a different model for the checker.
3. A check for missing key results.

## 6. After the review fixes (second run, same six lessons)

The review (see the commit "Fix review findings in the claim checker") tightened the checker: titles are now checked too, framing is accepted only in the introduction and conclusion, the checker's numbering must match the sentences exactly, sentences are split on quotes, brackets and digits, and paper videos no longer use the trace animation path (which re-narrates a section with text nobody checked).

- **Planted errors: 18 of 18 caught again** (6 of 6 in each kind).
- **False alarms: 5 of 78 untouched sentences (6%)**, against 14% in the first run. The sentences are now split more finely, so fewer rejections are caused by a long sentence that mixed a supported part with an unsupported one. One rejection was right: "Formally, a building block is defined as F + x." came from a section whose equation had no extracted text.
- **No unusable answers:** the real model's numbering matched the sentences every time, so the new refusal of a mismatching answer did not trigger.
- **Latency varies:** writing plus checking took 31 to 50 seconds per script, and one script took 224 seconds (a slow model response).
- Still not measured: subtle paraphrase errors, a different model as the checker, and missing key results.
