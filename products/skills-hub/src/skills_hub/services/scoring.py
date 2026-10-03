"""Deterministic keyword scoring shared by both store backends (SPEC-014 R-3).

A single pure ``score`` function keeps in-memory and Postgres retrieval
byte-identical: Postgres pre-filters candidates with ``to_tsvector`` and
re-ranks them here. A query token found in the title scores 3, in the tags 2,
in the ``skill_id`` slug 2, and each body occurrence 1 (saturating at
``BODY_OCCURRENCE_CAP`` so long documents cannot drown out title/tag matches);
every per-token contribution is then scaled by a corpus-derived inverse document
frequency, and the capped body contribution is damped sublinearly by document
length. Zero-score records are excluded; equal scores break ties by ``skill_id``
ascending.

SPEC-066 delivered four lexical-fidelity fixes, made unconditional at R-9 (the
four measurement flags that gated them during R-8's re-measurement are gone):

* R-1 — the ``skill_id`` slug is a fourth scored field, at ``TAG_WEIGHT``;
* R-2 — each token is weighted by a corpus-derived inverse document frequency
  (``CorpusStats``), which is why ``score``/``rank`` take an explicit, required
  statistics value;
* R-3 — the capped body contribution is damped sublinearly by document length;
* R-4 — CamelCase/digit identifiers are split into their parts *and* the whole
  token retained, on the **query side only** (``tokenize_query``). Document
  fields stay unsplit (``tokenize``) so they remain byte-identical to
  PostgreSQL's ``to_tsvector('simple', …)`` lexemes, which is what makes R-5's
  prefilter a sound over-approximation and R-6's parity invariant hold **by
  construction** rather than by prefix-lexeme luck.

R-7's content de-duplication in ``rank`` is a no-op on a duplicate-free corpus
and is regression protection rather than a ranking change.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from skills_hub.schemas.skill import Skill

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
# SPEC-066 R-4: a maximal run of alphanumerics is one *surface* token position.
# Splitting happens on the original-cased text (lowercasing first would erase
# the boundaries), then each part is lowercased through ``TOKEN_PATTERN``.
_ALNUM_RUN_PATTERN = re.compile(r"[A-Za-z0-9]+")
# The two standard CamelCase boundaries only: ``lower/digit -> Upper`` and
# ``Upper -> Upper+lower``. Deliberately **no** third letter<->digit boundary,
# so ``HTTP503`` stays the single token ``http503`` and ``v0211`` stays
# ``v0211`` — the decision pinned in the R-4 case table (tasks.md Stage 2).
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

TITLE_WEIGHT = 3.0
TAG_WEIGHT = 2.0
BODY_WEIGHT = 1.0
BODY_OCCURRENCE_CAP = 5
EXCERPT_MAX_CHARS = 400


def _run_tokens(run: str) -> list[str]:
    """The distinct tokens of one surface alphanumerics run (query side only).

    The run is split on the CamelCase boundaries and each part lowercased through
    ``TOKEN_PATTERN``; the **whole** (lowercased) run is admitted only when it
    differs from its parts, so a run with no internal boundary (``pod``) yields
    ``[pod]`` once rather than ``[pod, pod]``. Because every run emits distinct
    tokens, ``_query_tokens``' de-duplication keeps the split non-inflating: a
    query credits a document token once however many surface forms produced it.
    Only ``tokenize_query`` calls this — the document side (``tokenize``) never
    splits, so it needs no such guard and its body occurrence count keeps its
    shipped meaning automatically.
    """
    whole = run.lower()
    parts: list[str] = []
    for sub in _CAMEL_BOUNDARY.split(run):
        parts.extend(TOKEN_PATTERN.findall(sub.lower()))
    tokens = list(dict.fromkeys(parts))  # distinct, order-stable
    if whole not in tokens:
        tokens.append(whole)
    return tokens


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens — the **document-side** matching unit.

    This is the single tokenizer for every document field (``title``, ``tags``,
    ``body``, ``skill_id``) and for R-2's ``df`` (``compute_stats``), so the
    statistics path and the scoring path can never drift apart. It is **never**
    CamelCase-split: SPEC-066 R-4 (amended) splits the *query* only, in
    ``tokenize_query``. Keeping the document side on the plain ``[a-z0-9]+`` rule
    is what makes it byte-identical to PostgreSQL's ``to_tsvector('simple', …)``
    lexemes, so R-5's prefilter is a sound over-approximation and R-6's parity
    invariant holds **by construction**. Document-side splitting was the sole
    source of the cross-backend divergence R-6 forbids: a plain query word (``set``)
    matching a part Python split out of an identifier (``StatefulSet``) that
    ``to_tsvector`` keeps whole and the prefix term ``set:*`` cannot reach.
    """
    return TOKEN_PATTERN.findall(text.lower())


