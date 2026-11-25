import csv
import json
import time
import boto3
from botocore.exceptions import ClientError

TARGET_REGIONS = ["us-east-1"]


def _as_list(val):
    """Normalize AWS IAM policy fields that may be a single str or a list."""
    if val is None:
        return []
    return val if isinstance(val, list) else [val]


def inspect_execution_role(iam_client, role_arn):
    """Resolve trust policy, inline policies, and managed policies for an IAM role."""
    if not role_arn:
        return {
            "trust_policy": {},
            "allowed_access": [],
            "denied_access": [],
            "broad_access_flag": False,
            "warnings": ["Missing execution role ARN"],
        }

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
            "trust_policy": {},
            "allowed_access": [],
            "denied_access": [],
            "broad_access_flag": False,
            "warnings": [f"Role lookup error ({role_name}): {e.response['Error']['Code']}"],
        }

    policy_docs = []

    # 1. Inline policies (paginated)
    try:
        for page in iam_client.get_paginator("list_role_policies").paginate(RoleName=role_name):
            for pol_name in page.get("PolicyNames", []):
                pol = iam_client.get_role_policy(RoleName=role_name, PolicyName=pol_name)
                policy_docs.append((f"inline:{pol_name}", pol["PolicyDocument"]))
    except ClientError as e:
        warnings.append(f"Inline policy error: {e.response['Error']['Code']}")

    # 2. Managed policies (paginated)
    try:
        for page in iam_client.get_paginator("list_attached_role_policies").paginate(
            RoleName=role_name
        ):
            for attached in page.get("AttachedPolicies", []):
                pol_arn = attached["PolicyArn"]
                ver_id = iam_client.get_policy(PolicyArn=pol_arn)["Policy"]["DefaultVersionId"]
                ver_doc = iam_client.get_policy_version(PolicyArn=pol_arn, VersionId=ver_id)[
                    "PolicyVersion"
                ]["Document"]
                policy_docs.append((f"managed:{attached['PolicyName']}", ver_doc))
    except ClientError as e:
        warnings.append(f"Managed policy error: {e.response['Error']['Code']}")

    # 3. Parse and normalize statements
    for source_name, doc in policy_docs:
        for stmt in _as_list(doc.get("Statement", [])):
            effect = stmt.get("Effect", "Allow")
            actions = [a for a in _as_list(stmt.get("Action")) if not a.startswith("logs:")]
            resources = _as_list(stmt.get("Resource"))
            if not actions:
                continue

            for res in resources:
                if res == "*" or res.endswith(":*") or (res.endswith("/*") and res.count(":") < 5):
                    broad_access_flag = True

            entry = {
                "policy": source_name,
                "actions": actions,
                "resources": resources,
            }
            if effect == "Allow":
                allowed_access.append(entry)
            else:
                denied_access.append(entry)

    return {
        "trust_policy": trust_policy,
        "allowed_access": allowed_access,
        "denied_access": denied_access,
        "broad_access_flag": broad_access_flag,
        "warnings": warnings,
    }


def lookup_creator_in_cloudtrail(ct_client, resource_identifiers, event_prefixes):
    """Query CloudTrail Event History (90-day window) with rate-limit delay."""
    time.sleep(0.6)  # Guard against 2 TPS LookupEvents throttle
    try:
        paginator = ct_client.get_paginator("lookup_events")
        for lookup_val in resource_identifiers:
            if not lookup_val:
                continue
            for page in paginator.paginate(
                LookupAttributes=[{"AttributeKey": "ResourceName", "AttributeValue": lookup_val}]
            ):
                for event in page.get("Events", []):
                    ev_name = event.get("EventName", "")
                    if any(ev_name.startswith(prefix) for prefix in event_prefixes):
                        raw = json.loads(event.get("CloudTrailEvent", "{}"))
                        creator_arn = (
                            raw.get("userIdentity", {}).get("arn")
                            or event.get("Username")
                            or "unknown"
                        )
                        return {
                            "creator": creator_arn,
                            "created_at": str(event.get("EventTime", "")),
                        }
    except ClientError as e:
        return {"creator": f"lookup_error:{e.response['Error']['Code']}", "created_at": ""}

    return {"creator": "not_found_in_90d_window", "created_at": ""}


