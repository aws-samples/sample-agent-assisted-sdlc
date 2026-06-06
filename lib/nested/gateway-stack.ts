import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import { NagSuppressions } from "cdk-nag";
import { Construct } from "constructs";

import { McpGateway } from "../constructs/gateway/mcp-gateway";
import { SdlcConfig } from "../config";
import { buildRuntimeEndpoint, registerGatewayTarget } from "../utils";

export interface McpTarget {
  name: string;
  runtimeArn: string;
  imageTag: string;
  resourcePriority?: number;
}

export interface GatewayStackProps extends cdk.StackProps {
  config: SdlcConfig;
  vpc: ec2.IVpc;
  securityGroup: ec2.ISecurityGroup;
  targets: McpTarget[];
}

export class GatewayStack extends cdk.Stack {
  public readonly gateway: McpGateway;
  public readonly gatewayId: string;
  public readonly gatewayUrl: string;

  constructor(scope: Construct, id: string, props: GatewayStackProps) {
    super(scope, id, props);

    const { config, targets } = props;

    this.gateway = new McpGateway(this, "Gateway", {
      name: `${config.project}-gateway`,
      authorizerType: config.gateway?.authorizerType || "AWS_IAM",
    });

    this.gatewayId = this.gateway.gatewayId;
    this.gatewayUrl = this.gateway.gatewayUrl;

    // Register all MCP server targets on the gateway
    for (const target of targets) {
      registerGatewayTarget(this, `Target${target.name}`, this.gateway.gatewayId, {
        name: target.name,
        mcpServerEndpoint: buildRuntimeEndpoint(config.region, target.runtimeArn),
        resourcePriority: target.resourcePriority ?? 10,
        credentialProviderType: "GATEWAY_IAM_ROLE",
        iamService: "bedrock-agentcore",
          sourceHash: target.imageTag,
      });
    }

    NagSuppressions.addStackSuppressions(this, [
      { id: "AwsSolutions-IAM5", reason: "Gateway and custom resource policies use CDK-managed wildcard resources" },
      { id: "AwsSolutions-IAM4", reason: "Custom resource Lambda uses AWS managed execution role policy" },
      { id: "AwsSolutions-L1", reason: "Custom resource Lambda runtime is managed by CDK" },
      { id: "AwsSolutions-SF1", reason: "Provider Framework state machine logging not required" },
      { id: "AwsSolutions-SF2", reason: "Provider Framework state machine X-Ray not required" },
    ], true);
  }
}
