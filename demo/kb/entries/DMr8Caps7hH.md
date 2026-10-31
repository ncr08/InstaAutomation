---
source_url: https://www.instagram.com/reel/DMr8Caps7hH/
shortcode: DMr8Caps7hH
creator: demo_creator_eight
date_added: '2026-10-12'
category: content-creation
problem: Captioning talking-head videos by hand takes ages
approach: Transcribe with Whisper and burn the captions in with ffmpeg
pinned: false
tools:
- Whisper
- ffmpeg
tags:
- video
- captions
---

## Summary

Whisper writes a subtitle file from the audio, and ffmpeg burns it into the video in one command.

## The technique

Generate an `.srt` with Whisper, then render it onto the video with ffmpeg's subtitles filter.

## Step-by-step instructions

1. Run `whisper talk.mp4 --output_format srt`
2. Fix any misheard words in `talk.srt`
3. Run `ffmpeg -i talk.mp4 -vf subtitles=talk.srt captioned.mp4`

## Prerequisites

- Whisper and ffmpeg installed

## When this is useful

For short videos you post with burned-in captions.

## Caveats

- Names and jargon are often misheard, so proofread the subtitles

<details>
<summary>Raw transcript and on-screen text</summary>

### Transcript

```text
Captions in two commands. Whisper makes the srt, ffmpeg burns it in. Done.
```

### On-screen text

```text
```

</details>
