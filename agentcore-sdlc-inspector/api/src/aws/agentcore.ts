// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * AgentCore InvokeAgentRuntimeCommand implementation with SigV4 signing.
 *
 * Mirrors the pattern in project-management/shared/pipeline.py:execute_command.
 * Sends a shell command to the runtime container via AgentCore's REST API.
 */

import { SignatureV4 } from "@smithy/signature-v4";
import { HttpRequest } from "@smithy/protocol-http";
import { Sha256 } from "@aws-crypto/sha256-js";
import { defaultProvider } from "@aws-sdk/credential-provider-node";

const region = process.env.AWS_REGION || "us-west-2";
const SERVICE = "bedrock-agentcore";

interface CommandResult {
  stdout: string;
  stderr: string;
  exitCode: number;
}

/**
 * Invoke AgentCore runtime command (shell execution in the runtime container).
 *
 * @param runtimeArn - ARN of the coding assistant runtime
 * @param sessionId - Session ID for the runtime
 * @param command - Shell command to execute (plaintext, no base64)
 * @param timeout - Command timeout in seconds (default 120)
 * @returns Object with stdout, stderr, exitCode
 */
export async function invokeAgentRuntimeCommand(
  runtimeArn: string,
  sessionId: string,
  command: string,
  timeout: number = 120,
): Promise<CommandResult> {
  // Construct the URL per pipeline.py pattern
  const encodedArn = encodeURIComponent(runtimeArn);
  const url = `https://bedrock-agentcore.${region}.amazonaws.com/runtimes/${encodedArn}/commands?qualifier=DEFAULT`;

  // Build the request body (plaintext command, no base64)
  const body = JSON.stringify({ command, timeout });

  // Headers per pipeline.py
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "application/vnd.amazon.eventstream",
    "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": sessionId,
    Host: `bedrock-agentcore.${region}.amazonaws.com`,
  };

  // Sign with SigV4
  const credentials = await defaultProvider()();
  const signer = new SignatureV4({
    credentials,
    region,
    service: SERVICE,
    sha256: Sha256,
  });

  const request = new HttpRequest({
    method: "POST",
    protocol: "https:",
    hostname: `bedrock-agentcore.${region}.amazonaws.com`,
    path: `/runtimes/${encodedArn}/commands`,
    query: { qualifier: "DEFAULT" },
    headers,
    body,
  });

  const signedRequest = await signer.sign(request);

  // Execute the request
  const response = await fetch(url, {
    method: "POST",
    headers: signedRequest.headers as Record<string, string>,
    body,
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(
      `AgentCore InvokeAgentRuntimeCommand failed: ${response.status} ${response.statusText} - ${errorText}`,
    );
  }

  // Parse the response body as text (simplified POC implementation)
  // In production, parse the event stream format properly with EventStreamCodec
  const text = await response.text();

  // Extract stdout from the response (simplified - assumes stdout is in the text)
  const stdout = text;
  const stderr = "";
  const exitCode = 0;

  return { stdout, stderr, exitCode };
}
