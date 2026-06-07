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
  SESSION_ID=$(cat .dev-claude/project.json 2>/dev/null | python3 -c "
import json, sys, uuid
try:
    d = json.load(sys.stdin)
    owner = d.get('owner','')
    repo = d.get('repo','')
    issue = d.get('issue_number', 0)
    sid = f'sdlc-{owner}-{repo}-issue-{issue:05d}-run'.ljust(33,'0')
    print(uuid.uuid5(uuid.NAMESPACE_DNS, sid))
except:
    pass
" 2>/dev/null)
  if [ -n "$SESSION_ID" ]; then
    exec claude --session-id "$SESSION_ID" --resume --plugin-dir /mnt/workplace/gitproject
  else
    exec claude --resume --plugin-dir /mnt/workplace/gitproject
  fi
else
  # Fresh interactive session
  exec claude --plugin-dir /mnt/workplace/gitproject "$@"
fi
