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
    await deleteGatewayWithTargets(GatewayId);
    return { PhysicalResourceId: event.PhysicalResourceId };
  }

  return {
    PhysicalResourceId: `gateway-${GatewayId}`,
    Data: { GatewayId },
  };
};

exports.isComplete = async (event) => {
  if (event.RequestType === "Delete") {
    return { IsComplete: true };
  }

  const { GatewayId } = event.ResourceProperties;
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

async function deleteGatewayWithTargets(gatewayId) {
  console.log("Deleting gateway and all targets:", gatewayId);

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

    if (targets.length > 0) {
      console.log("Waiting for targets to be deleted...");
      await sleep(10000);
    }

    console.log("Deleting gateway:", gatewayId);
    await client.send(new DeleteGatewayCommand({ gatewayIdentifier: gatewayId }));
  } catch (err) {
    if (err.name === "ResourceNotFoundException") {
      console.log("Gateway already deleted:", gatewayId);
      return;
    }
    throw err;
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
