---
title: Correct false Inbox closure without losing an unsent draft
scope: repo
area: inbox
tags: [identity, replay, drafts, correction]
created: 2026-10-15
status: active
---

## Problem
An unread item disappears after reading, leaving its unsent draft inaccessible.
Unverified cached history can also belong to another contact.

## Root cause
`run_sources` converted missing unread boxes into `owner_last=now`. Clients kept an
insert-only answered set. Reposting `msg` would change the source post used by drafts.
The history consumer trusted a cache command without validating row identity.

## Solution
Do not infer replies from unread markers. `corrections.plan_reopen` checks accepted
source/closure posts, latest item/contact and closure, and successful sends. The
collector also checks its stored WhatsApp destination. A plugin `reopened` fact is
`{id, post, corrects, contact, reset_history:true}`. Only the latest exact closure is
removed; source post and draft replies remain. The web initializes an unsent editor
from its saved draft if no owner edits exist. No send is triggered by reopening.
Duplicate corrections are idempotent. Missing retained source evidence refuses.

## How to apply
Adopt producer/web and native handling together before queuing the local operator
command documented in README. Native clients must track closure post references,
validate the correction, remove answered only, preserve selection/edits/draft/source,
and clear derived thread/parts/pagination on `reset_history`. A `thread_failed`
fact `{id,reset_history:true,error}` also clears unverified derived history.
The current web has no source-thread-history renderer; it consumes closure corrections.
WA rows require `source:{version:1,channel,account,peer,raw_id,captured_at}` matching
the configured expected account and requested peer; keep `source` in projected rows.
Legacy/mixed rows fail as a whole. No browser fallback, journal deletion or cache
migration. Source checks do not establish UI visibility or authorize activation.

## Verification
Offline Python tests cover unread loss across restart, source/account mismatches,
stale/sent/wrong-author corrections and destination checks. Node replay covers draft
identity, unsent editor, owner edits, duplicate events and successful-send protection.
Phone/desktop rendered checks and the real correction remain activation gates.
