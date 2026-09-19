# Belief updating

One setting selects how an investigation turns its evidence into an assessment:

    assessment:
      updater: linguistic | full_context | evidence_accumulator

All three run through `backend/belief/strategies.py::step`. The worker and the replay harness
call the same function. Before it runs, the round's evidence, answers, and verified calculations
are already in the state, so the strategy is given the current round's results.

None of the three is exact Bayesian inference. The sections below say what each one is.

## What a score is a score of

A score is stored on a state that names its `ScoringTarget`, and every evaluation output names
the target of the scores it contains. The default target is:

> H = 1: the reference review, applying the rubric to this claim as worded and to evidence
> admissible at the cutoff, would find a material overstatement.

No reference review data exists for this target. Every score for it is therefore uncalibrated.
A dataset experiment declares its own target from the dataset's labels. The AVeriTeC run uses
"H = 1: the AVeriTeC annotators labelled this claim Refuted". Scores for different targets are
not comparable.

`Finding.probability` is always null and `probability_status` is
`not_calibrated_for_this_target`. Internal scores are stored on the investigation state and on
each update record. The public endpoints leave them out. `GET /claims/{id}/research` returns
them with a notice, and only when `COUNTERCHECK_RESEARCH_VIEW` is set.

## linguistic

The model is given the previous assessment, the active evidence, the questions and answers, the
verified calculations, and the ids of what is new. It is not given withdrawn items, internal
scores, or the scoring target. It returns a status, mechanisms, and an explanation. No number is
produced. This is a model judgment that is conditioned on its own earlier judgment, so it can
depend on the order in which evidence arrived.

## full_context

The model is given the target, the claim, one item per active provenance group, the verified
calculations, and the question answers. It is not given any earlier assessment or score. It
returns a status and, optionally, its own estimate of P(H = 1). The estimate replaces the
previous one. Nothing is accumulated. It is stored as `raw_probability` with method
`full_context`, and only when it lies strictly between 0 and 1. It is a number stated by a
language model. It is not derived from a likelihood model.

## evidence_accumulator

The status comes from the linguistic update. In addition, a score is computed:

    z = logit(prior) + tempering * sum over scoring units u of s_u
    raw_probability = sigmoid(z)

- A scoring unit is one active provenance group, or several groups joined because one
  calculation reads its inputs from all of them. A calculation is derived from its input groups.
  If each input group were scored with the result, the result would count once per group. The
  first live run showed this: two groups read by one calculation each received about +4.5.
  They are now scored together and the result counts once.
- `s_u` is the log-evidence of unit `u`: the model's estimate of
  ln( P(evidence | H = 1) / P(evidence | H = 0) ), limited to [-5, 5]. Its method is recorded as
  `llm_estimated`. The interface also names `learned` and `validated_observation_model`. No
  scorer of those kinds exists here.
- Each unit counts once, however many passages repeat its sources.
- `prior` defaults to 0.5 and `tempering` to 1.0. The prior is a neutral scenario value. It was
  not estimated from data.
- The sum is recomputed from the active ledger at every update. Nothing is carried over, so the
  result does not depend on the order of arrival, a repeated passage adds nothing, a revised
  score replaces the old one, and a withdrawn group stops contributing.
- A score is stored with the hash of its conditioning context: target, cutoff, claim text and
  version, qualifications, the unit's members, the calculations that read from the unit, and
  the scorer version. When any of these changes, the unit is scored again.
- A score that is unavailable, not finite, or outside the limit is an abstention. The unit
  contributes nothing. It is not counted as zero evidence observed, and missing evidence is
  never a negative contribution.

This is an approximation with three known limitations. The units are treated as conditionally
independent given H, which is false when two sources share an unstated origin. The per-group
values are estimates by a language model, not measured likelihood ratios. No calibration data
exists, so `calibrated_probability` stays null and `calibration_status` stays `uncalibrated`.
A calibrator of the form sigmoid(a*z + b) would need labelled reference reviews for the target.

## Exact Bayes arithmetic

`backend/belief/accumulator.py::conditioned_bayes_update` computes posterior odds = prior odds
times a Bayes factor. It is exact arithmetic for given inputs. It is used only to check the
accumulator. The mechanics fixture `evaluation/fixtures/mechanics.json` uses invented factors:

| step | raw score |
|---|---|
| prior | 0.20 |
| admit A, factor 2 | 1/3 |
| admit B, factor 6 | 0.75 |
| admit B again from another page | 0.75 |
| remove the copy of B | 0.75 |
| correct B, factor 3 | 0.60 |
| withdraw B | 1/3 |

The factors are synthetic. The table shows that the ledger arithmetic is right. It says nothing
about any real evidence.

## What links a calculation to a verdict

A calculation names the output that measures the quantity the claim states and the value the
claim states for it. Code compares the two to the precision of the number as written in the
claim and stores
`claim_relation`: `agrees`, `disagrees`, or `none`. The expected value must be a number written
in the claim. When the result and the stated value have the same size and opposite signs, the
sign convention is unknown and the relation is `none`. A percentage change or reduction whose
base period is later than its comparison period is rejected before it is recorded. A verdict of `supported` or `contradicted` needs comparable evidence about the
claim in that direction, or a calculation whose relation is `agrees` or `disagrees`. A
calculation that answers a side question has relation `none` and cannot justify a verdict.

## Retries and failures

Each committed update stores a hash of what the strategy was shown. A retry with the same input
records no second update and does not change a score. When the provider call of a strategy fails,
the round's evidence, answers, and calculations stay recorded and no assessment transition is
written.

## Corrections, withdrawals, and merges

`backend/evidence/provenance.py` keeps a version and a history on every group. A withdrawal or a
correction removes the item from the active ledger, keeps it in `state.withdrawn`, raises the
group version, and removes every calculation that read its inputs from a group that is no longer
active or that cites the removed passage when no admitted item cites it any more. A question
whose answer rested only on the removed item is open again. A merge joins two groups and raises the version of the group that is kept. A score
applies to one group version, so after any of these the group is scored again. A repetition that
arrives before its original is grouped alone at first and joined to the original when it arrives.
Passages with identical text are joined into one group in every order of arrival, also when
only one of them was declared a repetition. One limit remains: when a passage is evidence for
two targets under different quotes, a repetition of that passage joins the group of whichever
quote was admitted first.
