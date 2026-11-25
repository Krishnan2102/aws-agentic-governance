import json
import os
import urllib.error
import urllib.request
from dotenv import load_dotenv
from crawler import crawl_all_regions, export_reports

load_dotenv()

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL_ID = "openai/gpt-oss-120b"


# --- Tool Implementations Exposed to the Agent ---
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


def tool_inspect_agent_lineage(records, agent_name):
    """Fetch full IAM data access, CloudTrail creator, tools, and metadata for one agent."""
    for r in records:
        if r["name"].lower() == agent_name.strip().lower():
            return r
    return {"error": f"Agent '{agent_name}' not found in current inventory."}


TOOLS_SCHEMA = [
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
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Groq API HTTP {e.code}: {err_body}") from e


def run_governance_agent(user_prompt, current_records, regions=None):
    """
    Execute a multi-turn tool-calling loop with openai/gpt-oss-120b.
    Returns (assistant_reply, updated_records, tool_trace).
    """
    records = list(current_records)
    tool_trace = []

    if not os.getenv("GROQ_API_KEY", "").strip():
        # Deterministic fallback if GROQ_API_KEY is missing
        audit = tool_audit_security_and_governance(records)
        fallback_msg = (
            f"**[Offline Mode — set `GROQ_API_KEY` in `.env` to enable `{MODEL_ID}`]**\n\n"
            f"- **Total Agents:** {audit['total_agents']}\n"
            f"- **Shadow Agents:** {', '.join(audit['shadow_agents']) or 'None'}\n"
            f"- **Wildcard IAM Exposure:** {', '.join(audit['broad_access_agents']) or 'None'}"
        )
        return fallback_msg, records, tool_trace

    system_prompt = (
        "You are an AWS Cloud Security & Agentic AI Governance Analyst. "
        "You have tools to scan AWS regions for AI agents, audit IAM least-privilege boundaries, "
        "and inspect CloudTrail creator attribution. Always ground your answers in tool outputs "
        "and highlight concrete IAM actions, resource ARNs, and creator identities."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"Current cached inventory has {len(records)} agent(s): "
                f"{[r['name'] for r in records]}.\n\nUser request: {user_prompt}"
            ),
        },
    ]

    # Up to 4 tool-calling iterations
    for _ in range(4):
        response = _call_groq(messages)
        choice = response["choices"][0]["message"]
        messages.append(choice)

        tool_calls = choice.get("tool_calls") or []
        if not tool_calls:
            return choice.get("content", ""), records, tool_trace

        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            args = json.loads(tc["function"].get("arguments") or "{}")

            if fn_name == "scan_aws_agents":
                result = tool_scan_aws_agents(args.get("regions") or regions or ["us-east-1"])
                records = result["agents"]
                summary_for_llm = {
                    "status": "success",
                    "total_agents_found": len(records),
                    "agents_summary": [
                        {
                            "name": r["name"],
                            "type": r["type"],
                            "creator": r["creator"],
                            "broad_access_flag": r["broad_access_flag"],
                            "warnings": r["notes_warnings"],
                        }
                        for r in records
                    ],
                }
                output_str = json.dumps(summary_for_llm)
            elif fn_name == "audit_security_and_governance":
                output_str = json.dumps(tool_audit_security_and_governance(records))
            elif fn_name == "inspect_agent_lineage":
                output_str = json.dumps(
                    tool_inspect_agent_lineage(records, args.get("agent_name", ""))
                )
            else:
                output_str = json.dumps({"error": f"Unknown tool {fn_name}"})

            tool_trace.append({"tool": fn_name, "arguments": args})
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "name": fn_name,
                    "content": output_str,
                }
            )

    return "Reached maximum tool-calling steps without a final summary.", records, tool_trace