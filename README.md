# AWS Agentic AI Discovery & Governance Crawler

An automated AWS discovery, IAM blast-radius auditing, and agentic governance framework built with Python, `boto3`, Groq (`openai/gpt-oss-120b`), and Streamlit.

This project deploys a reproducible multi-agent AWS testbed (comprising governed Lambda workers, a multi-agent orchestrator, and an untagged shadow agent), discovers deployed agents across AWS services, resolves their effective IAM permissions and CloudTrail creator lineage, and exposes the inventory through an interactive Streamlit console and tool-calling governance assistant.

---

## Architecture Overview

The system separates **deterministic cloud discovery** from **agentic security reasoning** so resource enumeration remains repeatable while multi-hop lineage tracing and risk synthesis are handled by an LLM tool-calling loop:

```text
+-------------------------------------------------------------------------+
|                   Streamlit Governance Console (app.py)                 |
|  - One-click AWS crawler scan trigger & KPI posture strip               |
|  - Structured agent inventory table & expandable IAM JSON inspection    |
|  - JSON / CSV report downloads                                          |
|  - Interactive Agentic Governance Assistant chat                        |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|            Agentic Governance Engine (agent_engine.py)                  |
|  - LLM: openai/gpt-oss-120b (Groq OpenAI-compatible API, low reasoning) |
|  - Autonomous Tool-Calling Loop:                                        |
|      1. scan_aws_agents() -> triggers multi-region boto3 discovery      |
|      2. audit_security_and_governance() -> flags wildcards & shadow AI  |
|      3. inspect_agent_lineage() -> traces CloudTrail & IAM policies     |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|             Deterministic Boto3 Cloud Crawler (crawler.py)              |
|  - Lambda + Resource Groups Tagging API cross-check (shadow detection)  |
|  - IAM Role Parser (trust, inline, & managed policy normalization)      |
|  - CloudTrail Event History lookup (CreateFunction / CreateAgent)       |
|  - Amazon Bedrock Agents Classic scan (graceful maintenance-mode skip)  |
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

The setup scripts provision four distinct Lambda agents in `us-east-1` (configured for zero-cost idle/free-tier operation) to test both governed least-privilege boundaries and shadow AI detection:

| Agent Name | Classification | Governance Tags | IAM Data / Service Access | Security Posture |
| --- | --- | --- | --- | --- |
| **`agent-tool-caller`** | `lambda` (Governed) | `type=agent`, `owner=krishnan` | `s3:GetObject`, `s3:ListBucket` scoped to `agent-crawler-data-krishnan-*` | Least-privilege compliant (`broad_access_flag: false`) |
| **`agent-function-caller`** | `lambda` (Governed) | `type=agent`, `owner=krishnan` | `dynamodb:GetItem`, `dynamodb:Query` scoped to `table/AgentTasks` | Least-privilege compliant (`broad_access_flag: false`) |
| **`agent-orchestrator`** | `lambda` (Governed) | `type=agent`, `owner=krishnan` | `lambda:InvokeFunction` scoped strictly to `agent-tool-caller` and `agent-function-caller` | Least-privilege compliant (`broad_access_flag: false`) |
| **`shadow-analytics-agent`** | `lambda-shadow` (Untagged) | None (omitted intentionally) | `s3:ListAllMyBuckets` on `Resource: "*"` | Flagged: missing `type=agent` tag + wildcard resource (`broad_access_flag: true`) |

---

## Key Capabilities

* **Shadow AI Agent Detection:** Cross-references `resourcegroupstaggingapi:get_resources` (`type=agent`) against `lambda:list_functions` to detect untagged agents matching naming or environment conventions (`agent` in function name or `AGENT_ROLE` variable) that tag-only queries miss.
* **IAM Execution Role & Blast-Radius Analysis:** Resolves inline and managed policies attached to each agent's execution role, normalizes single-string vs. list policy statements (`Statement`, `Action`, `Resource`), filters routine CloudWatch Logs permissions, and flags wildcard resource exposure (`*`).
* **CloudTrail Creator Attribution:** Queries CloudTrail's 90-day Event History (`CreateFunction*` / `CreateAgent`) with a rate-limit throttle guard (`0.6s` delay to stay safely within the 2 TPS `LookupEvents` limit) and falls back to the `owner` tag if an event has aged out of the 90-day window.
* **Graceful Bedrock Agents Handling:** Includes discovery support for Amazon Bedrock Agents (`list_agents`, `get_agent`, action groups, and knowledge bases) wrapped in `ClientError` handling so accounts affected by AWS's post-July 30, 2026 Bedrock Agents Classic maintenance-mode restriction degrade cleanly without interrupting scans.
* **Autonomous Governance Assistant:** Uses `openai/gpt-oss-120b` via Groq to invoke crawler, audit, and lineage tools on demand, with an automatic deterministic offline summary fallback if `GROQ_API_KEY` is omitted.

---

## Repository Structure

```text
aws-agentic-governance/
├── setup_agent_1.py               # Provisions S3 bucket + agent-tool-caller Lambda
├── setup_agents_2_and_3.py        # Provisions DynamoDB table + function-caller & orchestrator Lambdas
├── setup_shadow_agent.py          # Provisions untagged shadow-analytics-agent with wildcard S3 access
├── crawler.py                     # Multi-region deterministic AWS discovery & JSON/CSV exporter
├── agent_engine.py                # ReAct/tool-calling governance agent powered by openai/gpt-oss-120b
├── app.py                         # Streamlit governance dashboard & interactive agent chat UI
├── crawler_readonly_policy.json   # Least-privilege read-only IAM policy for running the crawler
├── cleanup_env.py                 # Teardown script to delete all provisioned AWS demo resources
├── requirements.txt               # Python dependencies (boto3, python-dotenv, streamlit)
└── .gitignore                     # Excludes .venv, .env secrets, and generated report artifacts

