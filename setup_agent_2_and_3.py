import io
import json
import time
import zipfile
import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
OWNER_NAME = "krishnan"  # Match your Step 1 owner tag
TABLE_NAME = "AgentTasks"

ddb = boto3.client("dynamodb", region_name=REGION)
iam = boto3.client("iam", region_name=REGION)
lam = boto3.client("lambda", region_name=REGION)
sts = boto3.client("sts", region_name=REGION)

ACCOUNT_ID = sts.get_caller_identity()["Account"]


# 1. Create Free-Tier Provisioned DynamoDB Table (1 RCU / 1 WCU)
def create_dynamodb_table():
    try:
        ddb.create_table(
            TableName=TABLE_NAME,
            KeySchema=[{"AttributeName": "task_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "task_id", "AttributeType": "S"}],
            BillingMode="PROVISIONED",
            ProvisionedThroughput={"ReadCapacityUnits": 1, "WriteCapacityUnits": 1},
            Tags=[
                {"Key": "type", "Value": "agent-data"},
                {"Key": "owner", "Value": OWNER_NAME},
            ],
        )
        print(f"[WAIT] Creating DynamoDB table '{TABLE_NAME}'...")
        waiter = ddb.get_waiter("table_exists")
        waiter.wait(TableName=TABLE_NAME)
        print(f"[OK] DynamoDB table '{TABLE_NAME}' is active")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceInUseException":
            print(f"[OK] Reusing existing DynamoDB table '{TABLE_NAME}'")
        else:
            raise

    ddb.put_item(
        TableName=TABLE_NAME,
        Item={
            "task_id": {"S": "TASK-101"},
            "status": {"S": "IN_PROGRESS"},
            "assignee": {"S": OWNER_NAME},
        },
    )
    print("[OK] Seeded sample item TASK-101 into DynamoDB")


def _ensure_role(role_name, policy_name, statements, description):
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
    try:
        resp = iam.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description=description,
            Tags=[
                {"Key": "type", "Value": "agent-role"},
                {"Key": "owner", "Value": OWNER_NAME},
            ],
        )
        role_arn = resp["Role"]["Arn"]
        print(f"[OK] Created IAM role: {role_arn}")
    except ClientError as e:
        if e.response["Error"]["Code"] == "EntityAlreadyExists":
            role_arn = iam.get_role(RoleName=role_name)["Role"]["Arn"]
            print(f"[OK] Reusing IAM role: {role_arn}")
        else:
            raise

    logs_stmt = {
        "Sid": "WriteCloudWatchLogs",
        "Effect": "Allow",
        "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
        "Resource": f"arn:aws:logs:{REGION}:{ACCOUNT_ID}:*",
    }
    iam.put_role_policy(
        RoleName=role_name,
        PolicyName=policy_name,
        PolicyDocument=json.dumps({"Version": "2012-10-17", "Statement": statements + [logs_stmt]}),
    )
    return role_arn


def _zip_code(code_str):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("lambda_function.py", code_str)
    buf.seek(0)
    return buf.read()


# 2. Deploy Agent 2: Function-Caller (reads DynamoDB)
def create_function_caller():
    table_arn = f"arn:aws:dynamodb:{REGION}:{ACCOUNT_ID}:table/{TABLE_NAME}"
    role_arn = _ensure_role(
        role_name="agent-function-caller-role",
        policy_name="function-caller-ddb-readonly",
        statements=[
            {
                "Sid": "ReadSpecificDynamoDBTable",
                "Effect": "Allow",
                "Action": ["dynamodb:GetItem", "dynamodb:Query"],
                "Resource": table_arn,
            }
        ],
        description="Execution role for function-caller Lambda agent",
    )
    time.sleep(10)

    code = '''import json
import os
import boto3

ddb = boto3.client("dynamodb")

def lambda_handler(event, context):
    """Structured function-calling agent querying DynamoDB task status."""
    fn_name = event.get("function", "")
    args = event.get("arguments", {})
    table = os.environ.get("DATA_TABLE", "")

    if fn_name == "get_task_status":
        task_id = args.get("task_id", "TASK-101")
        resp = ddb.get_item(TableName=table, Key={"task_id": {"S": task_id}})
        return {"statusCode": 200, "function_called": fn_name, "item": resp.get("Item", {})}

    return {"statusCode": 400, "error": "Unknown function call"}
'''
    try:
        resp = lam.create_function(
            FunctionName="agent-function-caller",
            Runtime="python3.12",
            Role=role_arn,
            Handler="lambda_function.lambda_handler",
            Code={"ZipFile": _zip_code(code)},
            Description="Function-calling AI agent that executes structured DynamoDB lookups",
            Timeout=15,
            MemorySize=128,
            Environment={
                "Variables": {
                    "AGENT_ROLE": "function-caller",
                    "AGENT_TOOLS": "get_task_status,validate_json_schema",
                    "AGENT_MODEL": "groq-llama-3.3-70b-mock",
                    "DATA_TABLE": TABLE_NAME,
                }
            },
            Tags={
                "type": "agent",
                "owner": OWNER_NAME,
                "purpose": "Executes structured JSON function calls against DynamoDB",
            },
        )
        print(f"[OK] Created Lambda agent: {resp['FunctionArn']}")
    except ClientError as e:
        print(f"[ERR] agent-function-caller: {e}")
        raise


# 3. Deploy Agent 3: Orchestrator (routes requests to Agent 1 & Agent 2)
def create_orchestrator():
    target_arns = [
        f"arn:aws:lambda:{REGION}:{ACCOUNT_ID}:function:agent-tool-caller",
        f"arn:aws:lambda:{REGION}:{ACCOUNT_ID}:function:agent-function-caller",
    ]
    role_arn = _ensure_role(
        role_name="agent-orchestrator-role",
        policy_name="orchestrator-invoke-subagents",
        statements=[
            {
                "Sid": "InvokeSubAgentsOnly",
                "Effect": "Allow",
                "Action": ["lambda:InvokeFunction"],
                "Resource": target_arns,
            }
        ],
        description="Execution role for orchestrator Lambda agent",
    )
    time.sleep(10)

    code = '''import json
import os
import boto3

lam = boto3.client("lambda")

def lambda_handler(event, context):
    """Rule-based router delegating tasks to specialized sub-agents."""
    intent = event.get("intent", "faq")
    target = "agent-function-caller" if intent == "task" else "agent-tool-caller"
    resp = lam.invoke(FunctionName=target, InvocationType="RequestResponse", Payload=json.dumps(event))
    payload = json.loads(resp["Payload"].read().decode("utf-8"))
    return {"statusCode": 200, "routed_to": target, "agent_response": payload}
'''
    try:
        resp = lam.create_function(
            FunctionName="agent-orchestrator",
            Runtime="python3.12",
            Role=role_arn,
            Handler="lambda_function.lambda_handler",
            Code={"ZipFile": _zip_code(code)},
            Description="Supervisor agent that routes user intents to worker agents",
            Timeout=20,
            MemorySize=128,
            Environment={
                "Variables": {
                    "AGENT_ROLE": "orchestrator",
                    "AGENT_TOOLS": "delegate_to_tool_caller,delegate_to_function_caller",
                    "AGENT_MODEL": "rule-based-router-v1",
                    "SUB_AGENTS": "agent-tool-caller,agent-function-caller",
                }
            },
            Tags={
                "type": "agent",
                "owner": OWNER_NAME,
                "purpose": "Routes incoming queries to specialized Lambda sub-agents",
            },
        )
        print(f"[OK] Created Lambda agent: {resp['FunctionArn']}")
    except ClientError as e:
        print(f"[ERR] agent-orchestrator: {e}")
        raise


if __name__ == "__main__":
    create_dynamodb_table()
    create_function_caller()
    create_orchestrator()