from __future__ import annotations

import json
from datetime import datetime, timezone

from parttwin.db import get_conn


def related_decisions(original_part: str, limit: int = 8) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM vault_decisions
            WHERE original_part = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (original_part.upper(), limit),
        ).fetchall()
    return [_decision_dict(r) for r in rows]


def list_decisions(limit: int = 50) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM vault_decisions ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_decision_dict(r) for r in rows]


def approve_recommendation(
    investigation: dict,
    engineer_name: str,
    engineer_notes: str,
    action: str = "approve",
) -> dict:
    original = (investigation.get("original") or {}).get("part_number")
    rec = investigation.get("recommendation") or {}
    recommended = rec.get("part_number") if action == "approve" else None
    if action == "approve" and not recommended:
        raise ValueError("No potential replacement to approve.")
    name = (engineer_name or "").strip()
    if not name:
        raise ValueError("Engineer name is required for vault write.")
    verdict = "APPROVED_POTENTIAL" if action == "approve" else "REJECTED_BY_ENGINEER"
    snapshot = {
        "goal": investigation.get("goal"),
        "recommended": recommended,
        "verdict": rec.get("verdict") if rec else None,
        "verify_items": investigation.get("verify_items"),
        "hard_fails_seen": [
            {"part": e["part_number"], "fails": e["hard_fails"]}
            for e in investigation.get("evaluated", [])
            if e["verdict"] == "REJECT"
        ][:12],
        "disclaimer": investigation.get("disclaimer"),
        "action": action,
        "historical": False,
    }
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO vault_decisions (
                original_part, recommended_part, verdict, engineer_name,
                engineer_notes, investigation_id, snapshot_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                original,
                recommended,
                verdict,
                name,
                (engineer_notes or "").strip(),
                investigation.get("investigation_id"),
                json.dumps(snapshot, default=str),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        vault_id = int(cur.lastrowid)
    return {
        "vault_id": vault_id,
        "verdict": verdict,
        "original_part": original,
        "recommended_part": recommended,
        "engineer_name": name,
    }


def _decision_dict(row) -> dict:
    d = dict(row) if not hasattr(row, "keys") else {k: row[k] for k in row.keys()}
    raw = d.get("snapshot_json")
    if isinstance(raw, str) and raw:
        try:
            d["snapshot"] = json.loads(raw)
        except json.JSONDecodeError:
            d["snapshot"] = {}
    else:
        d["snapshot"] = {}
    return d
