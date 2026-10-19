---
title: Shared Inbox task content without guessed task identity
scope: repo
area: web
tags: [inbox, plugins, tasks]
created: 2026-10-15
refs: [tests/task-body.test.mjs]
status: active
---
## Problem
Inbox text had its own presentation and lacked core task completion/decision context.

## Root cause
Incoming message IDs and prose do not identify a core task; matching them by words
would create actions with no explicit source relationship.

## Solution
Feature-detect the additive core taskBody/taskDecision helpers. Only an explicit
task_id matching snapshot.todo supplies task content and completion or actual choices.
Retain a queue/error/closed presentation node without altering reply/delivery state.
Older hubs keep literal text. Rendering and navigation send nothing.

## How to apply
Run the offline local gate with the core dependency on PYTHONPATH/HUB_CORE.
Check explicit and unknown IDs, actual choices, refusals, repeat clicks, queued
receipts, snapshot closure and the older-hub fallback. Source checks are not live
rendering or deployment. Do not invent a task association in the collector.
