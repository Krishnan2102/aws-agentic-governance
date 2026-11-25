import json
import time
import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
OWNER_NAME = "krishnan"
BEDROCK_ROLE_NAME = "AmazonBedrockExecutionRoleForAgents_CrawlerDemo"
BEDROCK_AGENT_NAME = "support-triage-bedrock-agent"
ACTION_GROUP_NAME = "faq-lookup-actions"
TARGET_LAMBDA_NAME = "agent-tool-caller"

iam = boto3.client("iam", region_name=REGION)
lam = boto3.client("lambda", region_name=REGION)
bedrock = boto3.client("bedrock-agent", region_name=REGION)
sts = boto3.client("sts", region_name=REGION)

ACCOUNT_ID = sts.get_caller_identity()["Account"]


def create_bedrock_service_role():
    """Create IAM execution role for Amazon Bedrock Agent (never invoked = $0)."""
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "bedrock.amazonaws.com"},
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {"aws:SourceAccount": ACCOUNT_ID},
                    "ArnLike": {
                        "aws:SourceArn": f"arn:aws:bedrock:{REGION}:{ACCOUNT_ID}:agent/*"
                    },
                },
            }
        ],
    }

    try:
        resp = iam.create_role(
            RoleName=BEDROCK_ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description="Execution role for uninvoked Bedrock Agent governance demo",
            Tags=[
                {"Key": "type", "Value": "agent-role"},
                {"Key": "owner", "Value": OWNER_NAME},
            ],
        )
        role_arn = resp["Role"]["Arn"]
        print(f"[OK] Created Bedrock IAM role: {role_arn}")
    except ClientError as e:
        if e.response["Error"]["Code"] == "EntityAlreadyExists":
            role_arn = iam.get_role(RoleName=BEDROCK_ROLE_NAME)["Role"]["Arn"]
            print(f"[OK] Reusing Bedrock IAM role: {role_arn}")
        else:
            raise

    # Minimal model + Lambda action group permissions for policy inspection
    inline_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowFoundationModelMetadata",
                "Effect": "Allow",
                "Action": ["bedrock:InvokeModel"],
                "Resource": f"arn:aws:bedrock:{REGION}::foundation-model/anthropic.claude-3-haiku-20240307-v1:0",
            },
            {
                "Sid": "AllowActionGroupLambda",
                "Effect": "Allow",
                "Action": ["lambda:InvokeFunction"],
                "Resource": f"arn:aws:lambda:{REGION}:{ACCOUNT_ID}:function:{TARGET_LAMBDA_NAME}",
            },
        ],
    }
    iam.put_role_policy(
        RoleName=BEDROCK_ROLE_NAME,
        PolicyName="bedrock-agent-least-privilege",
        PolicyDocument=json.dumps(inline_policy),
    )
    time.sleep(10)
    return role_arn


def create_bedrock_agent(role_arn):
    """Create Bedrock Agent + OpenAPI Action Group WITHOUT invoking it ($0 cost)."""
    existing = bedrock.list_agents().get("agentSummaries", [])
    agent_id = None
    for item in existing:
        if item["agentName"] == BEDROCK_AGENT_NAME:
            agent_id = item["agentId"]
            print(f"[OK] Reusing existing Bedrock Agent: {agent_id}")
            break

    if not agent_id:
        resp = bedrock.create_agent(
            agentName=BEDROCK_AGENT_NAME,
            agentResourceRoleArn=role_arn,
            foundationModel="anthropic.claude-3-haiku-20240307-v1:0",
            description="Customer support triage agent built on Amazon Bedrock (uninvoked demo)",
            instruction=(
                "You are a support triage assistant. Use the FAQ lookup action group to retrieve "
                "official internship guidelines and summarize answers clearly for the user."
            ),
            idleSessionTTLInSeconds=600,
            tags={
                "type": "agent",
                "owner": OWNER_NAME,
                "purpose": "Bedrock control-plane agent with Lambda action group",
            },
        )
        agent_id = resp["agent"]["agentId"]
        print(f"[OK] Created Bedrock Agent: {agent_id}")
        time.sleep(5)

    # Attach an inline OpenAPI 3.0 schema Action Group pointing to agent-tool-caller
    openapi_schema = {
        "openapi": "3.0.0",
        "info": {"title": "FAQ Lookup API", "version": "1.0.0"},
        "paths": {
            "/faq": {
                "get": {
                    "summary": "Retrieve internship FAQ text",
                    "description": "Fetches the FAQ document from S3 via Lambda.",
                    "operationId": "getFaqDocument",
                    "responses": {"200": {"description": "FAQ content returned"}},
                }
            }
        },
    }

    lambda_arn = f"arn:aws:lambda:{REGION}:{ACCOUNT_ID}:function:{TARGET_LAMBDA_NAME}"
    try:
        bedrock.create_agent_action_group(
            agentId=agent_id,
            agentVersion="DRAFT",
            actionGroupName=ACTION_GROUP_NAME,
            description="Queries S3 FAQ documents via agent-tool-caller Lambda",
            actionGroupExecutor={"lambda": lambda_arn},
            apiSchema={"payload": json.dumps(openapi_schema)},
            actionGroupState="ENABLED",
        )
        print(f"[OK] Attached Action Group '{ACTION_GROUP_NAME}' to Bedrock Agent")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConflictException":
            print(f"[OK] Action Group '{ACTION_GROUP_NAME}' already exists")
        else:
            raise

    # Allow Bedrock service principal to invoke the Lambda action group
    try:
        lam.add_permission(
            FunctionName=TARGET_LAMBDA_NAME,
            StatementId="AllowBedrockAgentInvoke",
            Action="lambda:InvokeFunction",
            Principal="bedrock.amazonaws.com",
            SourceArn=f"arn:aws:bedrock:{REGION}:{ACCOUNT_ID}:agent/{agent_id}",
        )
        print("[OK] Granted bedrock.amazonaws.com invoke permission on Lambda")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceConflictException":
            print("[OK] Lambda resource policy for Bedrock already exists")
        else:
            raise

    # Prepare the DRAFT agent so its configuration is valid (still $0 — no invocation)
    bedrock.prepare_agent(agentId=agent_id)
    print(f"[OK] Prepared Bedrock Agent '{BEDROCK_AGENT_NAME}' (ID: {agent_id}) - ZERO invocations")


if __name__ == "__main__":
    role = create_bedrock_service_role()
    create_bedrock_agent(role)