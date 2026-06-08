// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useState } from "react";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import ButtonGroup from "@cloudscape-design/components/button-group";
import Box from "@cloudscape-design/components/box";
import Badge from "@cloudscape-design/components/badge";
import Link from "@cloudscape-design/components/link";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import CopyToClipboard from "@cloudscape-design/components/copy-to-clipboard";
import ExpandableSection from "@cloudscape-design/components/expandable-section";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Alert from "@cloudscape-design/components/alert";
import KeyValuePairs from "@cloudscape-design/components/key-value-pairs";
import { checkClaude, stopSession, getRuntimeLifecycle } from "./api";
import type { GroupedSession } from "./SessionList";

interface SessionCardProps {
  group: GroupedSession;
}

function formatRelativeTime(isoString: string): string {
  const now = Date.now();
  const then = new Date(isoString).getTime();
  const diffMs = now - then;
  const diffMin = Math.floor(diffMs / 60000);

  if (diffMin < 1) return "just now";
  if (diffMin === 1) return "1m ago";
  if (diffMin < 60) return `${diffMin}m ago`;

  const diffHr = Math.floor(diffMin / 60);
  if (diffHr === 1) return "1h ago";
  if (diffHr < 24) return `${diffHr}h ago`;

  const diffDays = Math.floor(diffHr / 24);
  return `${diffDays}d ago`;
}

