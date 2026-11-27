```markdown
# AgentHub — AWS Agentic AI Discovery, Governance & Observability

An automated AWS discovery, IAM blast-radius auditing, and agentic governance framework built with Python, `boto3`, Groq (`openai/gpt-oss-120b`), Langfuse, and Streamlit.

This project provisions a reproducible multi-agent AWS testbed (comprising governed Lambda workers, a multi-agent orchestrator, and an untagged shadow agent), discovers deployed agents across AWS services on demand, resolves their effective IAM permissions and CloudTrail creator lineage, and surfaces both compliance insights and step-by-step execution traces in an interactive Streamlit console.

---

## Architecture Overview

The system decouples **deterministic cloud discovery** from **agentic security reasoning** and **end-to-end telemetry** so resource enumeration remains repeatable while multi-hop lineage tracing and risk synthesis run inside an observable tool-calling loop:

```text
+-------------------------------------------------------------------------+
|              AgentHub Streamlit Console (app.py)                        |
|  - On-demand crawler trigger, compliance score & Altair posture chart   |
|  - Color-coded agent cards, expandable IAM JSON & CSV/JSON exports      |
|  - Interactive Governance Assistant chat                                |
|  - Visual Trace Flowchart (st.html) + Langfuse Cloud v2 history         |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|            Agentic Governance Engine (agent_engine.py)                  |
|  - LLM: openai/gpt-oss-120b (Groq OpenAI-compatible API, low reasoning) |
|  - Observability: Langfuse v3 @observe() spans, generations & flush()   |
|  - Autonomous Tool-Calling Loop:                                        |
|      1. query_inventory() -> searches services, IAM actions & tools     |
|      2. scan_aws_agents() -> triggers live multi-region boto3 discovery |
|      3. audit_security_and_governance() -> flags wildcards & shadow AI  |
|      4. inspect_agent_lineage() -> traces CloudTrail & IAM policies     |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|             Deterministic Boto3 Cloud Crawler (crawler.py)              |
|  - Lambda + Resource Groups Tagging API cross-check (shadow detection)  |
|  - IAM Role Parser (trust, inline, & managed policy normalization)      |
|  - CloudTrail Event History lookup (CreateFunction / CreateAgent)       |
|  - Amazon Bedrock Agents Classic scan (graceful ClientError fallback)   |
+------------------------------------+------------------------------------+
                                     | Read-Only Boto3 APIs
                                     v
+-------------------------------------------------------------------------+
|                    AWS Environment (us-east-1)                          |
|  [agent-tool-caller]  [agent-function-caller]  [agent-orchestrator]     |
|  [shadow-analytics-agent]  |  S3 Bucket  |  DynamoDB (AgentTasks)       |
+-------------------------------------------------------------------------+

```

---

## Deployed Agent Testbed

The setup scripts deploy four distinct Lambda agents in `us-east-1` (configured for free-tier / minimal idle footprint) to validate least-privilege boundaries, multi-hop delegation, and shadow AI detection:

| Agent Name | Classification | Governance Tags | IAM Data / Service Access | Security Posture |
| --- | --- | --- | --- | --- |
| **`agent-tool-caller`** | `lambda` (Governed) | `type=agent`, `owner=krishnan` | `s3:GetObject`, `s3:ListBucket` scoped to `agent-crawler-data-krishnan-*` | Least-privilege compliant (`broad_access_flag: false`) |
| **`agent-function-caller`** | `lambda` (Governed) | `type=agent`, `owner=krishnan` | `dynamodb:GetItem`, `dynamodb:Query` scoped to `table/AgentTasks` | Least-privilege compliant (`broad_access_flag: false`) |
| **`agent-orchestrator`** | `lambda` (Governed) | `type=agent`, `owner=krishnan` | `lambda:InvokeFunction` scoped strictly to `agent-tool-caller` and `agent-function-caller` | Least-privilege compliant (`broad_access_flag: false`) |
| **`shadow-analytics-agent`** | `lambda-shadow` (Untagged) | None (omitted intentionally) | `s3:ListAllMyBuckets` on `Resource: "*"` | Flagged: missing `type=agent` tag + wildcard resource (`broad_access_flag: true`) |

---

## Key Capabilities

* **Shadow AI Agent Detection:** Cross-references `resourcegroupstaggingapi:get_resources` (`type=agent`) against `lambda:list_functions` to uncover untagged agents matching naming or environment conventions (`agent` in function name or `AGENT_ROLE` variable) that tag-only queries miss.
* **IAM Execution Role & Blast-Radius Analysis:** Resolves inline and managed policies attached to each agent's execution role, normalizes single-string vs. list policy fields (`Statement`, `Action`, `Resource`), separates `Allow` and `Deny` rules, filters routine CloudWatch Logs permissions, and flags wildcard (`*`) resource exposure.
* **CloudTrail Creator Attribution:** Queries CloudTrail's 90-day Event History (`CreateFunction*` / `CreateAgent`) with a rate-limit throttle guard (`0.6s` delay to stay within the 2 TPS `LookupEvents` limit) and falls back to the `owner` tag if an event ages out of the 90-day window.
* **Autonomous Governance Assistant (`openai/gpt-oss-120b`):** Uses Groq's OpenAI-compatible tool-calling API (`reasoning_effort="low"`) with a compact inventory snapshot and four specialized tools (`query_inventory`, `scan_aws_agents`, `audit_security_and_governance`, `inspect_agent_lineage`), falling back to a deterministic offline summary if `GROQ_API_KEY` is unset.
* **Langfuse Observability & Visual Trace Flowchart:** Instruments agent turns, Groq token generations, tool calls, and manual UI scans with Langfuse Python SDK v3 `@observe()` decorators. Renders a plain-English visual execution flowchart (`User Request` -> `AI Reasoning` -> `AWS Tool Action` -> `Complete`) alongside raw JSON span payloads and Langfuse Cloud v2 observations history (`/api/public/v2/observations`).
* **Graceful Bedrock Agents Support:** Scans Amazon Bedrock Agents (`list_agents`, `get_agent`, action groups, and knowledge bases) wrapped in `ClientError` handling so accounts restricted by Bedrock Agents Classic maintenance mode degrade cleanly without interrupting Lambda discovery.

---

## Repository Structure

```text
aws-agentic-governance/
├── setup_agent_1.py               # Provisions S3 bucket + agent-tool-caller Lambda
├── setup_agents_2_and_3.py        # Provisions DynamoDB table + function-caller & orchestrator Lambdas
├── setup_shadow_agent.py          # Provisions untagged shadow-analytics-agent with wildcard S3 access
├── crawler.py                     # Unified multi-region AWS discovery & JSON/CSV report exporter
├── agent_engine.py                # Groq tool-calling governance engine + Langfuse v3 instrumentation
├── app.py                         # AgentHub dark-mode Streamlit console & visual trace flowchart UI
├── crawler_readonly_policy.json   # Least-privilege read-only IAM policy for running the crawler
├── cleanup_env.py                 # Teardown script to delete all provisioned AWS demo resources
├── requirements.txt               # Python dependencies (boto3, python-dotenv, streamlit, langfuse)
└── .gitignore                     # Excludes .venv, .env secrets, and generated report artifacts

