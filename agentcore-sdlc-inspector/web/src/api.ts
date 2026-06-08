// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * API client for the inspector backend.
 */

import type { SessionRecord, CheckClaudeRequest, CheckClaudeResponse, HealthResponse } from "./types";

const API_BASE = "/api";

export async function fetchHealth(): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE}/health`);
  if (!response.ok) {
    throw new Error(`Health check failed: ${response.status} ${response.statusText}`);
  }
  return response.json();
}

export async function fetchSessions(windowMinutes?: number): Promise<SessionRecord[]> {
  const params = windowMinutes !== undefined ? `?window=${windowMinutes}` : "";
  const response = await fetch(`${API_BASE}/sessions${params}`);
  if (!response.ok) {
    throw new Error(`Fetch sessions failed: ${response.status} ${response.statusText}`);
  }
  return response.json();
}

export async function checkClaude(request: CheckClaudeRequest): Promise<CheckClaudeResponse> {
  const response = await fetch(`${API_BASE}/check-claude`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Check Claude failed: ${response.status} ${response.statusText} - ${errorText}`);
  }
  return response.json();
}

export interface StopSessionResponse {
  stopped: boolean;
  http_status: number;
  stopped_at: string;
}

export interface RuntimeLifecycleResponse {
  uptime_seconds: number;
  checked_at: string;
}

export async function getRuntimeLifecycle(request: { session_id: string; runtime_arn: string }): Promise<RuntimeLifecycleResponse> {
  const response = await fetch(`${API_BASE}/runtime-lifecycle`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Runtime lifecycle failed: ${response.status} - ${errorText}`);
  }
  return response.json();
}

export async function stopSession(request: CheckClaudeRequest): Promise<StopSessionResponse> {
  const response = await fetch(`${API_BASE}/stop-session`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Stop session failed: ${response.status} ${response.statusText} - ${errorText}`);
  }
  return response.json();
}
