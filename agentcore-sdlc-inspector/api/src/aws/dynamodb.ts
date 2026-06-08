// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * DynamoDB helpers for scanning the sessions table.
 */

import { DynamoDBClient } from "@aws-sdk/client-dynamodb";
import { DynamoDBDocumentClient, ScanCommand, QueryCommand, type ScanCommandOutput } from "@aws-sdk/lib-dynamodb";
import type { SessionRecord } from "../types.js";

function getClient(): DynamoDBDocumentClient {
  const region = process.env.AWS_REGION || "us-west-2";
  return DynamoDBDocumentClient.from(new DynamoDBClient({ region }));
}

/**
 * Get sessions with activity in the given time window, including ALL their invocations.
 *
 * Strategy: Scan with time filter to find session_ids with recent activity,
 * then Query each session_id to get the full invocation history.
 */
export async function getRecentSessions(
  tableName: string,
  windowMinutes: number = 10,
): Promise<SessionRecord[]> {
  const client = getClient();

  // Step 1: Find session_ids with activity in the window
  let recentSessionIds: Set<string>;

  if (windowMinutes > 0) {
    const now = new Date();
    const cutoff = new Date(now.getTime() - windowMinutes * 60 * 1000).toISOString();

    const scanParams = {
      TableName: tableName,
      FilterExpression: "started_at > :cutoff",
      ExpressionAttributeValues: { ":cutoff": cutoff },
      ProjectionExpression: "session_id",
    };

    recentSessionIds = new Set<string>();
    let lastKey: Record<string, unknown> | undefined = undefined;

    do {
      const result: ScanCommandOutput = await client.send(
        new ScanCommand({ ...scanParams, ExclusiveStartKey: lastKey } as Record<string, unknown>),
      );
      for (const item of (result.Items || []) as { session_id: string }[]) {
        recentSessionIds.add(item.session_id);
      }
      lastKey = result.LastEvaluatedKey;
    } while (lastKey);
  } else {
    // "All" — get all unique session_ids
    const scanParams = { TableName: tableName, ProjectionExpression: "session_id" };
    recentSessionIds = new Set<string>();
    let lastKey: Record<string, unknown> | undefined = undefined;

    do {
      const result: ScanCommandOutput = await client.send(
        new ScanCommand({ ...scanParams, ExclusiveStartKey: lastKey } as Record<string, unknown>),
      );
      for (const item of (result.Items || []) as { session_id: string }[]) {
        recentSessionIds.add(item.session_id);
      }
      lastKey = result.LastEvaluatedKey;
    } while (lastKey);
  }

  if (recentSessionIds.size === 0) return [];

  // Step 2: Query all invocations for each active session
  const allItems: SessionRecord[] = [];

  for (const sessionId of recentSessionIds) {
    const queryResult = await client.send(
      new QueryCommand({
        TableName: tableName,
        KeyConditionExpression: "session_id = :sid",
        ExpressionAttributeValues: { ":sid": sessionId },
      }),
    );
    allItems.push(...((queryResult.Items || []) as SessionRecord[]));
  }

  // Sort by started_at descending
  allItems.sort((a, b) => (a.started_at > b.started_at ? -1 : 1));

  return allItems;
}
