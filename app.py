import json
import os
import streamlit as st
from agent_engine import MODEL_ID, run_governance_agent
from crawler import crawl_all_regions, export_reports

st.set_page_config(
    page_title="AWS Agentic AI Governance Crawler",
    layout="wide",
)

st.title("AWS Agentic AI Discovery & Governance Console")
st.caption(
    f"Deterministic Boto3 Cloud Discovery + Autonomous Governance Agent (`{MODEL_ID}` via Groq)"
)

# Load existing report on startup if available
if "agents" not in st.session_state:
    if os.path.exists("agents_report.json"):
        with open("agents_report.json", "r", encoding="utf-8") as f:
            st.session_state.agents = json.load(f)
    else:
        st.session_state.agents = []

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# --- Sidebar Controls ---
with st.sidebar:
    st.header("Crawler Controls")
    regions_input = st.text_input("Target AWS Regions (comma-separated)", value="us-east-1")
    target_regions = [r.strip() for r in regions_input.split(",") if r.strip()]

    if st.button("Run AWS Crawler Scan", type="primary", use_container_width=True):
        with st.spinner("Scanning AWS Lambda, IAM, Tagging API, CloudTrail, and Bedrock..."):
            scanned = crawl_all_regions(target_regions)
            export_reports(scanned)
            st.session_state.agents = scanned
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
    api_status = "Connected" if os.getenv("GROQ_API_KEY") else "Missing GROQ_API_KEY"
    st.markdown(f"**LLM Status:** `{api_status}`")

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

# --- Main Tabs: Inventory Table vs. Agentic Governance Chat ---
tab_inventory, tab_chat = st.tabs(["Discovered Agent Inventory", "Agentic Governance Assistant"])

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
            with st.expander(f"{status_tag} {a['name']} ({a['type']}) — Role: {a['role_arn'].split('/')[-1]}"):
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
        "Ask the governance agent to audit IAM risks, inspect a specific agent's CloudTrail lineage, "
        "or trigger a fresh live AWS scan."
    )

    sample_cols = st.columns(3)
    if sample_cols[0].button("Audit all security & shadow risks", use_container_width=True):
        st.session_state.pending_prompt = "Audit all discovered agents for IAM wildcard risks and untagged shadow agents."
    if sample_cols[1].button("Inspect shadow-analytics-agent", use_container_width=True):
        st.session_state.pending_prompt = "Inspect shadow-analytics-agent and explain why it was flagged."
    if sample_cols[2].button("Re-scan AWS & summarize posture", use_container_width=True):
        st.session_state.pending_prompt = "Run a fresh AWS scan in us-east-1 and summarize our governance posture."

    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("tools"):
                st.caption(f"Tools executed: `{json.dumps(msg['tools'])}`")

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
                    reply, updated_records, trace = run_governance_agent(
                        user_input, st.session_state.agents, target_regions
                    )
                    st.session_state.agents = updated_records
                except Exception as exc:
                    reply = f"Error running governance agent: `{exc}`"
                    trace = []

            st.markdown(reply)
            if trace:
                st.caption(f"Tools executed: `{json.dumps(trace)}`")

        st.session_state.chat_history.append(
            {"role": "assistant", "content": reply, "tools": trace}
        )