#!/usr/bin/env python3
"""Offline render/import validation for the OpenObserve dashboards (SPEC-065 R-3).

This is the ``make verify`` gate for ``shared/platform-ops/dashboards/`` — the
config-as-code analog of ``kustomize build`` for the GitOps overlays. It never
touches a cluster or the network; it validates the committed dashboard JSON so
the artifact cannot silently rot between deploys. It fails (exit 1) when any
``*.dashboard.json``:

  1. does not parse as JSON, or is missing the OpenObserve dashboard envelope
     (``version`` / ``dashboardId`` / ``title`` / ``tabs[]`` / ``variables`` /
     ``defaultDatetimeDuration``);
  2. has a malformed panel (unknown ``type``/``queryType``, missing ``layout``,
     an empty query on a chart panel, or a duplicate panel id);
  3. references a metric stream that is **not** one of the OTel-mirror families
     actually emitted by the eight services (parsed from each
     ``products/*/src/*/core/metrics.py`` ``OTEL_MIRROR_FAMILIES`` via AST — no
     import, stdlib only). This is the anti-rot teeth: rename a metric in
     ``core/metrics.py`` and every dashboard still querying the old name fails
     here until it is updated;
  4. shares a ``dashboardId`` or ``title`` with another dashboard file.

Histogram families are referenced through their OpenObserve split streams
(``<name>_bucket`` / ``_sum`` / ``_count`` / ``_min`` / ``_max``), which the
metric cross-check resolves back to the base family.

Usage:
    python3 validate_dashboards.py [repo-root]

Defaults to the repository containing this script. Exits 0 on success (printing
a per-dashboard summary), 1 on any validation error.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

# --- OpenObserve dashboard vocabulary ---------------------------------------

# Panel types accepted by the OpenObserve v5+ dashboard renderer. A typo here
# (e.g. "areaa") fails the gate rather than importing as a blank panel.
ALLOWED_PANEL_TYPES = {
    "metric",
    "single-stat",
    "gauge",
    "line",
    "area",
    "area-stacked",
    "bar",
    "h-bar",
    "stacked-bar",
    "h-stacked-bar",
    "scatter",
    "pie",
    "donut",
    "heatmap",
    "table",
    "sankey",
    "maps",
    "custom-chart",
    "markdown",
    "html",
}
ALLOWED_QUERY_TYPES = {"sql", "promql", ""}
# Panels that carry no data query (static content).
CONTENT_TYPES = {"markdown", "html"}

# Histogram split-stream suffixes OpenObserve derives from an OTel histogram.
_HISTOGRAM_SUFFIXES = ("_bucket", "_sum", "_count", "_min", "_max")

# PromQL bare keywords that can appear as an identifier but are not metrics.
# (Functions are excluded structurally: an identifier followed by "(" is a call.)
_PROMQL_KEYWORDS = {
    "by",
    "without",
    "on",
    "ignoring",
    "group_left",
    "group_right",
    "offset",
    "bool",
    "and",
    "or",
    "unless",
    "le",
    "inf",
    "nan",
    "start",
    "end",
}

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_:]*")
_METRIC_WITH_SELECTOR = re.compile(r"([A-Za-z_][A-Za-z0-9_:]*)\s*\{")
_METRIC_WITH_RANGE = re.compile(r"([A-Za-z_][A-Za-z0-9_:]*)\s*\[")
_STRING_LITERAL = re.compile(r"\"[^\"]*\"|'[^']*'")
_BY_GROUP = re.compile(r"\b(?:by|without|on|ignoring|group_left|group_right)\s*\([^()]*\)")
_BRACES = re.compile(r"\{[^{}]*\}")
_BRACKETS = re.compile(r"\[[^\[\]]*\]")
_SQL_FROM = re.compile(r"\bFROM\s+\"?([A-Za-z0-9_]+)\"?", re.IGNORECASE)
_SQL_JOIN = re.compile(r"\bJOIN\s+\"?([A-Za-z0-9_]+)\"?", re.IGNORECASE)


def _promql_metric_refs(expr: str) -> set[str]:
    """Extract metric-stream names referenced by a PromQL expression."""
    s = _STRING_LITERAL.sub(" ", expr)
    refs: set[str] = set()
    refs.update(_METRIC_WITH_SELECTOR.findall(s))
    refs.update(_METRIC_WITH_RANGE.findall(s))
    # Drop selector/range bodies and label-list groups so their contents (label
    # names, "5m", regex values) are never mistaken for bare metric references.
    s = _BY_GROUP.sub(" ", s)
    s = _BRACES.sub(" ", s)
    s = _BRACKETS.sub(" ", s)
    for m in _IDENT.finditer(s):
        name = m.group(0)
        if name in _PROMQL_KEYWORDS:
            continue
        # An identifier immediately followed by "(" is a function/aggregate call.
        rest = s[m.end():]
        if rest.lstrip().startswith("("):
            continue
        refs.add(name)
    return refs


def _sql_metric_refs(expr: str) -> set[str]:
    """Extract metric-stream names referenced by a metrics SQL query."""
    return set(_SQL_FROM.findall(expr)) | set(_SQL_JOIN.findall(expr))


def _resolve(name: str, catalog: dict[str, str]) -> bool:
    """True when a referenced stream maps to an emitted family.

    A bare counter/gauge name matches directly; a histogram split stream
    (``<base>_bucket`` etc.) resolves to its base histogram family.
    """
    if name in catalog:
        return True
    for suffix in _HISTOGRAM_SUFFIXES:
        if name.endswith(suffix) and catalog.get(name[: -len(suffix)]) == "histogram":
            return True
    return False


def _emitted_catalog(repo: Path) -> dict[str, str]:
    """metric name -> kind, parsed from every service's OTEL_MIRROR_FAMILIES."""
    catalog: dict[str, str] = {}
    files = sorted((repo / "products").glob("*/src/*/core/metrics.py"))
    if not files:
        raise SystemExit(
            "validate_dashboards: no products/*/src/*/core/metrics.py found under "
            f"{repo} — cannot cross-check dashboard metric references."
        )
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        families = None
        for node in tree.body:
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
                value = node.value
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
                value = node.value
            else:
                continue
            if any(isinstance(t, ast.Name) and t.id == "OTEL_MIRROR_FAMILIES" for t in targets):
                families = ast.literal_eval(value)
        if families is None:
            raise SystemExit(
                f"validate_dashboards: {path} declares no OTEL_MIRROR_FAMILIES "
                "(expected after SPEC-065 R-2)."
            )
        for entry in families:
            name, kind = entry[0], entry[1]
            catalog[str(name)] = str(kind)
    return catalog


