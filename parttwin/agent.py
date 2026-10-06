from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from parttwin.compatibility import evaluate_candidate, fingerprint, preferred_recommendation
from parttwin.config import SEMANTIC_TOP_K, STAGES
from parttwin.db import get_conn, get_datasheets, get_part, search_parts_keyword
from parttwin.llm import explain_investigation, llm_available
from parttwin.search import part_document, semantic_search
from parttwin.vault import related_decisions

PART_RE = re.compile(r"\b([A-Z]{1,3}-\d{2,4}[A-Z]?)\b", re.I)


def parse_goal(goal: str) -> dict:
    found = [m.group(1).upper() for m in PART_RE.finditer(goal or "")]
    original = found[0] if found else None
    return {
        "goal": goal.strip(),
        "mentioned_parts": found,
        "original_part": original,
        "intent": "replacement_search",
    }


def _step(stage: str, title: str, detail: str, status: str = "done", data: dict | None = None) -> dict:
    return {
        "stage": stage,
        "title": title,
        "detail": detail,
        "status": status,
        "data": data or {},
    }


def _merge_candidates(semantic: list[tuple[dict, float]], keyword: list[dict], original_pn: str) -> list[tuple[dict, float]]:
    scores: dict[str, float] = {}
    parts: dict[str, dict] = {}
    for part, score in semantic:
        pn = part["part_number"]
        if pn == original_pn:
            continue
        parts[pn] = part
        scores[pn] = max(scores.get(pn, 0.0), score)
    for part in keyword:
        pn = part["part_number"]
        if pn == original_pn:
            continue
        parts[pn] = part
        scores[pn] = max(scores.get(pn, 0.0), 0.05)
    ranked = sorted(parts.values(), key=lambda p: scores[p["part_number"]], reverse=True)
    return [(p, scores[p["part_number"]]) for p in ranked]


def collect_evidence(original: dict, evaluated: dict) -> list[dict]:
    items = []
    cand = evaluated["candidate"]
    items.append({
        "source": f"Catalog {original['part_number']}",
        "section": "Compatibility fingerprint",
        "claim": (
            f"{original['function_label']}; {original.get('voltage')}; {original.get('connector')}; "
            f"{original.get('length_mm')}x{original.get('width_mm')}x{original.get('height_mm')} mm"
        ),
        "supports": original["part_number"],
    })
    for check in evaluated["checks"]:
        if check["status"] in {"fail", "pass", "verify", "unknown"}:
            items.append({
                "source": f"Catalog {cand['part_number']}",
                "section": check["name"],
                "claim": f"{check['detail']} Expected {check['expected']!r}, actual {check['actual']!r}.",
                "supports": cand["part_number"],
                "status": check["status"],
            })
    for sheet in get_datasheets(cand["part_number"]):
        items.append({
            "source": sheet["title"],
            "section": sheet["section"],
            "claim": sheet["body"],
            "supports": cand["part_number"],
            "status": "document",
        })
    return items


def build_risk_radar(evaluated: list[dict], recommendation: dict | None) -> dict:
    risks = []
    for ev in evaluated:
        pn = ev["part_number"]
        for fail in ev["hard_fails"]:
            risks.append({
                "severity": "hard",
                "part_number": pn,
                "title": f"{fail.title()} mismatch",
                "detail": ev["summary"],
            })
        for u in ev["unknowns"]:
            risks.append({
                "severity": "unknown",
                "part_number": pn,
                "title": f"Missing/unverified: {u}",
                "detail": "Unknown data is never treated as a match.",
            })
        for v in ev["verifies"]:
            risks.append({
                "severity": "verify",
                "part_number": pn,
                "title": "Verification required",
                "detail": v,
            })
    rec_risks = [r for r in risks if recommendation and r["part_number"] == recommendation["part_number"]]
    rec_risks = rec_risks or [
        {
            "severity": "info",
            "part_number": recommendation["part_number"] if recommendation else None,
            "title": "Engineer approval required",
            "detail": "A passing catalog check is a potential replacement, not a certified interchange.",
        }
    ] if recommendation else []
    return {
        "all": risks,
        "for_recommendation": rec_risks,
        "hard_reject_count": sum(1 for e in evaluated if e["verdict"] == "REJECT"),
        "unknown_count": sum(1 for e in evaluated if e["verdict"] == "UNKNOWN"),
        "potential_count": sum(1 for e in evaluated if e["verdict"] == "POTENTIAL"),
    }


