// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Shared TypeScript types for the inspector API.
 */

export interface SessionRecord {
  session_id: string;
  invocation_number: number;
  runtime_arn: string;
  assistant_type: string;
  repo_owner: string;
  repo_name: string;
  issue_number: number;
  issue_title: string;
  triggered_by: string;
  is_reinvocation: boolean;
  started_at: string;
  ttl: number;
  claude_session_uuid: string;
  issue_url: string;
  status: string;
}

export interface CheckClaudeRequest {
  session_id: string;
  runtime_arn: string;
  claude_session_uuid?: string;
}

export interface CheckClaudeResponse {
  claude_running: boolean;
  pids: number[];
  raw_stdout: string;
  checked_at: string;
}

export interface HealthResponse {
  ok: boolean;
  checked_at: string;
}
