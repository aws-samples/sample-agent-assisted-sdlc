import * as cdk from "aws-cdk-lib";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as cr from "aws-cdk-lib/custom-resources";
import { execSync } from "child_process";
import * as path from "path";
import { Construct } from "constructs";

export function buildRuntimeEndpoint(region: string, runtimeArn: string): string {
  const runtimeId = cdk.Fn.select(1, cdk.Fn.split("runtime/", runtimeArn));
  const encodedArn = cdk.Fn.join("", [
    "arn%3Aaws%3Abedrock-agentcore%3A",
    region,
    "%3A",
    cdk.Aws.ACCOUNT_ID,
    "%3Aruntime%2F",
    runtimeId,
  ]);
  return cdk.Fn.join("", [
    `https://bedrock-agentcore.${region}.amazonaws.com/runtimes/`,
    encodedArn,
    "/invocations",
  ]);
}

export interface GatewayTargetOptions {
  name: string;
  mcpServerEndpoint: string;
  resourcePriority?: number;
  credentialProviderType?: string;
  iamService?: string;
  allowedRequestHeaders?: string[];
  sourceHash?: string;
}

export function registerGatewayTarget(
  scope: Construct,
  id: string,
  gatewayId: string,
  props: GatewayTargetOptions,
): cr.AwsCustomResource {
  const credentialConfig = props.credentialProviderType === "GATEWAY_IAM_ROLE"
    ? [{
        credentialProviderType: "GATEWAY_IAM_ROLE",
        credentialProvider: {
          iamCredentialProvider: {
            service: props.iamService || "bedrock-agentcore",
          },
        },
      }]
    : undefined;

  const target = new cr.AwsCustomResource(scope, id, {
    installLatestAwsSdk: true,
    onCreate: {
      service: "bedrock-agentcore-control",
      action: "createGatewayTarget",
      parameters: {
        gatewayIdentifier: gatewayId,
        name: props.name,
        targetConfiguration: {
          mcp: {
            mcpServer: {
              endpoint: props.mcpServerEndpoint,
              ...(props.resourcePriority != null && { resourcePriority: props.resourcePriority }),
            },
          },
        },
        ...(credentialConfig && { credentialProviderConfigurations: credentialConfig }),
        ...(props.allowedRequestHeaders && {
          metadataConfiguration: {
            allowedRequestHeaders: props.allowedRequestHeaders,
          },
        }),
      },
      physicalResourceId: cr.PhysicalResourceId.fromResponse("targetId"),
    },
    onDelete: {
      service: "bedrock-agentcore-control",
      action: "deleteGatewayTarget",
      parameters: {
        gatewayIdentifier: gatewayId,
        targetId: new cr.PhysicalResourceIdReference(),
      },
      ignoreErrorCodesMatching: "ResourceNotFoundException|ValidationException",
    },
    policy: cr.AwsCustomResourcePolicy.fromStatements([
      new iam.PolicyStatement({
        actions: [
          "bedrock-agentcore:CreateGatewayTarget",
          "bedrock-agentcore:DeleteGatewayTarget",
          "bedrock-agentcore:GetGatewayTarget",
          "bedrock-agentcore:SynchronizeGatewayTargets",
        ],
        resources: ["*"],
      }),
    ]),
  });

  // Sync this target to fetch its tools (re-syncs when sourceHash changes)
  const syncId = props.sourceHash ? `${id}-sync-${props.sourceHash}` : `${id}-sync`;
  const sync = new cr.AwsCustomResource(scope, `${id}Sync`, {
    installLatestAwsSdk: true,
    onUpdate: {
      service: "bedrock-agentcore-control",
      action: "synchronizeGatewayTargets",
      parameters: {
        gatewayIdentifier: gatewayId,
        targetIdList: [target.getResponseField("targetId")],
      },
      physicalResourceId: cr.PhysicalResourceId.of(syncId),
    },
    policy: cr.AwsCustomResourcePolicy.fromStatements([
      new iam.PolicyStatement({
        actions: ["bedrock-agentcore:SynchronizeGatewayTargets"],
        resources: ["*"],
      }),
    ]),
  });

  // Wait for target to reach READY (fail deployment if target fails)
  const waiterLambdaPath = path.join(__dirname, "constructs/runtime/target-waiter-lambda");
  const waiterCode = lambda.Code.fromAsset(waiterLambdaPath, {
    bundling: {
      image: lambda.Runtime.NODEJS_20_X.bundlingImage,
      command: ["bash", "-c", "echo unused"],
      local: {
        tryBundle(outputDir: string) {
          execSync(`cp -r ${waiterLambdaPath}/* ${outputDir}/`);
          execSync("npm install --omit=dev", { cwd: outputDir, stdio: "inherit" });
          return true;
        },
      },
    },
  });

  const onEvent = new lambda.Function(scope, `${id}WaiterOnEvent`, {
    runtime: lambda.Runtime.NODEJS_20_X,
    handler: "index.onEvent",
    code: waiterCode,
    timeout: cdk.Duration.seconds(30),
  });
  onEvent.addToRolePolicy(new iam.PolicyStatement({
    actions: ["bedrock-agentcore:GetGatewayTarget"],
    resources: ["*"],
  }));

  const isComplete = new lambda.Function(scope, `${id}WaiterIsComplete`, {
    runtime: lambda.Runtime.NODEJS_20_X,
    handler: "index.isComplete",
    code: waiterCode,
    timeout: cdk.Duration.seconds(30),
  });
  isComplete.addToRolePolicy(new iam.PolicyStatement({
    actions: ["bedrock-agentcore:GetGatewayTarget"],
    resources: ["*"],
  }));

  const waiterProvider = new cr.Provider(scope, `${id}WaiterProvider`, {
    onEventHandler: onEvent,
    isCompleteHandler: isComplete,
    queryInterval: cdk.Duration.seconds(10),
    totalTimeout: cdk.Duration.minutes(10),
  });

  const waiter = new cdk.CustomResource(scope, `${id}WaitForReady`, {
    serviceToken: waiterProvider.serviceToken,
    properties: {
      GatewayId: gatewayId,
      TargetId: target.getResponseField("targetId"),
    },
  });
  waiter.node.addDependency(target);
  sync.node.addDependency(waiter);

  return target;
}
