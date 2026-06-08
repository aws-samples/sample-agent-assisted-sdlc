// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * AgentCore InvokeAgentRuntimeCommand implementation.
 *
 * Mirrors the pattern in project-management/shared/pipeline.py:execute_command.
 * Sends a shell command to the runtime container via AgentCore's REST API.
 */

import { signedAgentCoreRequest } from "./sign.js";

interface CommandResult {
  stdout: string;
  stderr: string;
  exitCode: number;
}

/**
 * Invoke AgentCore runtime command (shell execution in the runtime container).
 */
export async function invokeAgentRuntimeCommand(
  runtimeArn: string,
  sessionId: string,
  command: string,
  timeout: number = 120,
): Promise<CommandResult> {
  const encodedArn = encodeURIComponent(runtimeArn);
  const path = `/runtimes/${encodedArn}/commands?qualifier=DEFAULT`;
  const body = JSON.stringify({ command, timeout });

  const response = await signedAgentCoreRequest(
    path,
    sessionId,
    body,
    "application/vnd.amazon.eventstream",
  );

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(
      `AgentCore InvokeAgentRuntimeCommand failed: ${response.status} ${response.statusText} - ${errorText}`,
    );
  }

  // Parse the AWS event stream response.
  // Each frame: 4B total_len + 4B headers_len + 4B prelude_crc + headers + payload + 4B msg_crc
  const buffer = await response.arrayBuffer();
  const view = new DataView(buffer);

  const stdoutParts: string[] = [];
  const stderrParts: string[] = [];
  let exitCode = -1;

  let offset = 0;
  while (offset + 12 <= buffer.byteLength) {
    const totalLen = view.getUint32(offset, false);
    const headersLen = view.getUint32(offset + 4, false);

    if (totalLen < 16 || offset + totalLen > buffer.byteLength) break;

    const payloadStart = offset + 12 + headersLen;
    const payloadEnd = offset + totalLen - 4;

    if (payloadEnd > payloadStart) {
      const payloadBytes = new Uint8Array(buffer, payloadStart, payloadEnd - payloadStart);
      const payloadStr = new TextDecoder().decode(payloadBytes);

      try {
        const decoded = JSON.parse(payloadStr);
        const chunk = decoded.chunk ?? decoded;
        if (chunk.contentDelta?.stdout) {
          stdoutParts.push(chunk.contentDelta.stdout);
        }
        if (chunk.contentDelta?.stderr) {
          stderrParts.push(chunk.contentDelta.stderr);
        }
        if (chunk.contentStop?.exitCode !== undefined) {
          exitCode = Number(chunk.contentStop.exitCode);
        }
      } catch {
        // Non-JSON payload — skip
      }
    }

    offset += totalLen;
  }

  return {
    stdout: stdoutParts.join(""),
    stderr: stderrParts.join(""),
    exitCode,
  };
}
