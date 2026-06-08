// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * POST /api/stop-session - Stop an AgentCore runtime session.
 */

import type { Request, Response } from "express";
import { signedAgentCoreRequest } from "../aws/sign.js";
import pino from "pino";

const logger = pino();

interface StopSessionRequest {
  session_id: string;
  runtime_arn: string;
}

export async function stopSession(req: Request, res: Response): Promise<void> {
  const { session_id, runtime_arn } = req.body as StopSessionRequest;

  if (!session_id || !runtime_arn) {
    res.status(400).json({ error: "Missing session_id or runtime_arn" });
    return;
  }

  try {
    const encodedArn = encodeURIComponent(runtime_arn);
    const path = `/runtimes/${encodedArn}/stopruntimesession?qualifier=DEFAULT`;

    const response = await signedAgentCoreRequest(path, session_id, "{}");

    logger.info({ session_id, status: response.status }, "stop_session_completed");

    res.json({
      stopped: response.ok,
      http_status: response.status,
      stopped_at: new Date().toISOString(),
    });
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : String(error);
    logger.error({ session_id, error: message }, "stop_session_failed");
    res.status(500).json({ error: message });
  }
}
