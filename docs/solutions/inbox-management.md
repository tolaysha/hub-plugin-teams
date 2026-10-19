---
title: Shared Inbox delivery and private revision binding
scope: repo
area: inbox
tags: [delivery, revision, identity]
created: 2026-10-15
status: active
---

## Problem
Different manual/automatic request IDs could submit the same source version;
private instructions and empty edits were dropped, and empty success looked Sent.

## Root cause
Request-ID deduplication had no canonical version/editor claim. Raw assistant output
and transport exit success lacked source-bound completion evidence.

## Solution
The one collector writer persists a source/account/conversation claim before IO.
Versioned editor holds persist across restart at verified account/conversation
scope, so a new incoming row cannot race client polling or inherit an unheld state.
Per-item source tokens remain current-version CAS; matching manual Send consumes
the conversation hold and claim atomically. Legacy row holders migrate without
dropping conflicts, and canceled deferred replies hold the conversation too.
Check the actual account/source
immediately before transport; require a real message ID. Unknown outcomes stay held.
Bind private proposals to canonical Hub generation, request nonce, source and editor;
publish a plugin-authored explicit-Apply proposal, never an unsafe raw replacement.
After a verified Send, issue a fresh source token anchored to its actual outgoing
receipt/body for manual-only follow-ups. Recheck that own message against the source
before the next claim; keep automatic work closed. Match payload before returning
a duplicate receipt, and replay a completed versioned request without transport IO.

## How to apply
Use docs/inbox-management.md and the full offline local gate. Keep guard disabled
until every active client adopts it. Mocked receipts prove code behavior, not live
delivery. Unsupported adapters and incomplete canonical coverage remain explicit.
