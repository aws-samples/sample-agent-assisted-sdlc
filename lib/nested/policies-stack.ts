import * as cdk from "aws-cdk-lib";
import * as iam from "aws-cdk-lib/aws-iam";
import { Construct } from "constructs";

import * as lambda from "aws-cdk-lib/aws-lambda";
import { SdlcConfig, ResourcePolicyStatement } from "../config";

export interface PoliciesStackProps extends cdk.StackProps {
  config: SdlcConfig;
  codingAssistantRuntimeArn: string;
  codingAssistantExecutionRoleArn: string;
  gatewayArn: string;
  gatewayRoleArn: string;
  mcpServerRuntimeArns: string[];
  mcpServerExecutionRoleArns: string[];
  setupLambdaRoleArn: string;
  pipelineLambdaRoleArn: string;
  tokenLambdaArn?: string;
}

function buildPolicy(
  resourceArn: string,
  defaultStatements: Record<string, unknown>[],
  customStatements?: ResourcePolicyStatement[],
): string {
  const statements = [...defaultStatements];
  if (customStatements) {
    for (const s of customStatements) {
      statements.push({
        Effect: "Allow",
        Principal: { AWS: Array.isArray(s.principal) ? s.principal : [s.principal] },
        Action: Array.isArray(s.action) ? s.action : [s.action],
        Resource: resourceArn,
      });
    }
  }
  return JSON.stringify({ Version: "2012-10-17", Statement: statements });
}

export class PoliciesStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: PoliciesStackProps) {
    super(scope, id, props);

    const { config } = props;
    const customPolicies = config.resourcePolicies;

    const assistantActions = [
      "bedrock-agentcore:InvokeAgentRuntime",
      // TODO: add when supported in resource policies
      // "bedrock-agentcore:InvokeAgentRuntimeCommand",
      // "bedrock-agentcore:InvokeAgentRuntimeCommandShell",
      "bedrock-agentcore:StopRuntimeSession",
    ];

    // 1a. Coding Assistant Runtime policy
    const assistantPolicy = buildPolicy(
      props.codingAssistantRuntimeArn,
      [{
        Sid: "AllowLambdaInvoke",
        Effect: "Allow",
        Principal: { AWS: [props.setupLambdaRoleArn, props.pipelineLambdaRoleArn] },
        Action: assistantActions,
        Resource: props.codingAssistantRuntimeArn,
      }],
      customPolicies?.codingAssistant,
    );

    new cdk.CfnResource(this, "CodingAssistantPolicy", {
      type: "AWS::BedrockAgentCore::ResourcePolicy",
      properties: {
        Policy: assistantPolicy,
        ResourceArn: props.codingAssistantRuntimeArn,
      },
    });

    // 1b. Coding Assistant Endpoint policy (separate resource ARN)
    const assistantEndpointArn = `${props.codingAssistantRuntimeArn}/runtime-endpoint/DEFAULT`;
    const assistantEndpointPolicy = buildPolicy(
      assistantEndpointArn,
      [{
        Sid: "AllowLambdaInvokeEndpoint",
        Effect: "Allow",
        Principal: { AWS: [props.setupLambdaRoleArn, props.pipelineLambdaRoleArn] },
        Action: assistantActions,
        Resource: assistantEndpointArn,
      }],
    );

    new cdk.CfnResource(this, "CodingAssistantEndpointPolicy", {
      type: "AWS::BedrockAgentCore::ResourcePolicy",
      properties: {
        Policy: assistantEndpointPolicy,
        ResourceArn: assistantEndpointArn,
      },
    });

    // 2. Gateway — only invokable by coding assistant execution role
    const gatewayPolicy = buildPolicy(
      props.gatewayArn,
      [{
        Sid: "AllowAssistantInvoke",
        Effect: "Allow",
        Principal: { AWS: [props.codingAssistantExecutionRoleArn] },
        Action: "bedrock-agentcore:InvokeGateway",
        Resource: props.gatewayArn,
      }],
      customPolicies?.gateway,
    );

    new cdk.CfnResource(this, "GatewayPolicy", {
      type: "AWS::BedrockAgentCore::ResourcePolicy",
      properties: {
        Policy: gatewayPolicy,
        ResourceArn: props.gatewayArn,
      },
    });

    // 3. MCP Server Runtimes — only invokable by gateway role
    const mcpActions = [
      "bedrock-agentcore:InvokeAgentRuntime",
      // TODO: add when supported in resource policies
      // "bedrock-agentcore:InvokeAgentRuntimeCommand",
      // "bedrock-agentcore:InvokeAgentRuntimeCommandShell",
      "bedrock-agentcore:StopRuntimeSession",
    ];

    for (const [i, runtimeArn] of props.mcpServerRuntimeArns.entries()) {
      // 3a. Runtime policy
      const mcpPolicy = buildPolicy(
        runtimeArn,
        [{
          Sid: "AllowGatewayInvoke",
          Effect: "Allow",
          Principal: { AWS: [props.gatewayRoleArn] },
          Action: mcpActions,
          Resource: runtimeArn,
        }],
        customPolicies?.mcpServers,
      );

      new cdk.CfnResource(this, `McpServerPolicy${i}`, {
        type: "AWS::BedrockAgentCore::ResourcePolicy",
        properties: {
          Policy: mcpPolicy,
          ResourceArn: runtimeArn,
        },
      });

      // 3b. Endpoint policy
      const mcpEndpointArn = `${runtimeArn}/runtime-endpoint/DEFAULT`;
      const mcpEndpointPolicy = buildPolicy(
        mcpEndpointArn,
        [{
          Sid: "AllowGatewayInvokeEndpoint",
          Effect: "Allow",
          Principal: { AWS: [props.gatewayRoleArn] },
          Action: mcpActions,
          Resource: mcpEndpointArn,
        }],
      );

      new cdk.CfnResource(this, `McpServerEndpointPolicy${i}`, {
        type: "AWS::BedrockAgentCore::ResourcePolicy",
        properties: {
          Policy: mcpEndpointPolicy,
          ResourceArn: mcpEndpointArn,
        },
      });
    }

    // 4. Token Lambda — only invokable by MCP server roles + Setup Lambda
    if (props.tokenLambdaArn) {
      const tokenFn = lambda.Function.fromFunctionAttributes(this, "TokenFunction", {
        functionArn: props.tokenLambdaArn,
        sameEnvironment: true,
      });
      const allowedPrincipals = [
        ...props.mcpServerExecutionRoleArns,
        props.setupLambdaRoleArn,
      ];
      for (const [i, principalArn] of allowedPrincipals.entries()) {
        tokenFn.addPermission(`AllowInvoke${i}`, {
          principal: new iam.ArnPrincipal(principalArn),
          action: "lambda:InvokeFunction",
        });
      }
    }
  }
}
