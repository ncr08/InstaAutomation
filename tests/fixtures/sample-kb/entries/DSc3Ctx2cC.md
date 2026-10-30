---
source_url: https://www.instagram.com/reel/DSc3Ctx2cC/
shortcode: DSc3Ctx2cC
creator: sample_creator_three
date_added: '2025-11-20'
category: context-and-memory
problem: A long CLAUDE.md wastes context in every session
approach: Keep CLAUDE.md short and pull details in with @imports
pinned: false
tools:
- Claude Code
tags:
- claude-md
- context
---

## Summary

Everything in CLAUDE.md is loaded into every session. Keep it to the rules that always apply and move reference material into separate files it imports.

## The technique

Write a short CLAUDE.md and reference longer docs with `@path/to/file.md` import lines.

## Step-by-step instructions

1. Move long sections of CLAUDE.md into files under `docs/`
2. Replace each with a line like `@docs/testing.md`
3. Run `/memory` to check what is loaded

## Prerequisites

- A project with a CLAUDE.md

## When this is useful

When CLAUDE.md has grown past a page or two.

## Caveats

- Imported files are still loaded at startup, so this organises context rather than shrinking it

<details>
<summary>Raw transcript and on-screen text</summary>

### Transcript

```text
Your claude md is too long. Split it up, use at imports, check with slash memory.
```

### On-screen text

```text
@docs/testing.md
```

</details>
