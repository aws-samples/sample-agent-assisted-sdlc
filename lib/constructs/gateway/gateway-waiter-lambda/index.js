const {
  BedrockAgentCoreControlClient,
  GetGatewayCommand,
  ListGatewayTargetsCommand,
  DeleteGatewayTargetCommand,
  DeleteGatewayCommand,
} = require("@aws-sdk/client-bedrock-agentcore-control");

const client = new BedrockAgentCoreControlClient({});

exports.onEvent = async (event) => {
  const { GatewayId } = event.ResourceProperties;

  if (event.RequestType === "Delete") {
    // Initiate target deletion — isComplete will poll until done then delete gateway
    await initiateTargetDeletion(GatewayId);
    return { PhysicalResourceId: event.PhysicalResourceId };
  }

  return {
    PhysicalResourceId: `gateway-${GatewayId}`,
    Data: { GatewayId },
  };
};

exports.isComplete = async (event) => {
  const { GatewayId } = event.ResourceProperties;

  if (event.RequestType === "Delete") {
    try {
      // Check if targets still exist
      const resp = await client.send(new ListGatewayTargetsCommand({ gatewayIdentifier: GatewayId }));
      const remaining = (resp.targets || []).length;

      if (remaining > 0) {
        console.log(`${remaining} targets still deleting, waiting...`);
        return { IsComplete: false };
      }

      // All targets gone — delete the gateway
      console.log("All targets deleted, deleting gateway:", GatewayId);
      await client.send(new DeleteGatewayCommand({ gatewayIdentifier: GatewayId }));
      console.log("Gateway delete initiated");
      return { IsComplete: false }; // poll again to confirm gateway is gone
    } catch (err) {
      if (err.name === "ResourceNotFoundException") {
        console.log("Gateway deleted successfully");
        return { IsComplete: true };
      }
      // Gateway might be in DELETING state
      console.log("Error (may be transient):", err.message);
      return { IsComplete: false };
    }
  }

  // Create/Update: poll until READY
  console.log("Polling gateway status:", GatewayId);
  const response = await client.send(new GetGatewayCommand({ gatewayIdentifier: GatewayId }));
  console.log("Status:", response.status, "reasons:", response.statusReasons);

  if (response.status === "READY") {
    return { IsComplete: true, Data: { Status: response.status } };
  }
  if (response.status === "FAILED") {
    const reasons = (response.statusReasons || []).join("; ") || "no reason provided";
    throw new Error(`gateway ${GatewayId} entered FAILED status: ${reasons}`);
  }
  return { IsComplete: false };
};

async function initiateTargetDeletion(gatewayId) {
  console.log("Initiating target deletion for gateway:", gatewayId);

  try {
    const targets = [];
    let nextToken;
    do {
      const resp = await client.send(new ListGatewayTargetsCommand({
        gatewayIdentifier: gatewayId,
        ...(nextToken && { nextToken }),
      }));
      if (resp.targets) targets.push(...resp.targets);
      nextToken = resp.nextToken;
    } while (nextToken);

    console.log(`Found ${targets.length} targets to delete`);

    for (const target of targets) {
      try {
        console.log(`Deleting target: ${target.targetId} (${target.name})`);
        await client.send(new DeleteGatewayTargetCommand({
          gatewayIdentifier: gatewayId,
          targetId: target.targetId,
        }));
      } catch (err) {
        if (err.name === "ResourceNotFoundException") continue;
        console.log(`Warning: failed to delete target ${target.targetId}:`, err.message);
      }
    }
  } catch (err) {
    if (err.name === "ResourceNotFoundException") {
      console.log("Gateway already deleted:", gatewayId);
      return;
    }
    console.log("Error initiating target deletion (non-fatal):", err.message);
  }
}
