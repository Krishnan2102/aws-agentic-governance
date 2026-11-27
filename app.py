import json
import os
import time
import streamlit as st
from langfuse import get_client, observe
from agent_engine import (
    MODEL_ID,
    _langfuse_enabled,
    fetch_recent_langfuse_traces,
    run_governance_agent,
)
from crawler import crawl_all_regions, export_reports

st.set_page_config(
    page_title="AWS Agentic AI Governance Crawler",
    layout="wide",
)

st.title("AWS Agentic AI Discovery & Governance Console")
st.caption(
    f"Deterministic Boto3 Discovery + Governance Agent (`{MODEL_ID}`) + Langfuse Observability"
)

if "agents" not in st.session_state:
    if os.path.exists("agents_report.json"):
        with open("agents_report.json", "r", encoding="utf-8") as f:
            st.session_state.agents = json.load(f)
    else:
        st.session_state.agents = []

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

if "session_traces" not in st.session_state:
    st.session_state.session_traces = []


@observe(name="manual_ui_crawler_scan", as_type="span")
def _run_traced_manual_scan(regions):
    start = time.perf_counter()
    scanned = crawl_all_regions(regions)
    export_reports(scanned)
    elapsed_ms = round((time.perf_counter() - start) * 1000, 1)

    trace_id = None
    trace_url = None
    if _langfuse_enabled():
        try:
            lf = get_client()
            trace_id = lf.get_current_trace_id()
            trace_url = lf.get_trace_url()
            lf.flush()
        except Exception:
            pass

    return scanned, {
        "trace_id": trace_id,
        "trace_url": trace_url,
        "prompt": f"[Manual Button] Crawl regions: {', '.join(regions)}",
        "total_latency_ms": elapsed_ms,
        "total_tokens": 0,
        "spans": [
            {
                "step": "Manual Scan — crawl_all_regions",
                "type": "SPAN",
                "latency_ms": elapsed_ms,
                "tokens": 0,
                "input": {"regions": regions},
                "output": {"discovered_agents": [a["name"] for a in scanned]},
            }
        ],
    }


# --- Sidebar Controls ---
with st.sidebar:
    st.header("Crawler Controls")
    regions_input = st.text_input("Target AWS Regions (comma-separated)", value="us-east-1")
    target_regions = [r.strip() for r in regions_input.split(",") if r.strip()]

    if st.button("Run AWS Crawler Scan", type="primary", use_container_width=True):
        with st.spinner("Scanning AWS Lambda, IAM, Tagging API, CloudTrail, and Bedrock..."):
            scanned, manual_trace = _run_traced_manual_scan(target_regions)
            st.session_state.agents = scanned
            st.session_state.session_traces.insert(0, manual_trace)
        st.success(f"Scan complete: {len(scanned)} agent(s) discovered.")

    st.divider()
    st.subheader("Export Reports")
    if st.session_state.agents:
        st.download_button(
            label="Download agents_report.json",
            data=json.dumps(st.session_state.agents, indent=2, default=str),
            file_name="agents_report.json",
            mime="application/json",
            use_container_width=True,
        )
        if os.path.exists("agents_report.csv"):
            with open("agents_report.csv", "r", encoding="utf-8") as cf:
                csv_data = cf.read()
            st.download_button(
                label="Download agents_report.csv",
                data=csv_data,
                file_name="agents_report.csv",
                mime="text/csv",
                use_container_width=True,
            )

    st.divider()
    st.subheader("Telemetry & Model Status")
    groq_status = "Connected" if os.getenv("GROQ_API_KEY") else "Missing GROQ_API_KEY"
    lf_status = "Connected" if _langfuse_enabled() else "Disabled (set keys in .env)"
    st.markdown(f"**Groq LLM:** `{groq_status}`")
    st.markdown(f"**Langfuse Tracing:** `{lf_status}`")

agents = st.session_state.agents

# --- Executive KPI Strip ---
total_count = len(agents)
governed_count = sum(1 for a in agents if a.get("type") == "lambda")
shadow_count = sum(1 for a in agents if a.get("type") == "lambda-shadow")
broad_count = sum(1 for a in agents if a.get("broad_access_flag"))

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Discovered Agents", total_count)
col2.metric("Governed Tagged Agents", governed_count)
col3.metric("Untagged Shadow Agents", shadow_count)
col4.metric("Wildcard IAM Alerts", broad_count)

st.divider()

# --- Main Tabs ---
tab_inventory, tab_chat, tab_traces = st.tabs(
    [
        "Discovered Agent Inventory",
        "Agentic Governance Assistant",
        "Observability & Langfuse Traces",
    ]
)

with tab_inventory:
    if not agents:
        st.info("No agents loaded yet. Click **Run AWS Crawler Scan** in the sidebar to begin.")
    else:
        table_rows = [
            {
                "Agent Name": a["name"],
                "Type": a["type"],
                "Region": a["region"],
                "Creator (CloudTrail)": a["creator"],
                "Owner Tag": a["owner_tag"] or "MISSING",
                "Model": a["model"],
                "Tools": ", ".join(a["tools"]),
                "Broad Access": "YES" if a["broad_access_flag"] else "No",
                "Alerts": len(a["notes_warnings"]),
            }
            for a in agents
        ]
        st.dataframe(table_rows, use_container_width=True, hide_index=True)

        st.subheader("Detailed IAM Blast Radius & Lineage Inspection")
        for a in agents:
            status_tag = "[ALERT]" if a["notes_warnings"] else "[OK]"
            with st.expander(
                f"{status_tag} {a['name']} ({a['type']}) — Role: {a['role_arn'].split('/')[-1]}"
            ):
                left, right = st.columns(2)
                with left:
                    st.markdown(f"**Agent ARN:** `{a['agent_id']}`")
                    st.markdown(f"**Creator:** `{a['creator']}`")
                    st.markdown(f"**Created At:** `{a['created_at']}`")
                    st.markdown(f"**Discovery Source:** `{a['discovery_source']}`")
                    st.markdown(f"**Purpose:** {a['purpose']}")
                    if a["notes_warnings"]:
                        for w in a["notes_warnings"]:
                            st.warning(w)
                with right:
                    st.markdown("**Resolved IAM Data / Service Access:**")
                    st.json(a["data_access"])

