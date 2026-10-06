from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from parttwin.agent import investigate
from parttwin.config import STAGES
from parttwin.db import init_db, list_parts
from parttwin.search import get_index
from parttwin.seed import seed
from parttwin.vault import approve_recommendation, list_decisions

DEMO_GOAL = (
    "Part BX-310 is discontinued. Find a suitable replacement and tell me what I need to verify."
)

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@500;600&display=swap');

html, body, [class*="css"]  {
  font-family: "IBM Plex Sans", sans-serif;
}
.stApp {
  background:
    radial-gradient(1200px 500px at 10% -10%, #1b3a4a 0%, transparent 50%),
    linear-gradient(180deg, #0b1117 0%, #0e151c 40%, #0b1117 100%);
  color: #e8eef4;
}
section[data-testid="stSidebar"] {
  background: #0a1218;
  border-right: 1px solid #1f3344;
}
.pt-kicker {
  letter-spacing: 0.18em;
  font-size: 11px;
  color: #7fd0c5;
  text-transform: uppercase;
  font-weight: 600;
}
.pt-title {
  font-size: 28px;
  font-weight: 700;
  margin: 0 0 4px 0;
  color: #f4f8fb;
}
.pt-sub {
  color: #9bb0c0;
  margin-bottom: 1.2rem;
}
.stage-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 8px 0 18px 0;
}
.stage {
  font-size: 10px;
  letter-spacing: 0.06em;
  padding: 6px 8px;
  border: 1px solid #2a4256;
  border-radius: 4px;
  color: #8ea3b5;
  background: #101820;
}
.stage.done { border-color: #2f6f62; color: #b7eee4; background: #0f2a26; }
.stage.pending { border-color: #6a5420; color: #f0d48a; background: #241c0c; }
.stage.blocked { border-color: #5a2a2a; color: #f0b4b4; background: #241111; }
.card {
  background: #121b24;
  border: 1px solid #243546;
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 10px;
}
.pn { font-family: "IBM Plex Mono", monospace; font-weight: 600; }
.badge {
  display: inline-block;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  padding: 3px 8px;
  border-radius: 999px;
  margin-left: 8px;
}
.badge.POTENTIAL { background: #163528; color: #8ee0b5; }
.badge.REJECT { background: #3a1616; color: #ffb4b4; }
.badge.UNKNOWN { background: #3a3116; color: #f3d889; }
.badge.ORIGINAL { background: #1c2a3a; color: #bcd; }
.muted { color: #8ea3b5; font-size: 13px; }
.risk-hard { border-left: 3px solid #e05d5d; padding-left: 10px; margin: 8px 0; }
.risk-unknown { border-left: 3px solid #e0b85d; padding-left: 10px; margin: 8px 0; }
.risk-verify { border-left: 3px solid #5db7e0; padding-left: 10px; margin: 8px 0; }
.risk-info { border-left: 3px solid #7fd0c5; padding-left: 10px; margin: 8px 0; }
.disclaimer {
  border: 1px solid #3a3116;
  background: #1a160c;
  color: #e6d7a2;
  padding: 10px 12px;
  border-radius: 8px;
  font-size: 13px;
}
</style>
"""


def _ensure_db():
    init_db()
    parts = list_parts()
    if len(parts) < 20:
        seed(reset=True)
        get_index(refresh=True)


def _stage_class(steps, name: str) -> str:
    matches = [s for s in steps if s["stage"] == name]
    if not matches:
        return "pending"
    statuses = {m["status"] for m in matches}
    if "blocked" in statuses:
        return "blocked"
    if statuses == {"pending"}:
        return "pending"
    return "done"


def render_header():
    st.markdown(
        """
        <div class="pt-kicker">Agentic engineering teammate</div>
        <div class="pt-title">PartTwin</div>
        <div class="pt-sub">Legacy part replacement investigations — evidence first, similarity second.</div>
        """,
        unsafe_allow_html=True,
    )


def render_pipeline(steps):
    chips = []
    for name in STAGES:
        cls = _stage_class(steps, name)
        chips.append(f'<span class="stage {cls}">{html.escape(name)}</span>')
    st.markdown(f'<div class="stage-row">{"".join(chips)}</div>', unsafe_allow_html=True)


def verdict_badge(verdict: str) -> str:
    v = html.escape(verdict)
    return f'<span class="badge {v}">{v}</span>'


def render_investigation(result: dict):
    render_pipeline(result.get("steps") or [])
    if result.get("error"):
        st.error(result["error"])
        return

    original = result["original"]
    rec = result.get("recommendation")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Original", original["part_number"])
    c2.metric("Status", original.get("status", "—"))
    c3.metric("Potential survivors", result["radar"]["potential_count"])
    c4.metric("Hard rejects", result["radar"]["hard_reject_count"])

    st.markdown(
        f'<div class="disclaimer">{html.escape(result.get("disclaimer") or "")}</div>',
        unsafe_allow_html=True,
    )

    st.subheader("Investigation log")
    for step in result["steps"]:
        icon = {"done": "✅", "pending": "⏳", "blocked": "⛔"}.get(step["status"], "•")
        with st.expander(f"{icon} {step['stage']} — {step['title']}", expanded=step["stage"] in {"RECOMMEND", "RISK ASSESSMENT", "CHECK"}):
            st.write(step["detail"])

    rec_col, radar_col = st.columns((1.25, 1))
    with rec_col:
        st.subheader("Recommendation")
        if rec:
            st.markdown(
                f'<div class="card"><span class="pn">{html.escape(rec["part_number"])}</span>'
                f'{verdict_badge(rec["verdict"])}<div class="muted" style="margin-top:8px">'
                f'{html.escape(rec["summary"])}</div></div>',
                unsafe_allow_html=True,
            )
            st.markdown("**What you need to verify**")
            for item in result.get("verify_items") or []:
                st.markdown(f"- {item}")
            if result.get("llm_briefing"):
                st.info(result["llm_briefing"])
            else:
                st.caption("Deterministic engine mode (no LLM key required).")
        else:
            st.warning("No potential replacement survived hard constraints.")

        st.subheader("Candidate comparison")
        rows = []
        for e in result.get("focus") or []:
            rows.append({
                "Part": e["part_number"],
                "Verdict": e["verdict"],
                "Semantic": e["semantic_score"],
                "Voltage": e["candidate"].get("voltage"),
                "Connector": e["candidate"].get("connector"),
                "Hard fails": ", ".join(e["hard_fails"]) or "—",
                "Unknowns": ", ".join(e["unknowns"]) or "—",
                "Max Δ mm": e["dimensions"].get("max_delta_mm"),
            })
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
            st.caption("Semantic score never overrides a hard engineering mismatch.")

        st.subheader("All evaluated candidates")
        for e in result.get("evaluated") or []:
            with st.expander(f"{e['part_number']}  ·  {e['verdict']}  ·  sim {e['semantic_score']}"):
                st.write(e["summary"])
                st.write(e["candidate"].get("name"))
                for chk in e["checks"]:
                    st.markdown(
                        f"- **{chk['name']}** `{chk['status']}` — {chk['detail']} "
                        f"(expected `{chk['expected']}`, actual `{chk['actual']}`)"
                    )

    with radar_col:
        st.subheader("Risk Radar")
        rec_risks = (result.get("radar") or {}).get("for_recommendation") or []
        if rec and rec_risks:
            st.caption(f"Risks attached to {rec['part_number']}")
            for risk in rec_risks:
                cls = {"hard": "risk-hard", "unknown": "risk-unknown", "verify": "risk-verify"}.get(
                    risk["severity"], "risk-info"
                )
                st.markdown(
                    f'<div class="{cls}"><b>{html.escape(risk["title"])}</b><br>'
                    f'<span class="muted">{html.escape(risk["detail"])}</span></div>',
                    unsafe_allow_html=True,
                )
        st.caption("Catalog-wide investigation flags")
        for risk in (result.get("radar") or {}).get("all") or []:
            if rec and risk["part_number"] == rec["part_number"]:
                continue
            if risk["severity"] not in {"hard", "unknown"}:
                continue
            st.markdown(f"- `{risk['part_number']}` **{risk['title']}** — {risk['detail']}")

        st.subheader("Evidence")
        for ev in result.get("evidence") or []:
            st.markdown(
                f'<div class="card"><div class="muted">{html.escape(ev["source"])} · {html.escape(str(ev.get("section") or ""))}</div>'
                f'<div>{html.escape(ev["claim"])}</div></div>',
                unsafe_allow_html=True,
            )

        prior = result.get("prior_decisions") or []
        st.subheader("Related vault history")
        st.caption("Historical precedent used as evidence — not the current engineer's approval.")
        if not prior:
            st.caption("No prior approved decisions for this original part.")
        for d in prior:
            is_hist = d.get("snapshot", {}).get("historical", True)
            tag = "HISTORICAL EVIDENCE" if is_hist else "PREVIOUS DECISION"
            st.markdown(
                f'<div class="card" style="padding:10px 14px; margin-bottom:8px; border-left:3px solid #7fd0c5;">'
                f'<span class="badge" style="background:#1b3a4a;color:#7fd0c5;font-size:10px;padding:2px 6px;">{tag}</span> '
                f'<span class="pn">{html.escape(d.get("recommended_part") or "—")}</span> '
                f'{verdict_badge(d["verdict"])}<br>'
                f'<div class="muted" style="margin-top:4px;">Reviewed by <b>{html.escape(d["engineer_name"])}</b> · {html.escape(str(d["created_at"])[:10])}</div>'
                + (f'<div class="muted" style="font-size:12px;margin-top:2px;">{html.escape(d["engineer_notes"])}</div>' if d.get("engineer_notes") else "")
                + f'</div>',
                unsafe_allow_html=True,
            )

    st.subheader("Engineer approval")
    st.write("The agent will not store a replacement until an engineer explicitly approves it.")

    last_vault = st.session_state.get("last_vault")
    rec = result.get("recommendation")
    orig_pn = (result.get("original") or {}).get("part_number")

    if last_vault and last_vault.get("original_part") == orig_pn:
        if last_vault.get("verdict") == "APPROVED_POTENTIAL":
            st.success(f"✓ {last_vault.get('recommended_part') or 'BX-421'} approved and saved to Knowledge Vault")
        else:
            st.warning("✓ Recommendation rejected and recorded in Knowledge Vault")

    with st.form("approval"):
        name = st.text_input("Engineer name")
        notes = st.text_area("Notes (fit check, remaining risk, conditions)")
        col_a, col_b = st.columns(2)
        with col_a:
            approve = st.form_submit_button("Approve potential replacement", type="primary")
        with col_b:
            reject = st.form_submit_button("Reject recommendation")
        if approve or reject:
            try:
                saved = approve_recommendation(
                    result,
                    engineer_name=name,
                    engineer_notes=notes,
                    action="approve" if approve else "reject",
                )
                if "session_vault_ids" not in st.session_state:
                    st.session_state["session_vault_ids"] = set()
                st.session_state["session_vault_ids"].add(saved["vault_id"])
                st.session_state["last_vault"] = saved

                # Update workflow stages
                for stp in result.get("steps", []):
                    if stp["stage"] == "ENGINEER APPROVAL":
                        stp["status"] = "done"
                        stp["detail"] = f"{'Approved' if approve else 'Rejected'} by {saved['engineer_name']} ({saved['verdict']})"
                    elif stp["stage"] == "KNOWLEDGE VAULT":
                        stp["status"] = "done"
                        stp["detail"] = f"Saved to Knowledge Vault with record ID #{saved['vault_id']}"

                if approve:
                    target_part = saved.get("recommended_part") or (rec.get("part_number") if rec else "BX-421")
                    st.success(f"✓ {target_part} approved and saved to Knowledge Vault")
                else:
                    st.warning("✓ Recommendation rejected and recorded in Knowledge Vault")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


def render_vault():
    st.subheader("Knowledge Vault")
    st.caption("Only engineer-approved (or explicitly rejected) decisions are stored.")

    rows = list_decisions()
    if not rows:
        st.info("Vault is empty.")
        return

    session_ids = st.session_state.get("session_vault_ids", set())

    # Distinguish current session newly approved decisions from historical evidence
    new_decisions = [d for d in rows if d["id"] in session_ids]
    if new_decisions:
        st.markdown("#### Newly Approved Decisions (Current Session)")
        for d in new_decisions:
            st.markdown(
                f'<div class="card" style="border-left: 4px solid #8ee0b5; margin-bottom: 12px;">'
                f'<span class="badge" style="background:#163528;color:#8ee0b5;font-size:11px;">NEWLY APPROVED</span> '
                f'<span class="pn">{html.escape(d["original_part"])} → {html.escape(d.get("recommended_part") or "—")}</span> '
                f'{verdict_badge(d["verdict"])}<br>'
                f'<div style="margin-top:6px;"><b>Approved by:</b> {html.escape(d["engineer_name"])} · <b>Timestamp:</b> {html.escape(str(d["created_at"]))}</div>'
                + (f'<div class="muted" style="margin-top:4px;"><b>Engineer Notes:</b> {html.escape(d["engineer_notes"])}</div>' if d.get("engineer_notes") else "")
                + f'</div>',
                unsafe_allow_html=True,
            )

    st.markdown("#### All Knowledge Vault Records")
    st.caption("Historical decisions used as evidence vs. newly approved decisions.")
    table = []
    for d in rows:
        is_new = d["id"] in session_ids
        category = "★ Newly Approved" if is_new else "Historical Evidence"
        table.append({
            "ID": d["id"],
            "Record Type": category,
            "Original": d["original_part"],
            "Recommended": d.get("recommended_part") or "—",
            "Verdict": d["verdict"],
            "Engineer": d["engineer_name"],
            "Notes": d.get("engineer_notes") or "",
            "Timestamp": d["created_at"],
        })
    st.dataframe(pd.DataFrame(table), hide_index=True, use_container_width=True)


def render_catalog():
    st.subheader("Internal sample catalog")
    df = pd.DataFrame(list_parts())
    keep = [
        "part_number", "name", "status", "function_label", "voltage", "connector",
        "length_mm", "width_mm", "height_mm", "availability", "unit_cost",
    ]
    st.dataframe(df[keep], hide_index=True, use_container_width=True)


def main():
    st.set_page_config(page_title="PartTwin", page_icon="⧉", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    _ensure_db()
    render_header()

    def _load_demo_goal():
        st.session_state["goal_input"] = DEMO_GOAL

    with st.sidebar:
        st.markdown("**Investigation goal**")
        if "goal_input" not in st.session_state:
            st.session_state["goal_input"] = DEMO_GOAL
        goal = st.text_area("Goal", key="goal_input", height=120)
        run = st.button("Run investigation", type="primary", use_container_width=True)
        st.button("Load BX-310 demo goal", on_click=_load_demo_goal, use_container_width=True)
        st.markdown("---")
        st.caption("Stack: Python · SQLite · TF-IDF search · rule engine · Streamlit")
        st.caption("LLM optional. Hard constraints are never delegated to the model.")

    tab_inv, tab_vault, tab_cat = st.tabs(["Investigation", "Knowledge Vault", "Catalog"])

    if run:
        with st.spinner("Running compatibility investigation…"):
            st.session_state["result"] = investigate(goal)

    with tab_inv:
        result = st.session_state.get("result")
        if result:
            render_investigation(result)
        else:
            st.info("Enter a goal and run an investigation. Demo part: BX-310.")
            st.markdown(
                """
                Expected demo outcomes:
                - **BX-421** — potential; verify envelope
                - **BX-512** — reject; connector
                - **BX-620** — reject; voltage
                - **BX-715** — unknown; missing interface data
                """
            )
    with tab_vault:
        render_vault()
    with tab_cat:
        render_catalog()

