// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * POST /api/check-claude - Probe runtime container for running Claude process.
 */

import type { Request, Response } from "express";
import { invokeAgentRuntimeCommand } from "../aws/agentcore.js";
import type { CheckClaudeRequest, CheckClaudeResponse } from "../types.js";
import pino from "pino";

const logger = pino();

/**
 * Build a probe command that matches claude processes for a specific session UUID.
 *
 * Walks /proc directly (ps is not installed in the runtime container). Matches
 * claude processes whose cmdline contains the given session UUID — this distinguishes
 * the pipeline's claude from a user's interactive session in the same microVM.
 * Falls back to matching any claude process if no UUID is provided.
 */
function buildProbeCommand(claudeSessionUuid?: string): string {
  // Match claude processes by the executable name "claude" in cmdline, excluding
  // any sh/bash wrapper processes (which contain the UUID in the probe command itself).
  if (claudeSessionUuid) {
    return `sh -c 'PIDS=""; for p in $(ls /proc/ 2>/dev/null | grep -E "^[0-9]+$"); do [ -r /proc/$p/cmdline ] || continue; cmd=$(tr "\\0" " " < /proc/$p/cmdline); case "$cmd" in sh*|bash*) continue ;; *claude*${claudeSessionUuid}*) PIDS="$PIDS $p" ;; esac; done; if [ -n "$PIDS" ]; then echo "CLAUDE_RUNNING:$PIDS"; else echo "CLAUDE_NOT_RUNNING"; fi'`;
  }
  return `sh -c 'PIDS=""; for p in $(ls /proc/ 2>/dev/null | grep -E "^[0-9]+$"); do [ -r /proc/$p/cmdline ] || continue; cmd=$(tr "\\0" " " < /proc/$p/cmdline); case "$cmd" in *claude\\ *|*claude) PIDS="$PIDS $p" ;; esac; done; if [ -n "$PIDS" ]; then echo "CLAUDE_RUNNING:$PIDS"; else echo "CLAUDE_NOT_RUNNING"; fi'`;
}

export async function checkClaude(req: Request, res: Response): Promise<void> {
  const { session_id, runtime_arn, claude_session_uuid } = req.body as CheckClaudeRequest & { claude_session_uuid?: string };

  if (!session_id || !runtime_arn) {
    res.status(400).json({ error: "Missing session_id or runtime_arn" });
    return;
  }

  try {
    const probeCommand = buildProbeCommand(claude_session_uuid);
    const result = await invokeAgentRuntimeCommand(runtime_arn, session_id, probeCommand);
    const stdout = result.stdout || "";
    const running = stdout.includes("CLAUDE_RUNNING:");

    const pids = running
      ? stdout
          .match(/CLAUDE_RUNNING:(.+)/)?.[1]
          ?.trim()
          .split(" ")
          .map(Number)
          .filter(Boolean) || []
      : [];

    logger.info({ session_id, running }, "check_claude_completed");

    const response: CheckClaudeResponse = {
      claude_running: running,
      pids,
      raw_stdout: stdout,
      checked_at: new Date().toISOString(),
    };

    res.json(response);
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : String(error);
    logger.error({ session_id, error: message }, "check_claude_failed");
    res.status(500).json({ error: message });
  }
}
