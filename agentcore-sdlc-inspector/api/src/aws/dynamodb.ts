// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * DynamoDB helpers for scanning the sessions table.
 */

import { DynamoDBClient } from "@aws-sdk/client-dynamodb";
import { DynamoDBDocumentClient, ScanCommand, type ScanCommandOutput } from "@aws-sdk/lib-dynamodb";
import type { SessionRecord } from "../types.js";

const region = process.env.AWS_REGION || "us-west-2";
const client = DynamoDBDocumentClient.from(new DynamoDBClient({ region }));

/**
 * Scan the sessions table for records whose last_event_at is within the last N minutes.
 *
 * POC posture: uses Scan with a FilterExpression. For production, add a GSI on last_event_at
 * and switch to Query. Scan cost is acceptable for 1-2 concurrent users with <100 sessions.
 *
 * @param tableName - DynamoDB table name from SESSIONS_TABLE_NAME env var
 * @param windowMinutes - Time window in minutes (default 10)
 * @returns Array of sessions sorted by last_event_at descending
 */
export async function getRecentSessions(
  tableName: string,
  windowMinutes: number = 10,
): Promise<SessionRecord[]> {
  const now = new Date();
  const cutoff = new Date(now.getTime() - windowMinutes * 60 * 1000).toISOString();

  const params = {
    TableName: tableName,
    FilterExpression: "last_event_at > :cutoff",
    ExpressionAttributeValues: {
      ":cutoff": cutoff,
    },
  };

  let items: SessionRecord[] = [];
  let lastKey: Record<string, unknown> | undefined = undefined;

  do {
    const scanResult: ScanCommandOutput = await client.send(
      new ScanCommand({
        ...params,
        ExclusiveStartKey: lastKey,
      }),
    );

    items = items.concat((scanResult.Items || []) as SessionRecord[]);
    lastKey = scanResult.LastEvaluatedKey;
  } while (lastKey);

  // Sort by last_event_at descending in JS (most recent first)
  items.sort((a, b) => (a.last_event_at > b.last_event_at ? -1 : 1));

  return items;
}
