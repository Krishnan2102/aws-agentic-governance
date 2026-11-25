import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"

LAMBDA_FUNCTIONS = [
    "agent-tool-caller",
    "agent-function-caller",
    "agent-orchestrator",
    "shadow-analytics-agent",
]

IAM_ROLES = [
    "agent-tool-caller-role",
    "agent-function-caller-role",
    "agent-orchestrator-role",
    "shadow-analytics-agent-role",
    "AmazonBedrockExecutionRoleForAgents_CrawlerDemo",
]

DYNAMODB_TABLES = ["AgentTasks"]
BUCKET_PREFIX = "agent-crawler-data-"


def delete_lambdas():
    lam = boto3.client("lambda", region_name=REGION)
    for fn in LAMBDA_FUNCTIONS:
        try:
            lam.delete_function(FunctionName=fn)
            print(f"[DELETED] Lambda: {fn}")
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                print(f"[SKIP] Lambda not found: {fn}")
            else:
                print(f"[ERR] Lambda {fn}: {e}")


def delete_roles():
    iam = boto3.client("iam", region_name=REGION)
    for role in IAM_ROLES:
        try:
            # 1. Delete all inline policies first
            inline = iam.list_role_policies(RoleName=role).get("PolicyNames", [])
            for pol in inline:
                iam.delete_role_policy(RoleName=role, PolicyName=pol)

            # 2. Detach any managed policies
            attached = iam.list_attached_role_policies(RoleName=role).get("AttachedPolicies", [])
            for att in attached:
                iam.detach_role_policy(RoleName=role, PolicyArn=att["PolicyArn"])

            # 3. Delete the role
            iam.delete_role(RoleName=role)
            print(f"[DELETED] IAM Role: {role}")
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchEntity":
                print(f"[SKIP] IAM Role not found: {role}")
            else:
                print(f"[ERR] IAM Role {role}: {e}")


def delete_dynamodb_tables():
    ddb = boto3.client("dynamodb", region_name=REGION)
    for table in DYNAMODB_TABLES:
        try:
            ddb.delete_table(TableName=table)
            print(f"[DELETED] DynamoDB Table: {table}")
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                print(f"[SKIP] DynamoDB Table not found: {table}")
            else:
                print(f"[ERR] DynamoDB {table}: {e}")


def delete_project_buckets():
    s3 = boto3.client("s3", region_name=REGION)
    buckets = s3.list_buckets().get("Buckets", [])
    for b in buckets:
        name = b["Name"]
        if not name.startswith(BUCKET_PREFIX):
            continue
        try:
            # S3 buckets must be completely empty before delete_bucket succeeds
            objs = s3.list_objects_v2(Bucket=name).get("Contents", [])
            if objs:
                s3.delete_objects(
                    Bucket=name,
                    Delete={"Objects": [{"Key": o["Key"]} for o in objs]},
                )
            s3.delete_bucket(Bucket=name)
            print(f"[DELETED] S3 Bucket: {name}")
        except ClientError as e:
            print(f"[ERR] S3 Bucket {name}: {e}")


if __name__ == "__main__":
    print("Starting cleanup of AWS Agentic Governance demo resources...")
    delete_lambdas()
    delete_roles()
    delete_dynamodb_tables()
    delete_project_buckets()
    print("Cleanup complete.")