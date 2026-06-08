import * as fs from "fs";
import * as path from "path";

import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as iam from "aws-cdk-lib/aws-iam";
import * as cr from "aws-cdk-lib/custom-resources";
import { NagSuppressions } from "cdk-nag";
import { Construct } from "constructs";

import { CodingAssistant } from "../constructs/runtime/coding-assistant";
import { RuntimeObservability } from "../constructs/observability/runtime-observability";
import { S3FilesStorage } from "../constructs/storage/s3-files";
import { SessionsTable } from "../constructs/storage/sessions-table";
import { SdlcConfig, getAssistantDir } from "../config";

const DEFAULT_MODEL = "global.anthropic.claude-opus-4-7";

export interface AssistantStackProps extends cdk.StackProps {
  config: SdlcConfig;
  vpc: ec2.IVpc;
  securityGroup: ec2.ISecurityGroup;
  fileSystemSecurityGroup: ec2.ISecurityGroup;
  gatewayId?: string;
  gatewayUrl?: string;
  privateKeySecretArn?: string;
}

export class AssistantStack extends cdk.Stack {
  public readonly assistant: CodingAssistant;
  public readonly setupLambdaRoleArn: string;
  public readonly pipelineLambdaRoleArn: string;

  constructor(scope: Construct, id: string, props: AssistantStackProps) {
    super(scope, id, props);

    const { config, vpc, securityGroup, fileSystemSecurityGroup } = props;
    const resolvedGatewayUrl = props.gatewayUrl!;

    // S3 Files storage (bucket, filesystem, mount targets, access point, plugins, proxy deps)
    const isByoGateway = !!config.gateway?.url;
    const storage = new S3FilesStorage(this, "Storage", {
      vpc,
      fileSystemSecurityGroup,
      pluginsPath: `./coding-assistants/${getAssistantDir(config)}/plugin`,
      gatewayProxyPath: isByoGateway ? undefined : "./gateway/gateway-iam-proxy",
      region: config.region,
    });

    // DynamoDB sessions table for observability
    const sessionsTable = new SessionsTable(this, "SessionsTable", {
      project: config.project,
    });

    // Coding Assistant Runtime (depends on storage for mount targets to be available).
    // The runtime image runs an ADOT collector sidecar on 127.0.0.1:4318 that
    // SigV4-signs OTLP traffic and forwards to xray.<region>.amazonaws.com /
    // logs.<region>.amazonaws.com (AgentCore Observability). These env vars
    // tell Claude Code's native OTel SDK to send to the local collector.
    // Metrics are disabled — AgentCore expects EMF on a different port and
    // we haven't built that bridge yet.
    this.assistant = new CodingAssistant(this, "CodingAssistant", {
      name: `${config.project}_${config.codingAssistant.type.replace(/-/g, "_")}`,
      codePath: `./coding-assistants/${getAssistantDir(config)}/runtime`,
      vpc,
      securityGroup,
      sessionStorageMountPath: config.codingAssistant.sessionStorageMountPath || "/mnt/workplace",
      s3FilesAccessPointArn: storage.accessPointArn,
      s3FilesMountPath: "/mnt/plugins",
      idleTimeout: config.codingAssistant.idleTimeout,
      maxLifetime: config.codingAssistant.maxLifetime,
      environmentVariables: {
        OTEL_EXPORTER_OTLP_ENDPOINT: "http://127.0.0.1:4318",
        OTEL_EXPORTER_OTLP_PROTOCOL: "http/protobuf",
        OTEL_TRACES_EXPORTER: "otlp",
        OTEL_LOGS_EXPORTER: "otlp",
        OTEL_METRICS_EXPORTER: "none",
        OTEL_PROPAGATORS: "tracecontext,baggage",
        SDLC_LABEL_PREFIX: config.projectManagement.github?.labelPrefix || "agent",
      },
    });
    this.assistant.node.addDependency(storage);

    // CloudWatch application logs + X-Ray traces observability
    new RuntimeObservability(this, "Observability", {
      runtimeArn: this.assistant.runtimeArn,
      runtimeId: this.assistant.runtimeId,
      logRetentionDays: 30,
    });

    // Grant gateway invoke
    this.assistant.executionRole.addToPrincipalPolicy(new iam.PolicyStatement({
      actions: ["bedrock-agentcore:InvokeGateway"],
      resources: [`arn:aws:bedrock-agentcore:${this.region}:${this.account}:gateway/*`],
    }));

    // Write plugins/settings.json to S3 with codingAssistant.model substituted
    // into the {{MODEL}} placeholder. The static plugin/settings.json carries
    // the placeholder; this custom resource is the sole writer of the rendered
    // file (the plugins BucketDeployment excludes settings.json).
    //
    // Only claude-code ships a settings.json — Kiro and Codex use their own
    // config formats and ignore this file, so skip the resource for them.
    //
    // Ordering: depend on the plugins BucketDeployment so the directory shape
    // is in place before we put, and force the runtime to wait on this resource
    // so a cold-start session never mounts an unsubstituted file.
    if (config.codingAssistant.type === "claude-code") {
      const pluginDir = `./coding-assistants/${getAssistantDir(config)}/plugin`;
      const settingsTemplate = fs.readFileSync(
        path.join(pluginDir, "settings.json"),
        "utf-8",
      );
      const resolvedModel = config.codingAssistant.model ?? DEFAULT_MODEL;
      const resolvedSettings = settingsTemplate.replace("{{MODEL}}", resolvedModel);

      const resolveSettingsJson = new cr.AwsCustomResource(this, "ResolveSettingsJson", {
        onUpdate: {
          service: "S3",
          action: "putObject",
          parameters: {
            Bucket: storage.bucket.bucketName,
            Key: "plugins/settings.json",
            Body: resolvedSettings,
            ContentType: "application/json",
          },
          physicalResourceId: cr.PhysicalResourceId.of(`settings-json-${Date.now()}`),
        },
        policy: cr.AwsCustomResourcePolicy.fromStatements([
          new iam.PolicyStatement({
            actions: ["s3:PutObject"],
            resources: [`${storage.bucket.bucketArn}/plugins/settings.json`],
          }),
        ]),
      });
      resolveSettingsJson.node.addDependency(storage.pluginsDeployment);
      this.assistant.node.addDependency(resolveSettingsJson);
    }

    // Write .mcp.json to S3 (gateway proxy config)
    new cr.AwsCustomResource(this, "ResolveMcpJson", {
      onUpdate: {
        service: "S3",
        action: "putObject",
        parameters: {
          Bucket: storage.bucket.bucketName,
          Key: "plugins/.mcp.json",
          Body: JSON.stringify({
            mcpServers: {
              gateway: {
                type: "stdio",
                command: "node",
                args: [
                  "/mnt/plugins/gateway-iam-proxy/index.js",
                  "--gateway-url", resolvedGatewayUrl,
                  "--region", config.region,
                ],
              },
            },
          }, null, 2),
          ContentType: "application/json",
        },
        physicalResourceId: cr.PhysicalResourceId.of(`mcp-json-${Date.now()}`),
      },
      policy: cr.AwsCustomResourcePolicy.fromStatements([
        new iam.PolicyStatement({
          actions: ["s3:PutObject"],
          resources: [`${storage.bucket.bucketArn}/plugins/.mcp.json`],
        }),
      ]),
    });

    // Targets auto-sync on creation (DEFAULT listing mode).
    // Manual sync via CLI: aws bedrock-agentcore-control synchronize-gateway-targets

    // Step Functions + Lambdas
    // Bundle both connector/lambda and shared/ into the Lambda package
    const pmDir = path.resolve("./project-management");
    const lambdaCode = cdk.aws_lambda.Code.fromAsset(pmDir, {
      bundling: {
        image: cdk.aws_lambda.Runtime.PYTHON_3_12.bundlingImage,
        command: ["bash", "-c", "echo unused"],
        local: {
          tryBundle(outputDir: string) {
            const { execSync } = require("child_process");
            const lambdaDir = path.join(pmDir, "github/connector/lambda");
            const sharedDir = path.join(pmDir, "shared");

            // Copy Lambda handler files
            for (const f of fs.readdirSync(lambdaDir)) {
              fs.cpSync(path.join(lambdaDir, f), path.join(outputDir, f), { recursive: true });
            }
            // Copy shared modules
            fs.cpSync(path.join(sharedDir, "assistants"), path.join(outputDir, "assistants"), { recursive: true });
            fs.cpSync(path.join(sharedDir, "pipeline.py"), path.join(outputDir, "pipeline.py"));
            fs.cpSync(path.join(sharedDir, "invoke_pipeline.py"), path.join(outputDir, "invoke_pipeline.py"));
            fs.cpSync(path.join(sharedDir, "log.py"), path.join(outputDir, "log.py"));
            fs.cpSync(path.join(sharedDir, "errors.py"), path.join(outputDir, "errors.py"));
            // Install pip dependencies for Lambda target platform
            const reqFile = path.join(lambdaDir, "requirements.txt");
            execSync(`pip install -r "${reqFile}" -t "${outputDir}/" --quiet --platform manylinux2014_x86_64 --implementation cp --python-version 3.12 --only-binary=:all:`);
            return true;
          },
        },
      },
    });

    const setupLambda = new cdk.aws_lambda.Function(this, "SetupLambda", {
      runtime: cdk.aws_lambda.Runtime.PYTHON_3_12,
      handler: "index.handler",
      timeout: cdk.Duration.minutes(5),
      memorySize: 256,
      environment: {
        AGENT_RUNTIME_ARN: this.assistant.runtimeArn,
        ASSISTANT_TYPE: config.codingAssistant.type,
        PRIVATE_REPO: config.sourceControl.github?.privateRepo ? "true" : "false",
        AWS_REGION_NAME: config.region,
        ALLOWED_USERS: JSON.stringify(config.projectManagement.github?.allowedUsers || []),
        ALLOWED_REPOS: JSON.stringify(config.sourceControl.github?.allowedRepos || []),
        SDLC_LABEL_PREFIX: config.projectManagement.github?.labelPrefix || "agent",
        SESSIONS_TABLE_NAME: sessionsTable.table.tableName,
        ...(config.sourceControl.github?.privateRepo && {
          GITHUB_APP_CLIENT_ID: config.sourceControl.github.appClientId,
          GITHUB_INSTALLATION_ID: config.sourceControl.github.installationId,
          PRIVATE_KEY_SECRET_ARN: props.privateKeySecretArn || "",
        }),
      },
      code: lambdaCode,
    });

    setupLambda.addToRolePolicy(new iam.PolicyStatement({
      actions: [
        "bedrock-agentcore:InvokeAgentRuntime",
        "bedrock-agentcore:InvokeAgentRuntimeCommand",
        // Stop the prior microVM at the start of every Setup Lambda invocation
        // to refresh the session's 40-minute maxLifetime budget. Session ID
        // stays valid; persistent state on /mnt/workplace/ survives.
        "bedrock-agentcore:StopRuntimeSession",
      ],
      resources: [this.assistant.runtimeArn, `${this.assistant.runtimeArn}/runtime-endpoint/*`],
    }));

    if (props.privateKeySecretArn) {
      setupLambda.addToRolePolicy(new iam.PolicyStatement({
        actions: ["secretsmanager:GetSecretValue"],
        resources: [props.privateKeySecretArn],
      }));
    }

    // Grant DynamoDB access for session tracking
    sessionsTable.table.grantReadWriteData(setupLambda);

    const pipelineLambda = new cdk.aws_lambda.Function(this, "PipelineLambda", {
      runtime: cdk.aws_lambda.Runtime.PYTHON_3_12,
      handler: "invoke_pipeline.handler",
      timeout: cdk.Duration.minutes(15),
      memorySize: 256,
      environment: {
        AGENT_RUNTIME_ARN: this.assistant.runtimeArn,
        ASSISTANT_TYPE: config.codingAssistant.type,
        AWS_REGION_NAME: config.region,
      },
      code: lambdaCode,
    });

    pipelineLambda.addToRolePolicy(new iam.PolicyStatement({
      actions: ["bedrock-agentcore:InvokeAgentRuntime", "bedrock-agentcore:InvokeAgentRuntimeCommand"],
      resources: [this.assistant.runtimeArn, `${this.assistant.runtimeArn}/runtime-endpoint/*`],
    }));

    this.setupLambdaRoleArn = setupLambda.role!.roleArn;
    this.pipelineLambdaRoleArn = pipelineLambda.role!.roleArn;

    const setupTask = new cdk.aws_stepfunctions_tasks.LambdaInvoke(this, "SetupTask", {
      lambdaFunction: setupLambda,
      outputPath: "$.Payload",
    });

    const pipelineTask = new cdk.aws_stepfunctions_tasks.LambdaInvoke(this, "PipelineTask", {
      lambdaFunction: pipelineLambda,
      outputPath: "$.Payload",
    });

    const stateMachine = new cdk.aws_stepfunctions.StateMachine(this, "SdlcPipeline", {
      stateMachineName: `${config.project}_sdlc_pipeline`,
      definitionBody: cdk.aws_stepfunctions.DefinitionBody.fromChainable(setupTask.next(pipelineTask)),
      timeout: cdk.Duration.minutes(45),
    });

    // GitHub Actions OIDC role
    if (config.projectManagement.type === "github") {
      const oidcProvider = iam.OpenIdConnectProvider.fromOpenIdConnectProviderArn(
        this, "GitHubOidc",
        `arn:aws:iam::${this.account}:oidc-provider/token.actions.githubusercontent.com`,
      );

      const allowedRepos = config.sourceControl.github?.allowedRepos;
      if (!allowedRepos || allowedRepos.length === 0) {
        throw new Error(
          "sourceControl.github.allowedRepos is required. " +
          "List the repos that can trigger the pipeline (e.g., ['myorg/repo-a', 'myorg/repo-b']).",
        );
      }
      const subConditions = allowedRepos.map(r => `repo:${r}:*`);

      const ghActionsRole = new iam.Role(this, "GitHubActionsRole", {
        assumedBy: new iam.FederatedPrincipal(
          oidcProvider.openIdConnectProviderArn,
          {
            StringEquals: { "token.actions.githubusercontent.com:aud": "sts.amazonaws.com" },
            StringLike: { "token.actions.githubusercontent.com:sub": subConditions },
          },
          "sts:AssumeRoleWithWebIdentity",
        ),
      });

      ghActionsRole.addToPolicy(new iam.PolicyStatement({
        actions: ["states:StartExecution"],
        resources: [stateMachine.stateMachineArn],
      }));

      new cdk.CfnOutput(this, "StateMachineArn", { value: stateMachine.stateMachineArn });
      new cdk.CfnOutput(this, "GitHubActionsRoleArn", { value: ghActionsRole.roleArn });
    }

    // Outputs for session tracking
    new cdk.CfnOutput(this, "SessionsTableName", { value: sessionsTable.table.tableName });
    new cdk.CfnOutput(this, "SessionsTableArn", { value: sessionsTable.table.tableArn });

    NagSuppressions.addStackSuppressions(this, [
      { id: "AwsSolutions-IAM5", reason: "Lambda and custom resources use CDK-managed wildcard policies" },
      { id: "AwsSolutions-IAM4", reason: "Lambda execution roles use AWS managed policies" },
      { id: "AwsSolutions-L1", reason: "Lambda runtimes are managed by CDK" },
      { id: "AwsSolutions-SF1", reason: "Step Functions logging not required for MVP" },
      { id: "AwsSolutions-SF2", reason: "Step Functions X-Ray not required for MVP" },
      { id: "AwsSolutions-CB4", reason: "CodeBuild encryption not required for proxy deps" },
    ], true);
  }
}
