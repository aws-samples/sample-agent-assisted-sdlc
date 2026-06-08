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
   * Number of days to retain CloudWatch Logs.
   * @default 30
   */
  logRetentionDays?: number;

  /**
   * Whether to enable Identity (workload-identity-directory) log delivery.
   * @default true
   */
  enableIdentityLogs?: boolean;
}

/**
 * Reusable construct for AgentCore runtime observability delivery.
 *
 * Sets up four log delivery pipelines:
 *   Runtime tab:
 *     1. APPLICATION_LOGS → CloudWatch Logs
 *     2. USAGE_LOGS → CloudWatch Logs
 *     3. TRACES → X-Ray (custom resource, CFN doesn't support XRAY destination)
 *   Identity tab:
 *     4. APPLICATION_LOGS (workload-identity-directory) → CloudWatch Logs
 */
export class RuntimeObservability extends Construct {
  public readonly appLogGroupName: string;
  public readonly usageLogGroupName: string;
  public readonly identityLogGroupName: string;

  constructor(scope: Construct, id: string, props: RuntimeObservabilityProps) {
    super(scope, id);

    const stack = cdk.Stack.of(this);
    const retentionDays = props.logRetentionDays ?? 30;
    const shortId = props.runtimeId.substring(0, 49);
    const enableIdentity = props.enableIdentityLogs ?? true;

    // -------------------------------------------------------------------
    // 1. RUNTIME — APPLICATION_LOGS
    // -------------------------------------------------------------------

    const appLogGroup = new cdk.CfnResource(this, "ApplicationLogGroup", {
      type: "AWS::Logs::LogGroup",
      properties: {
        LogGroupName: `/aws/vendedlogs/bedrock-agentcore/runtime/APPLICATION_LOGS/${props.runtimeId}`,
        RetentionInDays: retentionDays,
        LogGroupClass: "STANDARD",
      },
    });
    this.appLogGroupName = appLogGroup.ref;

    const appSource = new cdk.CfnResource(this, "ApplicationLogsSource", {
      type: "AWS::Logs::DeliverySource",
      properties: {
        Name: `${shortId}-app-src`,
        LogType: "APPLICATION_LOGS",
        ResourceArn: props.runtimeArn,
      },
    });

    const appDest = new cdk.CfnResource(this, "ApplicationLogsDestination", {
      type: "AWS::Logs::DeliveryDestination",
      properties: {
        Name: `${shortId}-app-dst`,
        DeliveryDestinationType: "CWL",
        DestinationResourceArn: appLogGroup.getAtt("Arn").toString(),
      },
    });

    const appDelivery = new cdk.CfnResource(this, "ApplicationLogsDelivery", {
      type: "AWS::Logs::Delivery",
      properties: {
        DeliverySourceName: appSource.ref,
        DeliveryDestinationArn: appDest.getAtt("Arn").toString(),
      },
    });
    appDelivery.addDependency(appSource);
    appDelivery.addDependency(appDest);

    // -------------------------------------------------------------------
    // 2. RUNTIME — USAGE_LOGS
    // -------------------------------------------------------------------

    const usageLogGroup = new cdk.CfnResource(this, "UsageLogGroup", {
      type: "AWS::Logs::LogGroup",
      properties: {
        LogGroupName: `/aws/vendedlogs/bedrock-agentcore/runtime/USAGE_LOGS/${props.runtimeId}`,
        RetentionInDays: retentionDays,
        LogGroupClass: "STANDARD",
      },
    });
    this.usageLogGroupName = usageLogGroup.ref;

    const usageSource = new cdk.CfnResource(this, "UsageSource", {
      type: "AWS::Logs::DeliverySource",
      properties: {
        Name: `${shortId}-usg-src`,
        LogType: "USAGE_LOGS",
        ResourceArn: props.runtimeArn,
      },
    });

    const usageDest = new cdk.CfnResource(this, "UsageDestination", {
      type: "AWS::Logs::DeliveryDestination",
      properties: {
        Name: `${shortId}-usg-dst`,
        DeliveryDestinationType: "CWL",
        DestinationResourceArn: usageLogGroup.getAtt("Arn").toString(),
      },
    });

    const usageDelivery = new cdk.CfnResource(this, "UsageDelivery", {
      type: "AWS::Logs::Delivery",
      properties: {
        DeliverySourceName: usageSource.ref,
        DeliveryDestinationArn: usageDest.getAtt("Arn").toString(),
      },
    });
    usageDelivery.addDependency(usageSource);
    usageDelivery.addDependency(usageDest);

    // -------------------------------------------------------------------
    // 3. RUNTIME — X-RAY TRACES (Custom Resource)
    // -------------------------------------------------------------------

    const xrayDeliveryHandler = new lambda.Function(this, "XRayDeliveryHandler", {
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: "index.handler",
      code: lambda.Code.fromAsset(path.join(__dirname, "xray-delivery-lambda")),
      timeout: cdk.Duration.minutes(5),
    });

    xrayDeliveryHandler.addToRolePolicy(new iam.PolicyStatement({
      actions: [
        "logs:CreateLogGroup",
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
      actions: ["bedrock-agentcore:AllowVendedLogDeliveryForResource"],
      resources: ["*"],
    }));

    xrayDeliveryHandler.addToRolePolicy(new iam.PolicyStatement({
      actions: ["xray:PutResourcePolicy", "xray:ListResourcePolicies"],
      resources: ["*"],
    }));

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

    const xrayDeliveryProvider = new cr.Provider(this, "XRayDeliveryProvider", {
      onEventHandler: xrayDeliveryHandler,
    });

    new cdk.CustomResource(this, "XRayTracesDelivery", {
      serviceToken: xrayDeliveryProvider.serviceToken,
      properties: {
        RuntimeArn: props.runtimeArn,
        RuntimeId: props.runtimeId,
        AccountId: stack.account,
        EnableIdentity: enableIdentity ? "true" : "false",
      },
    });

    // -------------------------------------------------------------------
    // 4. IDENTITY — APPLICATION_LOGS (workload-identity-directory)
    // -------------------------------------------------------------------

    if (enableIdentity) {
      const identityArn = `arn:aws:bedrock-agentcore:${stack.region}:${stack.account}:workload-identity-directory/default/workload-identity/${props.runtimeId}`;

      // The identity log group is shared across all runtimes in the account.
      // Reference it by ARN rather than creating it — it may already exist
      // from another runtime or from console-based setup.
      const identityLogGroupArn = `arn:aws:logs:${stack.region}:${stack.account}:log-group:/aws/vendedlogs/bedrock-agentcore/workload-identity-directory/APPLICATION_LOGS/default`;
      this.identityLogGroupName = "/aws/vendedlogs/bedrock-agentcore/workload-identity-directory/APPLICATION_LOGS/default";

      const identitySource = new cdk.CfnResource(this, "IdentitySource", {
        type: "AWS::Logs::DeliverySource",
        properties: {
          Name: `${shortId}-id-src`,
          LogType: "APPLICATION_LOGS",
          ResourceArn: identityArn,
        },
      });

      const identityDest = new cdk.CfnResource(this, "IdentityDestination", {
        type: "AWS::Logs::DeliveryDestination",
        properties: {
          Name: `${shortId}-id-dst`,
          DeliveryDestinationType: "CWL",
          DestinationResourceArn: identityLogGroupArn,
        },
      });

      const identityDelivery = new cdk.CfnResource(this, "IdentityDelivery", {
        type: "AWS::Logs::Delivery",
        properties: {
          DeliverySourceName: identitySource.ref,
          DeliveryDestinationArn: identityDest.getAtt("Arn").toString(),
        },
      });
      identityDelivery.addDependency(identitySource);
      identityDelivery.addDependency(identityDest);
    }
  }
}
