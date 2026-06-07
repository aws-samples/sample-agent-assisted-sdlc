#!/bin/bash
# Restricts GitHub MCP operations to the assigned repo/issue only.
# Reads project.json for allowed scope. Exit 2 = block, Exit 0 = allow.

INPUT=$(cat)
TOOL_INPUT=$(echo "$INPUT" | jq -r '.tool_input // {}')

PROJECT_FILE="./.dev-claude/project.json"
if [ ! -f "$PROJECT_FILE" ]; then
  echo "BLOCKED: project.json not found — cannot verify scope"
  exit 2
fi

ALLOWED_OWNER=$(jq -r '.owner' "$PROJECT_FILE" 2>/dev/null)
ALLOWED_REPO=$(jq -r '.repo' "$PROJECT_FILE" 2>/dev/null)
ALLOWED_ISSUE=$(jq -r '.issue_number' "$PROJECT_FILE" 2>/dev/null)

# Check owner
INPUT_OWNER=$(echo "$TOOL_INPUT" | jq -r '.owner // empty')
if [ -n "$INPUT_OWNER" ] && [ "$INPUT_OWNER" != "$ALLOWED_OWNER" ]; then
  echo "BLOCKED: owner '$INPUT_OWNER' != allowed '$ALLOWED_OWNER'"
  exit 2
fi

# Check repo
INPUT_REPO=$(echo "$TOOL_INPUT" | jq -r '.repo // empty')
if [ -n "$INPUT_REPO" ] && [ "$INPUT_REPO" != "$ALLOWED_REPO" ]; then
  echo "BLOCKED: repo '$INPUT_REPO' != allowed '$ALLOWED_REPO'"
  exit 2
fi

# Check issue_number (for issue operations)
INPUT_ISSUE=$(echo "$TOOL_INPUT" | jq -r '.issue_number // empty')
if [ -n "$INPUT_ISSUE" ] && [ "$INPUT_ISSUE" != "$ALLOWED_ISSUE" ]; then
  echo "BLOCKED: issue_number '$INPUT_ISSUE' != allowed '$ALLOWED_ISSUE'"
  exit 2
fi

# Check branch (for push/branch/PR operations)
BRANCH=$(echo "$TOOL_INPUT" | jq -r '.branch // .ref // .head // empty')
if [ -n "$BRANCH" ]; then
  if [[ "$BRANCH" == "main" || "$BRANCH" == "master" ]]; then
    echo "BLOCKED: cannot target protected branch '$BRANCH'"
    exit 2
  fi
  if [[ "$BRANCH" != "feat/issue-${ALLOWED_ISSUE}" ]]; then
    echo "BLOCKED: branch '$BRANCH' != allowed 'feat/issue-${ALLOWED_ISSUE}'"
    exit 2
  fi
fi

exit 0
