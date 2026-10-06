from __future__ import annotations

import json

from parttwin.db import get_conn, init_db
from parttwin.seed_data import DATASHEETS, HISTORICAL_VAULT_DECISIONS, PARTS


def seed_historical_vault(conn) -> None:
    """Non-destructively seed baseline historical decisions if they do not already exist."""
    for dec in HISTORICAL_VAULT_DECISIONS:
        exists = conn.execute(
            "SELECT 1 FROM vault_decisions WHERE original_part = ? AND engineer_name = ?",
            (dec["original_part"], dec["engineer_name"]),
        ).fetchone()
        if not exists:
            conn.execute(
                """
                INSERT INTO vault_decisions (
                    original_part, recommended_part, verdict, engineer_name,
                    engineer_notes, investigation_id, snapshot_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dec["original_part"],
                    dec["recommended_part"],
                    dec["verdict"],
                    dec["engineer_name"],
                    dec["engineer_notes"],
                    None,
                    json.dumps(dec.get("snapshot") or {"historical": True}),
                    dec["created_at"],
                ),
            )


def seed(reset: bool = True, reset_vault: bool = False) -> int:
    init_db()
    with get_conn() as conn:
        if reset:
            conn.execute("DELETE FROM datasheets")
            conn.execute("DELETE FROM parts")
        if reset_vault:
            conn.execute("DELETE FROM vault_decisions")
        for part in PARTS:
            payload = dict(part)
            payload.pop("spec_conflict", None)
            payload["missing_fields"] = json.dumps(payload.get("missing_fields") or [])
            conn.execute(
                """
                INSERT OR REPLACE INTO parts (
                    part_number, name, status, family, function_code, function_label,
                    voltage, connector, length_mm, width_mm, height_mm, mounting,
                    ip_rating, channels, io_type, region, unit_cost, availability,
                    description, missing_fields, notes
                ) VALUES (
                    :part_number, :name, :status, :family, :function_code, :function_label,
                    :voltage, :connector, :length_mm, :width_mm, :height_mm, :mounting,
                    :ip_rating, :channels, :io_type, :region, :unit_cost, :availability,
                    :description, :missing_fields, :notes
                )
                """,
                payload,
            )
        for sheet in DATASHEETS:
            conn.execute(
                """
                INSERT INTO datasheets (part_number, title, section, body)
                VALUES (:part_number, :title, :section, :body)
                """,
                sheet,
            )
        seed_historical_vault(conn)
    return len(PARTS)


if __name__ == "__main__":
    n = seed()
    print(f"Seeded {n} parts")
