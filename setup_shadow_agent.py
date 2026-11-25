import io
import json
import time
import zipfile
import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
ROLE_NAME = "shadow-analytics-agent-role"
FUNCTION_NAME = "shadow-analytics-agent"

iam = boto3.client("iam", region_name=REGION)
lam = boto3.client("lambda", region_name=REGION)


def create_shadow_agent():
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
        role_arn = iam.create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description="Execution role for shadow untagged agent demo",
        )["Role"]["Arn"]
    except ClientError as e:
        if e.response["Error"]["Code"] == "EntityAlreadyExists":
            role_arn = iam.get_role(RoleName=ROLE_NAME)["Role"]["Arn"]
        else:
            raise

    # Deliberately overly broad S3 resource ('*') to test crawler broad_access_flag
    inline_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "OverlyBroadS3List",
                "Effect": "Allow",
                "Action": ["s3:ListAllMyBuckets"],
                "Resource": "*",
            }
        ],
    }
    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName="shadow-agent-broad-s3",
        PolicyDocument=json.dumps(inline_policy),
    )
    time.sleep(10)

    code = '''def lambda_handler(event, context):
    return {"statusCode": 200, "result": "Shadow analytics agent stub"}
'''
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("lambda_function.py", code)
    buf.seek(0)

    try:
        resp = lam.create_function(
            FunctionName=FUNCTION_NAME,
            Runtime="python3.12",
            Role=role_arn,
            Handler="lambda_function.lambda_handler",
            Code={"ZipFile": buf.read()},
            Description="Untagged analytics agent deployed without governance tags",
            Timeout=10,
            MemorySize=128,
            Environment={
                "Variables": {
                    "AGENT_ROLE": "analytics-worker",
                    "AGENT_TOOLS": "list_all_buckets",
                    "AGENT_MODEL": "rule-based-v1",
                }
            },
            # Intentionally NO Tags passed here to test shadow-agent discovery
        )
        print(f"[OK] Created untagged shadow agent: {resp['FunctionArn']}")
    except ClientError as e:
        print(f"[ERR] {e}")
        raise


if __name__ == "__main__":
    create_shadow_agent()