```

---

## Setup & Execution Guide

### 1. Prerequisites

* Python 3.10+
* Configured AWS CLI credentials (`aws configure`) with permissions to provision IAM roles, Lambda functions, S3 buckets, and DynamoDB tables
* *(Optional)* A [Groq API Key](https://console.groq.com/) for the `openai/gpt-oss-120b` Governance Assistant
* *(Optional)* [Langfuse Cloud](https://cloud.langfuse.com/) project keys (`LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY`) for trace ingestion and Cloud history sync

### 2. Local Environment Setup

```bash
git clone [https://github.com/Krishnan2102/aws-agentic-governance.git](https://github.com/Krishnan2102/aws-agentic-governance.git)
cd aws-agentic-governance

python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# Linux / macOS:
# source .venv/bin/activate

pip install -r requirements.txt

```

Create a `.env` file in the project root (ignored by Git):

```env
GROQ_API_KEY=gsk_your_groq_api_key_here
LANGFUSE_PUBLIC_KEY=pk-lf-your_public_key_here
LANGFUSE_SECRET_KEY=sk-lf-your_secret_key_here
LANGFUSE_BASE_URL=[https://cloud.langfuse.com](https://cloud.langfuse.com)

```

*(Use `https://us.cloud.langfuse.com` if your Langfuse project is hosted in the US region.)*

### 3. Provision the AWS Multi-Agent Testbed

Run the setup scripts in sequence to create the S3 bucket, DynamoDB table, three governed agents, and one untagged shadow agent:

```bash
python setup_agent_1.py
python setup_agents_2_and_3.py
python setup_shadow_agent.py

```

### 4. Run the Standalone CLI Crawler (Optional)

Run `crawler.py` directly to scan `us-east-1` from the terminal and export `agents_report.json` and `agents_report.csv`:

```bash
python crawler.py

```

### 5. Launch the AgentHub Streamlit Console

Start the interactive governance and observability dashboard:

```bash
streamlit run app.py

```

Open `http://localhost:8501` in your browser and click **Run Crawler** to populate the compliance score, Altair posture chart, agent inventory cards, Governance Assistant chat, and **Observability & Langfuse** visual trace flowcharts.

---

## Security & Least-Privilege Operation

For production or read-only audit runs, attach `crawler_readonly_policy.json` to a dedicated IAM user or role. The crawler uses only read-only discovery permissions (`lambda:List*`, `lambda:Get*`, `tag:GetResources`, `iam:Get*`, `iam:List*`, `cloudtrail:LookupEvents`, `bedrock:List*`, `bedrock:Get*`, `sts:GetCallerIdentity`) with no write or invocation permissions, and does not execute deployed Lambda functions or foundation models during scans.

---

## Environment Teardown

When testing is complete, remove all provisioned Lambda functions, IAM execution roles, the DynamoDB table, and the S3 bucket (including objects) with a single command:

```bash
python cleanup_env.py

```

```

Commit and push the updated `README.md` alongside your final `app.py` and `agent_engine.py`:

```powershell
git add README.md app.py agent_engine.py requirements.txt
git commit -m "Update README with AgentHub UI, Langfuse v3 tracing, and visual trace flowcharts"
git push origin main

```
