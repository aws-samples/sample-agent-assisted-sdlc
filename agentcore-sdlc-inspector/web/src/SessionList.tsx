// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import SpaceBetween from "@cloudscape-design/components/space-between";
import Box from "@cloudscape-design/components/box";
import { SessionCard } from "./SessionCard";
import type { SessionRecord } from "./types";

interface SessionListProps {
  sessions: SessionRecord[];
}

export interface GroupedSession {
  session_id: string;
  latest: SessionRecord;
  invocations: SessionRecord[];
}

export function SessionList({ sessions }: SessionListProps) {
  if (sessions.length === 0) {
    return (
      <Box textAlign="center" padding="xxl" color="text-status-inactive">
        <Box variant="p" fontSize="heading-m">No sessions found.</Box>
        <Box variant="p">Sessions will appear here when the pipeline is triggered.</Box>
      </Box>
    );
  }

  const grouped = new Map<string, SessionRecord[]>();
  for (const s of sessions) {
    const existing = grouped.get(s.session_id) || [];
    existing.push(s);
    grouped.set(s.session_id, existing);
  }

  const groups: GroupedSession[] = [];
  for (const [session_id, invocations] of grouped) {
    invocations.sort((a, b) => b.invocation_number - a.invocation_number);
    const latest = invocations.find((inv) => inv.status !== "skipped_already_running") || invocations[0];
    groups.push({ session_id, latest, invocations });
  }

  groups.sort((a, b) => (a.latest.started_at > b.latest.started_at ? -1 : 1));

  return (
    <SpaceBetween size="l">
      {groups.map((group) => (
        <SessionCard key={group.session_id} group={group} />
      ))}
    </SpaceBetween>
  );
}
