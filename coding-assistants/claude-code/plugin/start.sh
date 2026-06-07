#!/bin/bash
# Launch claude interactively inside the AgentCore runtime.
# Usage: bash /mnt/workplace/gitproject/start.sh
#   or:  bash /mnt/workplace/gitproject/start.sh --resume

export CLAUDE_CONFIG_DIR=/mnt/workplace/.claude-data
export CLAUDE_CODE_USE_BEDROCK=1
export CLAUDE_CODE_ENABLE_TELEMETRY=1
export CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1
export OTEL_LOG_TOOL_DETAILS=1

cd /mnt/workplace/gitproject

if [ "$1" = "--resume" ]; then
  # Resume the pipeline's conversation
  PROJECT_FILE="/mnt/workplace/gitproject/.dev-claude/project.json"
  if [ ! -f "$PROJECT_FILE" ]; then
    echo "Error: $PROJECT_FILE not found. No session to resume."
    exit 1
  fi
  SESSION_ID=$(python3 -c "
import json, uuid
d = json.load(open('$PROJECT_FILE'))
owner = d.get('owner','')
repo = d.get('repo','')
issue = d.get('issue_number', 0)
sid = f'sdlc-{owner}-{repo}-issue-{issue:05d}-run'.ljust(33,'0')
print(uuid.uuid5(uuid.NAMESPACE_DNS, sid))
" 2>/dev/null)
  if [ -n "$SESSION_ID" ]; then
    exec claude --resume "$SESSION_ID" --plugin-dir /mnt/workplace/gitproject
  else
    echo "Error: could not derive session ID from $PROJECT_FILE"
    exit 1
  fi
else
  # Fresh interactive session
  exec claude --plugin-dir /mnt/workplace/gitproject "$@"
fi
