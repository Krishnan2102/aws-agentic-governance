import json
import os
import time
import urllib.error
import urllib.request
from dotenv import load_dotenv
from langfuse import get_client, observe
from crawler import crawl_all_regions, export_reports
import base64

load_dotenv()

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL_ID = "openai/gpt-oss-120b"


def _langfuse_enabled():
    return bool(
        os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
        and os.getenv("LANGFUSE_SECRET_KEY", "").strip()
    )


# --- Tool Implementations Exposed to the Agent ---
@observe(name="tool:scan_aws_agents", as_type="span")
def tool_scan_aws_agents(regions=None):
    """Run live AWS discovery across specified regions and persist JSON/CSV reports."""
    target_regions = regions or ["us-east-1"]
    records = crawl_all_regions(target_regions)
    export_reports(records)
    return {
        "status": "success",
        "scanned_regions": target_regions,
        "total_agents_found": len(records),
        "agents": records,
    }


@observe(name="tool:audit_security_and_governance", as_type="span")
def tool_audit_security_and_governance(records):
    """Evaluate IAM wildcard exposure, untagged shadow agents, and compliance posture."""
    shadow_agents = [r["name"] for r in records if r["type"] == "lambda-shadow"]
    broad_access_agents = [r["name"] for r in records if r.get("broad_access_flag")]
    untagged_agents = [r["name"] for r in records if not r.get("owner_tag")]

    findings = []
    for r in records:
        if r.get("notes_warnings"):
            findings.append(
                {
                    "agent_name": r["name"],
                    "type": r["type"],
                    "creator": r["creator"],
                    "warnings": r["notes_warnings"],
                    "data_access": r["data_access"],
                }
            )

    return {
        "total_agents": len(records),
        "shadow_agent_count": len(shadow_agents),
        "shadow_agents": shadow_agents,
        "broad_access_count": len(broad_access_agents),
        "broad_access_agents": broad_access_agents,
        "missing_owner_tag": untagged_agents,
        "detailed_findings": findings,
    }


@observe(name="tool:inspect_agent_lineage", as_type="span")
def tool_inspect_agent_lineage(records, agent_name):
    """Fetch full IAM data access, CloudTrail creator, tools, and metadata for one agent."""
    for r in records:
        if r["name"].lower() == agent_name.strip().lower():
            return r
    return {"error": f"Agent '{agent_name}' not found in current inventory."}


@observe(name="tool:query_inventory", as_type="span")
def tool_query_inventory(records, keyword=""):
    """Search across all agents' tools, IAM actions, resources, purpose, and metadata."""
    kw = keyword.strip().lower()
    if not kw:
        return records

    matches = []
    for r in records:
        blob = json.dumps(r, default=str).lower()
        if kw in blob:
            matches.append(
                {
                    "name": r["name"],
                    "type": r["type"],
                    "purpose": r["purpose"],
                    "tools": r["tools"],
                    "data_access": r["data_access"],
                    "creator": r["creator"],
                    "broad_access_flag": r["broad_access_flag"],
                }
            )
    return {
        "keyword": keyword,
        "match_count": len(matches),
        "matches": matches,
    }


TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "query_inventory",
            "description": "Searches all discovered agents by keyword across IAM actions, AWS services (e.g. 's3', 'dynamodb', 'lambda'), resource ARNs, tools, creator, or purpose.",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "Service, IAM action, tool, or term to filter by (leave empty to list all agents with full details).",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scan_aws_agents",
            "description": "Triggers a live AWS crawler scan across regions to discover Lambda and Bedrock agents, resolve IAM roles, query CloudTrail creators, and export JSON/CSV reports.",
            "parameters": {
                "type": "object",
                "properties": {
                    "regions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of AWS region codes, e.g. ['us-east-1']",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "audit_security_and_governance",
            "description": "Audits the current agent inventory for IAM wildcard permissions, untagged shadow agents, and missing owner tags.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_agent_lineage",
            "description": "Returns full IAM policy permissions, CloudTrail creator ARN, tools, and warnings for a single named agent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_name": {
                        "type": "string",
                        "description": "Exact name of the AWS agent, e.g. 'shadow-analytics-agent'",
                    }
                },
                "required": ["agent_name"],
            },
        },
    },
]


