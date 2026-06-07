# AgentCore SDLC Inspector (POC)

Local inspector UI for observing in-flight AgentCore SDLC pipeline sessions. Lists active sessions from DynamoDB (last 10 minutes) and provides a "Check Claude running" button to probe the runtime container's process table.

## Quick Start

```bash
cd agentcore-sdlc-inspector
npm install
npm run dev
```

This starts both the API server (port 8787) and the frontend dev server (port 5173). Open http://localhost:5173 in your browser.

## Environment Variables

Create a `.env` file in this directory or set these in your shell:

- `AWS_REGION` — AWS region where the sessions table lives (default: us-west-2)
- `SESSIONS_TABLE_NAME` — DynamoDB table name (e.g., `myproject_sdlc_sessions`)
- `INSPECTOR_API_PORT` — API server port (default: 8787)
- `INSPECTOR_WEB_PORT` — Frontend dev server port (default: 5173)

The API reads the table name from the environment. After running `cdk deploy`, you can find the table name in the CloudFormation outputs (`SessionsTableName`).

## AWS Credentials

The inspector uses the AWS SDK default credential chain (reads from `~/.aws/credentials`, `AWS_PROFILE`, etc.). Your IAM principal needs:

- `dynamodb:Scan` on the sessions table
- `bedrock-agentcore:InvokeAgentRuntimeCommand` on the runtime ARN (for the "Check Claude running" button)

Example IAM policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "dynamodb:Scan",
      "Resource": "arn:aws:dynamodb:us-west-2:123456789012:table/myproject_sdlc_sessions"
    },
    {
      "Effect": "Allow",
      "Action": "bedrock-agentcore:InvokeAgentRuntimeCommand",
      "Resource": "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/*"
    }
  ]
}
```

## Architecture

- **API** (Express + TypeScript): `/api/health`, `/api/sessions` (DDB scan), `/api/check-claude` (AgentCore probe)
- **Frontend** (React + Vite + TypeScript): Session list with auto-refresh every 15s, "Check Claude running" button per session

## POC Posture

- **Local-only.** No deployment plumbing (no API Gateway, CloudFront, Cognito).
- **Scan cost.** The API uses DynamoDB `Scan` with a filter on `last_event_at`. For 1-2 concurrent users this is fine. If the table grows or many users run the inspector, add a GSI on `last_event_at` and switch to `Query`.
- **No CI coverage.** The inspector tree is not part of the main repo's CI (no tests in this PR). Track "add inspector tests" as a follow-up.
- **No CSS framework.** Minimal styling — this is a POC for functionality.
- **Simplified event stream parsing.** The API reads the AgentCore response as plain text. This works for the current `/proc` probe but won't handle complex multi-event streams. Production should use `@smithy/eventstream-codec` to parse the event stream format properly.

## Manual Verification Steps

1. After `cdk deploy`, trigger an issue with the `agent:start` label.
2. Open the inspector at `http://localhost:5173`.
3. The new session appears in the list within 15s, with `triggered_by` correctly populated.
4. Click "Check Claude running" while the agent is mid-run → green "Running (PIDs: ...)".
5. After the agent finishes (PR opened or session terminated), click again → red "Not running".

## License

Apache-2.0
