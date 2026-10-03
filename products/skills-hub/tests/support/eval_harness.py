"""Rebuilt R-8 evaluation harness (SPEC-066).

The offline harness that produced eval-set §8 is **not committed** (``git
ls-files`` shows only the label fixture and the two prose artifacts). R-8 is the
merge gate, so its instrument must exist in the repository: this module is that
rebuild. Two properties are load-bearing and both are deliberate:

* it is driven through a store's async ``search()`` — **not** ``rank()``
  directly — so on the Postgres backend the ``to_tsvector`` prefilter is inside
  the measured path. A memory-path gain that the prefilter silently turns into a
  disappearance is exactly what R-8 exists to catch (OQ-4's first condition);
* it grades each returned ``skill_id`` against the committed label fixture and
  computes the full §8 metric set, plus the pre-registered paired bootstrap and
  exact sign test, so no candidate number is produced by an ad-hoc script again.

``corpus.verify_corpus_md5`` is asserted **first** by the caller: a corpus whose
``body_md5`` drifted from the graded fixture invalidates every metric, so the
harness refuses to compute rather than report a plausible-looking wrong number.

The MD5 used there and in R-7's ``rank()`` de-duplication is a **content-identity
key, not a security digest**.
"""

from __future__ import annotations

import math
import random
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass

# A store's bound ``search``: async (query_text, limit) -> ordered SearchHit list.
SearchFn = Callable[[str, int], Awaitable[Sequence]]

BOOTSTRAP_SEED = 20261001
BOOTSTRAP_RESAMPLES = 10_000
DEPTH = 10  # §5 grades candidates at depth 10; nDCG@10 / R@10 need it.


@dataclass(frozen=True)
class GradedQuery:
    """One labeled query: its text and the code -> grade (0/1/2) map."""

    id: str
    stratum: str
    text: str
    grades: dict[str, int]

    def relevant(self, threshold: int) -> set[str]:
        return {code for code, g in self.grades.items() if g >= threshold}

    def exactly(self, grade: int) -> set[str]:
        return {code for code, g in self.grades.items() if g == grade}


@dataclass(frozen=True)
class Metrics:
    """The §8 metric set for one query population and one backend."""

    n: int
    top1_grade2: int
    zero_hit: int
    zero_relevant: int
    precision_at_5: float
    mrr: float
    mrr2: float
    ndcg_at_10: float
    recall_at_5_ge1: float
    recall_at_10_ge1: float
    recall_at_5_eq2: float

    def as_dict(self) -> dict[str, float | int]:
        return {
            "n": self.n,
            "top1_grade2": self.top1_grade2,
            "zero_hit": self.zero_hit,
            "zero_relevant": self.zero_relevant,
            "precision_at_5": self.precision_at_5,
            "mrr": self.mrr,
            "mrr2": self.mrr2,
            "ndcg_at_10": self.ndcg_at_10,
            "recall_at_5_ge1": self.recall_at_5_ge1,
            "recall_at_10_ge1": self.recall_at_10_ge1,
            "recall_at_5_eq2": self.recall_at_5_eq2,
        }


def load_graded(labels: dict) -> list[GradedQuery]:
    """The 38 graded queries (stratum B + C); stratum A is regression-only."""
    return [
        GradedQuery(
            id=q["id"],
            stratum=q["stratum"],
            text=q["text"],
            grades=dict(q["grades"]),
        )
        for q in labels["queries"]
    ]


def code_maps(labels: dict) -> tuple[dict[str, str], dict[str, str]]:
    """``skill_id -> code`` and ``code -> skill_id`` from the corpus snapshot."""
    id_to_code = {d["skill_id"]: d["code"] for d in labels["corpus_snapshot"]["documents"]}
    code_to_id = {code: sid for sid, code in id_to_code.items()}
    return id_to_code, code_to_id