def _validate_dashboard(path: Path, catalog: dict[str, str], errors: list[str]) -> dict | None:
    def err(msg: str) -> None:
        errors.append(f"{path.name}: {msg}")

    try:
        dash = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        err(f"invalid JSON ({exc})")
        return None
    if not isinstance(dash, dict):
        err("top level is not a JSON object")
        return None

    # --- envelope ---
    if not isinstance(dash.get("version"), int) or dash["version"] < 5:
        err(f"version must be an int >= 5 (got {dash.get('version')!r})")
    for key in ("dashboardId", "title"):
        if not isinstance(dash.get(key), str) or not dash[key].strip():
            err(f"{key} must be a non-empty string (got {dash.get(key)!r})")
    tabs = dash.get("tabs")
    if not isinstance(tabs, list) or not tabs:
        err("tabs must be a non-empty list")
        return dash
    if not isinstance(dash.get("variables"), dict):
        err("variables must be an object")
    if not isinstance(dash.get("defaultDatetimeDuration"), dict):
        err("defaultDatetimeDuration must be an object")

    seen_panel_ids: set[str] = set()
    for ti, tab in enumerate(tabs):
        if not isinstance(tab, dict):
            err(f"tabs[{ti}] is not an object")
            continue
        if not isinstance(tab.get("name"), str) or not tab["name"].strip():
            err(f"tabs[{ti}].name must be a non-empty string")
        if "tabId" not in tab:
            err(f"tabs[{ti}] missing tabId")
        panels = tab.get("panels")
        if not isinstance(panels, list):
            err(f"tabs[{ti}].panels must be a list")
            continue
        for pi, panel in enumerate(panels):
            _validate_panel(panel, catalog, err, seen_panel_ids, f"tabs[{ti}].panels[{pi}]")
    return dash


