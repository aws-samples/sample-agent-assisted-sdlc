import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import { NagSuppressions } from "cdk-nag";
import { Construct } from "constructs";

import { McpServer } from "../constructs/runtime/mcp-server";
import { RuntimeObservability } from "../constructs/observability/runtime-observability";
import { SdlcConfig } from "../config";

export interface ProjectManagementStackProps extends cdk.StackProps {
  config: SdlcConfig;
  vpc: ec2.IVpc;
  securityGroup: ec2.ISecurityGroup;
  privateKeySecretArn: string;
}

export class ProjectManagementStack extends cdk.Stack {
  public readonly runtimeArn: string;
  public readonly executionRoleArn: string;
  public readonly imageTag: string;

  constructor(scope: Construct, id: string, props: ProjectManagementStackProps) {
    super(scope, id, props);

    const { config, vpc, securityGroup, privateKeySecretArn } = props;

    if (config.projectManagement.type !== "github") {
      throw new Error(
        `Unsupported projectManagement.type: "${config.projectManagement.type}". ` +
        `Only "github" is implemented. Add a connector under project-management/<type>/mcp/.`,
      );
    }

    const ghConfig = config.sourceControl.github!;
    const pmConfig = config.projectManagement.github;

    const privateKeySecret = secretsmanager.Secret.fromSecretCompleteArn(
      this, "PrivateKeySecret", privateKeySecretArn,
    );

    const mcp = new McpServer(this, "McpServer", {
      name: `${config.project}_github_issues`,
      codePath: "./project-management/github/mcp",
      vpc,
      securityGroup,
      protocol: "MCP",
      maxLifetime: pmConfig?.maxLifetime || 3300,
      environmentVariables: {
        GITHUB_APP_CLIENT_ID: ghConfig.appClientId,
        GITHUB_INSTALLATION_ID: ghConfig.installationId,
        PRIVATE_KEY_SECRET_ARN: privateKeySecretArn,
        GITHUB_TOOLSETS: pmConfig?.toolsets || "issues",
      },
    });

    privateKeySecret.grantRead(mcp.executionRole);

    new RuntimeObservability(this, "Observability", {
      runtimeArn: mcp.runtimeArn,
      runtimeId: mcp.runtimeId,
      logRetentionDays: 30,
    });

    this.runtimeArn = mcp.runtimeArn;
    this.executionRoleArn = (mcp.executionRole as any).roleArn;
    this.imageTag = mcp.imageTag;

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
