// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Main App component - auto-refreshing session list.
 */

import { useEffect, useState } from "react";
import { fetchSessions } from "./api";
import { SessionList } from "./SessionList";
import type { SessionRecord } from "./types";

const REFRESH_INTERVAL_MS = 15000; // 15 seconds

export function App() {
  const [sessions, setSessions] = useState<SessionRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const loadSessions = async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    else setLoading(true);

    setError(null);

    try {
      const data = await fetchSessions();
      setSessions(data);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    // Initial load
    loadSessions();

    // Auto-refresh every 15s, paused when tab is hidden
    const intervalId = setInterval(() => {
      if (document.visibilityState === "visible") {
        loadSessions(true);
      }
    }, REFRESH_INTERVAL_MS);

    return () => clearInterval(intervalId);
  }, []);

  return (
    <div style={{ maxWidth: "1200px", margin: "0 auto", padding: "24px" }}>
      <h1>AgentCore SDLC Inspector</h1>
      <p style={{ color: "#6b7280" }}>
        Active sessions (last 10 minutes) • Auto-refreshes every 15s
        {refreshing && <span> • Refreshing...</span>}
      </p>

      {loading && <p>Loading sessions...</p>}
      {error && <p style={{ color: "#dc2626" }}>Error: {error}</p>}
      {!loading && !error && <SessionList sessions={sessions} />}
    </div>
  );
}
