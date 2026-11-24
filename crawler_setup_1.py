import json
import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"


def discover_lambda_agents(region):
    lam = boto3.client("lambda", region_name=region)
    paginator = lam.get_paginator("list_functions")
    matched_agents = []

    try:
        for page in paginator.paginate():
            for fn in page.get("Functions", []):
                fn_arn = fn["FunctionArn"]
                try:
                    tags_resp = lam.list_tags(Resource=fn_arn)
                    tags = tags_resp.get("Tags", {})
                except ClientError as e:
                    print(f"[WARN] Could not read tags for {fn_arn}: {e}")
                    continue

                if tags.get("type") == "agent":
                    matched_agents.append(
                        {
                            "function_config": fn,
                            "tags": tags,
                        }
                    )
    except ClientError as e:
        print(f"[ERR] Failed listing functions in {region}: {e}")

    return matched_agents


if __name__ == "__main__":
    agents = discover_lambda_agents(REGION)
    print(f"Found {len(agents)} Lambda agent(s) in {REGION}:")
    print(json.dumps(agents, indent=2, default=str))