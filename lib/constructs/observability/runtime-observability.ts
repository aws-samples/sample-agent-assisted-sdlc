import * as path from "path";

import * as cdk from "aws-cdk-lib";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as cr from "aws-cdk-lib/custom-resources";
import { NagSuppressions } from "cdk-nag";
import { Construct } from "constructs";

export interface RuntimeObservabilityProps {
  /**
   * The ARN of the AgentCore runtime resource.
   */
  runtimeArn: string;

  /**
   * The unique identifier of the runtime (used in log group naming).
   */
  runtimeId: string;

  /**
   * Number of days to retain CloudWatch Logs application logs.
   * @default 30
   */
  logRetentionDays?: number;
}

/**
 * Reusable construct for AgentCore runtime observability delivery.
 *
 * Sets up CloudWatch Logs delivery for APPLICATION_LOGS (declarative CFN)
 * and X-Ray traces delivery (custom resource Lambda). The construct is
 * generic and can be applied to any AgentCore runtime by passing the
 * runtime ARN and ID.
 */
export class RuntimeObservability extends Construct {
  /**
   * CloudWatch log group name for application logs.
   */
  public readonly logGroupName: string;

  constructor(scope: Construct, id: string, props: RuntimeObservabilityProps) {
    super(scope, id);

    const retentionDays = props.logRetentionDays ?? 30;

    // -------------------------------------------------------------------
    // APPLICATION LOGS (Declarative CloudFormation Resources)
    // -------------------------------------------------------------------

    // CloudWatch LogGroup for vended logs
    const logGroup = new cdk.CfnResource(this, "ApplicationLogGroup", {
      type: "AWS::Logs::LogGroup",
      properties: {
        LogGroupName: `/aws/vendedlogs/bedrock-agentcore/${props.runtimeId}`,
        RetentionInDays: retentionDays,
        LogGroupClass: "STANDARD",
      },
    });
    this.logGroupName = logGroup.ref;

    // Delivery source for APPLICATION_LOGS
    const deliverySource = new cdk.CfnResource(this, "ApplicationLogsSource", {
      type: "AWS::Logs::DeliverySource",
      properties: {
        Name: `${props.runtimeId}-application-logs-source`,
        LogType: "APPLICATION_LOGS",
        ResourceArn: props.runtimeArn,
      },
    });

    // Delivery destination pointing to CloudWatch Logs
    const deliveryDestination = new cdk.CfnResource(this, "ApplicationLogsDestination", {
      type: "AWS::Logs::DeliveryDestination",
      properties: {
        Name: `${props.runtimeId}-application-logs-destination`,
        DeliveryDestinationType: "CWL",
        DestinationResourceArn: logGroup.getAtt("Arn").toString(),
      },
    });

    // Delivery linking source to destination
    const delivery = new cdk.CfnResource(this, "ApplicationLogsDelivery", {
      type: "AWS::Logs::Delivery",
      properties: {
        DeliverySourceName: deliverySource.ref,
        DeliveryDestinationArn: deliveryDestination.getAtt("Arn").toString(),
      },
    });
    delivery.addDependency(deliverySource);
    delivery.addDependency(deliveryDestination);

    // -------------------------------------------------------------------
    // X-RAY TRACES (Custom Resource Lambda)
    // -------------------------------------------------------------------

    // Lambda function for X-Ray delivery management
    const xrayDeliveryHandler = new lambda.Function(this, "XRayDeliveryHandler", {
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: "index.handler",
      code: lambda.Code.fromAsset(path.join(__dirname, "xray-delivery-lambda")),
      timeout: cdk.Duration.minutes(5),
    });

    // IAM permissions for CloudWatch Logs Delivery API and X-Ray
    xrayDeliveryHandler.addToRolePolicy(new iam.PolicyStatement({
      actions: [
        "logs:PutDeliverySource",
        "logs:DeleteDeliverySource",
        "logs:PutDeliveryDestination",
        "logs:DeleteDeliveryDestination",
        "logs:CreateDelivery",
        "logs:DeleteDelivery",
      ],
      resources: ["*"],
    }));

    xrayDeliveryHandler.addToRolePolicy(new iam.PolicyStatement({
      actions: [
        "bedrock-agentcore:AllowVendedLogDeliveryForResource",
      ],
      resources: ["*"],
    }));

    xrayDeliveryHandler.addToRolePolicy(new iam.PolicyStatement({
      actions: [
        "xray:PutResourcePolicy",
        "xray:ListResourcePolicies",
      ],
      resources: ["*"],
    }));

    // Suppress cdk-nag warnings for Lambda role wildcard resources
    NagSuppressions.addResourceSuppressions(
      xrayDeliveryHandler.role!,
      [
        {
          id: "AwsSolutions-IAM5",
          reason: "CloudWatch Logs Delivery API requires wildcard resources for cross-service delivery setup",
        },
      ],
      true,
    );

    // Custom resource provider (single onEvent handler, no isComplete needed)
    const xrayDeliveryProvider = new cr.Provider(this, "XRayDeliveryProvider", {
      onEventHandler: xrayDeliveryHandler,
    });

    // Custom resource for X-Ray traces delivery
    const xrayDelivery = new cdk.CustomResource(this, "XRayTracesDelivery", {
      serviceToken: xrayDeliveryProvider.serviceToken,
      properties: {
        RuntimeArn: props.runtimeArn,
        RuntimeId: props.runtimeId,
      },
    });
  }
}
