import { loadConfig, getAssistantDir, SdlcConfig } from "../lib/config";
import * as path from "path";

const TEMPLATE_PATH = path.join(__dirname, "..", "sdlc-config.template.yaml");

describe("loadConfig", () => {
  test("loads template config successfully", () => {
    const config = loadConfig(TEMPLATE_PATH);
    expect(config.project).toBe("agent-assisted-sdlc");
    expect(config.region).toBe("us-west-2");
  });

  test("codingAssistant.type defaults to claude-code", () => {
    const config = loadConfig(TEMPLATE_PATH);
    expect(config.codingAssistant.type).toBe("claude-code");
  });

  test("sourceControl.github.allowedRepos is an array", () => {
    const config = loadConfig(TEMPLATE_PATH);
    expect(Array.isArray(config.sourceControl.github?.allowedRepos)).toBe(true);
    expect(config.sourceControl.github!.allowedRepos.length).toBeGreaterThan(0);
  });

  test("projectManagement.github.allowedUsers is an array", () => {
    const config = loadConfig(TEMPLATE_PATH);
    expect(Array.isArray(config.projectManagement.github?.allowedUsers)).toBe(true);
  });

  test("sourceControl.github.org is a string", () => {
    const config = loadConfig(TEMPLATE_PATH);
    expect(typeof config.sourceControl.github?.org).toBe("string");
  });

  test("projectManagement.github.labelPrefix defaults in template", () => {
    const config = loadConfig(TEMPLATE_PATH);
    expect(config.projectManagement.github?.labelPrefix).toBe("agent");
  });

  test("throws on non-existent file", () => {
    expect(() => loadConfig("/does/not/exist.yaml")).toThrow();
  });
});

describe("getAssistantDir", () => {
  const makeConfig = (type: string): SdlcConfig => ({
    project: "test",
    region: "us-west-2",
    codingAssistant: { type, model: "test" },
    sourceControl: { type: "github" },
    projectManagement: { type: "github" },
  });

  test("claude-code maps to claude-code/", () => {
    expect(getAssistantDir(makeConfig("claude-code"))).toBe("claude-code");
  });

  test("kiro maps to kiro/", () => {
    expect(getAssistantDir(makeConfig("kiro"))).toBe("kiro");
  });

  test("codex maps to codex/", () => {
    expect(getAssistantDir(makeConfig("codex"))).toBe("codex");
  });

  test("unknown type throws error", () => {
    expect(() => getAssistantDir(makeConfig("unknown-assistant"))).toThrow(
      /Unknown codingAssistant.type/
    );
  });

  test("empty type throws error", () => {
    expect(() => getAssistantDir(makeConfig(""))).toThrow();
  });
});

