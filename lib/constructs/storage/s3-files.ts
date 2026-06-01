import * as cdk from "aws-cdk-lib";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as s3deploy from "aws-cdk-lib/aws-s3-deployment";
import * as iam from "aws-cdk-lib/aws-iam";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as codebuild from "aws-cdk-lib/aws-codebuild";
import * as cr from "aws-cdk-lib/custom-resources";
import * as fs from "fs";
import * as crypto from "crypto";
import { Construct } from "constructs";
import { NagSuppressions } from "cdk-nag";

export interface S3FilesStorageProps {
  vpc: ec2.IVpc;
  fileSystemSecurityGroup: ec2.ISecurityGroup;
  pluginsPath: string;
  gatewayProxyPath?: string;
  gatewayUrl?: string;
  region?: string;
}

export class S3FilesStorage extends Construct {
  public readonly bucket: s3.IBucket;
  public readonly accessPointArn: string;
  public readonly fileSystemId: string;
  public readonly pluginsDeployment: s3deploy.BucketDeployment;

  constructor(scope: Construct, id: string, props: S3FilesStorageProps) {
    super(scope, id);

    const stack = cdk.Stack.of(this);

    this.bucket = new s3.Bucket(this, "Bucket", {
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      versioned: true,
      enforceSSL: true,
    });

    // Upload plugins (excludes node_modules — handled by CodeBuild).
    // settings.json is excluded so the AssistantStack's ResolveSettingsJson
    // custom resource is the sole writer of plugins/settings.json — see
    // assistant-stack.ts for the substitution + ordering.
    this.pluginsDeployment = new s3deploy.BucketDeployment(this, "DeployPlugins", {
      sources: [
        s3deploy.Source.asset(props.pluginsPath, {
          exclude: ["*.pyc", "__pycache__", "node_modules", ".mcp.json.template", "settings.json"],
        }),
      ],
      destinationBucket: this.bucket,
      destinationKeyPrefix: "plugins/",
      prune: false,
    });

    // Upload gateway proxy source (only if gateway is configured)
    let proxyDeployment: s3deploy.BucketDeployment | undefined;
    if (props.gatewayProxyPath) {
      proxyDeployment = new s3deploy.BucketDeployment(this, "DeployGatewayProxy", {
        sources: [
          s3deploy.Source.asset(props.gatewayProxyPath, {
            exclude: ["node_modules"],
          }),
        ],
        destinationBucket: this.bucket,
        destinationKeyPrefix: "plugins/gateway-iam-proxy/",
        prune: false,
      });
    }

    // IAM role for S3 Files
    const s3FilesRole = new iam.Role(this, "S3FilesRole", {
      assumedBy: new iam.ServicePrincipal("elasticfilesystem.amazonaws.com", {
        conditions: {
          StringEquals: { "aws:SourceAccount": stack.account },
          ArnLike: { "aws:SourceArn": `arn:aws:s3files:${stack.region}:${stack.account}:file-system/*` },
        },
      }),
    });

    s3FilesRole.addToPolicy(new iam.PolicyStatement({
      actions: ["s3:ListBucket", "s3:ListBucketVersions"],
      resources: [this.bucket.bucketArn],
      conditions: { StringEquals: { "aws:ResourceAccount": stack.account } },
    }));

    s3FilesRole.addToPolicy(new iam.PolicyStatement({
      actions: ["s3:AbortMultipartUpload", "s3:DeleteObject*", "s3:GetObject*", "s3:List*", "s3:PutObject*"],
      resources: [`${this.bucket.bucketArn}/*`],
      conditions: { StringEquals: { "aws:ResourceAccount": stack.account } },
    }));

    s3FilesRole.addToPolicy(new iam.PolicyStatement({
      actions: ["events:DeleteRule", "events:DisableRule", "events:EnableRule", "events:PutRule", "events:PutTargets", "events:RemoveTargets"],
      resources: ["arn:aws:events:*:*:rule/DO-NOT-DELETE-S3-Files*"],
      conditions: { StringEquals: { "events:ManagedBy": "elasticfilesystem.amazonaws.com" } },
    }));

    s3FilesRole.addToPolicy(new iam.PolicyStatement({
      actions: ["events:DescribeRule", "events:ListRuleNamesByTarget", "events:ListRules", "events:ListTargetsByRule"],
      resources: ["arn:aws:events:*:*:rule/*"],
    }));

    // S3 Files FileSystem
    const fileSystem = new cdk.CfnResource(this, "FileSystem", {
      type: "AWS::S3Files::FileSystem",
      properties: {
        Bucket: this.bucket.bucketArn,
        RoleArn: s3FilesRole.roleArn,
        AcceptBucketWarning: true,
        Tags: [{ Key: "Project", Value: "agent-assisted-sdlc" }],
      },
    });

    this.fileSystemId = fileSystem.getAtt("FileSystemId").toString();

    // Mount targets
    const privateSubnets = props.vpc.privateSubnets;
    for (let i = 0; i < privateSubnets.length; i++) {
      const mt = new cdk.CfnResource(this, `MountTarget${i}`, {
        type: "AWS::S3Files::MountTarget",
        properties: {
          FileSystemId: fileSystem.getAtt("FileSystemId"),
          SubnetId: privateSubnets[i].subnetId,
          SecurityGroups: [props.fileSystemSecurityGroup.securityGroupId],
        },
      });
      mt.addDependency(fileSystem);
    }

    // Access point
    const accessPoint = new cdk.CfnResource(this, "AccessPoint", {
      type: "AWS::S3Files::AccessPoint",
      properties: {
        FileSystemId: fileSystem.getAtt("FileSystemId"),
        PosixUser: { Uid: "1000", Gid: "1000" },
        RootDirectory: {
          Path: "/plugins",
          CreationPermissions: { OwnerUid: "1000", OwnerGid: "1000", Permissions: "755" },
        },
      },
    });
    accessPoint.addDependency(fileSystem);

    this.accessPointArn = accessPoint.getAtt("AccessPointArn").toString();

    // CodeBuild for gateway-iam-proxy node_modules (only if gateway is configured)
    if (props.gatewayProxyPath) {
      const installDeps = new codebuild.Project(this, "InstallProxyDeps", {
        description: "Installs gateway-iam-proxy node_modules and syncs to S3",
        environment: {
          buildImage: codebuild.LinuxBuildImage.STANDARD_7_0,
          computeType: codebuild.ComputeType.SMALL,
        },
        environmentVariables: { BUCKET_NAME: { value: this.bucket.bucketName } },
        buildSpec: codebuild.BuildSpec.fromObject({
          version: "0.2",
          phases: {
            install: {
              commands: [
                "aws s3 cp s3://$BUCKET_NAME/plugins/gateway-iam-proxy/package.json ./package.json",
                "aws s3 cp s3://$BUCKET_NAME/plugins/gateway-iam-proxy/package-lock.json ./package-lock.json || true",
              ],
            },
            build: { commands: ["npm ci --omit=dev || npm install --omit=dev"] },
            post_build: {
              commands: ["aws s3 sync ./node_modules s3://$BUCKET_NAME/plugins/gateway-iam-proxy/node_modules/ --delete"],
            },
          },
        }),
      });

      this.bucket.grantReadWrite(installDeps);

      const lockfilePath = `${props.gatewayProxyPath}/package-lock.json`;
      const lockfileHash = fs.existsSync(lockfilePath)
        ? crypto.createHash("md5").update(fs.readFileSync(lockfilePath)).digest("hex")
        : "no-lockfile";

      const trigger = new cr.AwsCustomResource(this, "TriggerInstallDeps", {
        onUpdate: {
          service: "CodeBuild",
          action: "startBuild",
          parameters: { projectName: installDeps.projectName },
          physicalResourceId: cr.PhysicalResourceId.of(`install-deps-${lockfileHash}`),
        },
        policy: cr.AwsCustomResourcePolicy.fromStatements([
          new iam.PolicyStatement({ actions: ["codebuild:StartBuild"], resources: [installDeps.projectArn] }),
        ]),
      });
      if (proxyDeployment) {
        trigger.node.addDependency(proxyDeployment);
      }

      NagSuppressions.addResourceSuppressions(installDeps, [
        { id: "AwsSolutions-IAM5", reason: "CodeBuild needs S3 read/write for the bucket contents" },
        { id: "AwsSolutions-CB4", reason: "CodeBuild encryption not required for npm install artifacts" },
      ], true);
    }

    NagSuppressions.addResourceSuppressions(s3FilesRole, [
      { id: "AwsSolutions-IAM5", reason: "S3 Files role needs broad S3 access to the backing bucket" },
    ], true);

    NagSuppressions.addResourceSuppressions(this.bucket, [
      { id: "AwsSolutions-S1", reason: "Access logs omitted for cost — enable in production" },
    ], true);

    NagSuppressions.addStackSuppressions(cdk.Stack.of(this), [
      { id: "AwsSolutions-IAM5", reason: "BucketDeployment Lambda uses CDK-managed wildcard policies" },
      { id: "AwsSolutions-IAM4", reason: "BucketDeployment uses AWS managed policies" },
      { id: "AwsSolutions-L1", reason: "BucketDeployment Lambda runtime is managed by CDK" },
    ], true);

    new cdk.CfnOutput(scope, "BucketName", { value: this.bucket.bucketName });
    new cdk.CfnOutput(scope, "FileSystemId", { value: this.fileSystemId });
    new cdk.CfnOutput(scope, "AccessPointArn", { value: this.accessPointArn });
  }

  public grantMount(role: iam.IRole): void {
    const stack = cdk.Stack.of(this);
    role.addToPrincipalPolicy(new iam.PolicyStatement({
      actions: ["s3files:ClientMount", "s3files:ClientWrite"],
      resources: [`arn:aws:s3files:${stack.region}:${stack.account}:file-system/${this.fileSystemId}`],
      conditions: { ArnEquals: { "s3files:AccessPointArn": this.accessPointArn } },
    }));
    role.addToPrincipalPolicy(new iam.PolicyStatement({
      actions: ["s3files:ListMountTargets"],
      resources: [`arn:aws:s3files:${stack.region}:${stack.account}:file-system/${this.fileSystemId}`],
    }));
    role.addToPrincipalPolicy(new iam.PolicyStatement({
      actions: ["s3files:GetAccessPoint"],
      resources: [this.accessPointArn],
    }));
  }
}
