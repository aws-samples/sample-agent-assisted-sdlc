// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Express API server for the inspector POC.
 *
 * Routes:
 * - GET /api/health
 * - GET /api/sessions
 * - POST /api/check-claude
 */

import express from "express";
import cors from "cors";
import pino from "pino";
import { listSessions } from "./routes/sessions.js";
import { checkClaude } from "./routes/check-claude.js";
import type { HealthResponse } from "./types.js";

const logger = pino();

const app = express();
const port = parseInt(process.env.INSPECTOR_API_PORT || "8787", 10);
const webPort = parseInt(process.env.INSPECTOR_WEB_PORT || "5173", 10);

// CORS enabled for the frontend only
app.use(
  cors({
    origin: `http://localhost:${webPort}`,
    credentials: true,
  }),
);

app.use(express.json());

// Health check
app.get("/api/health", (req, res) => {
  const response: HealthResponse = {
    ok: true,
    checked_at: new Date().toISOString(),
  };
  res.json(response);
});

// List recent sessions
app.get("/api/sessions", listSessions);

// Check if Claude is running in a session
app.post("/api/check-claude", checkClaude);

app.listen(port, () => {
  logger.info({ port, webPort }, "inspector_api_started");
});
