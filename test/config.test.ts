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
