"""Headless check of the BX-310 investigation story."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from parttwin.agent import investigate
from parttwin.search import get_index, semantic_search
from parttwin.seed import seed
from parttwin.vault import approve_recommendation, list_decisions


def main() -> int:
    seed(reset=True)
    get_index(refresh=True)
    goal = "Part BX-310 is discontinued. Find a suitable replacement and tell me what I need to verify."
    result = investigate(goal, persist=True)

    by_pn = {e["part_number"]: e for e in result["evaluated"]}
    rec = result["recommendation"]
    errors = []

    if not rec or rec["part_number"] != "BX-421":
        errors.append(f"Expected recommendation BX-421, got {None if not rec else rec['part_number']}")
    else:
        if rec["verdict"] != "POTENTIAL":
            errors.append(f"BX-421 verdict {rec['verdict']} != POTENTIAL")
        if not any("imensional" in v or "physical" in v.lower() for v in rec["verifies"] + result["verify_items"]):
            errors.append("BX-421 should require dimensional/physical verification")

    for pn, field in (("BX-512", "connector"), ("BX-620", "voltage")):
        ev = by_pn.get(pn)
        if not ev:
            errors.append(f"{pn} missing from evaluated set")
            continue
        if ev["verdict"] != "REJECT":
            errors.append(f"{pn} expected REJECT, got {ev['verdict']}")
        if field not in ev["hard_fails"]:
            errors.append(f"{pn} expected hard fail {field}, got {ev['hard_fails']}")
        # Similarity must not rescue a hard fail
        if ev["semantic_score"] > 0.2 and ev["verdict"] != "REJECT":
            errors.append(f"{pn} high similarity overrode hard fail")

    ev715 = by_pn.get("BX-715")
    if not ev715:
        errors.append("BX-715 missing")
    elif ev715["verdict"] != "UNKNOWN":
        errors.append(f"BX-715 expected UNKNOWN, got {ev715['verdict']}")
    else:
        if "voltage" not in ev715["unknowns"] and "connector" not in ev715["unknowns"]:
            errors.append(f"BX-715 unknowns {ev715['unknowns']} should include voltage/connector")

    # Semantic search still retrieves mismatches
    hits = semantic_search("Compact Digital I/O Expansion Module 24V BX-310", k=15, exclude="BX-310")
    hit_pns = {p["part_number"] for p, _ in hits}
    for pn in ("BX-512", "BX-620", "BX-421"):
        if pn not in hit_pns and pn not in by_pn:
            errors.append(f"{pn} not discovered by search")

    saved = approve_recommendation(result, "Ada Engineer", "Fit check scheduled on Line 3.", "approve")
    vault = list_decisions()
    if not any(d["id"] == saved["vault_id"] and d["recommended_part"] == "BX-421" for d in vault):
        errors.append("Vault did not store approved BX-421")

    if errors:
        print("FAIL")
        for e in errors:
            print(" -", e)
        # helpful dump
        print("Recommendation:", None if not rec else rec["part_number"], None if not rec else rec["verdict"])
        for pn in ("BX-421", "BX-512", "BX-620", "BX-715"):
            ev = by_pn.get(pn)
            if ev:
                print(pn, ev["verdict"], ev["hard_fails"], ev["unknowns"], ev["semantic_score"])
        return 1
    print("PASS")
    print("Recommended:", rec["part_number"], rec["verdict"])
    print("BX-512", by_pn["BX-512"]["verdict"], by_pn["BX-512"]["hard_fails"], "sim", by_pn["BX-512"]["semantic_score"])
    print("BX-620", by_pn["BX-620"]["verdict"], by_pn["BX-620"]["hard_fails"], "sim", by_pn["BX-620"]["semantic_score"])
    print("BX-715", by_pn["BX-715"]["verdict"], by_pn["BX-715"]["unknowns"])
    print("Vault id", saved["vault_id"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