def investigate(goal: str, persist: bool = True) -> dict:
    steps: list[dict] = []
    parsed = parse_goal(goal)
    original_pn = parsed["original_part"]

    steps.append(_step(
        "UNDERSTAND",
        "Goal interpreted",
        (
            f"Replacement investigation for {original_pn}."
            if original_pn else
            "No catalog part number detected in the goal. Ask the engineer to include a part number such as BX-310."
        ),
        data=parsed,
    ))

    if not original_pn:
        result = _empty_result(goal, steps, "Could not identify the original part number.")
        if persist:
            _save_investigation(result)
        return result

    original = get_part(original_pn)
    if not original:
        steps.append(_step("UNDERSTAND", "Part not in catalog", f"{original_pn} is not in the internal sample catalog."))
        result = _empty_result(goal, steps, f"{original_pn} was not found in the catalog.")
        if persist:
            _save_investigation(result)
        return result

    fp = fingerprint(original)
    steps.append(_step(
        "UNDERSTAND",
        "Compatibility fingerprint",
        (
            f"{original['name']} — {original.get('function_label')}, "
            f"{original.get('voltage')}, {original.get('connector')}, "
            f"envelope {original.get('length_mm')}x{original.get('width_mm')}x{original.get('height_mm')} mm. "
            f"Status: {original.get('status')}."
        ),
        data=fp,
    ))

    query_text = " ".join([
        goal,
        part_document(original),
        original.get("function_label") or "",
        "digital io expansion compact module",
    ])
    semantic_hits = semantic_search(query_text, k=SEMANTIC_TOP_K, exclude=original_pn)
    keyword_hits = search_parts_keyword("Compact Digital I/O")
    # Always surface demo relatives if investigating BX-310 so the story is complete
    for extra in ("BX-421", "BX-512", "BX-620", "BX-715"):
        p = get_part(extra)
        if p and p["part_number"] != original_pn:
            keyword_hits.append(p)

    merged = _merge_candidates(semantic_hits, keyword_hits, original_pn)
    steps.append(_step(
        "SEARCH",
        "Catalog + semantic search",
        f"Retrieved {len(merged)} unique candidates. Similarity is used for discovery only.",
        data={
            "semantic": [{"part_number": p["part_number"], "score": round(s, 4)} for p, s in semantic_hits],
            "count": len(merged),
        },
    ))

    evaluated = [evaluate_candidate(original, part, score) for part, score in merged]
    evaluated.sort(key=lambda e: e["rank_key"])

    rejects = [e for e in evaluated if e["verdict"] == "REJECT"]
    unknowns = [e for e in evaluated if e["verdict"] == "UNKNOWN"]
    potentials = [e for e in evaluated if e["verdict"] == "POTENTIAL"]

    highlight = []
    for pn in ("BX-512", "BX-620", "BX-715", "BX-421"):
        hit = next((e for e in evaluated if e["part_number"] == pn), None)
        if hit:
            highlight.append(f"{pn}: {hit['verdict']}")

    steps.append(_step(
        "CHECK",
        "Hard constraints applied",
        (
            f"{len(rejects)} rejected, {len(unknowns)} unknown, {len(potentials)} potential. "
            "Connector, voltage, and function mismatches reject regardless of semantic score. "
            + ("Demo highlights: " + ", ".join(highlight) if highlight else "")
        ),
        data={"rejects": [e["part_number"] for e in rejects[:12]]},
    ))

    compare_rows = []
    focus = []
    for pn in ("BX-421", "BX-512", "BX-620", "BX-715"):
        hit = next((e for e in evaluated if e["part_number"] == pn), None)
        if hit:
            focus.append(hit)
    if not focus:
        focus = evaluated[:6]
    for e in focus:
        compare_rows.append({
            "part_number": e["part_number"],
            "verdict": e["verdict"],
            "semantic_score": e["semantic_score"],
            "hard_fails": e["hard_fails"],
            "unknowns": e["unknowns"],
            "voltage": e["candidate"].get("voltage"),
            "connector": e["candidate"].get("connector"),
            "function": e["candidate"].get("function_label"),
            "dimensions": e["dimensions"],
        })
    steps.append(_step(
        "COMPARE",
        "Candidate comparison",
        "Side-by-side of key candidates. High similarity with a hard fail remains REJECT.",
        data={"rows": compare_rows},
    ))

    investigation_notes = []
    for e in evaluated:
        if e["verdict"] in {"POTENTIAL", "UNKNOWN", "REJECT"} and e["part_number"] in {
            "BX-421", "BX-512", "BX-620", "BX-715"
        } or (e["verdict"] == "POTENTIAL" and e == preferred_recommendation(evaluated)):
            sheets = get_datasheets(e["part_number"])
            if sheets:
                investigation_notes.append(
                    f"{e['part_number']}: retrieved {len(sheets)} internal datasheet excerpt(s)."
                )
            else:
                investigation_notes.append(
                    f"{e['part_number']}: no datasheet excerpts on file; catalog fields only."
                )
    steps.append(_step(
        "INVESTIGATE",
        "Additional evidence retrieval",
        " ".join(investigation_notes) or "No extra documents retrieved.",
        data={"notes": investigation_notes},
    ))

    recommendation = preferred_recommendation(evaluated)
    radar = build_risk_radar(evaluated, recommendation)
    rec_verify = []
    if recommendation:
        rec_verify = list(recommendation["verifies"])
        rec_verify.append("Engineer must confirm physical fit, wiring, and application before adoption.")
        rec_verify.append("This is a potential replacement from an internal fictional catalog — not a safety certification.")
    steps.append(_step(
        "RISK ASSESSMENT",
        "Risk Radar",
        (
            f"Hard rejects: {radar['hard_reject_count']}. Unknown records: {radar['unknown_count']}. "
            f"Potential survivors: {radar['potential_count']}."
        ),
        data=radar,
    ))

    evidence = []
    if recommendation:
        evidence = collect_evidence(original, recommendation)
        for e in evaluated:
            if e["part_number"] in {"BX-512", "BX-620", "BX-715"}:
                evidence.extend(collect_evidence(original, e)[:4])
    steps.append(_step(
        "EVIDENCE",
        "Evidence layer",
        f"{len(evidence)} internal catalog/datasheet claims attached. Sources are fictional/internal only.",
        data={"count": len(evidence)},
    ))

    if recommendation:
        rec_text = (
            f"{recommendation['part_number']} is a POTENTIAL replacement for {original_pn}. "
            f"Function, voltage, and connector match on catalog data. "
            + ("Dimensional difference requires physical verification. " if recommendation["verifies"] else "")
            + "It is not a certified interchange. Engineer approval is required before the Knowledge Vault stores this decision."
        )
    else:
        rec_text = (
            f"No potential replacement passed hard constraints for {original_pn}. "
            "Unknowns are listed for verification; rejected parts must not be adopted."
        )
    steps.append(_step("RECOMMEND", "Recommendation", rec_text, data={
        "recommended_part": recommendation["part_number"] if recommendation else None,
        "caveat": "potential_only",
    }))

    steps.append(_step(
        "ENGINEER APPROVAL",
        "Waiting for engineer",
        "The agent does not adopt a replacement. Approve or reject explicitly to write the Knowledge Vault.",
        status="pending",
    ))
    steps.append(_step(
        "KNOWLEDGE VAULT",
        "Not written yet",
        "Vault write happens only after explicit engineer approval.",
        status="pending",
    ))

    prior = related_decisions(original_pn)
    briefing_payload = {
        "goal": goal,
        "original": original_pn,
        "recommendation": recommendation["part_number"] if recommendation else None,
        "verifies": rec_verify,
        "rejects": [{"part": e["part_number"], "reason": e["hard_fails"]} for e in rejects[:8]],
    }
    llm_text = explain_investigation(briefing_payload) if llm_available() else None

    result = {
        "goal": goal,
        "original": original,
        "fingerprint": fp,
        "steps": steps,
        "evaluated": evaluated,
        "focus": focus,
        "recommendation": recommendation,
        "radar": radar,
        "evidence": evidence,
        "verify_items": rec_verify,
        "prior_decisions": prior,
        "llm_briefing": llm_text,
        "llm_mode": "llm" if llm_text else "deterministic",
        "stages": STAGES,
        "disclaimer": (
            "Fictional internal catalog for demonstration. "
            "Potential replacements are not certified, safety-approved, or production-released."
        ),
    }
    if persist:
        result["investigation_id"] = _save_investigation(result)
    return result


