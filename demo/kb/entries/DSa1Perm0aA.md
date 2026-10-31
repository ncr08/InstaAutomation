---
source_url: https://www.instagram.com/reel/DSa1Perm0aA/
shortcode: DSa1Perm0aA
creator: sample_creator_one
date_added: '2026-09-12'
category: coding-agents
problem: Claude Code keeps stopping to ask permission for harmless commands
approach: Allowlist safe commands under permissions.allow in settings.json
pinned: false
tools:
- Claude Code
tags:
- permissions
- settings
---

## Summary

Claude Code asks before every shell command it hasn't been allowed to run. Allowlisting the read-only ones you run constantly removes most prompts without giving up safety.

## The technique

Add rules like `Bash(git status)` or `Bash(npm run test:*)` to `permissions.allow` in `~/.claude/settings.json` (all projects) or `.claude/settings.json` (one repo).

## Step-by-step instructions

1. Open `~/.claude/settings.json`
2. Add `"permissions": {"allow": ["Bash(git status)", "Bash(git diff:*)", "Bash(npm run test:*)"]}`
3. Restart Claude Code and check with `/permissions`

## Prerequisites

- Claude Code installed

## When this is useful

When you approve the same harmless commands many times a session.

## Caveats

- Never allowlist commands that delete or push

<details>
<summary>Raw transcript and on-screen text</summary>

### Transcript

```text
Stop clicking yes a hundred times. Open your settings json, add a permissions allow list with git status, git diff, your test command. Restart, done.
```

### On-screen text

```text
"permissions": {"allow": ["Bash(git status)"
```

</details>