def _build_compact_snapshot(records):
    snapshot = []
    for r in records:
        actions = []
        resources = []
        for stmt in r.get("data_access", []):
            actions.extend(stmt.get("actions", []))
            resources.extend(stmt.get("resources", []))
        snapshot.append(
            {
                "name": r["name"],
                "type": r["type"],
                "tools": r["tools"],
                "iam_actions": actions,
                "iam_resources": resources,
                "broad_access_flag": r["broad_access_flag"],
                "warnings": r["notes_warnings"],
            }
        )
    return snapshot


@observe(name="groq:chat_completion", as_type="generation")
def _call_groq(messages):
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        return None

    payload = {
        "model": MODEL_ID,
        "messages": messages,
        "tools": TOOLS_SCHEMA,
        "tool_choice": "auto",
        "reasoning_effort": "low",
        "temperature": 0.1,
        "max_tokens": 1024,
    }
    req = urllib.request.Request(
        GROQ_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "aws-agentic-governance/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Groq API HTTP {e.code}: {err_body}") from e

    # Attach model & token usage metadata to the active Langfuse generation span
    if _langfuse_enabled():
        try:
            usage = data.get("usage", {})
            get_client().update_current_generation(
                model=MODEL_ID,
                usage_details={
                    "input": usage.get("prompt_tokens", 0),
                    "output": usage.get("completion_tokens", 0),
                    "total": usage.get("total_tokens", 0),
                },
            )
        except Exception:
            pass

    return data


@observe(name="governance_agent_turn", as_type="agent")
def _execute_agent_loop(user_prompt, records, regions):
    """Inner traced agent execution returning reply, updated records, and local span waterfall."""
    trace_id = None
    trace_url = None
    if _langfuse_enabled():
        try:
            lf = get_client()
            trace_id = lf.get_current_trace_id()
            trace_url = lf.get_trace_url()
        except Exception:
            pass

    spans = []
    turn_start = time.perf_counter()

    if not os.getenv("GROQ_API_KEY", "").strip():
        matches = tool_query_inventory(records, user_prompt)
        audit = tool_audit_security_and_governance(records)
        fallback_msg = (
            f"**[Offline Mode — set `GROQ_API_KEY` in `.env` to enable `{MODEL_ID}`]**\n\n"
            f"- **Total Agents:** {audit['total_agents']}\n"
            f"- **Shadow Agents:** {', '.join(audit['shadow_agents']) or 'None'}\n"
            f"- **Wildcard IAM Exposure:** {', '.join(audit['broad_access_agents']) or 'None'}\n"
            f"- **Direct Keyword Matches:** {matches.get('match_count', 0)}"
        )
        return fallback_msg, records, {
            "trace_id": trace_id,
            "trace_url": trace_url,
            "prompt": user_prompt,
            "total_latency_ms": round((time.perf_counter() - turn_start) * 1000, 1),
            "total_tokens": 0,
            "spans": spans,
        }

    system_prompt = (
        "You are an AWS Cloud Security & Agentic AI Governance Analyst. "
        "You can answer both general inventory questions (e.g., which agents use S3, DynamoDB, or specific tools) "
        "and deep security/lineage audits. Use `query_inventory` when searching across agents by service, action, or keyword, "
        "`inspect_agent_lineage` for deep single-agent metadata, `audit_security_and_governance` for risk posture, "
        "and `scan_aws_agents` only when the user explicitly asks to re-scan or refresh live AWS data."
    )

    snapshot = _build_compact_snapshot(records)
    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"Cached inventory ({len(records)} agents):\n"
                f"{json.dumps(snapshot, indent=2)}\n\n"
                f"User question: {user_prompt}"
            ),
        },
    ]

    total_tokens = 0
    final_reply = "Reached maximum tool-calling steps without a final summary."

    for step_idx in range(1, 5):
        llm_start = time.perf_counter()
        response = _call_groq(messages)
        llm_ms = round((time.perf_counter() - llm_start) * 1000, 1)

        usage = response.get("usage", {})
        step_tokens = usage.get("total_tokens", 0)
        total_tokens += step_tokens

        choice = response["choices"][0]["message"]
        messages.append(choice)
        tool_calls = choice.get("tool_calls") or []

        spans.append(
            {
                "step": f"Turn {step_idx} — LLM Generation ({MODEL_ID})",
                "type": "GENERATION",
                "latency_ms": llm_ms,
                "tokens": step_tokens,
                "input": user_prompt if step_idx == 1 else "Tool outputs",
                "output": (
                    [tc["function"]["name"] for tc in tool_calls]
                    if tool_calls
                    else choice.get("content", "")
                ),
            }
        )

        if not tool_calls:
            final_reply = choice.get("content", "")
            break

        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            args = json.loads(tc["function"].get("arguments") or "{}")
            tool_start = time.perf_counter()

            if fn_name == "query_inventory":
                raw_out = tool_query_inventory(records, args.get("keyword", ""))
            elif fn_name == "scan_aws_agents":
                result = tool_scan_aws_agents(args.get("regions") or regions or ["us-east-1"])
                records = result["agents"]
                raw_out = {
                    "status": "success",
                    "total_agents_found": len(records),
                    "agents_summary": _build_compact_snapshot(records),
                }
            elif fn_name == "audit_security_and_governance":
                raw_out = tool_audit_security_and_governance(records)
            elif fn_name == "inspect_agent_lineage":
                raw_out = tool_inspect_agent_lineage(records, args.get("agent_name", ""))
            else:
                raw_out = {"error": f"Unknown tool {fn_name}"}

            tool_ms = round((time.perf_counter() - tool_start) * 1000, 1)
            output_str = json.dumps(raw_out, default=str)

            spans.append(
                {
                    "step": f"Turn {step_idx} — Tool: {fn_name}",
                    "type": "SPAN",
                    "latency_ms": tool_ms,
                    "tokens": 0,
                    "input": args,
                    "output": raw_out,
                }
            )

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "name": fn_name,
                    "content": output_str,
                }
            )

    trace_summary = {
        "trace_id": trace_id,
        "trace_url": trace_url,
        "prompt": user_prompt,
        "total_latency_ms": round((time.perf_counter() - turn_start) * 1000, 1),
        "total_tokens": total_tokens,
        "spans": spans,
    }
    return final_reply, records, trace_summary


