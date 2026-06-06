import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as cr from "aws-cdk-lib/custom-resources";
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

    // 4. Inline Lambda: attach PolicyEngine to gateway + wait for READY
    const attachFnRole = new iam.Role(this, "AttachEngineFnRole", {
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      managedPolicies: [iam.ManagedPolicy.fromAwsManagedPolicyName("service-role/AWSLambdaBasicExecutionRole")],
    });
    attachFnRole.addToPolicy(new iam.PolicyStatement({
      actions: ["bedrock-agentcore:UpdateGateway", "bedrock-agentcore:GetGateway"],
      resources: ["*"],
    }));
    attachFnRole.addToPolicy(new iam.PolicyStatement({
      actions: ["iam:PassRole"],
      resources: [this.gateway.gatewayRole.roleArn],
    }));

    const attachFn = new lambda.Function(this, "AttachEngineFn", {
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: "index.handler",
      timeout: cdk.Duration.minutes(5),
      role: attachFnRole,
      code: lambda.Code.fromInline(`
import json, os, time, urllib.request

def send_response(event, context, status, data=None, reason=None):
    body = json.dumps({
        "Status": status,
        "Reason": reason or f"See CloudWatch: {context.log_stream_name}",
        "PhysicalResourceId": event.get("PhysicalResourceId", context.log_stream_name),
        "StackId": event["StackId"],
        "RequestId": event["RequestId"],
        "LogicalResourceId": event["LogicalResourceId"],
        "Data": data or {},
    }).encode()
    req = urllib.request.Request(event["ResponseURL"], data=body, method="PUT")
    req.add_header("Content-Type", "")
    urllib.request.urlopen(req)

def signed_request(method, url, body=None):
    """Make a SigV4-signed HTTP request to AgentCore control plane."""
    import botocore.session
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest
    session = botocore.session.get_session()
    creds = session.get_credentials().get_frozen_credentials()
    headers = {"Content-Type": "application/json"}
    req = AWSRequest(method=method, url=url, data=body, headers=headers)
    SigV4Auth(creds, "bedrock-agentcore", session.get_config_variable("region") or "us-west-2").add_auth(req)
    http_req = urllib.request.Request(url, data=body.encode() if body else None, method=method)
    for k, v in dict(req.headers).items():
        http_req.add_header(k, v)
    resp = urllib.request.urlopen(http_req)
    return json.loads(resp.read())

def handler(event, context):
    print(json.dumps(event))
    props = event["ResourceProperties"]
    request_type = event["RequestType"]
    region = os.environ.get("AWS_REGION", "us-west-2")
    base = f"https://bedrock-agentcore-control.{region}.amazonaws.com"
    gw_id = props["GatewayId"]
    try:
        if request_type in ("Create", "Update"):
            body = json.dumps({
                "name": props["GatewayName"],
                "roleArn": props["GatewayRoleArn"],
                "authorizerType": props["AuthorizerType"],
                "policyEngineConfiguration": {"arn": props["PolicyEngineArn"], "mode": "ENFORCE"},
            })
            signed_request("PUT", f"{base}/gateways/{gw_id}/", body)
            for _ in range(30):
                time.sleep(10)
                resp = signed_request("GET", f"{base}/gateways/{gw_id}/")
                print(f"Gateway status: {resp.get('status')}")
                if resp.get("status") == "READY":
                    send_response(event, context, "SUCCESS")
                    return
            send_response(event, context, "FAILED", reason="Gateway not READY in 5 min")
        elif request_type == "Delete":
            try:
                body = json.dumps({
                    "name": props["GatewayName"],
                    "roleArn": props["GatewayRoleArn"],
                    "authorizerType": props["AuthorizerType"],
                })
                signed_request("PUT", f"{base}/gateways/{gw_id}/", body)
            except Exception as e:
                print(f"Detach failed (non-fatal): {e}")
            send_response(event, context, "SUCCESS")
    except Exception as e:
        print(f"Error: {e}")
        send_response(event, context, "FAILED", reason=str(e))
`),
    });

    const attachPolicyEngine = new cdk.CustomResource(this, "AttachPolicyEngine", {
      serviceToken: attachFn.functionArn,
      properties: {
        GatewayId: this.gateway.gatewayId,
        GatewayName: `${config.project}-gateway`,
        GatewayRoleArn: this.gateway.gatewayRole.roleArn,
        AuthorizerType: config.gateway?.authorizerType || "AWS_IAM",
        PolicyEngineArn: policyEngineArn,
      },
    });
    attachPolicyEngine.node.addDependency(policyEngine);

    // 6. Cedar policies (depend on gateway being READY with engine attached)
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
    branchProtectionPolicy.node.addDependency(attachPolicyEngine);

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
    branchPatternPolicy.node.addDependency(attachPolicyEngine);

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
    labelGovernancePolicy.node.addDependency(attachPolicyEngine);

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
    defaultPermitPolicy.node.addDependency(attachPolicyEngine);

    NagSuppressions.addStackSuppressions(this, [
      { id: "AwsSolutions-IAM5", reason: "Gateway and custom resource policies use CDK-managed wildcard resources" },
      { id: "AwsSolutions-IAM4", reason: "Custom resource Lambda uses AWS managed execution role policy" },
      { id: "AwsSolutions-L1", reason: "Custom resource Lambda runtime is managed by CDK" },
      { id: "AwsSolutions-SF1", reason: "Provider Framework state machine logging not required" },
      { id: "AwsSolutions-SF2", reason: "Provider Framework state machine X-Ray not required" },
    ], true);
  }
}