def get_tagged_arns(region):
    """Cross-check resources tagged with type=agent via Resource Groups Tagging API."""
    tag_client = boto3.client("resourcegroupstaggingapi", region_name=region)
    tagged = set()
    try:
        paginator = tag_client.get_paginator("get_resources")
        for page in paginator.paginate(TagFilters=[{"Key": "type", "Values": ["agent"]}]):
            for mapping in page.get("ResourceTagMappingList", []):
                tagged.add(mapping["ResourceARN"])
    except ClientError as e:
        print(f"[WARN] Tagging API unavailable in {region}: {e.response['Error']['Code']}")
    return tagged


def crawl_region(region):
    """Discover Lambda agents (tagged + shadow) and Bedrock agents in one region."""
    lam = boto3.client("lambda", region_name=region)
    iam = boto3.client("iam", region_name=region)
    ct = boto3.client("cloudtrail", region_name=region)
    bedrock = boto3.client("bedrock-agent", region_name=region)

    tagged_arns = get_tagged_arns(region)
    records = []

    # 1. Discover Lambda Agents (Tagged + Untagged Shadow Agents)
    try:
        for page in lam.get_paginator("list_functions").paginate():
            for fn in page.get("Functions", []):
                fn_arn = fn["FunctionArn"]
                fn_name = fn["FunctionName"]
                env_vars = fn.get("Environment", {}).get("Variables", {})

                try:
                    tags = lam.list_tags(Resource=fn_arn).get("Tags", {})
                except ClientError:
                    tags = {}

                is_tagged_agent = tags.get("type") == "agent" or fn_arn in tagged_arns
                is_shadow_agent = (
                    not is_tagged_agent
                    and ("agent" in fn_name.lower() or "AGENT_ROLE" in env_vars)
                )

                if not (is_tagged_agent or is_shadow_agent):
                    continue

                sources = ["lambda:list_functions"]
                if fn_arn in tagged_arns:
                    sources.append("resourcegroupstaggingapi:get_resources")

                iam_info = inspect_execution_role(iam, fn.get("Role", ""))
                warnings = list(iam_info["warnings"])

                if is_shadow_agent:
                    warnings.append("Governance Alert: Untagged shadow agent (missing type=agent tag)")
                if iam_info["broad_access_flag"]:
                    warnings.append("Security Alert: Wildcard '*' resource permission detected")

                ct_info = lookup_creator_in_cloudtrail(ct, [fn_name, fn_arn], ["CreateFunction"])
                creator = ct_info["creator"]
                if creator.startswith("not_found"):
                    creator = f"tag_fallback:{tags.get('owner', 'unknown')}"

                records.append(
                    {
                        "agent_id": fn_arn,
                        "name": fn_name,
                        "type": "lambda-shadow" if is_shadow_agent else "lambda",
                        "region": region,
                        "creator": creator,
                        "owner_tag": tags.get("owner", ""),
                        "purpose": tags.get("purpose", fn.get("Description", "")),
                        "tools": [
                            t.strip() for t in env_vars.get("AGENT_TOOLS", "").split(",") if t.strip()
                        ],
                        "model": env_vars.get("AGENT_MODEL", "unspecified"),
                        "data_access": iam_info["allowed_access"],
                        "denied_access": iam_info["denied_access"],
                        "broad_access_flag": iam_info["broad_access_flag"],
                        "role_arn": fn.get("Role", ""),
                        "created_at": ct_info["created_at"],
                        "discovery_source": "+".join(sources),
                        "notes_warnings": warnings,
                    }
                )
    except ClientError as e:
        print(f"[ERR] Lambda scan failed in {region}: {e.response['Error']['Code']}")

    # 2. Discover Amazon Bedrock Agents (gracefully skipped if restricted/maintenance mode)
    try:
        for page in bedrock.get_paginator("list_agents").paginate():
            for summary in page.get("agentSummaries", []):
                agent_id = summary["agentId"]
                detail = bedrock.get_agent(agentId=agent_id)["agent"]
                agent_arn = detail["agentArn"]
                agent_name = detail["agentName"]

                try:
                    tags = bedrock.list_tags_for_resource(resourceArn=agent_arn).get("tags", {})
                except ClientError:
                    tags = {}

                warnings = []
                if tags.get("type") != "agent":
                    warnings.append("Governance Alert: Missing standard tag type=agent")

                tools = []
                ag_page = bedrock.list_agent_action_groups(agentId=agent_id, agentVersion="DRAFT")
                for ag in ag_page.get("agentActionGroupSummaries", []):
                    ag_detail = bedrock.get_agent_action_group(
                        agentId=agent_id,
                        agentVersion="DRAFT",
                        actionGroupId=ag["actionGroupId"],
                    )["agentActionGroup"]
                    executor = ag_detail.get("actionGroupExecutor", {})
                    target = executor.get("lambda") or executor.get("customControl") or "builtin"
                    tools.append(f"{ag['actionGroupName']}->{target}")

                kb_page = bedrock.list_agent_knowledge_bases(agentId=agent_id, agentVersion="DRAFT")
                kb_ids = [
                    kb["knowledgeBaseId"]
                    for kb in kb_page.get("agentKnowledgeBaseSummaries", [])
                ]

                iam_info = inspect_execution_role(iam, detail.get("agentResourceRoleArn", ""))
                warnings.extend(iam_info["warnings"])
                if iam_info["broad_access_flag"]:
                    warnings.append("Security Alert: Wildcard '*' resource permission detected")

                ct_info = lookup_creator_in_cloudtrail(
                    ct, [agent_id, agent_name, agent_arn], ["CreateAgent"]
                )
                creator = ct_info["creator"]
                if creator.startswith("not_found"):
                    creator = f"tag_fallback:{tags.get('owner', 'unknown')}"

                sources = ["bedrock-agent:list_agents"]
                if agent_arn in tagged_arns:
                    sources.append("resourcegroupstaggingapi:get_resources")

                data_access = list(iam_info["allowed_access"])
                if kb_ids:
                    data_access.append(
                        {
                            "policy": "bedrock-kb-association",
                            "actions": ["bedrock:Retrieve"],
                            "resources": kb_ids,
                        }
                    )

                records.append(
                    {
                        "agent_id": agent_arn,
                        "name": agent_name,
                        "type": "bedrock",
                        "region": region,
                        "creator": creator,
                        "owner_tag": tags.get("owner", ""),
                        "purpose": tags.get("purpose", detail.get("description", "")),
                        "tools": tools,
                        "model": detail.get("foundationModel", "unspecified"),
                        "data_access": data_access,
                        "denied_access": iam_info["denied_access"],
                        "broad_access_flag": iam_info["broad_access_flag"],
                        "role_arn": detail.get("agentResourceRoleArn", ""),
                        "created_at": ct_info["created_at"] or str(detail.get("createdAt", "")),
                        "discovery_source": "+".join(sources),
                        "notes_warnings": warnings,
                    }
                )
    except ClientError as e:
        print(f"[INFO] Bedrock Agent scan skipped in {region}: {e.response['Error']['Code']}")

    return records


