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
