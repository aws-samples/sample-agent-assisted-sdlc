import * as cdk from "aws-cdk-lib";
import * as iam from "aws-cdk-lib/aws-iam";
import * as cr from "aws-cdk-lib/custom-resources";
import { Construct } from "constructs";
import { NagSuppressions } from "cdk-nag";

import { SdlcConfig } from "../config";

export interface AgentCorePolicyStackProps extends cdk.StackProps {
  config: SdlcConfig;
  gatewayArn: string;
  gatewayId: string;
  gatewayName: string;
  gatewayRoleArn: string;
  gatewayAuthorizerType: string;
}

export class AgentCorePolicyStack extends cdk.Stack {
  public readonly policyEngineId: string;

  constructor(scope: Construct, id: string, props: AgentCorePolicyStackProps) {
    super(scope, id, props);

    const { config, gatewayArn, gatewayId, gatewayName, gatewayRoleArn, gatewayAuthorizerType } = props;

    // Create PolicyEngine
    const policyEngine = new cdk.CfnResource(this, "PolicyEngine", {
      type: "AWS::BedrockAgentCore::PolicyEngine",
      properties: {
        Name: config.project.replace(/-/g, "_") + "_cedar_engine",
      },
    });
    this.policyEngineId = policyEngine.getAtt("PolicyEngineId").toString();

    // Attach PolicyEngine to Gateway via UpdateGateway
    // updateGateway is a full-replace API — all required fields must be passed
    const policyEngineArn = policyEngine.getAtt("PolicyEngineArn").toString();
    const updateGateway = new cr.AwsCustomResource(this, "AttachPolicyEngine", {
      installLatestAwsSdk: true,
      onCreate: {
        service: "bedrock-agentcore-control",
        action: "updateGateway",
        parameters: {
          gatewayIdentifier: gatewayId,
          name: gatewayName,
          roleArn: gatewayRoleArn,
          authorizerType: gatewayAuthorizerType,
          protocolConfiguration: {
            mcp: {
              supportedVersions: ["2025-11-25"],
            },
          },
          policyEngineConfiguration: {
            arn: policyEngineArn,
            mode: "ENFORCE",
          },
        },
        physicalResourceId: cr.PhysicalResourceId.of(`policy-engine-attachment-${gatewayId}`),
      },
      onUpdate: {
        service: "bedrock-agentcore-control",
        action: "updateGateway",
        parameters: {
          gatewayIdentifier: gatewayId,
          name: gatewayName,
          roleArn: gatewayRoleArn,
          authorizerType: gatewayAuthorizerType,
          protocolConfiguration: {
            mcp: {
              supportedVersions: ["2025-11-25"],
            },
          },
          policyEngineConfiguration: {
            arn: policyEngineArn,
            mode: "ENFORCE",
          },
        },
        physicalResourceId: cr.PhysicalResourceId.of(`policy-engine-attachment-${gatewayId}`),
      },
      onDelete: {
        service: "bedrock-agentcore-control",
        action: "updateGateway",
        parameters: {
          gatewayIdentifier: gatewayId,
          name: gatewayName,
          roleArn: gatewayRoleArn,
          authorizerType: gatewayAuthorizerType,
          protocolConfiguration: {
            mcp: {
              supportedVersions: ["2025-11-25"],
            },
          },
        },
        ignoreErrorCodesMatching: "ResourceNotFoundException",
      },
      policy: cr.AwsCustomResourcePolicy.fromStatements([
        new iam.PolicyStatement({
          actions: ["bedrock-agentcore:UpdateGateway", "bedrock-agentcore:GetGateway"],
          resources: ["*"],
        }),
        new iam.PolicyStatement({
          actions: ["iam:PassRole"],
          resources: [gatewayRoleArn],
        }),
      ]),
    });
    updateGateway.node.addDependency(policyEngine);

    // Extract label prefix from config
    const labelPrefix = config.projectManagement.github?.labelPrefix || "agent";

    // Helper to sanitize project name for Cedar policy names (no hyphens, max 48 chars)
    const sanitizeName = (name: string) => name.replace(/-/g, "_").substring(0, 30);
    const projectPrefix = sanitizeName(config.project);

    // Policy 1: Branch protection (forbid main/master)
    const branchProtectionPolicy = new cdk.CfnResource(this, "BranchProtectionPolicy", {
      type: "AWS::BedrockAgentCore::Policy",
      properties: {
        Name: `${projectPrefix}_branch_protect`,
        PolicyEngineId: this.policyEngineId,
        Definition: {
          Cedar: { Statement: `
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
`.trim() },
        },
      },
    });
    branchProtectionPolicy.node.addDependency(updateGateway);

    // Policy 2: Branch pattern enforcement (permit only feat/issue-*)
    const branchPatternPolicy = new cdk.CfnResource(this, "BranchPatternPolicy", {
      type: "AWS::BedrockAgentCore::Policy",
      properties: {
        Name: `${projectPrefix}_branch_pattern`,
        PolicyEngineId: this.policyEngineId,
        Definition: {
          Cedar: { Statement: `
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
`.trim() },
        },
      },
    });
    branchPatternPolicy.node.addDependency(updateGateway);

    // Policy 3: Label governance (forbid {prefix}:start)
    const labelGovernancePolicy = new cdk.CfnResource(this, "LabelGovernancePolicy", {
      type: "AWS::BedrockAgentCore::Policy",
      properties: {
        Name: `${projectPrefix}_label_gov`,
        PolicyEngineId: this.policyEngineId,
        Definition: {
          Cedar: { Statement: `
forbid(
  principal is AgentCore::IamEntity,
  action == AgentCore::Action::"project-management___issue_write",
  resource == AgentCore::Gateway::"${gatewayArn}"
)
when {
  context.input has labels &&
  context.input.labels.contains("${labelPrefix}:start")
};
`.trim() },
        },
      },
    });
    labelGovernancePolicy.node.addDependency(updateGateway);

    // Policy 4: Default permit for authenticated callers
    const defaultPermitPolicy = new cdk.CfnResource(this, "DefaultPermitPolicy", {
      type: "AWS::BedrockAgentCore::Policy",
      properties: {
        Name: `${projectPrefix}_default_permit`,
        PolicyEngineId: this.policyEngineId,
        Definition: {
          Cedar: { Statement: `
permit(
  principal is AgentCore::IamEntity,
  action,
  resource == AgentCore::Gateway::"${gatewayArn}"
);
`.trim() },
        },
      },
    });
    defaultPermitPolicy.node.addDependency(updateGateway);

    NagSuppressions.addStackSuppressions(this, [
      { id: "AwsSolutions-IAM5", reason: "UpdateGateway custom resource uses wildcard resources for gateway API calls" },
      { id: "AwsSolutions-IAM4", reason: "Custom resource Lambda uses AWS managed execution role policy" },
      { id: "AwsSolutions-L1", reason: "Custom resource Lambda runtime is managed by CDK" },
      { id: "AwsSolutions-SF1", reason: "Provider Framework state machine logging not required" },
      { id: "AwsSolutions-SF2", reason: "Provider Framework state machine X-Ray not required" },
    ], true);
  }
}
