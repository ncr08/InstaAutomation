---
source_url: https://www.instagram.com/reel/DMo5Hook4eE/
shortcode: DMo5Hook4eE
creator: demo_creator_five
date_added: '2026-10-24'
category: coding-agents
problem: Claude Code leaves code unformatted after its edits
approach: Run the formatter automatically with a PostToolUse hook
pinned: true
tools:
- Claude Code
- Prettier
tags:
- hooks
- formatting
---

## Summary

A hook runs your formatter every time Claude edits a file, so you never have to remind it or fix the formatting yourself.

## The technique

Add a `PostToolUse` hook matching `Edit|Write` that runs the formatter on the edited file.

## Step-by-step instructions

1. Open `.claude/settings.json` in the repo
2. Add a `PostToolUse` hook with matcher `Edit|Write`
3. Set its command to `npx prettier --write "$CLAUDE_FILE_PATHS"`
4. Edit a file with Claude and check it comes out formatted

## Prerequisites

- Claude Code installed
- A formatter set up in the project

## When this is useful

When you keep asking Claude to format its own changes.

## Caveats

- A slow formatter slows down every edit

<details>
<summary>Raw transcript and on-screen text</summary>

### Transcript

```text
Stop telling Claude to run prettier. Add a post tool use hook and it formats every file it touches.
```

### On-screen text

```text
```

</details>
