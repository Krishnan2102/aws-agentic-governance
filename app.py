import html
import json
import os
import time
import altair as alt
import pandas as pd
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
    page_title="AgentHub | AWS Governance & Observability",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');

    html, body, [class*="css"] {
        font-family: 'Plus Jakarta Sans', sans-serif;
    }

    .stApp {
        background-color: #0D0D14;
        background-image: radial-gradient(circle at 20% 0%, rgba(79, 70, 229, 0.28) 0%, rgba(13, 13, 20, 0) 45%),
                          radial-gradient(circle at 85% 10%, rgba(236, 72, 153, 0.14) 0%, rgba(13, 13, 20, 0) 40%);
        color: #F3F4F6;
    }

    section[data-testid="stSidebar"] {
        background-color: #12121C;
        border-right: 1px solid #232336;
    }

    .hero-title {
        font-size: 2.6rem;
        font-weight: 800;
        line-height: 1.15;
        letter-spacing: -0.02em;
        color: #FFFFFF;
        margin-bottom: 0.75rem;
    }

    .hero-sub {
        font-size: 1rem;
        color: #9CA3AF;
        line-height: 1.6;
        margin-bottom: 1.5rem;
    }

    .featured-card {
        background: linear-gradient(135deg, #3B49DF 0%, #242B8F 55%, #1E216B 100%);
        border: 1px solid rgba(129, 140, 248, 0.45);
        border-radius: 18px;
        padding: 1.75rem;
        box-shadow: 0 12px 32px rgba(59, 73, 223, 0.25);
        min-height: 230px;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
    }

    .featured-label {
        font-size: 0.95rem;
        font-weight: 600;
        color: #E0E7FF;
        letter-spacing: 0.01em;
    }

    .featured-value {
        font-size: 3.6rem;
        font-weight: 800;
        color: #FFFFFF;
        line-height: 1.05;
        margin: 0.35rem 0;
    }

    .featured-foot {
        font-size: 0.85rem;
        color: #C7D2FE;
    }

    .cyan-pill {
        display: inline-block;
        background: #7CE8FF;
        color: #0B1120;
        font-weight: 700;
        font-size: 0.78rem;
        padding: 0.35rem 0.9rem;
        border-radius: 999px;
        margin-top: 0.75rem;
        width: fit-content;
    }

    .dark-card {
        background-color: #151521;
        border: 1px solid #26263A;
        border-radius: 16px;
        padding: 1.35rem 1.5rem;
        height: 100%;
    }

    .dark-card-title {
        font-size: 1.05rem;
        font-weight: 700;
        color: #FFFFFF;
        margin-bottom: 0.4rem;
    }

    .dark-card-desc {
        font-size: 0.88rem;
        color: #9CA3AF;
        line-height: 1.55;
    }

    .kpi-card {
        background-color: #151521;
        border: 1px solid #26263A;
        border-radius: 14px;
        padding: 1.15rem 1.25rem;
    }

    .kpi-label {
        font-size: 0.8rem;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: #9CA3AF;
        font-weight: 600;
    }

    .kpi-num {
        font-size: 2rem;
        font-weight: 800;
        margin-top: 0.25rem;
    }

    .agent-card {
        background-color: #151521;
        border: 1px solid #26263A;
        border-radius: 14px;
        padding: 1.15rem 1.35rem;
        margin-bottom: 0.85rem;
    }

    .agent-card-alert {
        background-color: #1A1423;
        border: 1px solid rgba(244, 63, 94, 0.5);
        border-radius: 14px;
        padding: 1.15rem 1.35rem;
        margin-bottom: 0.85rem;
    }

    .badge-ok {
        background: rgba(124, 232, 255, 0.16);
        color: #7CE8FF;
        border: 1px solid rgba(124, 232, 255, 0.4);
        padding: 0.2rem 0.65rem;
        border-radius: 999px;
        font-size: 0.72rem;
        font-weight: 700;
        margin-right: 0.4rem;
    }

    .badge-alert {
        background: rgba(244, 63, 94, 0.18);
        color: #FB7185;
        border: 1px solid rgba(244, 63, 94, 0.45);
        padding: 0.2rem 0.65rem;
        border-radius: 999px;
        font-size: 0.72rem;
        font-weight: 700;
        margin-right: 0.4rem;
    }

    .tool-chip {
        display: inline-block;
        background: #222235;
        color: #D1D5DB;
        border: 1px solid #32324D;
        padding: 0.18rem 0.55rem;
        border-radius: 6px;
        font-size: 0.75rem;
        margin: 0.2rem 0.3rem 0.2rem 0;
        font-family: monospace;
    }

    div.stButton > button[kind="primary"] {
        background: linear-gradient(90deg, #7CE8FF 0%, #6366F1 100%);
        color: #0B1120;
        font-weight: 700;
        border: none;
        border-radius: 999px;
        padding: 0.55rem 1.25rem;
    }

    div.stButton > button[kind="primary"]:hover {
        opacity: 0.92;
        color: #0B1120;
    }

    .stTabs [data-baseweb="tab-list"] {
        gap: 0.75rem;
        background-color: transparent;
    }

    .stTabs [data-baseweb="tab"] {
        background-color: #151521;
        border: 1px solid #26263A;
        border-radius: 10px;
        color: #9CA3AF;
        padding: 0.5rem 1.1rem;
        font-weight: 600;
    }

    .stTabs [aria-selected="true"] {
        background: linear-gradient(90deg, rgba(99, 102, 241, 0.25), rgba(236, 72, 153, 0.22)) !important;
        border-color: #818CF8 !important;
        color: #FFFFFF !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

if "has_scanned" not in st.session_state:
    st.session_state.has_scanned = False

if "agents" not in st.session_state:
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
        "prompt": f"[Manual Scan] Crawl regions: {', '.join(regions)}",
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


def _friendly_step_meta(span, is_last_step):
    step_name = span.get("step", "")
    step_type = span.get("type", "SPAN")

    if step_type == "GENERATION":
        if is_last_step:
            return (
                "AI Final Response",
                "Synthesized the findings into a clear governance answer",
                "#EC4899",
                "rgba(236, 72, 153, 0.14)",
            )
        return (
            "AI Reasoning & Planning",
            "Analyzed your question and selected the right AWS tool",
            "#A855F7",
            "rgba(168, 85, 247, 0.15)",
        )

    lower = step_name.lower()
    if "query_inventory" in lower:
        return (
            "Search AWS Inventory",
            "Filtered discovered agents by service, action, or keyword",
            "#38BDF8",
            "rgba(56, 189, 248, 0.14)",
        )
    if "audit_security" in lower:
        return (
            "Security & Shadow Audit",
            "Checked IAM policies for wildcards (*) and missing tags",
            "#FB7185",
            "rgba(251, 113, 133, 0.14)",
        )
    if "inspect_agent_lineage" in lower:
        return (
            "Trace Agent Lineage",
            "Inspected CloudTrail creator identity and IAM permissions",
            "#34D399",
            "rgba(52, 211, 153, 0.14)",
        )
    if "scan_aws_agents" in lower or "manual scan" in lower:
        return (
            "Live AWS Cloud Scan",
            "Queried AWS Lambda, IAM, Tagging API, and CloudTrail",
            "#7CE8FF",
            "rgba(124, 232, 255, 0.14)",
        )

    return (
        step_name,
        "Executed backend governance operation",
        "#818CF8",
        "rgba(129, 140, 248, 0.14)",
    )


def render_trace_flowchart(trace):
    prompt_text = html.escape(str(trace.get("prompt", "")))
    spans = trace.get("spans", [])
    total_ms = trace.get("total_latency_ms", 0)
    total_tokens = trace.get("total_tokens", 0)

    nodes_html = [
        f"""
        <div style="background:#181828; border:1px solid #6366F1; border-radius:14px;
                    padding:14px 18px; width:100%; max-width:680px; margin:0 auto;
                    box-shadow:0 4px 18px rgba(99,102,241,0.18);">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <span style="color:#818CF8; font-size:0.75rem; font-weight:800; letter-spacing:0.06em;">
                    STEP 0 &bull; USER REQUEST
                </span>
                <span style="background:rgba(99,102,241,0.2); color:#C7D2FE; padding:2px 10px;
                             border-radius:999px; font-size:0.72rem; font-weight:700;">START</span>
            </div>
            <div style="color:#FFFFFF; font-size:0.95rem; font-weight:600; margin-top:6px;">
                "{prompt_text}"
            </div>
        </div>
        """
    ]

    arrow_html = """
        <div style="text-align:center; padding:6px 0; color:#6366F1; font-size:1.3rem; font-weight:800;">
            &#8595;
        </div>
    """

    for i, sp in enumerate(spans):
        is_last = i == len(spans) - 1
        title, subtitle, accent, bg_tint = _friendly_step_meta(sp, is_last)
        latency = sp.get("latency_ms", 0)
        tokens = sp.get("tokens", 0)
        token_badge = (
            f"<span style='background:#222235; color:#E5E7EB; padding:2px 8px; border-radius:999px; "
            f"font-size:0.72rem; margin-left:6px;'>{tokens} tokens</span>"
            if tokens
            else ""
        )

        nodes_html.append(arrow_html)
        nodes_html.append(
            f"""
            <div style="background:{bg_tint}; border:1px solid {accent}; border-radius:14px;
                        padding:14px 18px; width:100%; max-width:680px; margin:0 auto;">
                <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:6px;">
                    <span style="color:{accent}; font-size:0.75rem; font-weight:800; letter-spacing:0.06em;">
                        STEP {i + 1} &bull; {html.escape(title.upper())}
                    </span>
                    <div>
                        <span style="background:#151521; color:{accent}; border:1px solid {accent};
                                     padding:2px 9px; border-radius:999px; font-size:0.72rem; font-weight:700;">
                            {latency} ms
                        </span>
                        {token_badge}
                    </div>
                </div>
                <div style="color:#F3F4F6; font-size:0.9rem; margin-top:6px;">
                    {html.escape(subtitle)}
                </div>
            </div>
            """
        )

    nodes_html.append(arrow_html)
    nodes_html.append(
        f"""
        <div style="background:rgba(16,185,129,0.12); border:1px solid #10B981; border-radius:14px;
                    padding:12px 18px; width:100%; max-width:680px; margin:0 auto;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <span style="color:#34D399; font-size:0.75rem; font-weight:800; letter-spacing:0.06em;">
                    COMPLETE &bull; TRACE FINISHED
                </span>
                <span style="color:#A7F3D0; font-size:0.78rem; font-weight:700;">
                    Total: {total_ms} ms &bull; {total_tokens} tokens
                </span>
            </div>
        </div>
        """
    )

    st.html("".join(nodes_html))


def trigger_scan(regions):
    with st.spinner("Scanning AWS Lambda, IAM, Tagging API, CloudTrail, and Bedrock..."):
        scanned, manual_trace = _run_traced_manual_scan(regions)
        st.session_state.agents = scanned
        st.session_state.has_scanned = True
        st.session_state.session_traces.insert(0, manual_trace)


with st.sidebar:
    st.markdown("### AgentHub")
    st.caption("AWS Agentic Governance & Observability")
    st.divider()

    regions_input = st.text_input("Target AWS Regions", value="us-east-1")
    target_regions = [r.strip() for r in regions_input.split(",") if r.strip()]

    if st.button("Run Crawler", type="primary", use_container_width=True):
        trigger_scan(target_regions)
        st.rerun()

    if st.session_state.has_scanned and st.session_state.agents:
        st.divider()
        st.markdown("#### Export Reports")
        st.download_button(
            label="Download JSON Report",
            data=json.dumps(st.session_state.agents, indent=2, default=str),
            file_name="agents_report.json",
            mime="application/json",
            use_container_width=True,
        )
        if os.path.exists("agents_report.csv"):
            with open("agents_report.csv", "r", encoding="utf-8") as cf:
                csv_data = cf.read()
            st.download_button(
                label="Download CSV Report",
                data=csv_data,
                file_name="agents_report.csv",
                mime="text/csv",
                use_container_width=True,
            )

    st.divider()
    st.markdown("#### System Telemetry")
    groq_ok = bool(os.getenv("GROQ_API_KEY", "").strip())
    lf_ok = _langfuse_enabled()
    st.markdown(
        f"<span class='{'badge-ok' if groq_ok else 'badge-alert'}'>"
        f"GROQ: {'ONLINE' if groq_ok else 'OFFLINE'}</span>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<span class='{'badge-ok' if lf_ok else 'badge-alert'}'>"
        f"LANGFUSE: {'TRACING' if lf_ok else 'DISABLED'}</span>",
        unsafe_allow_html=True,
    )


if not st.session_state.has_scanned:
    col_left, col_mid, col_right = st.columns([1.25, 1.0, 1.35], gap="large")

    with col_left:
        st.markdown(
            """
            <div style="padding-top: 0.75rem;">
                <div class="hero-title">Empowering Agentic<br>Cloud Governance</div>
                <div class="hero-sub">
                    Discover AWS Lambda & Bedrock agents on demand, audit IAM blast radius,
                    detect untagged shadow AI, and trace every reasoning step in Langfuse.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Run Crawler Now", type="primary", use_container_width=False):
            trigger_scan(target_regions)
            st.rerun()

    with col_mid:
        st.markdown(
            f"""
            <div class="featured-card">
                <div class="featured-label">Live AWS Discovery Status</div>
                <div class="featured-value">—</div>
                <div class="featured-foot">
                    Awaiting scan trigger in <b>{', '.join(target_regions)}</b>.<br>
                    Zero background polling.
                </div>
                <div class="cyan-pill">Ready to Scan</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col_right:
        st.markdown(
            """
            <div class="dark-card">
                <div class="dark-card-title">Visual Governance Analytics</div>
                <div class="dark-card-desc">
                    Click <b>Run Crawler</b> to populate live compliance metrics,
                    IAM wildcard exposure charts, and CloudTrail creator attribution.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("<div style='height: 1.75rem;'></div>", unsafe_allow_html=True)

    f1, f2, f3 = st.columns(3, gap="medium")
    with f1:
        st.markdown(
            """
            <div class="dark-card">
                <div class="dark-card-title">Shadow AI Detection</div>
                <div class="dark-card-desc">
                    Cross-references AWS Resource Groups Tagging API against live Lambda
                    inventories to expose untagged shadow agents immediately.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with f2:
        st.markdown(
            """
            <div class="dark-card">
                <div class="dark-card-title">IAM Blast-Radius Audit</div>
                <div class="dark-card-desc">
                    Resolves inline and managed execution policies, normalizing JSON statements
                    to flag wildcard (*) permissions and data-store exposure.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with f3:
        st.markdown(
            """
            <div class="dark-card">
                <div class="dark-card-title">Langfuse Observability</div>
                <div class="dark-card-desc">
                    Captures every Groq tool-calling turn, latency waterfall, and token metric
                    with direct links to Langfuse Cloud traces.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

else:
    agents = st.session_state.agents
    total_count = len(agents)
    governed_count = sum(1 for a in agents if a.get("type") == "lambda")
    shadow_count = sum(1 for a in agents if a.get("type") == "lambda-shadow")
    broad_count = sum(1 for a in agents if a.get("broad_access_flag"))
    compliance_score = int(round((governed_count / total_count) * 100)) if total_count else 0

    hero_l, hero_r = st.columns([1.0, 1.8], gap="large")
    with hero_l:
        st.markdown(
            f"""
            <div class="featured-card">
                <div class="featured-label">Governance Compliance Score</div>
                <div class="featured-value">{compliance_score}%</div>
                <div class="featured-foot">
                    {governed_count} of {total_count} discovered agents follow tagging
                    & least-privilege standards.
                </div>
                <div class="cyan-pill">Region: {', '.join(target_regions)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with hero_r:
        chart_df = pd.DataFrame(
            {
                "Category": ["Governed Agents", "Shadow Agents", "Wildcard IAM Alerts"],
                "Count": [governed_count, shadow_count, broad_count],
                "Color": ["#7CE8FF", "#F43F5E", "#A855F7"],
            }
        )
        bar_chart = (
            alt.Chart(chart_df)
            .mark_bar(cornerRadiusTopLeft=8, cornerRadiusTopRight=8, size=48)
            .encode(
                x=alt.X("Category:N", axis=alt.Axis(labelAngle=0, labelColor="#D1D5DB", title=None)),
                y=alt.Y("Count:Q", axis=alt.Axis(tickMinStep=1, labelColor="#9CA3AF", gridColor="#232336", title=None)),
                color=alt.Color("Color:N", scale=None, legend=None),
                tooltip=["Category", "Count"],
            )
            .properties(height=210, title=alt.TitleParams("Visual Governance Posture", color="#FFFFFF", fontSize=15))
            .configure_view(strokeWidth=0, fill="#151521")
            .configure(background="#151521")
        )
        st.altair_chart(bar_chart, use_container_width=True)

    st.markdown("<div style='height: 1rem;'></div>", unsafe_allow_html=True)

    k1, k2, k3, k4 = st.columns(4, gap="medium")
    k1.markdown(
        f"<div class='kpi-card'><div class='kpi-label'>Total Agents</div>"
        f"<div class='kpi-num' style='color:#FFFFFF;'>{total_count}</div></div>",
        unsafe_allow_html=True,
    )
    k2.markdown(
        f"<div class='kpi-card'><div class='kpi-label'>Governed Tagged</div>"
        f"<div class='kpi-num' style='color:#7CE8FF;'>{governed_count}</div></div>",
        unsafe_allow_html=True,
    )
    k3.markdown(
        f"<div class='kpi-card'><div class='kpi-label'>Untagged Shadow</div>"
        f"<div class='kpi-num' style='color:#FB7185;'>{shadow_count}</div></div>",
        unsafe_allow_html=True,
    )
    k4.markdown(
        f"<div class='kpi-card'><div class='kpi-label'>Wildcard IAM Alerts</div>"
        f"<div class='kpi-num' style='color:#C084FC;'>{broad_count}</div></div>",
        unsafe_allow_html=True,
    )

    st.markdown("<div style='height: 1.25rem;'></div>", unsafe_allow_html=True)

    tab_inventory, tab_chat, tab_traces = st.tabs(
        [
            "Agent Inventory & IAM",
            "Governance Assistant",
            "Observability & Langfuse",
        ]
    )

    with tab_inventory:
        for a in agents:
            is_alert = bool(a["notes_warnings"])
            card_cls = "agent-card-alert" if is_alert else "agent-card"
            status_badge = (
                "<span class='badge-alert'>SHADOW / ALERT</span>"
                if is_alert
                else "<span class='badge-ok'>GOVERNED</span>"
            )
            wildcard_badge = (
                "<span class='badge-alert'>WILDCARD *</span>"
                if a["broad_access_flag"]
                else "<span class='badge-ok'>LEAST PRIVILEGE</span>"
            )
            tools_html = "".join(f"<span class='tool-chip'>{t}</span>" for t in a["tools"]) or "<span class='tool-chip'>none</span>"

            st.markdown(
                f"""
                <div class="{card_cls}">
                    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:0.5rem;">
                        <div style="font-size:1.1rem; font-weight:700; color:#FFFFFF;">{a['name']}</div>
                        <div>{status_badge}{wildcard_badge}</div>
                    </div>
                    <div style="color:#9CA3AF; font-size:0.86rem; margin-top:0.35rem;">{a['purpose']}</div>
                    <div style="margin-top:0.6rem; font-size:0.8rem; color:#D1D5DB;">
                        <b>Creator:</b> <code>{a['creator']}</code> &nbsp;|&nbsp;
                        <b>Role:</b> <code>{a['role_arn'].split('/')[-1]}</code> &nbsp;|&nbsp;
                        <b>Model:</b> <code>{a['model']}</code>
                    </div>
                    <div style="margin-top:0.45rem;">{tools_html}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            with st.expander(f"Inspect IAM Policy & CloudTrail Metadata — {a['name']}"):
                c_left, c_right = st.columns(2)
                with c_left:
                    st.markdown(f"**Agent ARN:** `{a['agent_id']}`")
                    st.markdown(f"**Created At:** `{a['created_at']}`")
                    st.markdown(f"**Discovery Source:** `{a['discovery_source']}`")
                    if a["notes_warnings"]:
                        for w in a["notes_warnings"]:
                            st.warning(w)
                with c_right:
                    st.markdown("**Resolved IAM Data Access:**")
                    st.json(a["data_access"])

    with tab_chat:
        st.markdown(
            f"Query your discovered AWS inventory using **`{MODEL_ID}`** with autonomous tool calling."
        )

        q1, q2, q3 = st.columns(3)
        if q1.button("Which agents utilize S3?", use_container_width=True):
            st.session_state.pending_prompt = "Which agents utilize S3 and what specific permissions do they have?"
        if q2.button("Audit shadow & wildcard risks", use_container_width=True):
            st.session_state.pending_prompt = "Audit all discovered agents for IAM wildcard risks and untagged shadow agents."
        if q3.button("Trace agent-orchestrator lineage", use_container_width=True):
            st.session_state.pending_prompt = "Trace the full execution chain starting from agent-orchestrator down to S3 and DynamoDB."

        for msg in st.session_state.chat_history:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                if msg.get("trace_meta"):
                    meta = msg["trace_meta"]
                    tool_names = [s["step"] for s in meta.get("spans", []) if s["type"] == "SPAN"]
                    parts = [
                        f"Latency: `{meta['total_latency_ms']} ms`",
                        f"Tokens: `{meta['total_tokens']}`",
                    ]
                    if tool_names:
                        parts.append(f"Tools: `{', '.join(tool_names)}`")
                    if meta.get("trace_url"):
                        parts.append(f"[Open in Langfuse]({meta['trace_url']})")
                    st.caption(" | ".join(parts))

        user_input = st.chat_input("Ask about S3 access, IAM blast radius, or CloudTrail creators...")
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
                    parts = [
                        f"Latency: `{trace_summary['total_latency_ms']} ms`",
                        f"Tokens: `{trace_summary['total_tokens']}`",
                    ]
                    if tool_names:
                        parts.append(f"Tools: `{', '.join(tool_names)}`")
                    if trace_summary.get("trace_url"):
                        parts.append(f"[Open in Langfuse]({trace_summary['trace_url']})")
                    st.caption(" | ".join(parts))

            st.session_state.chat_history.append(
                {"role": "assistant", "content": reply, "trace_meta": trace_summary}
            )

    with tab_traces:
        st.markdown("#### Visual Trace Flowchart")
        st.caption("See exactly how the AI agent thought, which AWS tools it ran, and how long each step took.")

        if not st.session_state.session_traces:
            st.info("Run a crawler scan or ask the Governance Assistant a question to generate a visual trace.")
        else:
            trace_labels = [
                f"#{idx} — {tr['prompt'][:65]} ({tr['total_latency_ms']} ms)"
                for idx, tr in enumerate(st.session_state.session_traces, start=1)
            ]
            selected_idx = st.selectbox(
                "Select an execution to visualize",
                options=range(len(trace_labels)),
                format_func=lambda i: trace_labels[i],
            )
            active_trace = st.session_state.session_traces[selected_idx]

            meta_l, meta_r = st.columns([3, 1])
            with meta_l:
                st.markdown(f"**Langfuse Trace ID:** `{active_trace.get('trace_id') or 'local-only'}`")
            with meta_r:
                if active_trace.get("trace_url"):
                    st.link_button("Open in Langfuse UI", active_trace["trace_url"], use_container_width=True)

            st.markdown("<div style='height:0.5rem;'></div>", unsafe_allow_html=True)
            render_trace_flowchart(active_trace)
            st.markdown("<div style='height:1rem;'></div>", unsafe_allow_html=True)

            with st.expander("Developer View: Raw Span Payloads (JSON)"):
                for sp in active_trace.get("spans", []):
                    badge = "badge-alert" if sp["type"] == "GENERATION" else "badge-ok"
                    st.markdown(
                        f"<span class='{badge}'>{sp['type']}</span> "
                        f"<b>{sp['step']}</b> — <code>{sp['latency_ms']} ms</code>",
                        unsafe_allow_html=True,
                    )
                    in_col, out_col = st.columns(2)
                    with in_col:
                        st.caption("Input")
                        st.json(sp["input"] if isinstance(sp["input"], (dict, list)) else {"value": sp["input"]})
                    with out_col:
                        st.caption("Output")
                        st.json(sp["output"] if isinstance(sp["output"], (dict, list)) else {"value": sp["output"]})
                    st.divider()

        st.divider()
        st.markdown("#### Recent Langfuse Cloud History")
        if st.button("Refresh Langfuse History"):
            st.session_state.lf_cloud_cache = fetch_recent_langfuse_traces(limit=10)

        cloud_res = st.session_state.get("lf_cloud_cache") or fetch_recent_langfuse_traces(limit=10)
        if not cloud_res["enabled"]:
            st.warning("Set `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` in `.env` to sync Langfuse Cloud.")
        elif cloud_res["error"]:
            st.error(f"Langfuse API notice: {cloud_res['error']}")
        elif not cloud_res["traces"]:
            st.info("Connected to Langfuse Cloud — no observations returned yet.")
        else:
            st.dataframe(
                cloud_res["traces"],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "url": st.column_config.LinkColumn("Langfuse Trace", display_text="Open Trace"),
                    "latency_sec": st.column_config.NumberColumn("Latency (s)", format="%.2f s"),
                    "total_cost": st.column_config.NumberColumn("Cost ($)", format="$%.5f"),
                },
            )