---
source_url: https://www.instagram.com/reel/DSd4Mcp3dD/
shortcode: DSd4Mcp3dD
creator: sample_creator_four
date_added: '2026-10-01'
category: agents-and-automation
problem: Claude can't see GitHub issues and pull requests
approach: Add the GitHub MCP server with claude mcp add
pinned: true
tools:
- Claude Code
- GitHub MCP server
tags:
- mcp
- github
---

## Summary

With the GitHub MCP server connected, Claude can read and comment on issues and pull requests directly.

## The technique

Register the GitHub MCP server at user scope so it's available in every project.

## Step-by-step instructions

1. Create a GitHub personal access token
2. Run `claude mcp add --scope user github -- npx -y @modelcontextprotocol/server-github`
3. Set `GITHUB_PERSONAL_ACCESS_TOKEN` in the server's environment
4. Check it with `claude mcp list`

## Prerequisites

- Node.js
- A GitHub token

## When this is useful

When you manage issues and PRs while coding.

## Caveats

- If you already use the gh CLI, Claude can do most of this through Bash without a server

<details>
<summary>Raw transcript and on-screen text</summary>

### Transcript

```text
Give Claude GitHub. claude mcp add, scope user, github, then your token. Now it reads your issues.
```

### On-screen text

```text
claude mcp add --scope user github
```

</details>
