# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""DynamoDB session tracking for observability.

Writes one row per invocation (PK: session_id, SK: invocation_number) to a DynamoDB
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
    issue_url: str = "",
    status: str = "started",
) -> None:
    """Write a new invocation record to DynamoDB.

    Each invocation creates a separate row with:
      PK: session_id (S)
      SK: invocation_number (N) — auto-incremented by querying current max

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
        issue_url: URL to the issue (GitHub, Jira, etc.)
    """
    region = os.environ.get(
        "AWS_REGION", os.environ.get("AWS_REGION_NAME", "us-west-2")
    )
    dynamodb = boto3.client("dynamodb", region_name=region)

    now = datetime.datetime.now(datetime.timezone.utc)
    now_iso = now.isoformat()
    ttl_val = int((now + datetime.timedelta(days=7)).timestamp())

    truncated_title = issue_title[:200]

    # Determine invocation number by querying existing rows for this session
    invocation_number = 1
    if is_reinvocation:
        resp = dynamodb.query(
            TableName=table_name,
            KeyConditionExpression="session_id = :sid",
            ExpressionAttributeValues={":sid": {"S": session_id}},
            Select="COUNT",
        )
        invocation_number = resp.get("Count", 0) + 1

    item = {
        "session_id": {"S": session_id},
        "invocation_number": {"N": str(invocation_number)},
        "runtime_arn": {"S": runtime_arn},
        "assistant_type": {"S": assistant_type},
        "repo_owner": {"S": repo_owner},
        "repo_name": {"S": repo_name},
        "issue_number": {"N": str(issue_number)},
        "issue_title": {"S": truncated_title},
        "triggered_by": {"S": triggered_by},
        "is_reinvocation": {"BOOL": is_reinvocation},
        "claude_session_uuid": {"S": claude_session_uuid},
        "issue_url": {"S": issue_url},
        "status": {"S": status},
        "started_at": {"S": now_iso},
        "ttl": {"N": str(ttl_val)},
    }

    try:
        dynamodb.put_item(
            TableName=table_name,
            Item=item,
            ConditionExpression="attribute_not_exists(session_id) AND attribute_not_exists(invocation_number)",
        )
    except dynamodb.exceptions.ConditionalCheckFailedException:
        pass
