const { CodeBuildClient, StartBuildCommand, BatchGetBuildsCommand } = require("@aws-sdk/client-codebuild");

const client = new CodeBuildClient({});

exports.onEvent = async (event) => {
  if (event.RequestType === "Delete") {
    return { PhysicalResourceId: event.PhysicalResourceId };
  }

  const { ProjectName } = event.ResourceProperties;
  console.log("Starting build:", ProjectName);

  const resp = await client.send(new StartBuildCommand({ projectName: ProjectName }));
  const buildId = resp.build.id;
  console.log("Build started:", buildId);

  return {
    PhysicalResourceId: buildId,
    Data: { BuildId: buildId },
  };
};

exports.isComplete = async (event) => {
  if (event.RequestType === "Delete") {
    return { IsComplete: true };
  }

  const buildId = event.PhysicalResourceId;
  console.log("Polling build:", buildId);

  const resp = await client.send(new BatchGetBuildsCommand({ ids: [buildId] }));
  const build = resp.builds[0];
  console.log("Build status:", build.buildStatus);

  if (build.buildStatus === "SUCCEEDED") {
    return { IsComplete: true, Data: { BuildStatus: "SUCCEEDED" } };
  }
  if (["FAILED", "FAULT", "TIMED_OUT", "STOPPED"].includes(build.buildStatus)) {
    throw new Error(`Build ${buildId} failed with status: ${build.buildStatus}`);
  }
  return { IsComplete: false };
};
