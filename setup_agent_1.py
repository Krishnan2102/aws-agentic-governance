import io
import json
import time
import zipfile
import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"  # Change this to your preferred AWS region
OWNER_NAME = "krishnan"  # Change this to your name/handle
BUCKET_NAME = f"agent-crawler-data-{OWNER_NAME}-{int(time.time())}"
ROLE_NAME = "agent-tool-caller-role"
FUNCTION_NAME = "agent-tool-caller"

s3 = boto3.client("s3", region_name=REGION)
iam = boto3.client("iam", region_name=REGION)
lam = boto3.client("lambda", region_name=REGION)


# 1. Create a small S3 bucket with a sample file
def create_bucket():
    try:
        # Note: us-east-1 does NOT accept CreateBucketConfiguration LocationConstraint
        s3.create_bucket(Bucket=BUCKET_NAME)
        s3.put_object(
            Bucket=BUCKET_NAME,
            Key="docs/faq.txt",
            Body=b"Internship FAQ: Submissions are evaluated on security, accuracy, and documentation.",
        )
        print(f"[OK] Created S3 bucket: {BUCKET_NAME}")
    except ClientError as e:
        print(f"[ERR] S3: {e}")
        raise


# 2. Create IAM Execution Role with Trust Policy + Least-Privilege Inline Policy
def create_execution_role():
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
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description="Execution role for tool-caller Lambda agent",
            Tags=[
                {"Key": "type", "Value": "agent-role"},
                {"Key": "owner", "Value": OWNER_NAME},
            ],
        )
        role_arn = resp["Role"]["Arn"]
        print(f"[OK] Created IAM role: {role_arn}")
    except ClientError as e:
        if e.response["Error"]["Code"] == "EntityAlreadyExists":
            role_arn = iam.get_role(RoleName=ROLE_NAME)["Role"]["Arn"]
            print(f"[OK] Reusing existing IAM role: {role_arn}")
        else:
            raise

    # Least-privilege inline policy: read-only on our specific bucket + CloudWatch Logs
    inline_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "ReadSpecificS3Bucket",
                "Effect": "Allow",
                "Action": ["s3:GetObject", "s3:ListBucket"],
                "Resource": [
                    f"arn:aws:s3:::{BUCKET_NAME}",
                    f"arn:aws:s3:::{BUCKET_NAME}/*",
                ],
            },
            {
                "Sid": "WriteCloudWatchLogs",
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                "Resource": f"arn:aws:logs:{REGION}:*:*",
            },
        ],
    }

    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName="tool-caller-least-privilege",
        PolicyDocument=json.dumps(inline_policy),
    )
    print("[OK] Attached inline least-privilege policy")

    # IAM propagation pause so Lambda can assume the new role immediately
    time.sleep(10)
    return role_arn


# 3. Package and create the Lambda agent
def create_lambda_agent(role_arn):
    handler_code = '''import json
import os
import boto3

s3 = boto3.client("s3")

def lambda_handler(event, context):
    """Simple rule-based tool-calling agent (zero paid LLM calls)."""
    query = event.get("query", "").lower()
    bucket = os.environ.get("DATA_BUCKET", "")

    if "faq" in query or "doc" in query:
        obj = s3.get_object(Bucket=bucket, Key="docs/faq.txt")
        content = obj["Body"].read().decode("utf-8")
        return {"statusCode": 200, "tool_used": "s3_doc_reader", "result": content}

    return {
        "statusCode": 200,
        "tool_used": "none",
        "result": "No matching tool triggered. Try asking about 'faq'.",
    }
'''
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("lambda_function.py", handler_code)
    zip_buffer.seek(0)

    try:
        resp = lam.create_function(
            FunctionName=FUNCTION_NAME,
            Runtime="python3.12",
            Role=role_arn,
            Handler="lambda_function.lambda_handler",
            Code={"ZipFile": zip_buffer.read()},
            Description="Tool-calling AI agent that reads S3 knowledge documents",
            Timeout=15,
            MemorySize=128,
            Environment={
                "Variables": {
                    "AGENT_ROLE": "tool-caller",
                    "AGENT_TOOLS": "s3_doc_reader,keyword_matcher",
                    "AGENT_MODEL": "rule-based-v1",
                    "DATA_BUCKET": BUCKET_NAME,
                }
            },
            Tags={
                "type": "agent",
                "owner": OWNER_NAME,
                "purpose": "Retrieves FAQ documents from S3 using tool calls",
            },
        )
        print(f"[OK] Created Lambda agent: {resp['FunctionArn']}")
    except ClientError as e:
        print(f"[ERR] Lambda: {e}")
        raise


if __name__ == "__main__":
    create_bucket()
    arn = create_execution_role()
    create_lambda_agent(arn)