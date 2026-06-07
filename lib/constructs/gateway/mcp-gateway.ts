import * as cdk from "aws-cdk-lib";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as cr from "aws-cdk-lib/custom-resources";
import { execSync } from "child_process";
import * as path from "path";
import { Construct } from "constructs";
import { NagSuppressions } from "cdk-nag";

export interface McpGatewayProps {
  name: string;
  authorizerType?: string;
}

export class McpGateway extends Construct {
  public readonly gatewayArn: string;
  public readonly gatewayId: string;
  public readonly gatewayUrl: string;
  public readonly gatewayRole: iam.Role;

  constructor(scope: Construct, id: string, props: McpGatewayProps) {
    super(scope, id);

    const stack = cdk.Stack.of(this);

    this.gatewayRole = new iam.Role(this, "GatewayRole", {
      assumedBy: new iam.ServicePrincipal("bedrock-agentcore.amazonaws.com", {
        conditions: {
          StringEquals: {
            "aws:SourceAccount": stack.account,
          },
          ArnLike: {
            "aws:SourceArn": `arn:aws:bedrock-agentcore:${stack.region}:${stack.account}:*`,
          },
        },
      }),
    });

    // Broad permission so the gateway can invoke any runtime in this account
    this.gatewayRole.addToPolicy(new iam.PolicyStatement({
      actions: ["bedrock-agentcore:InvokeAgentRuntime"],
      resources: [
        `arn:aws:bedrock-agentcore:${stack.region}:${stack.account}:runtime/*`,
        `arn:aws:bedrock-agentcore:${stack.region}:${stack.account}:runtime/*/runtime-endpoint/*`,
      ],
    }));

    const createGateway = new cr.AwsCustomResource(this, "CreateGateway", {
      installLatestAwsSdk: true,
      onCreate: {
        service: "bedrock-agentcore-control",
        action: "createGateway",
        parameters: {
          name: props.name,
          roleArn: this.gatewayRole.roleArn,
          protocolType: "MCP",
          authorizerType: props.authorizerType || "AWS_IAM",
          protocolConfiguration: {
            mcp: {
              supportedVersions: ["2025-11-25"],
              streamingConfiguration: {
                enableResponseStreaming: true,
              },
              sessionConfiguration: {
                sessionTimeoutInSeconds: 3600,
              },
            },
          },
        },
        physicalResourceId: cr.PhysicalResourceId.fromResponse("gatewayId"),
      },
      onUpdate: {
        service: "bedrock-agentcore-control",
        action: "getGateway",
        parameters: {
          gatewayIdentifier: new cr.PhysicalResourceIdReference(),
        },
        physicalResourceId: cr.PhysicalResourceId.fromResponse("gatewayId"),
      },
      onDelete: {
        service: "bedrock-agentcore-control",
        action: "deleteGateway",
        parameters: {
          gatewayIdentifier: new cr.PhysicalResourceIdReference(),
        },
        ignoreErrorCodesMatching: "ResourceNotFoundException|ValidationException",
      },
      policy: cr.AwsCustomResourcePolicy.fromStatements([
        new iam.PolicyStatement({
          actions: [
            "bedrock-agentcore:CreateGateway",
            "bedrock-agentcore:GetGateway",
            "bedrock-agentcore:CreateWorkloadIdentity",
            "bedrock-agentcore:DeleteWorkloadIdentity",
            "bedrock-agentcore:GetWorkloadIdentity",
            "bedrock-agentcore:ListGatewayTargets",
            "bedrock-agentcore:DeleteGatewayTarget",
            "bedrock-agentcore:DeleteGateway",
          ],
          resources: ["*"],
        }),
        new iam.PolicyStatement({
          actions: ["iam:PassRole"],
          resources: [this.gatewayRole.roleArn],
        }),
      ]),
    });

    this.gatewayId = createGateway.getResponseField("gatewayId");
    this.gatewayArn = createGateway.getResponseField("gatewayArn");
    this.gatewayUrl = createGateway.getResponseField("gatewayUrl");

    // Waiter: polls getGateway until READY, handles cleanup (delete targets + gateway) on stack deletion
    const waiterLambdaPath = path.join(__dirname, "gateway-waiter-lambda");
    const waiterCode = lambda.Code.fromAsset(waiterLambdaPath, {
      bundling: {
        image: lambda.Runtime.NODEJS_20_X.bundlingImage,
        command: ["bash", "-c", "echo 'docker bundling unused'"],
        local: {
          tryBundle(outputDir: string) {
            execSync(`cp -r ${waiterLambdaPath}/* ${outputDir}/`);
            execSync("npm install --omit=dev", { cwd: outputDir, stdio: "inherit" });
            return true;
          },
        },
      },
    });
    const waiterPolicy = new iam.PolicyStatement({
      actions: [
        "bedrock-agentcore:GetGateway",
        "bedrock-agentcore:ListGatewayTargets",
        "bedrock-agentcore:DeleteGatewayTarget",
        "bedrock-agentcore:DeleteGateway",
      ],
      resources: ["*"],
    });

    const waiterOnEvent = new lambda.Function(this, "WaiterOnEvent", {
      runtime: lambda.Runtime.NODEJS_20_X,
      handler: "index.onEvent",
      code: waiterCode,
      timeout: cdk.Duration.minutes(5),
    });
    waiterOnEvent.addToRolePolicy(waiterPolicy);

    const waiterIsComplete = new lambda.Function(this, "WaiterIsComplete", {
      runtime: lambda.Runtime.NODEJS_20_X,
      handler: "index.isComplete",
      code: waiterCode,
      timeout: cdk.Duration.seconds(60),
    });
    waiterIsComplete.addToRolePolicy(waiterPolicy);

    const waiterProvider = new cr.Provider(this, "WaiterProvider", {
      onEventHandler: waiterOnEvent,
      isCompleteHandler: waiterIsComplete,
      queryInterval: cdk.Duration.seconds(10),
      totalTimeout: cdk.Duration.minutes(10),
    });

    new cdk.CustomResource(this, "WaitForReady", {
      serviceToken: waiterProvider.serviceToken,
      properties: { GatewayId: this.gatewayId },
    }).node.addDependency(createGateway);

    NagSuppressions.addResourceSuppressions(this.gatewayRole, [
      { id: "AwsSolutions-IAM5", reason: "Gateway role needs broad InvokeAgentRuntime for all runtimes in account" },
    ], true);

    new cdk.CfnOutput(scope, "GatewayId", { value: this.gatewayId });
    new cdk.CfnOutput(scope, "GatewayUrl", { value: this.gatewayUrl });
  }

  public grantInvoke(role: iam.IRole): void {
    role.addToPrincipalPolicy(new iam.PolicyStatement({
      actions: ["bedrock-agentcore:InvokeGateway"],
      resources: [`arn:aws:bedrock-agentcore:${cdk.Stack.of(this).region}:${cdk.Stack.of(this).account}:gateway/*`],
    }));
  }
}
