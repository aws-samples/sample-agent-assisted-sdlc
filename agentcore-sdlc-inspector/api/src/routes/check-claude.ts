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
 * Resilient Claude probe shell command.
 *
 * Walks /proc directly (ps is not installed in the runtime container). Matches
 * the executable name "claude" whether followed by args or appearing bare, but
 * does NOT match substrings like "claude-code-test" or "notclaude".
 */
const PROBE_COMMAND = `PIDS=""; for p in $(ls /proc/ 2>/dev/null | grep -E '^[0-9]+$'); do [ -r /proc/$p/cmdline ] || continue; cmd=$(tr '\\0' ' ' < /proc/$p/cmdline); case "$cmd" in *claude\\ * | *claude) PIDS="$PIDS $p" ;; esac; done; if [ -n "$PIDS" ]; then echo "CLAUDE_RUNNING:$PIDS"; else echo "CLAUDE_NOT_RUNNING"; fi`;

export async function checkClaude(req: Request, res: Response): Promise<void> {
  const { session_id, runtime_arn } = req.body as CheckClaudeRequest;

  if (!session_id || !runtime_arn) {
    res.status(400).json({ error: "Missing session_id or runtime_arn" });
    return;
  }

  try {
    const result = await invokeAgentRuntimeCommand(runtime_arn, session_id, PROBE_COMMAND);
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
