// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Shared SigV4 signing for AgentCore API requests.
 */

import { SignatureV4 } from "@smithy/signature-v4";
import { HttpRequest } from "@smithy/protocol-http";
import { Sha256 } from "@aws-crypto/sha256-js";
import { defaultProvider } from "@aws-sdk/credential-provider-node";

const region = process.env.AWS_REGION || "us-west-2";
const SERVICE = "bedrock-agentcore";
const hostname = `bedrock-agentcore.${region}.amazonaws.com`;

export interface SignedFetchResult {
  response: globalThis.Response;
}

/**
 * Sign and send a request to the AgentCore API.
 */
export async function signedAgentCoreRequest(
  path: string,
  sessionId: string,
  body: string,
  accept?: string,
): Promise<globalThis.Response> {
  const credentials = await defaultProvider()();
  const signer = new SignatureV4({
    credentials,
    region,
    service: SERVICE,
    sha256: Sha256,
  });

  const [pathPart, queryString] = path.split("?");
  const query: Record<string, string> = {};
  if (queryString) {
    for (const pair of queryString.split("&")) {
      const [k, v] = pair.split("=");
      query[k] = v;
    }
  }

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": sessionId,
    Host: hostname,
  };
  if (accept) {
    headers["Accept"] = accept;
  }

  const request = new HttpRequest({
    method: "POST",
    protocol: "https:",
    hostname,
    path: pathPart,
    query,
    headers,
    body,
  });

  const signedRequest = await signer.sign(request);

  const url = `https://${hostname}${path}`;
  return fetch(url, {
    method: "POST",
    headers: signedRequest.headers as Record<string, string>,
    body,
  });
}