async def collect_ranks(
    search: SearchFn,
    queries: Iterable[GradedQuery],
    id_to_code: dict[str, str],
    limit: int = DEPTH,
) -> dict[str, list[str]]:
    """Run every query through ``search`` and map query id -> ranked codes.

    Driven through the store's ``search()`` so the Postgres prefilter is in the
    measured path. A returned ``skill_id`` absent from the snapshot (impossible
    on the pinned corpus, but defensive) grades as an unknown code.
    """
    ranks: dict[str, list[str]] = {}
    for q in queries:
        hits = await search(q.text, limit)
        ranks[q.id] = [id_to_code.get(h.skill.skill_id, h.skill.skill_id) for h in hits]
    return ranks


def _dcg(gains: Sequence[float]) -> float:
    return sum(g / math.log2(i + 2) for i, g in enumerate(gains))


def _gain(grade: int) -> float:
    """Exponential nDCG gain (``2**grade - 1``): grades 0/1/2 -> 0/1/3.

    This is the convention §8.1's published nDCG@10 uses — reproduced exactly
    against the baseline table (B 0.868, C 0.742, combined 0.813). A linear gain
    gives 0.862/0.750/0.813 and does **not** match, so the gain is pinned here
    rather than left as an implementation choice.
    """
    return (2.0 ** grade) - 1.0


def _ndcg_at_10(codes: Sequence[str], query: GradedQuery) -> float | None:
    """nDCG@10, or ``None`` when the query has no relevant document (IDCG 0).

    §8.1 excludes a no-relevance query from the nDCG/recall means rather than
    counting it as a zero — averaging over all ``n`` understates every stratum
    (combined 0.727 vs the published 0.813). The exclusion is per metric, so
    ``compute_metrics`` averages each over its own non-empty denominator.
    """
    gains = [_gain(query.grades.get(code, 0)) for code in codes[:10]]
    ideal = [_gain(g) for g in sorted(query.grades.values(), reverse=True)[:10]]
    idcg = _dcg(ideal)
    if idcg <= 0:
        return None
    return _dcg(gains) / idcg


def _reciprocal_rank(codes: Sequence[str], query: GradedQuery, grade: int) -> float:
    for i, code in enumerate(codes, start=1):
        if query.grades.get(code, 0) >= grade:
            return 1.0 / i
    return 0.0


