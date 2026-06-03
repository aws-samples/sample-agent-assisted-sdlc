#!/bin/bash
# Blocks GitHub-facing content (comments, PR titles/bodies, commit messages)
# that contains @-mentions of agent persona names or trailing agent-name
# signoffs. The orchestrator skill names the agent "dev-claude" for
# prompt-internal use; if the agent writes that as `@dev-claude` it pings a
# real GitHub user (github.com/dev-claude, ID 144746186). This hook is the
# enforcement layer — instructional rules in skills are too easy to drift
# past.
#
# Exit 2 = block (Claude Code surfaces stderr to the agent for self-correction).
# Exit 0 = allow.
#
# Inspects, depending on the tool:
#   add_issue_comment         -> .tool_input.body
#   add_pull_request_comment  -> .tool_input.body
#   issue_write               -> .tool_input.body (when present)
#   create_pull_request       -> .tool_input.body  AND  .tool_input.title
#   push_files                -> .tool_input.message
#
# Forbidden patterns (case-insensitive):
#   - @dev-claude / @devclaude
#   - @claude
#   - Trailing signoff line of the form `^—\s*@?<name>$` where <name> is a
#     persona token (dev-claude, claude, bot, agent, dev-claude-bot, etc.)
#
# NOT blocked:
#   - Issue/PR cross-references like #42 (intentional)
#   - @<handle> for handles not on the persona list (legitimate user pings)
#
# Limitation: does not exempt code fences. Putting persona names inside a
# code block to demonstrate the rule will trip the hook. Acceptable for
# v1 — agents have no legitimate reason to put persona names in code
# blocks.

set -euo pipefail

INPUT=$(cat)

# Pull every body / title / message field we care about into one blob.
# `// empty` keeps jq from emitting "null" as text. The `-r` outputs raw
# strings; concatenating with newlines is fine because we only grep.
CONTENT=$(echo "$INPUT" | jq -r '
  [
    .tool_input.body    // empty,
    .tool_input.title   // empty,
    .tool_input.message // empty
  ] | join("\n")
' 2>/dev/null || true)

if [ -z "$CONTENT" ]; then
  exit 0
fi

# Persona @-mentions. -i for case-insensitive. -E for extended regex.
# \B before @ means "not preceded by a word char" — avoids matching
# emails like user@dev-claude.example (uncommon, but cheap to be safe).
if echo "$CONTENT" | grep -qiE '(^|[^[:alnum:]_])@(dev-claude|devclaude|claude|coding-assistant|sdlc-ai-developer)\b'; then
  echo "BLOCKED: comment contains @-mention of an agent persona name." >&2
  echo "" >&2
  echo "Persona names from skill prompts (e.g. 'dev-claude') must NEVER appear" >&2
  echo "as @ mentions in GitHub-facing content. They will notify real GitHub" >&2
  echo "users who happen to own those handles." >&2
  echo "" >&2
  echo "Fix: remove the @ prefix (e.g. '@dev-claude' -> 'the agent'), or drop" >&2
  echo "the signoff line entirely. The comment author is shown in the GitHub" >&2
  echo "UI header automatically; manual signoffs are redundant." >&2
  exit 2
fi

# Trailing agent-name signoff lines. The em-dash (— U+2014) is the marker
# the orchestrator and other skills emit. Match a line consisting of
# em-dash + optional spaces + optional @ + a persona token, optionally
# trailed by whitespace, anchored end-of-line. Use literal UTF-8 bytes.
if echo "$CONTENT" | grep -qiE '(^|\n)—[[:space:]]*@?(dev-claude|devclaude|claude|coding-assistant|sdlc-ai-developer|bot|agent)[[:space:]]*$'; then
  echo "BLOCKED: comment ends with an agent-name signoff line." >&2
  echo "" >&2
  echo "Signoffs like '— dev-claude' or '— @claude' are redundant — the" >&2
  echo "GitHub App that posts the comment is already shown as the comment" >&2
  echo "author. They also risk pinging real users when prefixed with @." >&2
  echo "" >&2
  echo "Fix: remove the trailing signoff line." >&2
  exit 2
fi

exit 0
