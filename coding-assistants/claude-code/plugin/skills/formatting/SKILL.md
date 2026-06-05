---
name: formatting
description: Markdown formatting rules for issue comments, PR bodies, and .md files written by the pipeline
---

Apply to all `.md` files you write AND every issue/PR comment you post.
Ignore for code blocks, tables, and bulleted lists.

- Do NOT hard-wrap paragraphs at a column limit (no 70- or 80-char wraps). Write one paragraph per line and let the renderer wrap. Hard wrapping makes diffs noisy and future edits painful.
- Use ATX-style headings (`#`, `##`, `###`). Don't stack equivalent headings.
- Match the existing project's heading hierarchy and bullet style.
- Issue comments: prefix with the designated `### Report` heading. Do NOT add `#` or `##` inside the body — start subsections at `###` or lower.
- The PR body starts at `##` (What / Why / How / Testing) — no `#` H1.
- Refer to critique findings as "Finding N", NOT "Issue #N" or "#N". NEVER write a bare "#N" — GitHub auto-links to unrelated issues.
