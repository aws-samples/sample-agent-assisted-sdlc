// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useState } from "react";
import { applyMode, Mode } from "@cloudscape-design/global-styles";
import AppLayout from "@cloudscape-design/components/app-layout";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import SpaceBetween from "@cloudscape-design/components/space-between";
import SegmentedControl from "@cloudscape-design/components/segmented-control";
import Alert from "@cloudscape-design/components/alert";
import Spinner from "@cloudscape-design/components/spinner";
import Box from "@cloudscape-design/components/box";
import Badge from "@cloudscape-design/components/badge";
import SideNavigation from "@cloudscape-design/components/side-navigation";
import TopNavigation from "@cloudscape-design/components/top-navigation";
import Toggle from "@cloudscape-design/components/toggle";
import { fetchSessions } from "./api";
import { SessionList } from "./SessionList";
import type { SessionRecord } from "./types";

const REFRESH_INTERVAL_MS = 15000;

const TIME_WINDOWS = [
  { id: "10", text: "10 min" },
  { id: "60", text: "1 hour" },
  { id: "1440", text: "1 day" },
  { id: "0", text: "All" },
];

export function App() {
  const [sessions, setSessions] = useState<SessionRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [windowMinutes, setWindowMinutes] = useState("10");
  const [darkMode, setDarkMode] = useState(() => {
    const saved = localStorage.getItem("inspector-dark-mode");
    return saved === "true";
  });

  useEffect(() => {
    applyMode(darkMode ? Mode.Dark : Mode.Light);
    localStorage.setItem("inspector-dark-mode", String(darkMode));
  }, [darkMode]);

  const loadSessions = async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    else setLoading(true);

    setError(null);

    try {
      const mins = parseInt(windowMinutes);
      const data = await fetchSessions(Number.isNaN(mins) ? undefined : mins);
      setSessions(data);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    loadSessions();

    const intervalId = setInterval(() => {
      if (document.visibilityState === "visible") {
        loadSessions(true);
      }
    }, REFRESH_INTERVAL_MS);

    return () => clearInterval(intervalId);
  }, [windowMinutes]);

  const uniqueSessions = new Set(sessions.map((s) => s.session_id)).size;

  return (
    <>
      <div id="top-nav">
        <TopNavigation
          identity={{
            href: "/",
            title: "AgentCore SDLC Inspector",
          }}
          utilities={[
            {
              type: "button",
              text: darkMode ? "☀ Light" : "🌙 Dark",
              onClick: () => setDarkMode(!darkMode),
            },
            {
              type: "button",
              text: "Documentation",
              href: "https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/",
              external: true,
              externalIconAriaLabel: "(opens in new tab)",
            },
            {
              type: "button",
              text: "GitHub",
              href: "https://github.com/aws-samples/sample-agent-assisted-sdlc",
              external: true,
              externalIconAriaLabel: "(opens in new tab)",
            },
          ]}
        />
      </div>
      <AppLayout
        navigation={
          <SideNavigation
            header={{ href: "/", text: "Inspector" }}
            activeHref="/"
            items={[
              { type: "link", text: "Sessions", href: "/" },
              { type: "divider" },
              {
                type: "section",
                text: "Resources",
                items: [
                  { type: "link", text: "AgentCore Docs", href: "https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/", external: true },
                  { type: "link", text: "AgentCore CLI", href: "https://github.com/aws/agentcore-cli", external: true },
                  { type: "link", text: "Observability", href: "https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html", external: true },
                ],
              },
              { type: "divider" },
              {
                type: "section",
                text: "Configuration",
                items: [
                  { type: "link", text: "Runtime Lifecycle", href: "https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-lifecycle-settings.html", external: true },
                  { type: "link", text: "MCP Protocol", href: "https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-mcp-protocol-contract.html", external: true },
                  { type: "link", text: "Security", href: "https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-security-best-practices.html", external: true },
                ],
              },
            ]}
          />
        }
        toolsHide
        content={
          <ContentLayout
            header={
              <Header
                variant="h1"
                description="Monitor in-flight AgentCore SDLC pipeline sessions"
                actions={
                  <SpaceBetween direction="horizontal" size="xs" alignItems="center">
                    {refreshing && <Spinner size="normal" />}
                    <Badge color="blue">{uniqueSessions} session{uniqueSessions !== 1 ? "s" : ""}</Badge>
                  </SpaceBetween>
                }
              >
                Sessions
              </Header>
            }
          >
            <SpaceBetween size="l">
              <SpaceBetween direction="horizontal" size="xs" alignItems="center">
                <SegmentedControl
                  selectedId={windowMinutes}
                  onChange={({ detail }) => setWindowMinutes(detail.selectedId)}
                  options={TIME_WINDOWS}
                />
                <Box color="text-status-inactive" fontSize="body-s">
                  Auto-refreshes every 15s
                </Box>
              </SpaceBetween>

              {error && (
                <Alert type="error" header="Failed to load sessions">
                  {error}
                </Alert>
              )}

              {loading ? (
                <Box textAlign="center" padding="xxl">
                  <Spinner size="large" />
                </Box>
              ) : (
                <SessionList sessions={sessions} />
              )}
            </SpaceBetween>
          </ContentLayout>
        }
      />
    </>
  );
}
