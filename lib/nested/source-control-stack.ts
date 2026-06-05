import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import { NagSuppressions } from "cdk-nag";
import { Construct } from "constructs";

import { McpServer } from "../constructs/runtime/mcp-server";
import { GitHubConnector } from "../constructs/connectors/github/github-connector";
import { SdlcConfig } from "../config";

export interface SourceControlStackProps extends cdk.StackProps {
  config: SdlcConfig;
  vpc: ec2.IVpc;
  securityGroup: ec2.ISecurityGroup;
}

export class SourceControlStack extends cdk.Stack {
  public readonly runtimeArn: string;
  public readonly executionRoleArn: string;
  public readonly imageTag: string;
  public readonly privateKeySecretArn: string;
  public readonly tokenLambdaArn: string;

  constructor(scope: Construct, id: string, props: SourceControlStackProps) {
    super(scope, id, props);

    const { config, vpc, securityGroup } = props;
    const ghConfig = config.sourceControl.github!;

    const githubConnector = new GitHubConnector(this, "GitHubConnector", {
      appClientId: ghConfig.appClientId,
      installationId: ghConfig.installationId,
      privateKeyPath: ghConfig.privateKeyPath,
      toolsets: ghConfig.toolsets || "repos,pull_requests,context,actions",
      maxLifetime: ghConfig.maxLifetime,
    });

    this.privateKeySecretArn = githubConnector.privateKeySecret.secretArn;
    this.tokenLambdaArn = githubConnector.tokenFunction.functionArn;

    const mcp = new McpServer(this, "McpServer", {
      name: `${config.project}_github_code`,
      codePath: "./source-control/github/mcp",
      vpc,
      securityGroup,
      protocol: "MCP",
      maxLifetime: ghConfig.maxLifetime || 3300,
      environmentVariables: {
        GITHUB_APP_CLIENT_ID: ghConfig.appClientId,
        GITHUB_INSTALLATION_ID: ghConfig.installationId,
        PRIVATE_KEY_SECRET_ARN: githubConnector.privateKeySecret.secretArn,
        GITHUB_TOOLSETS: ghConfig.toolsets || "repos,pull_requests,context,actions",
      },
    });

    githubConnector.grantTokenGeneration(mcp.executionRole);

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
