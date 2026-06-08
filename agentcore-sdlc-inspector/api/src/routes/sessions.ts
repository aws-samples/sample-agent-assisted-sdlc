// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * GET /api/sessions - List active sessions from DynamoDB.
 */

import type { Request, Response } from "express";
import { getRecentSessions } from "../aws/dynamodb.js";
import pino from "pino";

const logger = pino();

export async function listSessions(req: Request, res: Response): Promise<void> {
  const tableName = process.env.SESSIONS_TABLE_NAME;

  if (!tableName) {
    res.status(500).json({ error: "SESSIONS_TABLE_NAME not configured" });
    return;
  }

  logger.info({ tableName, region: process.env.AWS_REGION }, "scanning_table");

  const parsed = parseInt(req.query.window as string);
  const windowMinutes = Number.isNaN(parsed) ? 10 : parsed;

  try {
    const sessions = await getRecentSessions(tableName, windowMinutes);
    logger.info({ count: sessions.length, windowMinutes }, "sessions_fetched");
    res.json(sessions);
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : String(error);
    logger.error({ error: message }, "sessions_fetch_failed");
    res.status(500).json({ error: message });
  }
}
