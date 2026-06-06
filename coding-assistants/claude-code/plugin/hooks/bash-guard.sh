#!/bin/bash
# Blocks destructive or out-of-scope bash commands.
# Exit 2 = block, Exit 0 = allow.

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

if [ -z "$COMMAND" ]; then
  exit 0
fi

# Block destructive filesystem operations outside workspace and /tmp
if echo "$COMMAND" | grep -qE 'rm\s+(-[a-zA-Z]*[rf]){1,}.*\s+/[^mt]'; then
  echo "BLOCKED: Destructive rm command targeting paths outside workspace."
  exit 2
fi

# Block force push (short flag -f, long flag --force, refspec +syntax)
if echo "$COMMAND" | grep -qE 'git\s+push\s+.*(--force|-f|\+[a-zA-Z])'; then
  echo "BLOCKED: Force push is not allowed."
  exit 2
fi

# Block environment variable leaks
if echo "$COMMAND" | grep -qE '(^|\s|;|&&|\|)(env|printenv|set|/usr/bin/env)(\s|$|;|&&|\|)'; then
  echo "BLOCKED: Environment variable dump could leak secrets."
  exit 2
fi
if echo "$COMMAND" | grep -qE 'python.*os\.environ|node.*process\.env'; then
  echo "BLOCKED: Environment variable access via scripting language."
  exit 2
fi

# Block curl/wget posting to external URLs (data exfiltration)
if echo "$COMMAND" | grep -qE '(curl|wget).*(-d|--data|--post|--upload-file|-T|-F).*http'; then
  echo "BLOCKED: Posting data to external URLs is not allowed."
  exit 2
fi
if echo "$COMMAND" | grep -qE 'curl.*@.*http'; then
  echo "BLOCKED: Uploading file content to external URLs is not allowed."
  exit 2
fi

# Block writes outside workspace (grep -E doesn't support lookahead, so use inverse match)
if echo "$COMMAND" | grep -qE '>\s*/' && ! echo "$COMMAND" | grep -qE '>\s*/(mnt/workplace|tmp)/'; then
  echo "BLOCKED: Writing to paths outside /mnt/workplace/ is not allowed."
  exit 2
fi

exit 0
