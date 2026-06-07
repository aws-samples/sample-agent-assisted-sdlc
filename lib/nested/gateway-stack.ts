import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import { NagSuppressions } from "cdk-nag";
import { Construct } from "constructs";

import { McpGateway } from "../constructs/gateway/mcp-gateway";
import { SdlcConfig } from "../config";
import { buildRuntimeEndpoint, registerGatewayTarget } from "../utils";

const sanitizeName = (name: string) => name.replace(/-/g, "_").substring(0, 30);

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

    // 1. PolicyEngine
    const policyEngine = new cdk.CfnResource(this, "PolicyEngine", {
      type: "AWS::BedrockAgentCore::PolicyEngine",
      properties: {
        Name: sanitizeName(config.project) + "_cedar_v3",
      },
    });
    const policyEngineArn = policyEngine.getAtt("PolicyEngineArn").toString();
    const policyEngineId = policyEngine.getAtt("PolicyEngineId").toString();

    // 2. Gateway (without policyEngineConfiguration — attached separately after READY)
    this.gateway = new McpGateway(this, "Gateway", {
      name: `${config.project}-gateway`,
      authorizerType: config.gateway?.authorizerType || "AWS_IAM",
    });

    this.gatewayId = this.gateway.gatewayId;
    this.gatewayUrl = this.gateway.gatewayUrl;

    // 3. Register all MCP server targets on the gateway
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

    // Gateway-to-PolicyEngine attachment is done manually post-deploy via:
    //   aws bedrock-agentcore-control update-gateway --gateway-identifier <id> \
    //     --name <name> --role-arn <arn> --authorizer-type AWS_IAM \
    //     --policy-engine-configuration '{"arn":"<engine-arn>","mode":"ENFORCE"}'


    // 6. Cedar policies (created without gateway attachment — attach manually post-deploy)
    const gatewayArn = this.gateway.gatewayArn;
    const labelPrefix = config.projectManagement.github?.labelPrefix || "agent";
    const projectPrefix = sanitizeName(config.project);

    const branchProtectionPolicy = new cdk.CfnResource(this, "BranchProtectionPolicy", {
      type: "AWS::BedrockAgentCore::Policy",
      properties: {
        Name: `${projectPrefix}_branch_protect`,
        PolicyEngineId: policyEngineId,
        Definition: {
          Cedar: { Statement: `forbid(principal is AgentCore::IamEntity, action in [AgentCore::Action::"source-control___push_files", AgentCore::Action::"source-control___create_branch", AgentCore::Action::"source-control___create_pull_request"], resource == AgentCore::Gateway::"${gatewayArn}") when { context.input has branch && (context.input.branch == "main" || context.input.branch == "master") };` },
        },
      },
    });
    branchProtectionPolicy.node.addDependency(policyEngine);

    const branchPatternPolicy = new cdk.CfnResource(this, "BranchPatternPolicy", {
      type: "AWS::BedrockAgentCore::Policy",
      properties: {
        Name: `${projectPrefix}_branch_pattern`,
        PolicyEngineId: policyEngineId,
        Definition: {
          Cedar: { Statement: `forbid(principal is AgentCore::IamEntity, action in [AgentCore::Action::"source-control___push_files", AgentCore::Action::"source-control___create_branch"], resource == AgentCore::Gateway::"${gatewayArn}") when { context.input has branch && !(context.input.branch like "feat/issue-*") };` },
        },
      },
    });
    branchPatternPolicy.node.addDependency(policyEngine);

    const labelGovernancePolicy = new cdk.CfnResource(this, "LabelGovernancePolicy", {
      type: "AWS::BedrockAgentCore::Policy",
      properties: {
        Name: `${projectPrefix}_label_gov`,
        PolicyEngineId: policyEngineId,
        Definition: {
          Cedar: { Statement: `forbid(principal is AgentCore::IamEntity, action == AgentCore::Action::"project-management___issue_write", resource == AgentCore::Gateway::"${gatewayArn}") when { context.input has labels && context.input.labels.contains("${labelPrefix}:start") };` },
        },
      },
    });
    labelGovernancePolicy.node.addDependency(policyEngine);

    const defaultPermitPolicy = new cdk.CfnResource(this, "DefaultPermitPolicy", {
      type: "AWS::BedrockAgentCore::Policy",
      properties: {
        Name: `${projectPrefix}_default_permit`,
        PolicyEngineId: policyEngineId,
        Definition: {
          Cedar: { Statement: `permit(principal is AgentCore::IamEntity, action, resource == AgentCore::Gateway::"${gatewayArn}");` },
        },
      },
    });
    defaultPermitPolicy.node.addDependency(policyEngine);

    NagSuppressions.addStackSuppressions(this, [
      { id: "AwsSolutions-IAM5", reason: "Gateway and custom resource policies use CDK-managed wildcard resources" },
      { id: "AwsSolutions-IAM4", reason: "Custom resource Lambda uses AWS managed execution role policy" },
      { id: "AwsSolutions-L1", reason: "Custom resource Lambda runtime is managed by CDK" },
      { id: "AwsSolutions-SF1", reason: "Provider Framework state machine logging not required" },
      { id: "AwsSolutions-SF2", reason: "Provider Framework state machine X-Ray not required" },
    ], true);
  }
}
