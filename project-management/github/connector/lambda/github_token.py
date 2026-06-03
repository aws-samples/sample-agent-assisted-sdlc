# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""GitHub App installation token generation."""

import json
import os
import time
import urllib.request

import boto3
import jwt


def get_token() -> str:
    """Generate a GitHub App installation token from Secrets Manager.

    Requires env vars:
      GITHUB_APP_CLIENT_ID
      GITHUB_INSTALLATION_ID
      PRIVATE_KEY_SECRET_ARN
    """
    region = os.environ.get(
        "AWS_REGION", os.environ.get("AWS_REGION_NAME", "us-west-2")
    )
    client_id = os.environ["GITHUB_APP_CLIENT_ID"]
    installation_id = os.environ["GITHUB_INSTALLATION_ID"]
    secret_arn = os.environ["PRIVATE_KEY_SECRET_ARN"]

    sm = boto3.client("secretsmanager", region_name=region)
    secret = sm.get_secret_value(SecretId=secret_arn)
    private_key = secret["SecretString"].encode()

    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + 600, "iss": client_id}
    jwt_token = jwt.encode(payload, private_key, algorithm="RS256")

    url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
    req = urllib.request.Request(
        url,
        method="POST",
        headers={
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )

    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
        return data["token"]