def crawl_all_regions(regions=None):
    """Run discovery across all configured regions."""
    target_list = regions or TARGET_REGIONS
    all_records = []
    for reg in target_list:
        all_records.extend(crawl_region(reg))
    return all_records


def export_reports(records, json_path="agents_report.json", csv_path="agents_report.csv"):
    """Write discovered agent inventory to JSON and CSV files."""
    with open(json_path, "w", encoding="utf-8") as jf:
        json.dump(records, jf, indent=2, default=str)

    fieldnames = [
        "agent_id",
        "name",
        "type",
        "region",
        "creator",
        "owner_tag",
        "purpose",
        "tools",
        "model",
        "data_access",
        "denied_access",
        "broad_access_flag",
        "role_arn",
        "created_at",
        "discovery_source",
        "notes_warnings",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as cf:
        writer = csv.DictWriter(cf, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for rec in records:
            flat = dict(rec)
            flat["tools"] = "; ".join(rec["tools"])
            flat["data_access"] = json.dumps(rec["data_access"])
            flat["denied_access"] = json.dumps(rec.get("denied_access", []))
            flat["notes_warnings"] = "; ".join(rec["notes_warnings"])
            writer.writerow(flat)

    print(f"[OK] Exported {len(records)} agent(s) to {json_path} and {csv_path}")


if __name__ == "__main__":
    agents = crawl_all_regions()
    export_reports(agents)
    print(json.dumps(agents, indent=2, default=str))