def run_governance_agent(user_prompt, current_records, regions=None):
    """Public entrypoint that executes the traced agent and flushes Langfuse telemetry."""
    reply, updated_records, trace_summary = _execute_agent_loop(
        user_prompt, list(current_records), regions
    )
    if _langfuse_enabled():
        try:
            get_client().flush()
        except Exception:
            pass
    return reply, updated_records, trace_summary


import base64


def fetch_recent_langfuse_traces(limit=10):
    pub = os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
    sec = os.getenv("LANGFUSE_SECRET_KEY", "").strip()
    base_url = (
        os.getenv("LANGFUSE_BASE_URL")
        or os.getenv("LANGFUSE_HOST")
        or "https://cloud.langfuse.com"
    ).rstrip("/")

    if not (pub and sec):
        return {"enabled": False, "traces": [], "error": "Langfuse keys not set in .env"}

    token = base64.b64encode(f"{pub}:{sec}".encode("utf-8")).decode("utf-8")
    url = f"{base_url}/api/public/v2/observations?limit={limit}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Basic {token}",
            "Accept": "application/json",
            "User-Agent": "aws-agentic-governance/1.0",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))

        lf = get_client()
        items = []
        for obs in payload.get("data", []):
            tid = obs.get("traceId", "")
            items.append(
                {
                    "trace_id": tid,
                    "name": obs.get("name", ""),
                    "type": obs.get("type", ""),
                    "start_time": str(obs.get("startTime", "")),
                    "latency_sec": obs.get("latency"),
                    "total_cost": obs.get("calculatedTotalCost"),
                    "url": lf.get_trace_url(trace_id=tid) if tid else "",
                }
            )
        return {"enabled": True, "traces": items, "error": None}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="ignore")
        return {"enabled": True, "traces": [], "error": f"HTTP {e.code}: {detail}"}
    except Exception as e:
        return {"enabled": True, "traces": [], "error": str(e)}