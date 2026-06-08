// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * POST /api/runtime-lifecycle - Get microVM uptime.
 */

import type { Request, Response } from "express";
import { invokeAgentRuntimeCommand } from "../aws/agentcore.js";
import pino from "pino";

const logger = pino();

export async function runtimeLifecycle(req: Request, res: Response): Promise<void> {
  const { session_id, runtime_arn } = req.body as { session_id: string; runtime_arn: string };

  if (!session_id || !runtime_arn) {
    res.status(400).json({ error: "Missing session_id or runtime_arn" });
    return;
  }

  try {
    const result = await invokeAgentRuntimeCommand(
      runtime_arn,
      session_id,
      "sh -c 'awk \"{print \\$1}\" /proc/uptime'",
      10,
    );
    const uptimeSeconds = parseFloat(result.stdout.trim()) || 0;

    logger.info({ session_id, uptimeSeconds }, "runtime_lifecycle_checked");

    res.json({
      uptime_seconds: Math.round(uptimeSeconds),
      checked_at: new Date().toISOString(),
    });
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : String(error);
    logger.error({ session_id, error: message }, "runtime_lifecycle_failed");
    res.status(500).json({ error: message });
  }
}
