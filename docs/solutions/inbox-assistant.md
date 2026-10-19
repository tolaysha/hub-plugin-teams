---
title: Keep Inbox assistant routing, private context and approval consistent
scope: repo
area: inbox
tags: [prompts, context, drafts, approval, routing]
created: 2026-10-15
status: active
---

## Problem
Manual drafting omitted owner guidance. A one-line reason did not explain the thread or next action, and a
misheard assistant name could encourage sending the request to an unrelated route.

## Root cause
Automatic and manual builders carried separate instructions. Existing clients split private notes from the
reply, but a prompt could ask for no post when only private context was appropriate.

## Solution
Share assistant_contract(st), including cfg.prompt, verified Context and one approval-aware Next action. Keep
the canonical selected Hub route. Preserve reply-to-post and owner-only sends; context-only begins with ---.
Unavailable history stays unknown rather than triggering a browser/connector or a fabricated response.

## How to apply
Use docs/spec-inbox-assistant.md. Run tools/check.py with HUB_CORE pointing to core source. Prompt checks prove
owner guidance/data boundaries; split fixtures prove private fields stay out of recipient text. They do not
prove model adherence or a signed per-request result. asked.rid is dispatch acknowledgement only. Native
owners own hub/thread/stale response/edit guards; installing the plugin activates source and needs its own gate.