def compute_metrics(
    ranks: dict[str, list[str]], queries: Sequence[GradedQuery]
) -> Metrics:
    """The full §8 metric set over ``queries`` (as-returned; the corpus is
    duplicate-free so the distinct-document variant is identical — §8.1 fact 4).

    ``top1_grade2``/``zero_*``/``precision_at_5``/``mrr``/``mrr2`` average over
    all ``n``. ``ndcg_at_10`` and the three recall metrics average only over the
    queries where they are defined (a non-empty relevant set), matching §8.1's
    published baseline exactly — see ``_ndcg_at_10``.
    """
    n = len(queries)
    if n == 0:
        return Metrics(0, 0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    top1_grade2 = zero_hit = zero_relevant = 0
    p5 = mrr = mrr2 = 0.0
    ndcg_vals: list[float] = []
    r5ge1_vals: list[float] = []
    r10ge1_vals: list[float] = []
    r5eq2_vals: list[float] = []
    for q in queries:
        codes = ranks.get(q.id, [])
        if not codes:
            zero_hit += 1
        top5 = codes[:5]
        top5_ge1 = sum(1 for c in top5 if q.grades.get(c, 0) >= 1)
        if top5_ge1 == 0:
            zero_relevant += 1
        if codes and q.grades.get(codes[0], 0) == 2:
            top1_grade2 += 1
        p5 += top5_ge1 / 5.0
        mrr += _reciprocal_rank(codes, q, 1)
        mrr2 += _reciprocal_rank(codes, q, 2)
        ndcg = _ndcg_at_10(codes, q)
        if ndcg is not None:
            ndcg_vals.append(ndcg)
        rel1 = q.relevant(1)
        rel2 = q.exactly(2)
        if rel1:
            r5ge1_vals.append(len(set(top5) & rel1) / len(rel1))
            r10ge1_vals.append(len(set(codes[:10]) & rel1) / len(rel1))
        if rel2:
            r5eq2_vals.append(len(set(top5) & rel2) / len(rel2))

    def mean(xs: list[float]) -> float:
        return (sum(xs) / len(xs)) if xs else 0.0

    return Metrics(
        n=n,
        top1_grade2=top1_grade2,
        zero_hit=zero_hit,
        zero_relevant=zero_relevant,
        precision_at_5=p5 / n,
        mrr=mrr / n,
        mrr2=mrr2 / n,
        ndcg_at_10=mean(ndcg_vals),
        recall_at_5_ge1=mean(r5ge1_vals),
        recall_at_10_ge1=mean(r10ge1_vals),
        recall_at_5_eq2=mean(r5eq2_vals),
    )


def metrics_by_stratum(
    ranks: dict[str, list[str]], queries: Sequence[GradedQuery]
) -> dict[str, Metrics]:
    out: dict[str, Metrics] = {}
    for stratum in sorted({q.stratum for q in queries}):
        subset = [q for q in queries if q.stratum == stratum]
        out[stratum] = compute_metrics(ranks, subset)
    out["combined"] = compute_metrics(ranks, queries)
    return out


def per_query_ndcg(
    ranks: dict[str, list[str]], queries: Sequence[GradedQuery]
) -> dict[str, float]:
    """Per-query nDCG@10, the metric the paired bootstrap resamples.

    A no-relevance query (``_ndcg_at_10`` → ``None``) is scored 0.0 here so it
    contributes a zero delta to the bootstrap; it is undefined-but-identical
    under baseline and candidate, so including it is conservative, not skewing.
    """
    return {
        q.id: (_ndcg_at_10(ranks.get(q.id, []), q) or 0.0) for q in queries
    }


def paired_bootstrap_ci(
    base: dict[str, float],
    cand: dict[str, float],
    query_ids: Sequence[str],
    *,
    seed: int = BOOTSTRAP_SEED,
    resamples: int = BOOTSTRAP_RESAMPLES,
) -> tuple[float, float]:
    """95% CI on the mean per-query delta (candidate - baseline).

    The pre-registered method (§8.3): resample query ids with replacement,
    recompute the mean delta, take the 2.5/97.5 percentiles. A CI excluding 0
    is "outside the noise band".
    """
    deltas = [cand[qid] - base[qid] for qid in query_ids]
    n = len(deltas)
    if n == 0:
        return (0.0, 0.0)
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(resamples):
        sample = [deltas[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo = means[int(0.025 * resamples)]
    hi = means[int(0.975 * resamples) - 1]
    return (lo, hi)


def sign_test_p(discordant: tuple[int, int]) -> float:
    """Exact two-sided sign test on discordant top-1 pairs (§8.3).

    ``discordant`` is ``(improvements, regressions)``; ties (unchanged top-1
    grade) are excluded. Under H0 each discordant pair is a fair coin, so the
    two-sided p is ``2 * P(X <= min)`` on ``Binomial(n, 0.5)``, capped at 1.0.
    """
    wins, losses = discordant
    n = wins + losses
    if n == 0:
        return 1.0
    k = min(wins, losses)
    # Sum of binomial pmf for X <= k with p = 0.5, doubled for two-sided.
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n)
    return min(1.0, 2.0 * tail)


def top1_grade_deltas(
    base: dict[str, list[str]],
    cand: dict[str, list[str]],
    queries: Sequence[GradedQuery],
) -> tuple[int, int, int]:
    """``(improvements, regressions, lateral)`` in top-1 grade, base -> cand."""
    by_id = {q.id: q for q in queries}
    improved = regressed = lateral = 0
    for qid, q in by_id.items():
        b = base.get(qid, [])
        c = cand.get(qid, [])
        bg = q.grades.get(b[0], 0) if b else 0
        cg = q.grades.get(c[0], 0) if c else 0
        if cg > bg:
            improved += 1
        elif cg < bg:
            regressed += 1
        elif bg != cg or (b[:1] != c[:1] and bg == cg):
            # Same grade but a different document still moved top-1.
            if b[:1] != c[:1]:
                lateral += 1
    return improved, regressed, lateral
