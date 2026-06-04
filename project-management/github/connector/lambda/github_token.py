# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""GitHub App installation token generation."""

import json
import os
import time
import urllib.error
import urllib.request

import boto3
import botocore.exceptions
import jwt

try:
    from errors import TokenError
    from log import get_logger
except ImportError:  # pragma: no cover - test path
    from shared.errors import TokenError
    from shared.log import get_logger

logger = get_logger(__name__)


def get_token() -> str:
    """Generate a GitHub App installation token from Secrets Manager.

    Requires env vars:
      GITHUB_APP_CLIENT_ID
      GITHUB_INSTALLATION_ID
      PRIVATE_KEY_SECRET_ARN

    Raises:
        TokenError: When Secrets Manager access fails, the GitHub API
            request fails, or the response is missing the ``token`` key.
    """
    region = os.environ.get(
        "AWS_REGION", os.environ.get("AWS_REGION_NAME", "us-west-2")
    )
    client_id = os.environ["GITHUB_APP_CLIENT_ID"]
    installation_id = os.environ["GITHUB_INSTALLATION_ID"]
    secret_arn = os.environ["PRIVATE_KEY_SECRET_ARN"]

    sm = boto3.client("secretsmanager", region_name=region)
    try:
        secret = sm.get_secret_value(SecretId=secret_arn)
    except botocore.exceptions.ClientError as e:
        raise TokenError("Failed to read GitHub App private key from Secrets Manager") from e
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

    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise TokenError("GitHub installation-token request failed") from e
    except urllib.error.URLError as e:
        raise TokenError("GitHub installation-token transport error") from e

    try:
        return data["token"]
    except KeyError as e:
        raise TokenError("GitHub installation-token response missing 'token' key") from e
