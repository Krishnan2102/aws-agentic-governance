# AWS Agentic AI Environment & Governance Crawler

An automated AWS discovery and auditing crawler built with Python and `boto3` that inventories AI agents deployed across an AWS account, resolves their IAM execution permissions and data access boundaries, traces creator attribution via CloudTrail, and exports structured JSON/CSV governance reports.

---

## Architecture Overview

```text
+-------------------------------------------------------------------+
|                     AWS Account (us-east-1)                       |
|                                                                   |
|  +-----------------------+     +-------------------------------+  |
|  |  agent-orchestrator   |---->|       agent-tool-caller       |  |
|  | (Lambda - Python 3.12)|     |     (Lambda - Python 3.12)    |  |
|  +-----------------------+     +---------------+---------------+  |
|              |                                 |                  |
|              |                   s3:GetObject  |                  |
|              |                   s3:ListBucket |                  |
|              v                                 v                  |
|  +-----------------------+     +-------------------------------+  |
|  | agent-function-caller |     |           Amazon S3           |  |
|  | (Lambda - Python 3.12)|     |  (agent-crawler-data-bucket)  |  |
|  +-----------+-----------+     +-------------------------------+  |
|              |                                                    |
|              | dynamodb:GetItem, Query                            |
|              v                                                    |
|  +-----------------------+     +-------------------------------+  |
|  |    Amazon DynamoDB    |     |    Amazon Bedrock Agent       |  |
|  |     (AgentTasks)      |     |   (Planned - Control Plane)   |  |
|  +-----------------------+     +-------------------------------+  |
+-------------------------------------------------------------------+
                                 ^
                                 | Read-Only Boto3 API Calls
                                 | (Lambda, IAM, Tagging, CloudTrail, Bedrock)
+--------------------------------+----------------------------------+
|                 Local Crawler (Python + Boto3)                    |
|  - Discovers tagged & untagged agents across regions              |
|  - Parses IAM trust, inline & managed policies for blast radius   |
|  - Queries CloudTrail Event History (90-day window) for creator   |
|  - Exports agents_report.json and agents_report.csv               |
+-------------------------------------------------------------------+

```

---

## Deployed Agent Environment (`us-east-1`)

All agents run on **AWS Free Tier** resources with zero paid LLM token invocations (using rule-based routing and mock handlers) and consistent resource tagging (`type=agent`, `owner=<name>`, `purpose=<description>`).

| Agent Name | Runtime / Type | Execution Role | Least-Privilege Data / Action Scope |
| --- | --- | --- | --- |
| `agent-tool-caller` | AWS Lambda (`python3.12`) | `agent-tool-caller-role` | `s3:GetObject`, `s3:ListBucket` scoped strictly to the project S3 bucket (`docs/faq.txt`) |
| `agent-function-caller` | AWS Lambda (`python3.12`) | `agent-function-caller-role` | `dynamodb:GetItem`, `dynamodb:Query` scoped strictly to the `AgentTasks` table (1 RCU / 1 WCU) |
| `agent-orchestrator` | AWS Lambda (`python3.12`) | `agent-orchestrator-role` | `lambda:InvokeFunction` scoped strictly to `agent-tool-caller` and `agent-function-caller` |

---

## Local Setup & Usage

### 1. Prerequisites

* Python 3.10+
* An AWS account with CLI credentials configured (`aws configure`) under a non-root IAM user

### 2. Install Dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows PowerShell: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

```

### 3. Provision the Agent Environment

```bash
python setup_agent_1.py
python setup_agents_2_and_3.py

```

### 4. Run the Discovery Crawler

```bash
# Step 1: Discover Lambda agents via pagination and tag filtering
python crawler_step1.py

```

---

## Implementation Progress

* [x] **Phase 1:** S3 data bucket, least-privilege IAM role, `agent-tool-caller` Lambda, and initial paginated Lambda tag discovery (`crawler_step1.py`).
* [x] **Phase 2:** Provisioned DynamoDB table (`AgentTasks`), `agent-function-caller`, and `agent-orchestrator` multi-agent routing setup.
* [ ] **Phase 3:** IAM policy parser (trust, inline, and managed policies + wildcard detection) and CloudTrail `lookup_events` creator attribution.
* [ ] **Phase 4:** Resource Groups Tagging API cross-check, non-invoked Bedrock Agent discovery, multi-region scanning, and unified JSON/CSV report export.
* [ ] **Phase 5:** Read-only crawler IAM policy lockdown and environment teardown script.

---

## Known Limitations & Governance Scope

* **IAM Evaluation Boundaries:** The crawler inspects execution role trust policies, inline policies, and attached managed policies, flagging wildcard (`*`) resource access. It does not simulate effective permissions across S3 bucket policies, DynamoDB resource-based policies, IAM permission boundaries, Service Control Policies (SCPs), or cross-account role assumptions.
* **CloudTrail Attribution Window:** `cloudtrail:LookupEvents` queries AWS Event History, which retains management events for **90 days**. Agents created earlier than 90 days ago fall back to the resource's `owner` tag.
* **Discovery Scope:** Untagged Lambda functions or custom agent workloads hosted outside AWS Lambda / Amazon Bedrock (e.g., containers or external hosts) are outside automated tag-based discovery unless explicitly tagged.

```

Once you push this initial commit to GitHub, go ahead and run `crawler_step2.py` from our previous step and paste its output here so we can verify the IAM policy parsing and CloudTrail creator lookup.

```
