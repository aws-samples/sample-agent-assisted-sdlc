#!/bin/bash
# Prevents the agent from setting the {prefix}:start label (user-only trigger).
# Exit 2 = block, Exit 0 = allow.

INPUT=$(cat)
LABELS=$(echo "$INPUT" | jq -r '.tool_input.labels // [] | .[]' 2>/dev/null)

LABEL_PREFIX="${SDLC_LABEL_PREFIX:-agent}"
TRIGGER_LABEL="${LABEL_PREFIX}:start"

if echo "$LABELS" | grep -q "^${TRIGGER_LABEL}$"; then
  echo "BLOCKED: ${TRIGGER_LABEL} is a user-only label. The agent cannot set it."
  exit 2
fi

exit 0
