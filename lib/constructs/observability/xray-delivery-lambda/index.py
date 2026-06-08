# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Custom resource handler for X-Ray traces delivery (Runtime + Identity).

Manages CloudWatch Logs Delivery API lifecycle for X-Ray traces on both:
  - Runtime: TRACES delivery source using the runtime ARN
  - Identity: TRACES delivery source using the workload-identity ARN

Both share a single X-Ray delivery destination. Handles Create/Update/Delete
with idempotent cleanup.
"""

import json
import logging
import os
from typing import Any, Dict

import boto3
import botocore.exceptions

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def _delete_resource(logs_client, delete_fn, identifier, label):
    """Delete a delivery resource, ignoring ResourceNotFoundException."""
    try:
        delete_fn(**identifier)
        logger.info(f"deleted_{label}", extra=identifier)
    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            logger.info(f"{label}_already_deleted", extra=identifier)
        else:
            raise


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """CloudFormation custom resource handler for X-Ray delivery."""
    request_type = event["RequestType"]
    props = event["ResourceProperties"]
    runtime_arn = props["RuntimeArn"]
    runtime_id = props["RuntimeId"]
    enable_identity = props.get("EnableIdentity", "true") == "true"
    account_id = props["AccountId"]
    region = os.environ.get("AWS_REGION", "us-west-2")

    logger.info(
        "xray_delivery_handler",
        extra={
            "request_type": request_type,
            "runtime_id": runtime_id,
            "enable_identity": enable_identity,
        },
    )

    logs_client = boto3.client("logs", region_name=region)
    short_id = runtime_id[:49]

    # Runtime traces
    rt_src_name = f"{short_id}-xray-src"
    rt_dst_name = f"{short_id}-xray-dst"

    # Identity traces
    id_src_name = f"{short_id}-idxr-src"
    id_dst_name = f"{short_id}-idxr-dst"
    identity_arn = (
        f"arn:aws:bedrock-agentcore:{region}:{account_id}"
        f":workload-identity-directory/default/workload-identity/{runtime_id}"
    )

    try:
        if request_type == "Create":
            delivery_ids = []

            # Ensure shared identity log group exists (idempotent)
            if enable_identity:
                identity_log_group = (
                    "/aws/vendedlogs/bedrock-agentcore"
                    "/workload-identity-directory/APPLICATION_LOGS/default"
                )
                try:
                    logs_client.create_log_group(logGroupName=identity_log_group)
                    logger.info(
                        "created_identity_log_group",
                        extra={"log_group": identity_log_group},
                    )
                except botocore.exceptions.ClientError as e:
                    if e.response["Error"]["Code"] == "ResourceAlreadyExistsException":
                        logger.info(
                            "identity_log_group_exists",
                            extra={"log_group": identity_log_group},
                        )
                    else:
                        raise

            # --- Runtime TRACES ---
            logs_client.put_delivery_source(
                name=rt_src_name, logType="TRACES", resourceArn=runtime_arn
            )
            rt_dst_resp = logs_client.put_delivery_destination(
                name=rt_dst_name, deliveryDestinationType="XRAY"
            )
            rt_delivery = logs_client.create_delivery(
                deliverySourceName=rt_src_name,
                deliveryDestinationArn=rt_dst_resp["deliveryDestination"]["arn"],
            )
            delivery_ids.append(rt_delivery["delivery"]["id"])
            logger.info(
                "runtime_traces_created", extra={"delivery_id": delivery_ids[-1]}
            )

            # --- Identity TRACES ---
            if enable_identity:
                logs_client.put_delivery_source(
                    name=id_src_name, logType="TRACES", resourceArn=identity_arn
                )
                id_dst_resp = logs_client.put_delivery_destination(
                    name=id_dst_name, deliveryDestinationType="XRAY"
                )
                id_delivery = logs_client.create_delivery(
                    deliverySourceName=id_src_name,
                    deliveryDestinationArn=id_dst_resp["deliveryDestination"]["arn"],
                )
                delivery_ids.append(id_delivery["delivery"]["id"])
                logger.info(
                    "identity_traces_created", extra={"delivery_id": delivery_ids[-1]}
                )

            physical_id = json.dumps(delivery_ids)
            return {
                "PhysicalResourceId": physical_id,
                "Data": {"DeliveryIds": physical_id},
            }

        elif request_type == "Update":
            return {"PhysicalResourceId": event.get("PhysicalResourceId", "no-id")}

        elif request_type == "Delete":
            # Parse delivery IDs from physical resource ID
            physical_id = event.get("PhysicalResourceId", "[]")
            try:
                delivery_ids = json.loads(physical_id)
            except (json.JSONDecodeError, TypeError):
                delivery_ids = [physical_id] if physical_id else []

            # Delete deliveries
            for did in delivery_ids:
                _delete_resource(
                    logs_client, logs_client.delete_delivery, {"id": did}, "delivery"
                )

            # Delete runtime traces source/destination
            _delete_resource(
                logs_client,
                logs_client.delete_delivery_source,
                {"name": rt_src_name},
                "rt_source",
            )
            _delete_resource(
                logs_client,
                logs_client.delete_delivery_destination,
                {"name": rt_dst_name},
                "rt_destination",
            )

            # Delete identity traces source/destination
            if enable_identity:
                _delete_resource(
                    logs_client,
                    logs_client.delete_delivery_source,
                    {"name": id_src_name},
                    "id_source",
                )
                _delete_resource(
                    logs_client,
                    logs_client.delete_delivery_destination,
                    {"name": id_dst_name},
                    "id_destination",
                )

            return {"PhysicalResourceId": physical_id}

        else:
            raise ValueError(f"Unexpected request type: {request_type}")

    except Exception as e:
        logger.exception(
            "xray_delivery_handler_error",
            extra={
                "request_type": request_type,
                "runtime_id": runtime_id,
                "error": str(e),
            },
        )
        raise
