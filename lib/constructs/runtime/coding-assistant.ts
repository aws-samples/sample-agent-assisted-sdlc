import * as cdk from "aws-cdk-lib";
import * as ecr from "aws-cdk-lib/aws-ecr";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as s3_assets from "aws-cdk-lib/aws-s3-assets";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as codebuild from "aws-cdk-lib/aws-codebuild";
import * as cr from "aws-cdk-lib/custom-resources";
import * as path from "path";
import { Construct } from "constructs";
import { NagSuppressions } from "cdk-nag";

export interface CodingAssistantProps {
  name: string;
  codePath: string;
  vpc: ec2.IVpc;
  securityGroup: ec2.ISecurityGroup;
  sessionStorageMountPath?: string;
  s3FilesAccessPointArn?: string;
  s3FilesMountPath?: string;
  environmentVariables?: Record<string, string>;
  idleTimeout?: number;
  maxLifetime?: number;
}

export class CodingAssistant extends Construct {
  public readonly runtimeArn: string;
  public readonly runtimeId: string;
  public readonly executionRole: iam.Role;

  constructor(scope: Construct, id: string, props: CodingAssistantProps) {
    super(scope, id);

    const stack = cdk.Stack.of(this);

    const repo = new ecr.Repository(this, "Repo", {
      repositoryName: `sdlc-assistant-${props.name}`,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      emptyOnDelete: true,
    });

    const sourceAsset = new s3_assets.Asset(this, "SourceAsset", {
      path: props.codePath,
      exclude: ["node_modules", ".venv", "__pycache__", "*.pyc"],
    });
    const imageTag = sourceAsset.assetHash.substring(0, 12);

    const buildProject = new codebuild.Project(this, "Build", {
      description: `Builds container image for coding assistant: ${props.name}`,
      environment: {
        buildImage: codebuild.LinuxArmBuildImage.AMAZON_LINUX_2_STANDARD_3_0,
        computeType: codebuild.ComputeType.MEDIUM,
        privileged: true,
      },
      environmentVariables: {
        REPO_URI: { value: repo.repositoryUri },
        IMAGE_TAG: { value: imageTag },
        AWS_ACCOUNT_ID: { value: stack.account },
        AWS_REGION: { value: stack.region },
      },
      buildSpec: codebuild.BuildSpec.fromObject({
        version: "0.2",
        phases: {
          pre_build: {
            commands: [
              "aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com",
            ],
          },
          build: {
            commands: [
              "docker build -t $REPO_URI:$IMAGE_TAG .",
              "docker push $REPO_URI:$IMAGE_TAG",
            ],
          },
        },
      }),
      source: codebuild.Source.s3({
        bucket: sourceAsset.bucket,
        path: sourceAsset.s3ObjectKey,
      }),
    });

    repo.grantPullPush(buildProject);
    sourceAsset.grantRead(buildProject);

    const buildWaiterCode = lambda.Code.fromAsset(path.join(__dirname, "build-waiter-lambda"));
    const buildWaiterPolicy = new iam.PolicyStatement({
      actions: ["codebuild:StartBuild", "codebuild:BatchGetBuilds"],
      resources: [buildProject.projectArn],
    });

    const onEvent = new lambda.Function(this, "BuildOnEvent", {
      runtime: lambda.Runtime.NODEJS_20_X,
      handler: "index.onEvent",
      code: buildWaiterCode,
      timeout: cdk.Duration.seconds(30),
    });
    onEvent.addToRolePolicy(buildWaiterPolicy);

    const isComplete = new lambda.Function(this, "BuildIsComplete", {
      runtime: lambda.Runtime.NODEJS_20_X,
      handler: "index.isComplete",
      code: buildWaiterCode,
      timeout: cdk.Duration.seconds(30),
    });
    isComplete.addToRolePolicy(buildWaiterPolicy);

    const buildProvider = new cr.Provider(this, "BuildProvider", {
      onEventHandler: onEvent,
      isCompleteHandler: isComplete,
      queryInterval: cdk.Duration.seconds(30),
      totalTimeout: cdk.Duration.minutes(30),
    });

    const buildWaiter = new cdk.CustomResource(this, "BuildAndWait", {
      serviceToken: buildProvider.serviceToken,
      properties: {
        ProjectName: buildProject.projectName,
        SourceHash: imageTag,
      },
    });

    NagSuppressions.addResourceSuppressions(buildProject, [
      { id: "AwsSolutions-CB4", reason: "Container image builds do not require KMS encryption" },
    ], true);

    this.executionRole = new iam.Role(this, "ExecutionRole", {
      assumedBy: new iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
    });

    this.executionRole.addToPolicy(new iam.PolicyStatement({
      actions: ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream", "bedrock:CountTokens"],
      resources: [
        `arn:aws:bedrock:*:${stack.account}:inference-profile/*`,
        "arn:aws:bedrock:*::foundation-model/*",
      ],
    }));

    this.executionRole.addToPolicy(new iam.PolicyStatement({
      actions: ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:DescribeLogStreams", "logs:FilterLogEvents", "logs:GetLogEvents", "logs:PutLogEvents"],
      resources: [`arn:aws:logs:${stack.region}:${stack.account}:log-group:/aws/bedrock-agentcore/runtimes/*`],
    }));

    this.executionRole.addToPolicy(new iam.PolicyStatement({
      actions: [
        "ecr:GetAuthorizationToken",
        "logs:DescribeLogGroups",
        "xray:PutTelemetryRecords",
        "xray:PutTraceSegments",
        // Required by the OTLP /v1/traces endpoint at xray.<region>.amazonaws.com,
        // which the in-container ADOT sidecar forwards Claude Code spans to.
        "xray:PutSpans",
      ],
      resources: ["*"],
    }));

    // Vended logs delivery permissions for AgentCore observability
    this.executionRole.addToPolicy(new iam.PolicyStatement({
      actions: ["bedrock-agentcore:AllowVendedLogDeliveryForResource"],
      resources: ["*"],
    }));

    this.executionRole.addToPolicy(new iam.PolicyStatement({
      actions: ["cloudwatch:PutMetricData"],
      resources: ["*"],
      conditions: {
        StringEquals: { "cloudwatch:namespace": "bedrock-agentcore" },
      },
    }));
    this.executionRole.addToPolicy(new iam.PolicyStatement({
      actions: ["ecr:BatchCheckLayerAvailability", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"],
      resources: [repo.repositoryArn],
    }));

    // S3 Files permissions (required when mounting S3 Files access points)
    if (props.s3FilesAccessPointArn) {
      this.executionRole.addToPolicy(new iam.PolicyStatement({
        actions: ["s3files:GetAccessPoint", "s3files:ClientMount", "s3files:ClientWrite", "s3files:ListMountTargets"],
        resources: [`arn:aws:s3files:${stack.region}:${stack.account}:file-system/*`],
      }));
    }

    // Filesystem configurations
    const filesystemConfigurations: Record<string, unknown>[] = [];
    if (props.sessionStorageMountPath) {
      filesystemConfigurations.push({ SessionStorage: { MountPath: props.sessionStorageMountPath } });
    }
    if (props.s3FilesAccessPointArn && props.s3FilesMountPath) {
      filesystemConfigurations.push({
        S3FilesAccessPoint: { AccessPointArn: props.s3FilesAccessPointArn, MountPath: props.s3FilesMountPath },
      });
    }

    const runtime = new cdk.CfnResource(this, "Runtime", {
      type: "AWS::BedrockAgentCore::Runtime",
      properties: {
        AgentRuntimeName: props.name.replace(/-/g, "_"),
        AgentRuntimeArtifact: {
          ContainerConfiguration: {
            ContainerUri: `${repo.repositoryUri}:${imageTag}`,
          },
        },
        RoleArn: this.executionRole.roleArn,
        NetworkConfiguration: {
          NetworkMode: "VPC",
          NetworkModeConfig: {
            Subnets: props.vpc.privateSubnets.map((s) => s.subnetId),
            SecurityGroups: [props.securityGroup.securityGroupId],
          },
        },
        ProtocolConfiguration: "HTTP",
        LifecycleConfiguration: {
          IdleRuntimeSessionTimeout: props.idleTimeout || 900,
          MaxLifetime: props.maxLifetime || 2400,
        },
        ...(filesystemConfigurations.length > 0 && { FilesystemConfigurations: filesystemConfigurations }),
        ...(props.environmentVariables && { EnvironmentVariables: props.environmentVariables }),
        Tags: { Project: "agent-assisted-sdlc", Component: "coding-assistant" },
      },
    });
    runtime.applyRemovalPolicy(cdk.RemovalPolicy.DESTROY);
    runtime.node.addDependency(buildWaiter);

    this.runtimeArn = runtime.getAtt("AgentRuntimeArn").toString();
    this.runtimeId = runtime.getAtt("AgentRuntimeId").toString();

    NagSuppressions.addResourceSuppressions(this.executionRole, [
      { id: "AwsSolutions-IAM5", reason: "Bedrock, ECR, CloudWatch, X-Ray require wildcard resources" },
    ], true);

    new cdk.CfnOutput(scope, "CodingAssistantRuntimeArn", { value: this.runtimeArn });
  }
}
