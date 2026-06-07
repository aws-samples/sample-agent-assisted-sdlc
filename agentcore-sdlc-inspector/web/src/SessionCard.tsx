// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * SessionCard component - displays a single session with "Check Claude running" button.
 */

import { useState } from "react";
import { checkClaude } from "./api";
import type { SessionRecord } from "./types";

interface SessionCardProps {
  session: SessionRecord;
}

function formatRelativeTime(isoString: string): string {
  const now = Date.now();
  const then = new Date(isoString).getTime();
  const diffMs = now - then;
  const diffMin = Math.floor(diffMs / 60000);

  if (diffMin < 1) return "just now";
  if (diffMin === 1) return "1m ago";
  if (diffMin < 60) return `${diffMin}m ago`;

  const diffHr = Math.floor(diffMin / 60);
  if (diffHr === 1) return "1h ago";
  return `${diffHr}h ago`;
}

function truncateMiddle(text: string, maxLen: number): string {
  if (text.length <= maxLen) return text;
  const half = Math.floor(maxLen / 2);
  return `${text.slice(0, half)}...${text.slice(-half)}`;
}

export function SessionCard({ session }: SessionCardProps) {
  const [checking, setChecking] = useState(false);
  const [result, setResult] = useState<{ running: boolean; pids: number[]; error?: string } | null>(null);

  const handleCheck = async () => {
    setChecking(true);
    setResult(null);

    try {
      const response = await checkClaude({
        session_id: session.session_id,
        runtime_arn: session.runtime_arn,
      });
      setResult({ running: response.claude_running, pids: response.pids });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setResult({ running: false, pids: [], error: message });
    } finally {
      setChecking(false);
    }
  };

  return (
    <div style={{ border: "1px solid #ccc", padding: "16px", marginBottom: "16px", borderRadius: "4px" }}>
      <h3 style={{ marginTop: 0 }}>{session.issue_title}</h3>
      <p>
        <strong>Repo:</strong> {session.repo_owner}/{session.repo_name}#{session.issue_number}
      </p>
      <p>
        <strong>Triggered by:</strong> <span style={{ fontWeight: "bold", color: "#2563eb" }}>{session.triggered_by}</span>
      </p>
      <p>
        <strong>Assistant:</strong> {session.assistant_type}
      </p>
      <p>
        <strong>Invocation count:</strong> {session.invocation_count}
      </p>
      <p>
        <strong>Started:</strong> {formatRelativeTime(session.started_at)}
      </p>
      <p>
        <strong>Last event:</strong> {formatRelativeTime(session.last_event_at)}
      </p>
      <p title={session.session_id}>
        <strong>Session ID:</strong> {truncateMiddle(session.session_id, 40)}
      </p>

      <button onClick={handleCheck} disabled={checking} style={{ marginTop: "8px", padding: "8px 16px", cursor: checking ? "not-allowed" : "pointer" }}>
        {checking ? "Checking..." : "Check Claude running"}
      </button>

      {result && (
        <div style={{ marginTop: "12px" }}>
          {result.error ? (
            <p style={{ color: "#dc2626", fontWeight: "bold" }}>Error: {result.error}</p>
          ) : result.running ? (
            <p style={{ color: "#16a34a", fontWeight: "bold" }}>
              Running (PIDs: {result.pids.join(", ")})
            </p>
          ) : (
            <p style={{ color: "#dc2626", fontWeight: "bold" }}>Not running</p>
          )}
        </div>
      )}
    </div>
  );
}