export function SessionCard({ group }: SessionCardProps) {
  const { latest, invocations } = group;
  const [checking, setChecking] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [stopResult, setStopResult] = useState<{ stopped: boolean; error?: string } | null>(null);
  const [result, setResult] = useState<{ running: boolean; pids: number[]; error?: string } | null>(null);
  const [showTuiHelp, setShowTuiHelp] = useState(false);
  const [uptime, setUptime] = useState<number | null>(null);
  const [checkingLifecycle, setCheckingLifecycle] = useState(false);

  const handleCheck = async () => {
    setChecking(true);
    setResult(null);
    try {
      const response = await checkClaude({
        session_id: latest.session_id,
        runtime_arn: latest.runtime_arn,
        claude_session_uuid: latest.claude_session_uuid,
      });
      setResult({ running: response.claude_running, pids: response.pids });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setResult({ running: false, pids: [], error: message });
    } finally {
      setChecking(false);
    }
  };

  const handleStop = async () => {
    if (!window.confirm(`Stop session for issue #${latest.issue_number}? This will kill any running Claude process.`)) return;
    setStopping(true);
    setStopResult(null);
    try {
      const resp = await stopSession({ session_id: latest.session_id, runtime_arn: latest.runtime_arn });
      setStopResult({ stopped: resp.stopped });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setStopResult({ stopped: false, error: message });
    } finally {
      setStopping(false);
    }
  };

  const handleLifecycle = async () => {
    setCheckingLifecycle(true);
    try {
      const resp = await getRuntimeLifecycle({ session_id: latest.session_id, runtime_arn: latest.runtime_arn });
      setUptime(resp.uptime_seconds);
    } catch {
      setUptime(null);
    } finally {
      setCheckingLifecycle(false);
    }
  };

  const region = latest.runtime_arn.split(":")[3] || "us-west-2";
  const tuiCommand = `agentcore exec --it \\\n  --runtime ${latest.runtime_arn} \\\n  --region ${region} \\\n  --session-id ${latest.session_id}`;
  const previousInvocations = invocations.filter((inv) => inv.invocation_number !== latest.invocation_number);

  return (
    <Container
      header={
        <Header
          variant="h2"
          description={
            <SpaceBetween direction="horizontal" size="xs" alignItems="center">
              {latest.issue_url ? (
                <Link href={latest.issue_url} external>{latest.repo_owner}/{latest.repo_name}#{latest.issue_number}</Link>
              ) : (
                <span>{latest.repo_owner}/{latest.repo_name}#{latest.issue_number}</span>
              )}
              <Badge color="blue">{latest.assistant_type}</Badge>
              {latest.status === "skipped_already_running" && <Badge color="red">Skipped</Badge>}
            </SpaceBetween>
          }
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              <Button onClick={handleCheck} loading={checking}>
                Check Claude
              </Button>
              <Button onClick={handleLifecycle} loading={checkingLifecycle}>
                Runtime Lifecycle
              </Button>
              <Button
                onClick={() => {
                  navigator.clipboard.writeText(tuiCommand);
                  setShowTuiHelp(true);
                }}
                iconName="copy"
              >
                TUI Command
              </Button>
              <Button onClick={handleStop} loading={stopping} variant="normal">
                Stop Session
              </Button>
            </SpaceBetween>
          }
        >
          {latest.issue_url ? (
            <Link href={latest.issue_url} external fontSize="heading-m">{latest.issue_title}</Link>
          ) : (
            latest.issue_title
          )}
        </Header>
      }
    >
      <SpaceBetween size="l">
        <ColumnLayout columns={3} variant="text-grid">
          <KeyValuePairs
            items={[
              { label: "Triggered by", value: <Box fontWeight="bold">{latest.triggered_by}</Box> },
              {
                label: "Current invocation",
                value: (
                  <SpaceBetween direction="horizontal" size="xs" alignItems="center">
                    <span>#{latest.invocation_number}</span>
                    {latest.is_reinvocation && <Badge>re-invocation</Badge>}
                    <Box color="text-status-inactive">{formatRelativeTime(latest.started_at)}</Box>
                  </SpaceBetween>
                ),
              },
            ]}
          />
          <KeyValuePairs
            items={[
              {
                label: "AgentCore Session ID",
                value: <CopyToClipboard copyButtonAriaLabel="Copy" copySuccessText="Copied" copyErrorText="Failed" textToCopy={latest.session_id} variant="inline" />,
              },
              {
                label: "Claude Session ID",
                value: latest.claude_session_uuid ? (
                  <CopyToClipboard copyButtonAriaLabel="Copy" copySuccessText="Copied" copyErrorText="Failed" textToCopy={latest.claude_session_uuid} variant="inline" />
                ) : "—",
              },
            ]}
          />
          <KeyValuePairs
            items={[
              {
                label: "Status",
                value: result ? (
                  result.running ? (
                    <StatusIndicator type="success">Running (PIDs: {result.pids.join(", ")})</StatusIndicator>
                  ) : (
                    <StatusIndicator type="stopped">Not running</StatusIndicator>
                  )
                ) : (
                  <StatusIndicator type="pending">Unknown</StatusIndicator>
                ),
              },
              {
                label: "Uptime",
                value: uptime !== null ? `${Math.floor(uptime / 60)}m ${uptime % 60}s` : "—",
              },
            ]}
          />
        </ColumnLayout>

        {result?.error && (
          <Alert type="error">{result.error}</Alert>
        )}

        {stopResult && (
          <Alert type={stopResult.error ? "error" : stopResult.stopped ? "success" : "warning"}>
            {stopResult.error ? `Stop failed: ${stopResult.error}` : stopResult.stopped ? "Session stopped successfully" : "Session may already be stopped"}
          </Alert>
        )}

        {showTuiHelp && (
          <Alert type="info" header="TUI command copied to clipboard">
            <SpaceBetween size="xs">
              <Box>Paste in your terminal to connect to the runtime.</Box>
              <Box>
                <strong>Prerequisites:</strong> Install the{" "}
                <Link href="https://github.com/aws/agentcore-cli" external>AgentCore CLI</Link>{" "}
                and ensure you have{" "}
                <Link href="https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-command-shell.html" external>
                  InvokeAgentRuntimeCommand permissions
                </Link>.
              </Box>
            </SpaceBetween>
          </Alert>
        )}

        {previousInvocations.length > 0 && (
          <ExpandableSection headerText={`Previous invocations (${previousInvocations.length})`}>
            <SpaceBetween size="xs">
              {previousInvocations.map((inv) => (
                <Box key={inv.invocation_number} padding={{ vertical: "xs" }}>
                  <SpaceBetween direction="horizontal" size="xs" alignItems="center">
                    <Box fontWeight="bold">#{inv.invocation_number}</Box>
                    {inv.is_reinvocation && <Badge>re-invocation</Badge>}
                    <Box color="text-status-inactive">{formatRelativeTime(inv.started_at)}</Box>
                    {inv.status === "skipped_already_running" && (
                      <StatusIndicator type="warning">skipped</StatusIndicator>
                    )}
                  </SpaceBetween>
                </Box>
              ))}
            </SpaceBetween>
          </ExpandableSection>
        )}
      </SpaceBetween>
    </Container>
  );
}
