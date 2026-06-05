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

    // Create PolicyEngine if enabled
    let policyEngineId: string | undefined;
    if (config.gateway?.policyEngine?.enabled) {
      const policyEngine = new cdk.CfnResource(this, "PolicyEngine", {
        type: "AWS::BedrockAgentCore::PolicyEngine",
        properties: {
          Name: `${config.project}_policy_engine`,
        },
      });
      policyEngineId = policyEngine.ref;
    }

    this.gateway = new McpGateway(this, "Gateway", {
      name: `${config.project}-gateway`,
      authorizerType: config.gateway?.authorizerType || "AWS_IAM",
      policyEngineId: policyEngineId,
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

    // Create Cedar policies if enabled
    if (config.gateway?.policyEngine?.enabled && policyEngineId) {
      const region = cdk.Stack.of(this).region;
      const account = cdk.Stack.of(this).account;
      const gatewayArn = `arn:aws:bedrock-agentcore:${region}:${account}:gateway/${this.gateway.gatewayId}`;
      const labelPrefix = config.projectManagement.github?.labelPrefix || "agent";

      // Helper to sanitize project name for Cedar policy names (no hyphens, max 48 chars)
      const sanitizeName = (name: string) => name.replace(/-/g, "_").substring(0, 30);
      const projectPrefix = sanitizeName(config.project);

      // Policy 1: Branch protection (forbid main/master)
      new cdk.CfnResource(this, "BranchProtectionPolicy", {
        type: "AWS::BedrockAgentCore::Policy",
        properties: {
          Name: `${projectPrefix}_branch_protect`,
          PolicyEngineId: policyEngineId,
          Statement: `
forbid(
  principal is AgentCore::IamEntity,
  action in [
    AgentCore::Action::"source-control___push_files",
    AgentCore::Action::"source-control___create_branch",
    AgentCore::Action::"source-control___create_pull_request"
  ],
  resource == AgentCore::Gateway::"${gatewayArn}"
)
when {
  context.input has branch &&
  (context.input.branch == "main" || context.input.branch == "master")
};
`.trim(),
        },
      });

      // Policy 2: Branch pattern enforcement (permit only feat/issue-*)
      new cdk.CfnResource(this, "BranchPatternPolicy", {
        type: "AWS::BedrockAgentCore::Policy",
        properties: {
          Name: `${projectPrefix}_branch_pattern`,
          PolicyEngineId: policyEngineId,
          Statement: `
forbid(
  principal is AgentCore::IamEntity,
  action in [
    AgentCore::Action::"source-control___push_files",
    AgentCore::Action::"source-control___create_branch"
  ],
  resource == AgentCore::Gateway::"${gatewayArn}"
)
when {
  context.input has branch &&
  !(context.input.branch like "feat/issue-*")
};
`.trim(),
        },
      });

      // Policy 3: Label governance (forbid {prefix}:start)
      new cdk.CfnResource(this, "LabelGovernancePolicy", {
        type: "AWS::BedrockAgentCore::Policy",
        properties: {
          Name: `${projectPrefix}_label_gov`,
          PolicyEngineId: policyEngineId,
          Statement: `
forbid(
  principal is AgentCore::IamEntity,
  action == AgentCore::Action::"project-management___issue_write",
  resource == AgentCore::Gateway::"${gatewayArn}"
)
when {
  context.input has labels &&
  context.input.labels.contains("${labelPrefix}:start")
};
`.trim(),
        },
      });

      // Policy 4: Default permit for authenticated callers
      new cdk.CfnResource(this, "DefaultPermitPolicy", {
        type: "AWS::BedrockAgentCore::Policy",
        properties: {
          Name: `${projectPrefix}_default_permit`,
          PolicyEngineId: policyEngineId,
          Statement: `
permit(
  principal is AgentCore::IamEntity,
  action,
  resource == AgentCore::Gateway::"${gatewayArn}"
);
`.trim(),
        },
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