def tokenize_query(query: str) -> list[str]:
    """The **query-side** tokenizer: CamelCase/digit identifiers are split.

    SPEC-066 R-4 applies the split to the query only: a CamelCase/digit run is
    split into its parts *and* the whole token is retained (``KubePodNotReady``
    -> ``kube``, ``pod``, ``not``, ``ready``, ``kubepodnotready``). Text with no
    CamelCase tokenizes exactly as the document side (``tokenize``) does.

    Splitting the query is always parity-safe: ``score`` matches by **exact** token
    membership, so a split query part can only match a document token that is
    already that exact part, and R-5's prefilter emits an exact ``part`` term
    (alongside ``part:*``) for every query token — so query-side splitting only
    ever **widens** the prefilter, never under-admits. This is the win R-4 exists
    for: an operator's ``KubePodNotReady`` alert-name query reaches a runbook that
    uses the words ``pod`` / ``not`` / ``ready``, without any document field being
    split to meet it (which is what would break parity).
    """
    tokens: list[str] = []
    for run in _ALNUM_RUN_PATTERN.findall(query):
        tokens.extend(_run_tokens(run))
    return tokens


def _query_tokens(query: str) -> list[str]:
    """The query's scoring tokens, de-duplicated.

    The tokens are de-duplicated before the scoring loop — the position-aware
    shape R-4 requires — so a token that several surface forms produce (a whole
    identifier and one of its parts) is credited once rather than once per form.
    """
    return list(dict.fromkeys(tokenize_query(query)))


@dataclass(frozen=True)
class CorpusStats:
    """Corpus-wide document frequencies for IDF weighting (SPEC-066 R-2).

    An explicit, immutable value computed **in Python at sync time** over the
    whole catalog (``compute_stats``), persisted per backend, and passed into
    ``rank``/``score`` by the caller — ``rank`` is synchronous and pure while
    both stores are ``async``, so the statistics cannot be fetched inside it.
    ``n`` is the document count; ``df`` maps each token to the number of
    documents whose four scored fields contain it. Because both backends derive
    it from the same population with the same ``tokenize()``, the score is
    backend-independent — a numeric claim the R-6 parity harness asserts.
    """

    n: int = 0
    df: Mapping[str, int] = field(default_factory=dict)

    def idf(self, token: str) -> float:
        """``ln((1 + N) / (1 + df)) + 1`` — smoothed, and never a division by
        zero. An unseen token takes ``df = 0``; an empty corpus (``n = 0``,
        ``df = {}``) gives exactly ``1.0`` for every token, i.e. neutral, so a
        store that has not refreshed yet scores as the shipped scorer does.
        There is **no stoplist** anywhere in this path (OQ-2): a high-``df``
        token such as ``the`` is down-weighted by its own frequency, not by a
        hand-written list.
        """
        return math.log((1 + self.n) / (1 + self.df.get(token, 0))) + 1.0


EMPTY_STATS = CorpusStats()


def compute_stats(skills: Iterable[Skill]) -> CorpusStats:
    """A full-catalog document-frequency pass (SPEC-066 R-2).

    ``df`` is **global**, so a per-source swap invalidates all of it and the
    refresh is a whole-catalog pass (trivial at this scale, and cheap next to
    sync's git clone). Uses the *same* document-side ``tokenize()`` the scorer
    matches against — over all four scored fields, so the statistics path and the
    scoring path cannot diverge (a mismatch would be silent). Because the document
    side is never CamelCase-split (R-4 amended), ``df`` counts whole lexemes
    exactly as PostgreSQL's ``to_tsvector`` would; a query's CamelCase-derived
    part (from ``tokenize_query``) looks up the ``df`` of the documents carrying
    that part as a standalone token, and takes the unseen-token default when none
    do. A document counts once per distinct token, so ``df[token]`` is the number
    of documents containing it, not the number of occurrences.
    """
    n = 0
    df: Counter[str] = Counter()
    for skill in skills:
        n += 1
        tokens = set(tokenize(skill.title))
        tokens |= set(tokenize(skill.body))
        tokens |= set(tokenize(skill.skill_id))
        for tag in skill.tags or []:
            tokens |= set(tokenize(tag))
        df.update(tokens)
    return CorpusStats(n=n, df=dict(df))


def _length_norm(body: str) -> float:
    """``1 / log2(2 + len(body) / 1000)`` — the R-3 sublinear length damp.

    The argument is ``>= 2`` for any body length, so ``log2 >= 1`` and the
    factor is in ``(0, 1]``; an empty body gives exactly ``1.0`` (harmless,
    since an empty body also has zero occurrences) and there is no reachable
    division by zero. It depends only on the document, so it is
    backend-neutral by construction — the one fix needing no corpus state.
    """
    return 1.0 / math.log2(2.0 + len(body) / 1000.0)


