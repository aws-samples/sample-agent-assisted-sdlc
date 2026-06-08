# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Custom resource handler for CloudWatch Logs X-Ray traces delivery.

Manages the CloudWatch Logs Delivery API lifecycle for X-Ray traces delivery,
which is not supported by declarative CloudFormation. Handles Create/Update/Delete
lifecycle with idempotent cleanup on ResourceNotFoundException.
"""

import logging
import os
from typing import Any, Dict

import boto3
import botocore.exceptions

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """CloudFormation custom resource handler for X-Ray delivery.

    Creates CloudWatch Logs delivery sources, destinations, and delivery
    resources for X-Ray traces. Delete operations are idempotent and handle
    ResourceNotFoundException gracefully.

    Args:
        event: CloudFormation custom resource event containing RequestType,
               ResourceProperties with RuntimeArn and RuntimeId.
        context: Lambda context object.

    Returns:
        Response dict with PhysicalResourceId and optional Data fields.
    """
    request_type = event["RequestType"]
    runtime_arn = event["ResourceProperties"]["RuntimeArn"]
    runtime_id = event["ResourceProperties"]["RuntimeId"]

    logger.info(
        "xray_delivery_handler",
        extra={
            "request_type": request_type,
            "runtime_id": runtime_id,
            "runtime_arn": runtime_arn,
        },
    )

    region = os.environ.get("AWS_REGION", "us-west-2")
    logs_client = boto3.client("logs", region_name=region)

    source_name = f"{runtime_id}-xray-traces-source"
    destination_name = f"{runtime_id}-xray-traces-destination"

    try:
        if request_type == "Create":
            # Create delivery source for TRACES
            logs_client.put_delivery_source(
                name=source_name,
                logType="TRACES",
                resourceArn=runtime_arn,
            )
            logger.info(
                "created_delivery_source",
                extra={"source_name": source_name, "log_type": "TRACES"},
            )

            # Create delivery destination for X-Ray
            # Note: X-Ray delivery destinations don't have a specific resource ARN
            dest_response = logs_client.put_delivery_destination(
                name=destination_name,
                deliveryDestinationType="XRAY",
            )
            destination_arn = dest_response["deliveryDestination"]["arn"]
            logger.info(
                "created_delivery_destination",
                extra={
                    "destination_name": destination_name,
                    "destination_type": "XRAY",
                    "destination_arn": destination_arn,
                },
            )

            # Create delivery linking source to destination
            delivery_response = logs_client.create_delivery(
                deliverySourceName=source_name,
                deliveryDestinationArn=destination_arn,
            )
            delivery_id = delivery_response["delivery"]["id"]
            logger.info(
                "created_delivery",
                extra={"delivery_id": delivery_id},
            )

            return {
                "PhysicalResourceId": delivery_id,
                "Data": {
                    "DeliveryId": delivery_id,
                    "SourceName": source_name,
                    "DestinationName": destination_name,
                },
            }

        elif request_type == "Update":
            # X-Ray delivery is immutable — no-op on update
            physical_resource_id = event.get("PhysicalResourceId", "no-id")
            logger.info(
                "update_noop",
                extra={"physical_resource_id": physical_resource_id},
            )
            return {"PhysicalResourceId": physical_resource_id}

        elif request_type == "Delete":
            delivery_id = event.get("PhysicalResourceId", "")

            # Delete delivery (idempotent)
            try:
                logs_client.delete_delivery(id=delivery_id)
                logger.info(
                    "deleted_delivery",
                    extra={"delivery_id": delivery_id},
                )
            except botocore.exceptions.ClientError as e:
                if e.response["Error"]["Code"] == "ResourceNotFoundException":
                    logger.info(
                        "delivery_already_deleted",
                        extra={"delivery_id": delivery_id},
                    )
                else:
                    raise

            # Delete delivery source (idempotent)
            try:
                logs_client.delete_delivery_source(name=source_name)
                logger.info(
                    "deleted_delivery_source",
                    extra={"source_name": source_name},
                )
            except botocore.exceptions.ClientError as e:
                if e.response["Error"]["Code"] == "ResourceNotFoundException":
                    logger.info(
                        "delivery_source_already_deleted",
                        extra={"source_name": source_name},
                    )
                else:
                    raise

            # Delete delivery destination (idempotent)
            try:
                logs_client.delete_delivery_destination(name=destination_name)
                logger.info(
                    "deleted_delivery_destination",
                    extra={"destination_name": destination_name},
                )
            except botocore.exceptions.ClientError as e:
                if e.response["Error"]["Code"] == "ResourceNotFoundException":
                    logger.info(
                        "delivery_destination_already_deleted",
                        extra={"destination_name": destination_name},
                    )
                else:
                    raise

            return {"PhysicalResourceId": delivery_id}

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
