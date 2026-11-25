import json
import time
import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"


def _as_list(val):
    """Normalize AWS IAM policy fields that may be a single str or a list."""
    if val is None:
        return []
    return val if isinstance(val, list) else [val]


def inspect_execution_role(iam_client, role_arn):
    """Resolve trust policy, inline policies, and managed policies for an IAM role."""
    role_name = role_arn.split("/")[-1]
    allowed_access = []
    denied_access = []
    broad_access_flag = False
    warnings = []

    try:
        role_resp = iam_client.get_role(RoleName=role_name)
        trust_policy = role_resp["Role"].get("AssumeRolePolicyDocument", {})
    except ClientError as e:
        return {
            "role_arn": role_arn,
            "trust_policy": {},
            "allowed_access": [],
            "denied_access": [],
            "broad_access_flag": False,
            "warnings": [f"Could not read role {role_name}: {e.response['Error']['Code']}"],
        }

    policy_docs = []

    # 1. Inline policies (paginated)
    try:
        inline_paginator = iam_client.get_paginator("list_role_policies")
        for page in inline_paginator.paginate(RoleName=role_name):
            for pol_name in page.get("PolicyNames", []):
                pol = iam_client.get_role_policy(RoleName=role_name, PolicyName=pol_name)
                policy_docs.append((f"inline:{pol_name}", pol["PolicyDocument"]))
    except ClientError as e:
        warnings.append(f"Inline policy read error: {e.response['Error']['Code']}")

    # 2. Customer/AWS Managed policies (paginated)
    try:
        attached_paginator = iam_client.get_paginator("list_attached_role_policies")
        for page in attached_paginator.paginate(RoleName=role_name):
            for attached in page.get("AttachedPolicies", []):
                pol_arn = attached["PolicyArn"]
                pol_meta = iam_client.get_policy(PolicyArn=pol_arn)["Policy"]
                ver_id = pol_meta["DefaultVersionId"]
                ver_doc = iam_client.get_policy_version(PolicyArn=pol_arn, VersionId=ver_id)[
                    "PolicyVersion"
                ]["Document"]
                policy_docs.append((f"managed:{attached['PolicyName']}", ver_doc))
    except ClientError as e:
        warnings.append(f"Managed policy read error: {e.response['Error']['Code']}")

    # 3. Parse and normalize statements
    for source_name, doc in policy_docs:
        for stmt in _as_list(doc.get("Statement", [])):
            effect = stmt.get("Effect", "Allow")
            actions = _as_list(stmt.get("Action"))
            resources = _as_list(stmt.get("Resource"))

            # Exclude routine CloudWatch Logs write permissions when summarizing data access
            non_log_actions = [a for a in actions if not a.startswith("logs:")]
            if not non_log_actions:
                continue

            for res in resources:
                if res == "*" or res.endswith(":*") or (res.endswith("/*") and res.count(":") < 5):
                    broad_access_flag = True

            entry = {
                "policy": source_name,
                "actions": non_log_actions,
                "resources": resources,
            }
            if effect == "Allow":
                allowed_access.append(entry)
            else:
                denied_access.append(entry)

    return {
        "role_arn": role_arn,
        "trust_policy": trust_policy,
        "allowed_access": allowed_access,
        "denied_access": denied_access,
        "broad_access_flag": broad_access_flag,
        "warnings": warnings,
    }


def lookup_lambda_creator(ct_client, function_name, function_arn):
    """Query CloudTrail Event History (last 90 days) for function creation."""
    # Throttle guard: CloudTrail lookup_events limit is 2 TPS
    time.sleep(0.6)
    try:
        paginator = ct_client.get_paginator("lookup_events")
        for lookup_val in (function_name, function_arn):
            for page in paginator.paginate(
                LookupAttributes=[{"AttributeKey": "ResourceName", "AttributeValue": lookup_val}]
            ):
                for event in page.get("Events", []):
                    ev_name = event.get("EventName", "")
                    if ev_name.startswith("CreateFunction"):
                        raw = json.loads(event.get("CloudTrailEvent", "{}"))
                        user_id = raw.get("userIdentity", {})
                        creator_arn = user_id.get("arn") or event.get("Username") or "unknown"
                        return {
                            "creator": creator_arn,
                            "created_at": str(event.get("EventTime", "")),
                            "event_name": ev_name,
                        }
    except ClientError as e:
        return {
            "creator": f"lookup_error:{e.response['Error']['Code']}",
            "created_at": "",
            "event_name": "",
        }

    return {"creator": "not_found_in_90d_window", "created_at": "", "event_name": ""}


def crawl_lambda_agents(region):
    lam = boto3.client("lambda", region_name=region)
    iam = boto3.client("iam", region_name=region)
    ct = boto3.client("cloudtrail", region_name=region)

    paginator = lam.get_paginator("list_functions")
    results = []

    for page in paginator.paginate():
        for fn in page.get("Functions", []):
            fn_arn = fn["FunctionArn"]
            fn_name = fn["FunctionName"]
            tags = lam.list_tags(Resource=fn_arn).get("Tags", {})

            if tags.get("type") != "agent":
                continue

            env_vars = fn.get("Environment", {}).get("Variables", {})
            iam_info = inspect_execution_role(iam, fn["Role"])
            ct_info = lookup_lambda_creator(ct, fn_name, fn_arn)

            # Fallback to owner tag if CloudTrail event aged out (>90 days)
            creator = ct_info["creator"]
            if creator.startswith("not_found"):
                creator = f"tag_fallback:{tags.get('owner', 'unknown')}"

            results.append(
                {
                    "agent_id": fn_arn,
                    "name": fn_name,
                    "type": "lambda",
                    "region": region,
                    "creator": creator,
                    "owner_tag": tags.get("owner", ""),
                    "purpose": tags.get("purpose", fn.get("Description", "")),
                    "tools": env_vars.get("AGENT_TOOLS", ""),
                    "model": env_vars.get("AGENT_MODEL", ""),
                    "data_access": iam_info["allowed_access"],
                    "broad_access_flag": iam_info["broad_access_flag"],
                    "role_arn": fn["Role"],
                    "created_at": ct_info["created_at"],
                    "discovery_source": "lambda:list_functions",
                    "notes_warnings": iam_info["warnings"],
                }
            )

    return results


if __name__ == "__main__":
    agents = crawl_lambda_agents(REGION)
    print(json.dumps(agents, indent=2, default=str))