import * as cdk from "aws-cdk-lib";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import { Construct } from "constructs";
import { NagSuppressions } from "cdk-nag";

export interface SessionsTableProps {
  project: string;
}

/**
 * DynamoDB table for tracking AgentCore runtime sessions.
 * Stores session metadata for observability (who triggered, repo/issue, timestamps).
 * POC posture: RemovalPolicy.DESTROY (no production data).
 */
export class SessionsTable extends Construct {
  public readonly table: dynamodb.ITable;
  public readonly tableArn: string;

  constructor(scope: Construct, id: string, props: SessionsTableProps) {
    super(scope, id);

    this.table = new dynamodb.Table(this, "Table", {
      partitionKey: {
        name: "session_id",
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: "invocation_number",
        type: dynamodb.AttributeType.NUMBER,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      timeToLiveAttribute: "ttl",
      encryption: dynamodb.TableEncryption.AWS_MANAGED,
    });

    this.tableArn = this.table.tableArn;

    // Nag suppressions
    NagSuppressions.addResourceSuppressions(
      this.table,
      [
        {
          id: "AwsSolutions-DDB3",
          reason: "POC posture: Point-in-time recovery not required per spec (observability data, not authoritative state; RemovalPolicy.DESTROY)",
        },
      ],
      true,
    );
  }
}
