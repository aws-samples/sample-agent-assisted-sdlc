const { BedrockAgentCoreControlClient, GetGatewayTargetCommand } = require("@aws-sdk/client-bedrock-agentcore-control");

const client = new BedrockAgentCoreControlClient({});

exports.onEvent = async (event) => {
  if (event.RequestType === "Delete") {
    return { PhysicalResourceId: event.PhysicalResourceId };
  }
  const { GatewayId, TargetId } = event.ResourceProperties;
  return { PhysicalResourceId: `target-${TargetId}`, Data: { GatewayId, TargetId } };
};

exports.isComplete = async (event) => {
  if (event.RequestType === "Delete") {
    return { IsComplete: true };
  }

  const { GatewayId, TargetId } = event.ResourceProperties;
  console.log("Polling target status:", GatewayId, TargetId);

  const resp = await client.send(new GetGatewayTargetCommand({
    gatewayIdentifier: GatewayId,
    targetId: TargetId,
  }));
  console.log("Status:", resp.status, "reasons:", resp.statusReasons);

  if (resp.status === "READY") {
    return { IsComplete: true, Data: { Status: "READY" } };
  }
  if (["FAILED", "SYNCHRONIZE_UNSUCCESSFUL"].includes(resp.status)) {
    const reasons = (resp.statusReasons || []).join("; ") || "no reason provided";
    throw new Error(`Target ${TargetId} entered ${resp.status}: ${reasons}`);
  }
  return { IsComplete: false };
};
