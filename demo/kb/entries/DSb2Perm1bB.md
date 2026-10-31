---
source_url: https://www.instagram.com/reel/DSb2Perm1bB/
shortcode: DSb2Perm1bB
creator: sample_creator_two
date_added: '2026-02-03'
category: coding-agents
problem: Too many permission prompts slow Claude Code down
approach: Allowlist routine commands in Claude Code settings
pinned: false
tools:
- Claude Code
tags:
- permissions
---

## Summary

An older take on the same fix: put the commands you always approve into the allow list so Claude Code stops asking.

## The technique

Use the `/permissions` command to add allow rules interactively instead of editing JSON.

## Step-by-step instructions

1. Run `/permissions` in Claude Code
2. Choose Add rule and enter `Bash(ls:*)`
3. Save it to user settings

## Prerequisites

- Claude Code installed

## When this is useful

When approval prompts break your flow.

## Caveats

- Rules saved to project settings only apply in that repo

<details>
<summary>Raw transcript and on-screen text</summary>

### Transcript

```text
Type slash permissions, add rule, bash ls star, save to user settings. No more prompts.
```

### On-screen text

```text
/permissions
```

</details>