def _validate_panel(panel, catalog, err, seen_ids, where) -> None:
    if not isinstance(panel, dict):
        err(f"{where} is not an object")
        return
    pid = panel.get("id")
    if not isinstance(pid, str) or not pid.strip():
        err(f"{where} missing string id")
    elif pid in seen_ids:
        err(f"{where} duplicate panel id {pid!r}")
    else:
        seen_ids.add(pid)

    ptype = panel.get("type")
    if ptype not in ALLOWED_PANEL_TYPES:
        err(f"{where} unknown panel type {ptype!r}")

    qtype = panel.get("queryType", "")
    if qtype not in ALLOWED_QUERY_TYPES:
        err(f"{where} unknown queryType {qtype!r}")

    layout = panel.get("layout")
    if not isinstance(layout, dict) or not all(
        isinstance(layout.get(k), int) for k in ("x", "y", "w", "h")
    ):
        err(f"{where} layout must have integer x/y/w/h (got {layout!r})")

    queries = panel.get("queries")
    if not isinstance(queries, list):
        err(f"{where} queries must be a list")
        return

    if ptype in CONTENT_TYPES:
        content_key = "markdownContent" if ptype == "markdown" else "htmlContent"
        if not isinstance(panel.get(content_key), str) or not panel[content_key].strip():
            err(f"{where} {ptype} panel has empty {content_key}")
        return

    # Chart/stat panels must carry at least one non-empty query whose metric
    # references all resolve to emitted families.
    if not queries:
        err(f"{where} {ptype} panel has no queries")
        return
    for qi, q in enumerate(queries):
        if not isinstance(q, dict):
            err(f"{where}.queries[{qi}] is not an object")
            continue
        expr = q.get("query")
        if not isinstance(expr, str) or not expr.strip():
            err(f"{where}.queries[{qi}] has an empty query string")
            continue
        if qtype == "promql":
            refs = _promql_metric_refs(expr)
        elif qtype == "sql":
            refs = _sql_metric_refs(expr)
        else:
            err(f"{where}.queries[{qi}] chart panel must set queryType sql or promql")
            continue
        if not refs:
            err(f"{where}.queries[{qi}] references no metric stream: {expr!r}")
        for name in sorted(refs):
            if not _resolve(name, catalog):
                err(
                    f"{where}.queries[{qi}] references unknown metric {name!r} "
                    "(not in any service's OTEL_MIRROR_FAMILIES)"
                )


def main(argv: list[str]) -> int:
    here = Path(__file__).resolve().parent
    repo = Path(argv[1]).resolve() if len(argv) > 1 else here.parents[2]
    dash_dir = repo / "shared" / "platform-ops" / "dashboards"
    if not dash_dir.is_dir():
        print(f"validate_dashboards: no dashboards dir at {dash_dir}", file=sys.stderr)
        return 1

    files = sorted(dash_dir.glob("*.dashboard.json"))
    if not files:
        print(
            f"validate_dashboards: no *.dashboard.json under {dash_dir} — the R-3 "
            "artifact is missing (refusing to pass silently).",
            file=sys.stderr,
        )
        return 1

    catalog = _emitted_catalog(repo)
    errors: list[str] = []
    seen_ids: dict[str, str] = {}
    seen_titles: dict[str, str] = {}
    total_panels = 0

    for path in files:
        dash = _validate_dashboard(path, catalog, errors)
        if not isinstance(dash, dict):
            continue
        did = dash.get("dashboardId")
        title = dash.get("title")
        if isinstance(did, str):
            if did in seen_ids:
                errors.append(f"{path.name}: duplicate dashboardId {did!r} (also in {seen_ids[did]})")
            else:
                seen_ids[did] = path.name
        if isinstance(title, str):
            if title in seen_titles:
                errors.append(f"{path.name}: duplicate title {title!r} (also in {seen_titles[title]})")
            else:
                seen_titles[title] = path.name
        total_panels += sum(len(t.get("panels", [])) for t in dash.get("tabs", []) if isinstance(t, dict))

    if errors:
        print(f"validate_dashboards: FAILED ({len(errors)} problem(s))", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    print(
        f"validate_dashboards: OK — {len(files)} dashboard(s), {total_panels} panel(s); "
        f"all metric references resolve to {len(catalog)} emitted OTel-mirror families."
    )
    for path in files:
        print(f"  ✓ {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
