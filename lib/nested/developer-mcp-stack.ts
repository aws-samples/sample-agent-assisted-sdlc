import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import { NagSuppressions } from "cdk-nag";
import { Construct } from "constructs";

import { McpServer } from "../constructs/runtime/mcp-server";
import { RuntimeObservability } from "../constructs/observability/runtime-observability";
import { SdlcConfig } from "../config";

export interface DeveloperMcpStackProps extends cdk.StackProps {
  config: SdlcConfig;
  vpc: ec2.IVpc;
  securityGroup: ec2.ISecurityGroup;
}

export class DeveloperMcpStack extends cdk.Stack {
  public readonly runtimes: Array<{ name: string; runtimeArn: string; imageTag: string }> = [];

  constructor(scope: Construct, id: string, props: DeveloperMcpStackProps) {
    super(scope, id, props);

    const { config, vpc, securityGroup } = props;

    for (const serverConfig of config.gateway!.developerMcpServers!) {
      const server = new McpServer(this, `McpServer${serverConfig.name}`, {
        name: `${config.project}_${serverConfig.name.replace(/-/g, "_")}`,
        codePath: serverConfig.source,
        vpc,
        securityGroup,
        protocol: "MCP",
      });

      new RuntimeObservability(this, `Observability${serverConfig.name}`, {
        runtimeArn: server.runtimeArn,
        runtimeId: server.runtimeId,
        logRetentionDays: 30,
      });

      this.runtimes.push({
        name: serverConfig.name,
        runtimeArn: server.runtimeArn,
        imageTag: server.imageTag,
      });
    }

    NagSuppressions.addStackSuppressions(this, [
      { id: "AwsSolutions-IAM5", reason: "MCP server and custom resource policies use CDK-managed wildcard resources" },
      { id: "AwsSolutions-IAM4", reason: "Lambda uses AWS managed execution role policy" },
      { id: "AwsSolutions-L1", reason: "Lambda runtime is managed by CDK" },
      { id: "AwsSolutions-CB4", reason: "CodeBuild encryption not required for container image builds" },
      { id: "AwsSolutions-SF1", reason: "Provider Framework state machine logging not required" },
      { id: "AwsSolutions-SF2", reason: "Provider Framework state machine X-Ray not required" },
    ], true);
  }
}