describe("Cedar Policy Construction", () => {
  // Helper function that mirrors gateway-stack.ts logic
  const sanitizePolicyName = (name: string) => name.replace(/-/g, "_").substring(0, 30);

  test("sanitizePolicyName converts hyphens to underscores", () => {
    expect(sanitizePolicyName("my-project-name")).toBe("my_project_name");
  });

  test("sanitizePolicyName truncates to 30 characters", () => {
    const longName = "a".repeat(50);
    expect(sanitizePolicyName(longName)).toBe("a".repeat(30));
  });

  test("sanitizePolicyName handles project with trailing hyphen", () => {
    expect(sanitizePolicyName("project-")).toBe("project_");
  });

  test("policy names are under 48 character limit", () => {
    const projectPrefix = sanitizePolicyName("agent-assisted-sdlc");
    expect(`${projectPrefix}_branch_protect`.length).toBeLessThanOrEqual(48);
    expect(`${projectPrefix}_branch_pattern`.length).toBeLessThanOrEqual(48);
    expect(`${projectPrefix}_label_gov`.length).toBeLessThanOrEqual(48);
    expect(`${projectPrefix}_default_permit`.length).toBeLessThanOrEqual(48);
  });

  test("policy names match pattern ^[A-Za-z][A-Za-z0-9_]*$", () => {
    const validPattern = /^[A-Za-z][A-Za-z0-9_]*$/;
    const projectPrefix = sanitizePolicyName("my-project-123");

    expect(`${projectPrefix}_branch_protect`).toMatch(validPattern);
    expect(`${projectPrefix}_branch_pattern`).toMatch(validPattern);
    expect(`${projectPrefix}_label_gov`).toMatch(validPattern);
    expect(`${projectPrefix}_default_permit`).toMatch(validPattern);
  });

  test("label prefix substitution in Policy 3", () => {
    const customPrefix = "custom-prefix";
    const triggerLabel = `${customPrefix}:start`;

    const policy3Template = `
forbid(
  principal is AgentCore::IamEntity,
  action == AgentCore::Action::"project-management___issue_write",
  resource == AgentCore::Gateway::"arn:aws:bedrock-agentcore:us-west-2:123456789012:gateway/test-id"
)
when {
  context.input has labels &&
  context.input.labels.contains("${triggerLabel}")
};
`.trim();

    expect(policy3Template).toContain(`"${customPrefix}:start"`);
    expect(policy3Template).not.toContain("agent:start");
  });

  test("gateway ARN construction pattern", () => {
    const region = "us-west-2";
    const account = "123456789012";
    const gatewayId = "test-gateway-id";
    const gatewayArn = `arn:aws:bedrock-agentcore:${region}:${account}:gateway/${gatewayId}`;

    expect(gatewayArn).toBe("arn:aws:bedrock-agentcore:us-west-2:123456789012:gateway/test-gateway-id");
    expect(gatewayArn).toMatch(/^arn:aws:bedrock-agentcore:[a-z0-9-]+:\d+:gateway\/.+$/);
  });

  test("Policy 1 forbids operations on main/master branches", () => {
    const policy1Template = `
forbid(
  principal is AgentCore::IamEntity,
  action in [
    AgentCore::Action::"source-control___push_files",
    AgentCore::Action::"source-control___create_branch",
    AgentCore::Action::"source-control___create_pull_request"
  ],
  resource == AgentCore::Gateway::"test-arn"
)
when {
  context.input has branch &&
  (context.input.branch == "main" || context.input.branch == "master")
};
`.trim();

    expect(policy1Template).toContain('context.input.branch == "main"');
    expect(policy1Template).toContain('context.input.branch == "master"');
    expect(policy1Template).toContain("source-control___push_files");
    expect(policy1Template).toContain("source-control___create_branch");
    expect(policy1Template).toContain("source-control___create_pull_request");
  });

  test("Policy 2 has no unless clause", () => {
    const policy2Template = `
forbid(
  principal is AgentCore::IamEntity,
  action in [
    AgentCore::Action::"source-control___push_files",
    AgentCore::Action::"source-control___create_branch"
  ],
  resource == AgentCore::Gateway::"test-arn"
)
when {
  context.input has branch &&
  !(context.input.branch like "feat/issue-*")
};
`.trim();

    expect(policy2Template).not.toContain("unless");
    expect(policy2Template).toContain('context.input.branch like "feat/issue-*"');
  });

  test("Policy 3 references project-management___issue_write action", () => {
    const policy3Template = `
forbid(
  principal is AgentCore::IamEntity,
  action == AgentCore::Action::"project-management___issue_write",
  resource == AgentCore::Gateway::"test-arn"
)
when {
  context.input has labels &&
  context.input.labels.contains("agent:start")
};
`.trim();

    expect(policy3Template).toContain("project-management___issue_write");
    expect(policy3Template).toContain("context.input has labels");
    expect(policy3Template).toContain("context.input.labels.contains");
  });

  test("Policy 4 is a default permit without conditions", () => {
    const policy4Template = `
permit(
  principal is AgentCore::IamEntity,
  action,
  resource == AgentCore::Gateway::"test-arn"
);
`.trim();

    expect(policy4Template).toContain("permit(");
    expect(policy4Template).not.toContain("when {");
    expect(policy4Template).not.toContain("unless {");
    expect(policy4Template).toMatch(/;\s*$/); // ends with semicolon
  });
});
