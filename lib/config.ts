import * as fs from "fs";
import * as yaml from "js-yaml";

export interface VpcConfig {
  maxAzs?: number;
  natGateways?: number;
  vpcId?: string;
  privateSubnetIds?: string[];
  agentRuntimeSecurityGroupId?: string;
  fileSystemSecurityGroupId?: string;
}

export interface CodingAssistantConfig {
  type: string;
  model: string;
  idleTimeout?: number;
  maxLifetime?: number;
  sessionStorageMountPath?: string;
}

export interface McpServerConfig {
  name: string;
  source: string;
}

export interface GitHubSourceControlConfig {
  org: string;
  appClientId: string;
  installationId: string;
  privateKeyPath: string;
  toolsets?: string;
  maxLifetime?: number;
  privateRepo?: boolean;
  allowedRepos: string[];
}

export interface SourceControlConfig {
  type: string;
  github?: GitHubSourceControlConfig;
}

export interface GitHubProjectManagementConfig {
  toolsets?: string;
  maxLifetime?: number;
  allowedUsers: string[];
  labelPrefix?: string;
}

export interface JiraProjectManagementConfig {
  siteUrl: string;
  projectKey: string;
  clientId: string;
  clientSecret: string;
}

export interface ProjectManagementConfig {
  type: string;
  github?: GitHubProjectManagementConfig;
  jira?: JiraProjectManagementConfig;
}

export interface GatewayConfig {
  url?: string;
  authorizerType?: string;
  credentialProviderArn?: string;
  developerMcpServers?: McpServerConfig[];
}

export interface ResourcePolicyStatement {
  principal: string | string[];
  action: string | string[];
}

export interface ResourcePoliciesConfig {
  enabled: boolean;
  codingAssistant?: ResourcePolicyStatement[];
  gateway?: ResourcePolicyStatement[];
  mcpServers?: ResourcePolicyStatement[];
}

export interface SdlcConfig {
  project: string;
  region: string;
  vpc?: VpcConfig;
  codingAssistant: CodingAssistantConfig;
  sourceControl: SourceControlConfig;
  projectManagement: ProjectManagementConfig;
  gateway?: GatewayConfig;
  resourcePolicies?: ResourcePoliciesConfig;
}

const ASSISTANT_TO_DIR: Record<string, string> = {
  "claude-code": "claude-code",
  codex: "codex",
  kiro: "kiro",
};

export function getAssistantDir(config: SdlcConfig): string {
  const dir = ASSISTANT_TO_DIR[config.codingAssistant.type];
  if (!dir) {
    throw new Error(
      `Unknown codingAssistant.type: "${config.codingAssistant.type}". ` +
        `Supported: ${Object.keys(ASSISTANT_TO_DIR).join(", ")}`,
    );
  }
  return dir;
}

export function loadConfig(path: string): SdlcConfig {
  const content = fs.readFileSync(path, "utf-8");
  return yaml.load(content) as SdlcConfig;
}