with tab_chat:
    st.markdown(
        "Ask the governance agent to audit IAM risks, query which agents use S3/DynamoDB, "
        "inspect CloudTrail lineage, or trigger a live AWS scan."
    )

    sample_cols = st.columns(3)
    if sample_cols[0].button("Which agents utilize S3?", use_container_width=True):
        st.session_state.pending_prompt = "Which agents utilize S3 and what specific permissions do they have?"
    if sample_cols[1].button("Audit all security & shadow risks", use_container_width=True):
        st.session_state.pending_prompt = "Audit all discovered agents for IAM wildcard risks and untagged shadow agents."
    if sample_cols[2].button("Trace agent-orchestrator lineage", use_container_width=True):
        st.session_state.pending_prompt = "Trace the full execution chain starting from agent-orchestrator down to S3 and DynamoDB."

    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("trace_meta"):
                meta = msg["trace_meta"]
                tool_names = [
                    s["step"] for s in meta.get("spans", []) if s["type"] == "SPAN"
                ]
                caption_parts = [
                    f"Latency: `{meta['total_latency_ms']} ms`",
                    f"Tokens: `{meta['total_tokens']}`",
                ]
                if tool_names:
                    caption_parts.append(f"Tools: `{', '.join(tool_names)}`")
                if meta.get("trace_url"):
                    caption_parts.append(f"[View in Langfuse]({meta['trace_url']})")
                st.caption(" | ".join(caption_parts))

    user_input = st.chat_input("Ask a question about your AWS agents...")
    if "pending_prompt" in st.session_state:
        user_input = st.session_state.pop("pending_prompt")

    if user_input:
        st.session_state.chat_history.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        with st.chat_message("assistant"):
            with st.spinner(f"Reasoning with {MODEL_ID}..."):
                try:
                    reply, updated_records, trace_summary = run_governance_agent(
                        user_input, st.session_state.agents, target_regions
                    )
                    st.session_state.agents = updated_records
                    st.session_state.session_traces.insert(0, trace_summary)
                except Exception as exc:
                    reply = f"Error running governance agent: `{exc}`"
                    trace_summary = None

            st.markdown(reply)
            if trace_summary:
                tool_names = [
                    s["step"] for s in trace_summary.get("spans", []) if s["type"] == "SPAN"
                ]
                caption_parts = [
                    f"Latency: `{trace_summary['total_latency_ms']} ms`",
                    f"Tokens: `{trace_summary['total_tokens']}`",
                ]
                if tool_names:
                    caption_parts.append(f"Tools: `{', '.join(tool_names)}`")
                if trace_summary.get("trace_url"):
                    caption_parts.append(f"[View in Langfuse]({trace_summary['trace_url']})")
                st.caption(" | ".join(caption_parts))

        st.session_state.chat_history.append(
            {"role": "assistant", "content": reply, "trace_meta": trace_summary}
        )

with tab_traces:
    st.subheader("Session Execution Waterfall (Live Spans & Generations)")
    if not st.session_state.session_traces:
        st.info("No traces recorded in this session yet. Run a crawler scan or send a chat query.")
    else:
        for idx, tr in enumerate(st.session_state.session_traces, start=1):
            header = (
                f"#{idx} | {tr['prompt'][:75]} — "
                f"{tr['total_latency_ms']} ms | {tr['total_tokens']} tokens"
            )
            with st.expander(header, expanded=(idx == 1)):
                top_l, top_r = st.columns([3, 1])
                with top_l:
                    st.markdown(f"**Langfuse Trace ID:** `{tr.get('trace_id') or 'local-only'}`")
                with top_r:
                    if tr.get("trace_url"):
                        st.link_button("Open in Langfuse UI", tr["trace_url"], use_container_width=True)

                for sp in tr.get("spans", []):
                    st.markdown(
                        f"**`[{sp['type']}]` {sp['step']}** — `{sp['latency_ms']} ms`"
                        + (f" (`{sp['tokens']} tokens`)" if sp["tokens"] else "")
                    )
                    in_col, out_col = st.columns(2)
                    with in_col:
                        st.caption("Input")
                        st.json(sp["input"] if isinstance(sp["input"], (dict, list)) else {"value": sp["input"]})
                    with out_col:
                        st.caption("Output")
                        st.json(sp["output"] if isinstance(sp["output"], (dict, list)) else {"value": sp["output"]})
                    st.divider()

    st.subheader("Recent Traces from Langfuse Cloud")
    if st.button("Refresh Langfuse Cloud History"):
        st.session_state.lf_cloud_cache = fetch_recent_langfuse_traces(limit=10)

    cloud_res = st.session_state.get("lf_cloud_cache") or fetch_recent_langfuse_traces(limit=10)
    if not cloud_res["enabled"]:
        st.warning("Set `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` in `.env` to sync Langfuse Cloud traces.")
    elif cloud_res["error"]:
        st.error(f"Langfuse API notice: {cloud_res['error']}")
    elif not cloud_res["traces"]:
        st.info("Connected to Langfuse Cloud — no historical traces returned yet.")
    else:
        st.dataframe(cloud_res["traces"], use_container_width=True, hide_index=True)