def score(query: str, skill: Skill, stats: CorpusStats) -> float:
    """Deterministic relevance score; 0.0 means no match at all.

    The score stays **decomposable** into per-token, per-field contributions
    (``weight x idf(token) x norm(document)``) so a reviewer can answer "why did
    this rank first?" during an incident review — the surviving obligation from
    the retrieval memo's "do not silently redefine ``score``". ``idf`` comes from
    the required ``stats``; an unrefreshed store passes ``EMPTY_STATS``, whose
    ``idf`` is a neutral ``1.0``, so scoring degrades gracefully to plain field
    weighting until statistics are computed.

    The magnitude is an **ordering key within one query's result set, never a
    relevance value comparable across queries**: R-4's whole-token retention
    makes it query-shape dependent (measured — an exact ``KubePodNotReady``
    identifier query scores its title-matching owner **3.0**, the equivalent
    three-word phrase scores **9.0**, and a plain-word query against an
    identifier-only title scores **0.0**, the recall the query-only split forgoes
    for parity). Nothing downstream consumes the magnitude — ``rank`` orders by
    it and the API publishes it as ``score`` — so this is a documentation
    constraint, and the one the separate abstention backlog row must respect: no
    cross-query relevance threshold derives from these numbers without
    normalizing for query shape.
    """
    query_tokens = _query_tokens(query)
    if not query_tokens:
        return 0.0
    title_tokens = set(tokenize(skill.title))
    tag_tokens = {token for tag in skill.tags or [] for token in tokenize(tag)}
    # R-1: the slug is a fourth scored field, credited at TAG_WEIGHT (OQ-1(b)).
    # ``skill_id`` is the primary key, so no column is added anywhere.
    id_tokens = set(tokenize(skill.skill_id))
    body_counts = Counter(tokenize(skill.body))
    length_norm = _length_norm(skill.body)
    total = 0.0
    for token in query_tokens:
        contribution = 0.0
        if token in title_tokens:
            contribution += TITLE_WEIGHT
        if token in tag_tokens:
            contribution += TAG_WEIGHT
        if token in id_tokens:
            contribution += TAG_WEIGHT
        occurrences = body_counts.get(token, 0)
        if occurrences:
            # R-3 applies the norm to the already-capped body contribution.
            contribution += (
                BODY_WEIGHT * min(occurrences, BODY_OCCURRENCE_CAP) * length_norm
            )
        idf = stats.idf(token)
        total += contribution * idf
    return total


def excerpt(query: str, skill: Skill) -> str:
    """Bounded snippet around the first matched body region (≤ 400 chars).

    Falls back to the description head when the match lives only in
    title/tags — excerpts must never exceed the cap regardless of source.
    """
    query_tokens = tokenize_query(query)
    body_lower = skill.body.lower()
    first_pos = -1
    for token in query_tokens:
        pos = body_lower.find(token)
        if pos != -1 and (first_pos == -1 or pos < first_pos):
            first_pos = pos
    if first_pos == -1:
        return skill.description[:EXCERPT_MAX_CHARS]
    window = skill.body[first_pos : first_pos + EXCERPT_MAX_CHARS]
    if len(window) == EXCERPT_MAX_CHARS and first_pos + len(window) < len(
        skill.body
    ):
        window = window.rstrip() + "…"
    return window


@dataclass(frozen=True)
class SearchHit:
    skill: Skill
    score: float
    excerpt: str


def body_md5(skill: Skill) -> str:
    """The content-identity key R-7 de-duplicates on.

    MD5 here is a **content-identity key, not a security digest** — it matches
    the ``body_md5`` the label fixture already pins, so the identity key is
    consistent with the measurement artifact. A future security review should
    not read this as a weak hash in a security context. This is the only hashing
    in ``skills-hub``; none existed before SPEC-066.
    """
    return hashlib.md5(skill.body.encode("utf-8")).hexdigest()


def rank(
    query: str, records: list[Skill], limit: int, stats: CorpusStats
) -> list[SearchHit]:
    """Score, de-duplicate, filter zeros, order by (-score, skill_id), cap.

    ``stats`` is an explicit required parameter (R-2): ``rank`` is synchronous
    and pure, so the caller — not ``rank`` — supplies the corpus statistics.

    SPEC-066 R-7 collapses hits whose ``md5(body)`` matches one already kept
    **before** the sort and **before** ``[:limit]``, retaining the lowest
    ``skill_id`` (consistent with the ascending tie-break, so the survivor is
    deterministic regardless of input order). De-duplication must precede
    truncation: the measured defect was a duplicate *wasting a result slot*, not
    duplicate output. This is unconditional (not one of the four flags) and is a
    no-op on a duplicate-free corpus, so the fidelity gate still reproduces the
    shipped ordering exactly.
    """
    hits = []
    for skill in records:
        value = score(query, skill, stats)
        if value <= 0.0:
            continue
        hits.append(
            SearchHit(skill=skill, score=value, excerpt=excerpt(query, skill))
        )
    deduped: dict[str, SearchHit] = {}
    for hit in hits:
        key = body_md5(hit.skill)
        kept = deduped.get(key)
        if kept is None or hit.skill.skill_id < kept.skill.skill_id:
            deduped[key] = hit
    result = list(deduped.values())
    result.sort(key=lambda hit: (-hit.score, hit.skill.skill_id))
    return result[:limit]