```

---

## Setup & Execution Guide

### 1. Prerequisites

* Python 3.10+
* Configured AWS CLI credentials (`aws configure`) with permissions to provision IAM roles, Lambda functions, S3 buckets, and DynamoDB tables
* *(Optional)* A free-tier [Groq API Key](https://console.groq.com/) for the `openai/gpt-oss-120b` governance assistant

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

```

### 3. Provision the AWS Multi-Agent Testbed

Run the setup scripts in order to create the S3 data store, DynamoDB task table, three governed agents, and one untagged shadow agent:

```bash
python setup_agent_1.py
python setup_agents_2_and_3.py
python setup_shadow_agent.py

```

### 4. Run the CLI Crawler

Execute the standalone discovery pipeline to scan `us-east-1` and generate `agents_report.json` and `agents_report.csv`:

```bash
python crawler.py

```

### 5. Launch the Streamlit Governance Console

Start the interactive dashboard and tool-calling assistant:

```bash
streamlit run app.py

```

Open `http://localhost:8501` in your browser to trigger live scans, inspect IAM policy JSON per agent, download JSON/CSV reports, or query the governance assistant (e.g., *"Trace the execution chain from agent-orchestrator down to S3 and DynamoDB"*).

---

## Security & Least-Privilege Operation

For production or read-only audit runs, attach `crawler_readonly_policy.json` to a dedicated IAM user or role. The crawler requires **zero write permissions** (`lambda:List*`, `lambda:Get*`, `tag:GetResources`, `iam:Get*`, `iam:List*`, `cloudtrail:LookupEvents`, `bedrock:List*`, `bedrock:Get*`, `sts:GetCallerIdentity`) and never invokes deployed Lambda functions or foundation models during discovery.

---

## Environment Teardown

When testing is complete, remove all provisioned Lambda functions, IAM execution roles, the DynamoDB table, and the S3 bucket (including objects) with a single command:

```bash
python cleanup_env.py

```

```

### Push Your Final Changes to GitHub
Once you save `README.md`, commit and push your complete codebase (`crawler.py`, `agent_engine.py`, `app.py`, `setup_shadow_agent.py`, `crawler_readonly_policy.json`, `cleanup_env.py`, `requirements.txt`, and `README.md`) to `main`:

```powershell
git add README.md requirements.txt crawler.py agent_engine.py app.py setup_shadow_agent.py crawler_readonly_policy.json cleanup_env.py
git commit -m "Add unified crawler, agentic governance engine, Streamlit UI, and README"
git push origin main

```

When you're ready, let me know if you want to test `app.py` together or walk through any section of the code before your review!