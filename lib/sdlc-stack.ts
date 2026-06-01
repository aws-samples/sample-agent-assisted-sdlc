import * as cdk from "aws-cdk-lib";
import { Aspects } from "aws-cdk-lib";
import { AwsSolutionsChecks } from "cdk-nag";

import { InfrastructureStack } from "./nested/infrastructure-stack";
import { GatewayStack, McpTarget } from "./nested/gateway-stack";
import { SourceControlStack } from "./nested/source-control-stack";
import { ProjectManagementStack } from "./nested/project-management-stack";
import { DeveloperMcpStack } from "./nested/developer-mcp-stack";
import { AssistantStack } from "./nested/assistant-stack";
import { PoliciesStack } from "./nested/policies-stack";
import { SdlcConfig } from "./config";

export function createStacks(app: cdk.App, config: SdlcConfig) {
  if (!config.sourceControl) {
    throw new Error("sourceControl is required. Supported types: github");
  }
  if (!config.projectManagement) {
    throw new Error("projectManagement is required. Supported types: github, jira");
  }
  if (config.sourceControl.type === "github") {
    const ghConfig = config.sourceControl.github;
    if (!ghConfig?.appClientId || !ghConfig?.installationId || !ghConfig?.privateKeyPath) {
      throw new Error(
        "sourceControl.github requires appClientId, installationId, and privateKeyPath.",
      );
    }
  }

  const env = {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: config.region || process.env.CDK_DEFAULT_REGION,
  };

  const isByoGateway = !!config.gateway?.url;

  // ═══════════════════════════════════════════════
  // STACK 1: Infrastructure (VPC + Security Groups)
  // ═══════════════════════════════════════════════
  const infra = new InfrastructureStack(app, `${config.project}-infra`, { env, config });
  Aspects.of(infra).add(new AwsSolutionsChecks({ verbose: true }));

  if (isByoGateway) {
    const assistantStack = new AssistantStack(app, `${config.project}-assistant`, {
      env,
      config,
      vpc: infra.vpc,
      securityGroup: infra.agentRuntimeSecurityGroup,
      fileSystemSecurityGroup: infra.fileSystemSecurityGroup,
      gatewayUrl: config.gateway!.url,
    });
    assistantStack.addDependency(infra);
    Aspects.of(assistantStack).add(new AwsSolutionsChecks({ verbose: true }));
    return;
  }

  // ═══════════════════════════════════════════════
  // STACKS 2-4: MCP Server Runtimes (deploy in parallel after infra)
  // ═══════════════════════════════════════════════
  const targets: McpTarget[] = [];

  const sourceControlStack = new SourceControlStack(app, `${config.project}-source-control`, {
    env,
    config,
    vpc: infra.vpc,
    securityGroup: infra.agentRuntimeSecurityGroup,
  });
  sourceControlStack.addDependency(infra);
  Aspects.of(sourceControlStack).add(new AwsSolutionsChecks({ verbose: true }));
  targets.push({
    name: "github-code",
    runtimeArn: sourceControlStack.runtimeArn,
    imageTag: sourceControlStack.imageTag,
    resourcePriority: 5,
  });

  let lastMcpStack: cdk.Stack = sourceControlStack;
  let projectMgmtStack: ProjectManagementStack | undefined;

  if (config.projectManagement.type === "github") {
    projectMgmtStack = new ProjectManagementStack(app, `${config.project}-project-management`, {
      env,
      config,
      vpc: infra.vpc,
      securityGroup: infra.agentRuntimeSecurityGroup,
      privateKeySecretArn: sourceControlStack.privateKeySecretArn,
    });
    projectMgmtStack.addDependency(sourceControlStack);
    Aspects.of(projectMgmtStack).add(new AwsSolutionsChecks({ verbose: true }));
    targets.push({
      name: "github-issues",
      runtimeArn: projectMgmtStack.runtimeArn,
      imageTag: projectMgmtStack.imageTag,
      resourcePriority: 10,
    });
    lastMcpStack = projectMgmtStack;
  }

  const developerMcpServers = config.gateway?.developerMcpServers;
  if (developerMcpServers && developerMcpServers.length > 0) {
    const developerMcpStack = new DeveloperMcpStack(app, `${config.project}-developer-mcp`, {
      env,
      config,
      vpc: infra.vpc,
      securityGroup: infra.agentRuntimeSecurityGroup,
    });
    developerMcpStack.addDependency(infra);
    Aspects.of(developerMcpStack).add(new AwsSolutionsChecks({ verbose: true }));
    for (const [i, rt] of developerMcpStack.runtimes.entries()) {
      targets.push({
        name: rt.name,
        runtimeArn: rt.runtimeArn,
        imageTag: rt.imageTag,
        resourcePriority: 20 + i,
      });
    }
    lastMcpStack = developerMcpStack;
  }

  // ═══════════════════════════════════════════════
  // STACK 5: Gateway (creates gateway + registers all targets)
  // ═══════════════════════════════════════════════
  const gatewayStack = new GatewayStack(app, `${config.project}-gateway`, {
    env,
    config,
    vpc: infra.vpc,
    securityGroup: infra.agentRuntimeSecurityGroup,
    targets,
  });
  gatewayStack.addDependency(lastMcpStack);
  Aspects.of(gatewayStack).add(new AwsSolutionsChecks({ verbose: true }));

  // ═══════════════════════════════════════════════
  // STACK 6: Coding Assistant + Storage + Orchestration
  // ═══════════════════════════════════════════════
  const assistantStack = new AssistantStack(app, `${config.project}-assistant`, {
    env,
    config,
    vpc: infra.vpc,
    securityGroup: infra.agentRuntimeSecurityGroup,
    fileSystemSecurityGroup: infra.fileSystemSecurityGroup,
    gatewayId: gatewayStack.gatewayId,
    gatewayUrl: gatewayStack.gatewayUrl,
    privateKeySecretArn: sourceControlStack.privateKeySecretArn,
  });
  assistantStack.addDependency(gatewayStack);
  Aspects.of(assistantStack).add(new AwsSolutionsChecks({ verbose: true }));

  // ═══════════════════════════════════════════════
  // STACK 7: Resource-Based Policies (optional, production only)
  // ═══════════════════════════════════════════════
  if (config.resourcePolicies?.enabled) {
    const mcpExecutionRoleArns = [
      sourceControlStack.executionRoleArn,
      ...(config.projectManagement.type === "github" ? [projectMgmtStack!.executionRoleArn] : []),
    ];

    const policiesStack = new PoliciesStack(app, `${config.project}-policies`, {
      env,
      config,
      codingAssistantRuntimeArn: assistantStack.assistant.runtimeArn,
      codingAssistantExecutionRoleArn: assistantStack.assistant.executionRole.roleArn,
      gatewayArn: gatewayStack.gateway.gatewayArn,
      gatewayRoleArn: gatewayStack.gateway.gatewayRole.roleArn,
      mcpServerRuntimeArns: targets.map(t => t.runtimeArn),
      mcpServerExecutionRoleArns: mcpExecutionRoleArns,
      setupLambdaRoleArn: assistantStack.setupLambdaRoleArn,
      pipelineLambdaRoleArn: assistantStack.pipelineLambdaRoleArn,
      tokenLambdaArn: sourceControlStack.tokenLambdaArn,
    });
    policiesStack.addDependency(assistantStack);
    Aspects.of(policiesStack).add(new AwsSolutionsChecks({ verbose: true }));
  }
}
