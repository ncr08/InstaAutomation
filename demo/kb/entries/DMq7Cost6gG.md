---
source_url: https://www.instagram.com/reel/DMq7Cost6gG/
shortcode: DMq7Cost6gG
creator: demo_creator_seven
date_added: '2026-10-15'
category: models-and-costs
problem: API bills add up even for simple tasks
approach: Route easy tasks to a small, cheap model and keep the big one for hard ones
pinned: false
tools:
- Claude API
tags:
- costs
- model-routing
---

## Summary

Most requests in an app are simple. Sending those to a small model and only the hard ones to a large model cuts the bill without hurting quality.

## The technique

Classify each request first, then pick the model by difficulty.

## Step-by-step instructions

1. List the request types your app sends
2. Send classification, extraction and short rewrites to the small model
3. Keep long reasoning and code generation on the large model
4. Compare cost and quality for a week

## Prerequisites

- An app that calls an LLM API

## When this is useful

When most of your traffic is short, routine requests.

## Caveats

- Check the small model's output quality on real examples first

<details>
<summary>Raw transcript and on-screen text</summary>

### Transcript

```text
You don't need the biggest model for everything. Route the easy stuff to the small one and watch your bill drop.
```

### On-screen text

```text
```

</details>