def _empty_result(goal: str, steps: list[dict], message: str) -> dict:
    pending_rest = [s for s in STAGES if s not in {st["stage"] for st in steps}]
    for stage in pending_rest:
        steps.append(_step(stage, "Skipped", message, status="blocked"))
    return {
        "goal": goal,
        "original": None,
        "fingerprint": None,
        "steps": steps,
        "evaluated": [],
        "focus": [],
        "recommendation": None,
        "radar": {"all": [], "for_recommendation": [], "hard_reject_count": 0, "unknown_count": 0, "potential_count": 0},
        "evidence": [],
        "verify_items": [],
        "prior_decisions": [],
        "llm_briefing": None,
        "llm_mode": "deterministic",
        "stages": STAGES,
        "error": message,
        "disclaimer": "Fictional internal catalog for demonstration.",
    }


def _save_investigation(result: dict) -> int:
    slim = {
        "goal": result.get("goal"),
        "original": (result.get("original") or {}).get("part_number") if result.get("original") else None,
        "recommended": (result.get("recommendation") or {}).get("part_number") if result.get("recommendation") else None,
        "error": result.get("error"),
        "llm_mode": result.get("llm_mode"),
    }
    # Store a JSON-safe copy without sqlite internals
    dumpable = json.loads(json.dumps(result, default=str))
    dumpable.pop("investigation_id", None)
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO investigations (goal, original_part, created_at, result_json)
            VALUES (?, ?, ?, ?)
            """,
            (
                result.get("goal"),
                slim["original"],
                datetime.now(timezone.utc).isoformat(),
                json.dumps(dumpable),
            ),
        )
        return int(cur.lastrowid)
