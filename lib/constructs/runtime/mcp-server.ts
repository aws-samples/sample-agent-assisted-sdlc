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

export interface McpServerProps {
  name: string;
  codePath: string;
  vpc: ec2.IVpc;
  securityGroup: ec2.ISecurityGroup;
  protocol?: string;
  environmentVariables?: Record<string, string>;
  idleTimeout?: number;
  maxLifetime?: number;
}

export class McpServer extends Construct {
  public readonly runtimeArn: string;
  public readonly runtimeId: string;
  public readonly imageTag: string;
  public readonly executionRole: iam.IRole;

  constructor(scope: Construct, id: string, props: McpServerProps) {
    super(scope, id);

    const stack = cdk.Stack.of(this);

    const repo = new ecr.Repository(this, "Repo", {
      repositoryName: `sdlc-mcp-${props.name}`,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      emptyOnDelete: true,
    });

    const sourceAsset = new s3_assets.Asset(this, "SourceAsset", {
      path: props.codePath,
      exclude: ["node_modules", ".venv", "__pycache__", "*.pyc"],
    });
    const imageTag = sourceAsset.assetHash.substring(0, 12);
    this.imageTag = imageTag;

    const buildProject = new codebuild.Project(this, "Build", {
      description: `Builds container image for MCP server: ${props.name}`,
      environment: {
        buildImage: codebuild.LinuxArmBuildImage.AMAZON_LINUX_2_STANDARD_3_0,
        computeType: codebuild.ComputeType.SMALL,
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

    // Start build and wait for completion before updating the Runtime
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

    const executionRole = new iam.Role(this, "ExecutionRole", {
      assumedBy: new iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
    });
    this.executionRole = executionRole;

    executionRole.addToPolicy(new iam.PolicyStatement({
      actions: ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:DescribeLogStreams", "logs:PutLogEvents"],
      resources: [`arn:aws:logs:${stack.region}:${stack.account}:log-group:/aws/bedrock-agentcore/runtimes/*`],
    }));
    executionRole.addToPolicy(new iam.PolicyStatement({
      actions: ["ecr:GetAuthorizationToken"],
      resources: ["*"],
    }));
    executionRole.addToPolicy(new iam.PolicyStatement({
      actions: ["ecr:BatchCheckLayerAvailability", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"],
      resources: [repo.repositoryArn],
    }));
    executionRole.addToPolicy(new iam.PolicyStatement({
      actions: ["xray:PutTelemetryRecords", "xray:PutTraceSegments"],
      resources: ["*"],
    }));

    // Vended logs delivery permissions for AgentCore observability
    executionRole.addToPolicy(new iam.PolicyStatement({
      actions: ["bedrock-agentcore:AllowVendedLogDeliveryForResource"],
      resources: ["*"],
    }));

    executionRole.addToPolicy(new iam.PolicyStatement({
      actions: ["cloudwatch:PutMetricData"],
      resources: ["*"],
      conditions: {
        StringEquals: { "cloudwatch:namespace": "bedrock-agentcore" },
      },
    }));

    NagSuppressions.addResourceSuppressions(buildProject, [
      { id: "AwsSolutions-CB4", reason: "Container image builds do not require KMS encryption" },
    ], true);

    const runtime = new cdk.CfnResource(this, "Runtime", {  // depends on buildWaiter below
      type: "AWS::BedrockAgentCore::Runtime",
      properties: {
        AgentRuntimeName: props.name.replace(/-/g, "_"),
        AgentRuntimeArtifact: {
          ContainerConfiguration: {
            ContainerUri: `${repo.repositoryUri}:${imageTag}`,
          },
        },
        RoleArn: executionRole.roleArn,
        NetworkConfiguration: {
          NetworkMode: "VPC",
          NetworkModeConfig: {
            Subnets: props.vpc.privateSubnets.map((s) => s.subnetId),
            SecurityGroups: [props.securityGroup.securityGroupId],
          },
        },
        ProtocolConfiguration: props.protocol || "MCP",
        LifecycleConfiguration: {
          IdleRuntimeSessionTimeout: props.idleTimeout || 900,
          MaxLifetime: props.maxLifetime || 2400,
        },
        ...(props.environmentVariables && {
          EnvironmentVariables: props.environmentVariables,
        }),
        Tags: { Project: "agent-assisted-sdlc", Component: props.name },
      },
    });
    runtime.applyRemovalPolicy(cdk.RemovalPolicy.DESTROY);
    runtime.node.addDependency(buildWaiter);

    this.runtimeArn = runtime.getAtt("AgentRuntimeArn").toString();
    this.runtimeId = runtime.getAtt("AgentRuntimeId").toString();

    NagSuppressions.addResourceSuppressions(executionRole, [
      { id: "AwsSolutions-IAM5", reason: "ECR, CloudWatch, X-Ray, and AgentCore observability require wildcard resources" },
    ], true);

    new cdk.CfnOutput(scope, `${props.name}RuntimeArn`, { value: this.runtimeArn });
  }
}
