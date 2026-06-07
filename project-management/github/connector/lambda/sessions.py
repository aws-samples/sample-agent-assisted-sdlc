# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""DynamoDB session tracking for observability.

Writes session metadata (session ID, runtime ARN, repo/issue, timestamps) to a DynamoDB
table for consumption by the inspector POC. The write is non-blocking (caller wraps in
try/except) — auditing failure is acceptable; failing the pipeline is not.
"""

import datetime
import os

import boto3


def write_session_record(
    table_name: str,
    session_id: str,
    runtime_arn: str,
    assistant_type: str,
    repo_owner: str,
    repo_name: str,
    issue_number: int,
    issue_title: str,
    triggered_by: str,
    is_reinvocation: bool,
    claude_session_uuid: str,
) -> None:
    """Write session metadata to DynamoDB with atomic increment of invocation_count.

    Uses if_not_exists for immutable fields (set only on first write) and SET for mutable
    fields (updated every invocation). TTL is computed as started_at + 7 days.

    Args:
        table_name: DynamoDB table name from SESSIONS_TABLE_NAME env var
        session_id: AgentCore runtime session ID (partition key)
        runtime_arn: ARN of the coding assistant runtime
        assistant_type: claude-code | kiro | codex
        repo_owner: GitHub repo owner
        repo_name: GitHub repo name
        issue_number: GitHub issue number
        issue_title: GitHub issue title (truncated to 200 chars)
        triggered_by: GitHub username who triggered the pipeline, or "unknown"
        is_reinvocation: True if this is a re-invocation on the same issue
        claude_session_uuid: UUID derived from session_id via uuid5(NAMESPACE_DNS, session_id)
    """
    region = os.environ.get("AWS_REGION", os.environ.get("AWS_REGION_NAME", "us-west-2"))
    dynamodb = boto3.client("dynamodb", region_name=region)

    now = datetime.datetime.now(datetime.timezone.utc)
    now_iso = now.isoformat()
    ttl_val = int((now + datetime.timedelta(days=7)).timestamp())

    # Truncate issue_title to 200 chars
    truncated_title = issue_title[:200]

    # UpdateExpression: if_not_exists for immutable fields, SET for mutable, ADD for counter
    update_expr = (
        "SET #last_event_at = :last_event_at, "
        "#is_reinvocation = :is_reinvocation, "
        "#started_at = if_not_exists(#started_at, :started_at), "
        "#ttl = if_not_exists(#ttl, :ttl), "
        "#runtime_arn = if_not_exists(#runtime_arn, :runtime_arn), "
        "#assistant_type = if_not_exists(#assistant_type, :assistant_type), "
        "#repo_owner = if_not_exists(#repo_owner, :repo_owner), "
        "#repo_name = if_not_exists(#repo_name, :repo_name), "
        "#issue_number = if_not_exists(#issue_number, :issue_number), "
        "#issue_title = if_not_exists(#issue_title, :issue_title), "
        "#triggered_by = if_not_exists(#triggered_by, :triggered_by), "
        "#claude_session_uuid = if_not_exists(#claude_session_uuid, :claude_session_uuid) "
        "ADD #invocation_count :one"
    )

    expr_attr_names = {
        "#last_event_at": "last_event_at",
        "#is_reinvocation": "is_reinvocation",
        "#started_at": "started_at",
        "#ttl": "ttl",
        "#runtime_arn": "runtime_arn",
        "#assistant_type": "assistant_type",
        "#repo_owner": "repo_owner",
        "#repo_name": "repo_name",
        "#issue_number": "issue_number",
        "#issue_title": "issue_title",
        "#triggered_by": "triggered_by",
        "#claude_session_uuid": "claude_session_uuid",
        "#invocation_count": "invocation_count",
    }

    expr_attr_values = {
        ":last_event_at": {"S": now_iso},
        ":is_reinvocation": {"BOOL": is_reinvocation},
        ":started_at": {"S": now_iso},
        ":ttl": {"N": str(ttl_val)},
        ":runtime_arn": {"S": runtime_arn},
        ":assistant_type": {"S": assistant_type},
        ":repo_owner": {"S": repo_owner},
        ":repo_name": {"S": repo_name},
        ":issue_number": {"N": str(issue_number)},
        ":issue_title": {"S": truncated_title},
        ":triggered_by": {"S": triggered_by},
        ":claude_session_uuid": {"S": claude_session_uuid},
        ":one": {"N": "1"},
    }

    dynamodb.update_item(
        TableName=table_name,
        Key={"session_id": {"S": session_id}},
        UpdateExpression=update_expr,
        ExpressionAttributeNames=expr_attr_names,
        ExpressionAttributeValues=expr_attr_values,
    )
