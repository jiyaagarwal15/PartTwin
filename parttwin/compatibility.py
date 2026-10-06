from __future__ import annotations

import re
from typing import Any

from parttwin.config import DIMENSION_HIGH_RISK_MM, DIMENSION_VERIFY_MM

HARD_REJECT = "REJECT"
POTENTIAL = "POTENTIAL"
UNKNOWN = "UNKNOWN"

_VOLTAGE_RE = re.compile(
    r"(?P<volts>\d+(?:\.\d+)?)\s*v(?:olts?)?\s*(?P<kind>dc|ac)?",
    re.I,
)


def _norm(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text or text in {"none", "n/a", "unknown"}:
        return None
    text = re.sub(r"[\s_/]+", " ", text)
    return text


def normalize_voltage(value: Any) -> tuple[float | None, str | None]:
    if value is None:
        return None, None
    m = _VOLTAGE_RE.search(str(value))
    if not m:
        return None, _norm(value)
    volts = float(m.group("volts"))
    kind = (m.group("kind") or "").lower() or None
    return volts, kind


def voltages_match(a: Any, b: Any) -> bool | None:
    if _norm(a) is None or _norm(b) is None:
        return None
    va, ka = normalize_voltage(a)
    vb, kb = normalize_voltage(b)
    if va is None or vb is None:
        return _norm(a) == _norm(b)
    if abs(va - vb) > 0.51:
        return False
    if ka and kb and ka != kb:
        return False
    return True


def connectors_match(a: Any, b: Any) -> bool | None:
    na, nb = _norm(a), _norm(b)
    if na is None or nb is None:
        return None
    return na == nb


def functions_match(a_code: Any, b_code: Any) -> bool | None:
    na, nb = _norm(a_code), _norm(b_code)
    if na is None or nb is None:
        return None
    return na == nb


def _dim_delta(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return abs(float(a) - float(b))


def dimension_assessment(original: dict, candidate: dict) -> dict:
    axes = []
    max_delta = 0.0
    any_unknown = False
    for axis in ("length_mm", "width_mm", "height_mm"):
        delta = _dim_delta(original.get(axis), candidate.get(axis))
        if delta is None:
            any_unknown = True
            axes.append({"axis": axis, "delta_mm": None, "status": "unknown"})
            continue
        max_delta = max(max_delta, delta)
        if delta >= DIMENSION_HIGH_RISK_MM:
            status = "high"
        elif delta >= DIMENSION_VERIFY_MM:
            status = "verify"
        else:
            status = "ok"
        axes.append({"axis": axis, "delta_mm": round(delta, 2), "status": status})

    if any_unknown and max_delta == 0:
        overall = "unknown"
    elif max_delta >= DIMENSION_HIGH_RISK_MM:
        overall = "high"
    elif max_delta >= DIMENSION_VERIFY_MM:
        overall = "verify"
    else:
        overall = "ok"
    return {"axes": axes, "max_delta_mm": round(max_delta, 2), "overall": overall}


def fingerprint(part: dict) -> dict:
    return {
        "part_number": part["part_number"],
        "function_code": part.get("function_code"),
        "function_label": part.get("function_label"),
        "voltage": part.get("voltage"),
        "connector": part.get("connector"),
        "length_mm": part.get("length_mm"),
        "width_mm": part.get("width_mm"),
        "height_mm": part.get("height_mm"),
        "mounting": part.get("mounting"),
        "io_type": part.get("io_type"),
        "channels": part.get("channels"),
        "ip_rating": part.get("ip_rating"),
        "status": part.get("status"),
    }


def evaluate_candidate(original: dict, candidate: dict, semantic_score: float = 0.0) -> dict:
    """Deterministic compatibility. Semantic score is display-only and cannot pass a hard fail."""
    checks = []
    hard_fails: list[str] = []
    unknowns: list[str] = []
    verifies: list[str] = []
    evidence_keys: list[str] = []

    fn = functions_match(original.get("function_code"), candidate.get("function_code"))
    if fn is None:
        unknowns.append("function")
        checks.append(_check("function", "unknown", original.get("function_label"), candidate.get("function_label"),
                             "Function class is missing on at least one record."))
    elif fn is False:
        hard_fails.append("function")
        checks.append(_check("function", "fail", original.get("function_label"), candidate.get("function_label"),
                             "Major functional mismatch. Similarity cannot override this."))
        evidence_keys.append("function")
    else:
        checks.append(_check("function", "pass", original.get("function_label"), candidate.get("function_label"),
                             "Function class matches."))
        evidence_keys.append("function")

    vm = voltages_match(original.get("voltage"), candidate.get("voltage"))
    if vm is None:
        unknowns.append("voltage")
        checks.append(_check("voltage", "unknown", original.get("voltage"), candidate.get("voltage"),
                             "Voltage class is missing. Treat as unverified, not as a match."))
    elif vm is False:
        hard_fails.append("voltage")
        checks.append(_check("voltage", "fail", original.get("voltage"), candidate.get("voltage"),
                             "Voltage class mismatch. Semantic similarity cannot override this hard constraint."))
        evidence_keys.append("voltage")
    else:
        checks.append(_check("voltage", "pass", original.get("voltage"), candidate.get("voltage"),
                             "Voltage class matches."))
        evidence_keys.append("voltage")

    cm = connectors_match(original.get("connector"), candidate.get("connector"))
    if cm is None:
        unknowns.append("connector")
        checks.append(_check("connector", "unknown", original.get("connector"), candidate.get("connector"),
                             "Connector is missing. Treat as unverified, not as a match."))
    elif cm is False:
        hard_fails.append("connector")
        checks.append(_check("connector", "fail", original.get("connector"), candidate.get("connector"),
                             "Connector mismatch. Field harnesses will not mate. Similarity cannot override this."))
        evidence_keys.append("connector")
    else:
        checks.append(_check("connector", "pass", original.get("connector"), candidate.get("connector"),
                             "Connector designation matches."))
        evidence_keys.append("connector")

    dims = dimension_assessment(original, candidate)
    if dims["overall"] == "unknown":
        unknowns.append("dimensions")
        verifies.append("Physical envelope cannot be confirmed from catalog — dimensional verification required.")
        checks.append(_check("dimensions", "unknown", _dim_str(original), _dim_str(candidate),
                             "Mechanical envelope incomplete."))
    elif dims["overall"] in {"verify", "high"}:
        verifies.append(
            f"Dimensional difference (max {dims['max_delta_mm']} mm) requires physical fit verification on the rail/cabinet."
        )
        checks.append(_check("dimensions", "verify", _dim_str(original), _dim_str(candidate),
                             "Soft constraint: envelope differs. Not an automatic reject; physical check is required."))
        evidence_keys.append("dimensions")
    else:
        checks.append(_check("dimensions", "pass", _dim_str(original), _dim_str(candidate),
                             "Envelope within catalog tolerance."))
        evidence_keys.append("dimensions")

    orig_io, cand_io = _norm(original.get("io_type")), _norm(candidate.get("io_type"))
    if orig_io and cand_io and orig_io != cand_io:
        verifies.append(f"Output type differs ({original.get('io_type')} vs {candidate.get('io_type')}). Confirm field devices.")
        checks.append(_check("io_type", "verify", original.get("io_type"), candidate.get("io_type"),
                             "Soft electrical preference, not a hard family reject."))
    elif orig_io and cand_io:
        checks.append(_check("io_type", "pass", original.get("io_type"), candidate.get("io_type"),
                             "I/O polarity/type matches."))

    orig_ch, cand_ch = original.get("channels"), candidate.get("channels")
    if orig_ch and cand_ch and int(cand_ch) < int(orig_ch):
        verifies.append(f"Candidate has fewer channels ({cand_ch} < {orig_ch}). Confirm I/O count.")
        checks.append(_check("channels", "verify", orig_ch, cand_ch, "Capacity risk."))
    elif orig_ch and cand_ch:
        checks.append(_check("channels", "pass", orig_ch, cand_ch, "Channel count is equal or greater."))

    orig_mt, cand_mt = _norm(original.get("mounting")), _norm(candidate.get("mounting"))
    if orig_mt and cand_mt and orig_mt != cand_mt:
        verifies.append("Mounting style differs. Confirm installation method.")
        checks.append(_check("mounting", "verify", original.get("mounting"), candidate.get("mounting"),
                             "Soft mechanical preference."))
    elif orig_mt and cand_mt:
        checks.append(_check("mounting", "pass", original.get("mounting"), candidate.get("mounting"),
                             "Mounting style matches."))

    notes = (candidate.get("notes") or "") + " " + (candidate.get("description") or "")
    if "conflict" in notes.lower():
        unknowns.append("spec_conflict")
        verifies.append("Catalog/archive conflict recorded. Do not treat specifications as fully verified.")
        checks.append(_check("record_quality", "unknown", "catalog", "conflict flag",
                             "Conflicting source notes exist."))

    missing = candidate.get("missing_fields") or []
    for field in missing:
        if field not in unknowns:
            unknowns.append(field)

    if candidate.get("part_number") == original.get("part_number"):
        verdict = "ORIGINAL"
        summary = "This is the discontinued original, not a replacement."
    elif hard_fails:
        verdict = HARD_REJECT
        summary = (
            f"Rejected on hard constraint(s): {', '.join(hard_fails)}. "
            f"Semantic score {semantic_score:.3f} was ignored for pass/fail."
        )
    elif unknowns:
        verdict = UNKNOWN
        summary = (
            "Potential/unknown — missing or conflicting interface data. "
            "Not a verified match. Engineer verification required."
        )
    else:
        verdict = POTENTIAL
        if verifies:
            summary = (
                "Potential replacement on known hard constraints. "
                "Physical/engineering verification still required. Not a certified interchange."
            )
        else:
            summary = (
                "Potential replacement on known catalog constraints. "
                "Still requires engineer approval. Not a certified interchange."
            )

    rank_key = _rank_tuple(verdict, semantic_score, dims, candidate, verifies, unknowns)
    return {
        "part_number": candidate["part_number"],
        "candidate": candidate,
        "verdict": verdict,
        "summary": summary,
        "hard_fails": hard_fails,
        "unknowns": unknowns,
        "verifies": verifies,
        "checks": checks,
        "dimensions": dims,
        "semantic_score": round(float(semantic_score), 4),
        "evidence_keys": evidence_keys,
        "rank_key": rank_key,
    }


def _check(name: str, status: str, expected, actual, detail: str) -> dict:
    return {
        "name": name,
        "status": status,
        "expected": expected,
        "actual": actual,
        "detail": detail,
    }


def _dim_str(part: dict) -> str | None:
    vals = [part.get("length_mm"), part.get("width_mm"), part.get("height_mm")]
    if any(v is None for v in vals):
        return None
    return f"{vals[0]:g} x {vals[1]:g} x {vals[2]:g} mm"


def _rank_tuple(verdict: str, semantic: float, dims: dict, candidate: dict, verifies: list, unknowns: list):
    order = {"POTENTIAL": 0, "UNKNOWN": 1, "REJECT": 2, "ORIGINAL": 3}
    cost = candidate.get("unit_cost")
    cost_score = float(cost) if cost is not None else 1e9
    dim_penalty = dims.get("max_delta_mm") or 0
    text = f"{candidate.get('notes') or ''} {candidate.get('description') or ''}".lower()
    successor = 0 if "successor" in text else 1
    avail = f"{candidate.get('status') or ''} {candidate.get('availability') or ''}".lower()
    supply_penalty = 1 if ("last_time" in avail or "last-time" in avail or "obsolete" in avail) else 0
    return (
        order.get(verdict, 9),
        successor,
        supply_penalty,
        len(unknowns),
        len(verifies),
        dim_penalty,
        -semantic,
        cost_score,
        candidate.get("part_number") or "",
    )


def preferred_recommendation(evaluated: list[dict]) -> dict | None:
    potentials = [e for e in evaluated if e["verdict"] == POTENTIAL]
    if not potentials:
        return None
    potentials.sort(key=lambda e: e["rank_key"])
    return potentials[0]
