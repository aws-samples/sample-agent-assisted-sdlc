// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * SessionList component - renders a list of sessions or empty state.
 */

import { SessionCard } from "./SessionCard";
import type { SessionRecord } from "./types";

interface SessionListProps {
  sessions: SessionRecord[];
}

export function SessionList({ sessions }: SessionListProps) {
  if (sessions.length === 0) {
    return (
      <div style={{ padding: "32px", textAlign: "center", color: "#6b7280" }}>
        <p>No sessions in the last 10 minutes.</p>
      </div>
    );
  }

  return (
    <div>
      {sessions.map((session) => (
        <SessionCard key={session.session_id} session={session} />
      ))}
    </div>
  );
}
