---
title: A shared reply editor must retain collector identity and delivery truth
scope: repo
area: web
tags: [composer, inbox, identity, delivery]
created: 2026-10-15
status: active
---

## Problem
The legacy textarea lacked shared behavior and could group unrelated people with
the same display name. A visual migration could also lose collector CAS/receipt checks.

## Root cause
Editor and transport state lived in separate ad hoc UI handlers. Names doubled as
conversation keys. A queued feed post had no delivery authority.

## Solution
Use capability-gated shared input with explicit transport. Keep a protocol state
controller for acknowledged holds, exact private revision and local explicit Apply.
Retain submitted text through queued/unknown outcomes; only a matching receipt
closes the editor. Group by source contact/box identity; never merge unknown names.
Bound serialized requests before the feed can truncate them.

## How to apply
Run tools/check.py with HUB_CORE set to the matching web source. Browser fixtures
use an isolated real journal and synthetic collector facts, never provider accounts.
Assert prerequisite acknowledgements and matching proposal IDs before clicking.
Capture both themes and responsive widths. Offline receipts establish controller
behavior only; installation, policy activation and live delivery remain separate.

## Actual editing boundary
Opening or prefilling the editor does not acquire a new hold. The first owner
reply or private instruction input confirms it; intentional empty edits remain
held. Existing holds survive navigation, and closing a never-edited preview does
not release another editor. Incidental group/filter totals are omitted; explicit
bulk-action confirmation counts remain.

## Proposal visibility
The proposal body is bounded and scrolls separately from its Apply button. It
lives outside the private instruction disclosure, so receiving a result never
hides Apply below that disclosure's clipping boundary or moves the pinned reply.
The real-browser check verifies hit-testing the visible Apply action on390px.

## Durable owner text
Keep owner text in origin-local storage keyed by source, exact account/conversation,
and inbound message. Store the submitted request ID alongside a pending draft.
A matching accepted receipt may clear that record, but must never erase a newer
edit. Navigation and reload do not acquire a hold or replay a send. A blocked
store keeps the current text and displays an explicit save warning.
Browser action-spool reads consume events: after `queued("send")` asserts the
original request, the reload assertion must expect zero additional requests.

## Media continuity during feed updates
Keep the active conversation and unchanged media subtrees connected while replacing
other content. Replacing the whole thread resets a playing audio/video element.
Shared task-body renderers move their cached text nodes into the newly rendered
row, so retaining an old row wholesale loses text. Refresh its non-media children
and retain only the identical media subtree. The pinned native fixture with a
valid synthetic MP4 proves playback, pause and audio continuity during an unrelated
incoming message; the normal plugin gate also checks node identity and retained text.


### New-message interrupted delivery
A pending POST restored after reload is uncertain, not permanently sending. Keep its original rid, recipient and payload; lock recipient switching and show the original message beside an explicitly labelled retry. Text edited meanwhile remains a separate draft. A 30s receipt watchdog offers the same recovery without automatic submission. Search Enter must search rather than implicitly submit the form. Failed browser storage must be visible, and contact results need live announcements and an explicit control relationship. Hostile-review findings were reproduced with real synthetic browser interactions before repair; no provider calls.


### Scheduled replies and unknown collector outcomes
Unschedule posts the existing cancel protocol with the exact source id, delivery rid and editor identity. Keep the scheduled item visible until the collector confirms the matching source and rid; refusal/timeout leaves a retry. Cancellation releases only the local pending marker, preserving later text/files and the collector editor hold. A send_failed fact with unresolved:true is not a definitive refusal: retain the original pending delivery and same-rid recovery, including across reload. Never turn uncertainty into a fresh delivery id.

Cancellation facts are replayed from history on reload. Only release a stored pendingRid when it equals the canceled rid (or this page initiated the active cancellation); never clear a newer pending reply. A real reload regression reproduced the old cancellation clearing the new receipt binding, and checks the new matching receipt still clears the delivered draft.

### Suggested reply with a lost web acknowledgment
The legacy suggested-reply button treated a failed HTTP acknowledgment as a definitive
delivery refusal, enabling another Send with a new rid. Preserve unresolved state and
the original draft until a matching collector receipt arrives, as the shared composer
already does. Only change a still-waiting request: a collector outcome arriving first
must not be overwritten by a late HTTP failure. Reproduce by accepting the synthetic
POST, then throwing away its response; verify the suggestion remains disabled and the
exact sent receipt resolves it without another request.


### Context menus for historical messages
A history row has no ordinary source post of its own. Preserve the trusted thread post
and chunk location when ingesting history, then send the native ask fields: source
post, place, provider msg, from and at. Do not substitute the display row ID or raw
message text. Resolve menu identity again at activation, and close on source rebind.
Keep context menus inside the viewport at narrow widths; verify their actual masks
as well as dimensions, because missing CSS mask bindings render solid icon squares.


Context-menu follow-through: outside-dismiss handlers must run before a new row's
long-press timer is armed, or the same bubbling event cancels the next gesture.
Re-resolve the row element after refresh before opening or restoring focus. Work
quotes need the same trusted history location as Draft; the latest source post is
not the historical message. Copy the display text, omitting media placeholders.


### Consume only the captured action-spool snapshot
The browser can write a new fact while the fixture is inspecting an earlier one.
Deleting every directory entry after spool.take can remove an unfinished atomic
`.tmp` file or a newer completed request that the test never inspected. Consume
only the exact paths returned by take. The deterministic fixture regression
keeps an in-flight file and inserts a second fact after the snapshot; both must
remain available. This is fixture ownership, not a product retry or a weakened
recipient/delivery assertion.


### Preserve conversation menu state across feed refresh
The conversation header is rebuilt while message/media rows retain identity.
An open details menu and its focused action therefore need explicit restoration
only when the stable conversation key still matches. Scope persisted local
preferences independently from provider read state. Lazy storage access keeps
browsers that refuse localStorage from breaking module initialization; failed
writes must not be reflected as a saved pin.

Local preference caches must compare their stored serialization before mutations;
a cache keyed only by Hub silently loses changes made in another already-open tab.
Use the storage event to refresh visible state, preserving the current draft.
Shared menu styling does not justify reusing an editor-specific selector on an
unrelated conversation control: give each control its own semantic class.


### Local unread is a reminder, not a provider action
Do not implement Mark unread by deleting a seen ID alone: a provider unread=false
flag would immediately hide the reminder. Store an explicit local override using
exact Hub/source/conversation/message identity. Opening sets a local read override
without sending any provider action. Copy the cached Map before a write: a refused
setItem must not mutate the visible reminder. Keep draft storage independent and
return focus to the exact conversation row after marking unread.

Unread failure and flat-card actions restore focus to the same visible menu
summary. After a failed storage write, rendering a closed menu cannot focus its
now-hidden action; an explicit summary target is required. A grouped reminder
returns focus to its exact conversation row instead.


### 2026-10-17 — Read preference failures stay visible
Opening a conversation surfaces a failed local read write, leaves the reminder
unchanged, and keeps the editor usable. A successful retry clears that error.
Empty targets cannot report a saved reminder. Read preferences refuse growth
beyond 256 Ki characters per Hub, without deleting old reminders, to limit their
share of origin storage. This is a bounded stop, not a guarantee of free browser
quota; compaction and stable Hub rename migration remain separate work.


### Provider read recovery and menu bounds
`provider-read.js` owns a separate per-Hub receipt ledger, never the local unread reminder. Reload/replay reuses the original request; a source rebind has another target and cannot consume an old receipt. The 256 Ki-character bound compacts settled success records, reserves room for bounded failure receipts, and refuses growth instead of evicting unresolved IDs or drafts. Web Locks serialize request admission across browser tabs. Refused receipt persistence stays pending for same-rid recovery. Do not infer provider success from HTTP acceptance.

Conversation menus are anchored before two other header controls. A viewport-wide max-width can still place their left edge offscreen. Bound width to the space available before those controls and allow status text to wrap. The provider-read browser scenario checks actual menu edges at seven widths, light and dark when capturing.

Native header pseudo-element backdrops can cover positioned menu anchors even when their dropdown is layered. Keep both conversation and editor menu anchors above the backdrop; test hit targets with the actual header decoration, not visibility alone.

### Reply storage admission
A visible draft-storage warning is insufficient if the Send callback proceeds. Check persistence of the pending rid before invoking transport in both shared and fallback composers. If it fails, remove the local unsent pending claim, retain text/files, and restore the shared composer through its existing error-return path. A guarded editor's delivery token is still only local at this point and can be released; never clear a claim after transport has run. Synthetic browser tests cover quota refusal, recovery, guarded/external sources and attachments; the fallback VM test rejects transport while storage is blocked.

### A draft is not the pending delivery ledger
The draft's pendingRid alone does not prevent duplicate sends after reload: typing replaces the draft, and the in-memory sends map disappears. Save the exact request separately before transport and consult that record at admission. Restore guarded delivery context from that record so a receipt must match its original version, not just a visible message id. Preserve newer text independently, settle only the matching request, and never replace an uncertain operation with a fresh rid. Definitive refusal and cancellation release admission; unresolved outcomes do not.

### Send options on different composer versions
Check composerTrailing before using the optional right-side slot and place the menu in leading when absent. Both routes use the same DOM control and grid placement. Keep the date picker outside the parent form's validation association, handle its Enter explicitly, and consume the scheduling intent only for a valid nonempty submission. Otherwise a rejected empty scheduling attempt can silently schedule the next ordinary reply. Preserve focused menu nodes through feed repaint, and check actual popup bounds, Escape and focus at phone/tablet/desktop widths. More-specific existing last-child grid rules can place the trailing menu over Send despite correct DOM order.


### Await the actual request in synthetic acceptance

`requestSubmit()` returns before Web Locks and fetch complete. A single spool snapshot falsely failed three existing delivery cases after durable admission added an asynchronous lock. `queued(kind)` now waits up to five seconds for the actual matching queue event while consuming only completed spool files. A deterministic delayed-event regression covers this; delivery, receipt and newer-draft assertions remain unchanged.


### A conditional folder must fit the same toolbar

The unresolved-reply state adds a fourth folder. Live captures revealed that existing 8px gaps plus 52px padded folder icons pushed Inbox options beyond a 360px viewport and over the desktop conversation pane. The shared toolbar now removes redundant gaps, uses 44px folder targets and 8px outer padding. A seven-width test requires every visible toolbar control to remain within its own list pane and be hit-testable; it preserves folder/sort behavior and draft state.


### A matching request id is not enough for a delivery receipt

Bind the original target alongside rid and preserve it independently from editable draft text. Reject mismatched or missing target before editorFact can apply a receipt; guarded editor-state also rejects it directly. Owner echo must not overwrite a known original target. On reload, restore that binding from the pending request. Browser regressions cover external and guarded replies, wrong/missing target, trusted completion after reload, and newer-draft preservation. Scheduling and the fallback composer propagate the same target. Legacy targetless receipts remain supported only for targetless original requests.


### Recover the original request, not the current draft
An explicit replay can first-submit a request lost before collector admission. Label it Retry original reply, require the trusted reply_replay capability and a target-bound durable request, and send the saved object unchanged. Revalidate the current conversation and pending record inside the handler, because a detached button may outlive a source/config/storage change. Coalesce transport attempts, keep unknown outcomes pending, and preserve newer draft text/files. Guarded duplicate receipts must match the original version before either the editor or outgoing bubble changes state; rejecting settlement alone still falsely paints success and hides recovery.

Capability revocation tests must first observe the enabled control before awaiting its disappearance. Awaiting an already absent control can return before the revocation fact arrives and falsely characterize a stale-button click as a runtime failure.

A replay success can arrive without a live guarded editor to perform cleanup. Mirror fresh-success cleanup in the feed reducer: settle original request, accept only its matching draft tombstone, record answered state, and clear an unguarded composer only if no newer owner draft exists. Regressions cover unchanged external drafts and guarded success after reload with the editor closed.

Live synthetic rendering caught a separate stale global transport alert after confirmed delivery. Reply callers already own unresolved status; mark(send) must not also create a global Hub-unavailable banner that survives the receipt. Shared and fallback paths retain their pending reply and recoverable feedback; unrelated action/storage errors keep their own handling.


### Next opening belongs to the Hub calendar
Use trusted collector hours and the exact contact exception, not the browser timezone or a universal next morning. Resolve the opening as civil time in the configured IANA zone, with an explicit collector offset only as fallback; enumerate offsets across transitions to handle gaps and repeated hours. Labels belong to the device timezone. Recompute on opening and activation so a stale menu never sends a past instant. Keep the shortcut hidden when configuration is absent, and route submission through the existing durable admission rather than adding another transport path. Module checks cover strict-future boundaries, weekend inversions, custom openings, DST transitions and zone fallback; browser checks cover live configuration changes, preserved draft, click-time recalculation and reachable phone/tablet/desktop menu geometry.

A target can change while a draft-key-stable composer remains mounted. Revalidate menu submission identity and explain that the editor must reopen; a silently inert shortcut looks broken. Browser regression preserves the draft and requires zero sends after a target replacement. Config-revocation coverage must first observe the enabled shortcut, and weekday assertions must use the device timezone.


### A reaction is also a destination-bound operation
Binding replies alone left reactions with an id/rid pair and no target. A changed provider reference could receive the reaction, while a wrong-target receipt painted success. Carry target through the request, parser and receipt; verify it before updating reaction state. Detach old reaction requests when the source/contact/target identity changes, reject late owner echoes for the former target, and revalidate the current message when an old DOM control is activated. Keep the local ownership marker when its own echo arrives so a later unrelated echo cannot replace an in-flight local action. Legacy targetless events remain compatible; no automatic resend is introduced.

Live phone acceptance found the list-pane error banner is hidden while a conversation is open. Stale reaction controls now write a destination-scoped notice beside that message; a valid current reaction clears only that notice. The regression runs at390px and verifies zero stale sends, visible feedback and recovery.

The deployed collector and the web staging branch have different integration histories. Use the explicit reaction_target capability instead of assuming that message target support implies reaction parser support; do not import a single parser commit without its collector target/replay prerequisites. A failed partial cherry-pick was aborted, preserving both complete branches. Capability revocation tests must address the picker buttons after opening it, because its trigger is no longer in the DOM.

## Recipient weekend option
The send menu shares working-hours parsing with scheduling. Its weekend checkmark derives from base weekends XOR the exact contact exception. The additive hours_for_bound contract admits a persisted original request, not a naked optimistic toggle. Pending settings have an explicit retry using the original payload/rid; unknown outcomes block replacement requests while allowing the same original request to recover its receipt. Correlated hours_set/hours_failed facts are accepted only from the collector and never write configuration themselves. A later config remains authoritative.
For browser reload coverage navigate through about:blank: repeating the same hash URL can preserve the open menu, so blindly tapping its summary closes it. For palette captures use the app theme API; setting color-scheme alone leaves explicit theme colors unchanged and is not dark-theme evidence.


## Archive identity on replay

Message IDs can be reused with a changed recipient target. Clear the old hidden membership at the same exact-identity transition that detaches reactions and pending reply state. Do not emit an unhide operation: journal replay must reconstruct the same result, while same-identity updates keep their archive state. Regression covers archived original, unchanged identity, replacement target, reload and empty Archive for the replacement.
## Provider-local contact collision
Raw contact IDs merged Telegram and WhatsApp histories while their pins and archive
selection stayed separate. Use the existing source-family/contact pin identity as the
conversation key too; keep Teams categories together. The serialized preference key
must remain unchanged. Reproduce with identical contacts in two providers, then verify
separate history, drafts after reload, unread/pin state and exact archive membership.


## Context and icon drift
The supplied where field already carries the Teams category or provider context. Build the display from provider plus a distinct place, matching native Letter.origin, rather than adding category twice. Test DM, mention, channel, Telegram, WhatsApp and Mail. Shared core SVG icons inherit a different default size than plugin masks; set both explicitly on the action row and test wide tablet as well as desktop. Compact container rules still override both together.


## Native list metadata
Keep name normalization at the display boundary. Stripping bracketed UTC/GMT hour metadata from the stored message would change history/request identity; normalize only visible names and accessible labels. A list needs state marks even while its detail is closed. Derive them from existing authoritative send/reaction state and retained drafts, never from proposal content as if it were a receipt. Preserve uncertainty over success, let a successful retry supersede its own old failure, and keep a newer draft visible. Exercise the actual row renderer as well as pure state helpers; capture native fixture names and proposals in both themes.

Denied storage reads are not proof of a submitted reply. Distinguish unavailable storage from a corrupt existing pending record: both keep submission blocked, but only the latter implies uncertain prior work in list metadata. Reuse the same 150-second late-delivery predicate for list, detail and replay eligibility. Never mutate delivery state or resend merely because the display becomes overdue.

The shared button helper adds btn small; a toolbar font declaration can still lose to core desktop CSS. Measure computed font at tablet/desktop widths, not just the declared size. Scope the native folder rule through .tm so the17px label wins, and retain overflow/hit checks when Failed adds another control.
## Group authors and calendar boundaries

Use one previous-message cursor across loaded history and current messages. Resetting the cursor at that boundary repeats the day and sender; elapsed-hour thresholds miss midnight and repeat the same day after a long gap. Compare local calendar dates for chats and compare normalized display names only for label continuity, retaining raw identity for all storage and provider actions. Preserve the original source object when rendering historical rows so contextual actions retain their exact provider target. Check midnight, same-day gaps, outgoing interruptions, history/current continuity and invalid dates with the real renderer.

Mail is a separate boundary: reset the history cursor before the current mail message so its exact time header remains visible even when older mail arrived one minute earlier. Chat continuity must not erase mail metadata.

Teams surface types share a conversation key, so the newest message source cannot classify every earlier bubble. Use each current message source and honor explicit Teams history source metadata; history without metadata retains its parent source fallback. Flat cards already name their author in the header. Scope desktop header/source CSS to the detail pane so those cards retain one source label, and move the auto top margin to the first visible history child when the desktop source label is hidden.

## Flat source layouts

Hiding a grid detail does not remove its reserved column. Toggle the flat layout from the same source-filter predicate as detail visibility; test both source filters and the return to grouped conversations at phone, tablet and desktop widths. Await the synthetic feed before selecting its dynamically built filter. Group context by provider before deduplicating places: deduplicating full provider/place strings repeats the provider in mixed Teams conversations. Never split a supplied place on its display separator.

## Long reply width

A growing textarea can still be squeezed between discard, attach, send and options columns. Move a wrapped reply into its own full grid row, leaving actions below. Decide wrapping against compact available width rather than current expanded textarea width, otherwise layout can oscillate. Use the existing observer and root resize path; never rebuild the field or normalize draft/signature content to repair presentation. Cover short/long transitions, width changes, selected text, exact send payloads, attachments, scheduling and frozen host slots.

## Search recovery

An empty search is a recoverable result state, distinct from an empty folder. Share the same no-match renderer between grouped and flat lists, with the pinned native query-specific heading and centered action. Route its clear button through the existing search clear control to retain focus and filter behavior. Test literal markup-like queries, centered readable content, hit targets, exact retained drafts, flat filter recovery and truly empty folders.

Resolved themes can assign the same color to accent and muted. An accent-filled button then disappears into the desktop list pane even though default-theme tests pass. Derive this recovery control surface from foreground and muted, and measure the composited pixel difference against the pane under equal accent/muted tokens. Inspect actual deployed theme captures as well as the default test palette.

## Unselected desktop details

Use a separate placeholder node instead of replacing the hidden conversation tree. The latter risks disconnecting a retained editor, recording or draft while the user browses the list. Mirror grouped/selected state for visibility, and suppress the placeholder at the same container breakpoint as the single-pane layout. Exercise resize, close/reopen with the same textarea node, exact draft retention and both flat source filters.

Folder label and flex-space ownership must follow aria-pressed, not the Inbox folder ID. Native Sent and Archive expand their selected label, leaving Inbox as an icon. Check each selection across phone/tablet/desktop and retain the extra Failed-control compact mode; testing only the default Inbox misses this navigation mismatch.

## Outgoing folder previews

Incoming-message text cannot represent a Sent row. Select eligible outgoing states from the existing receipt reducer using the group's exact message IDs, and share that preview with conversation search. Never read the current editor or an unaccepted retry for Sent. Attachment-only replies use filenames; confirmed reactions use their emoji. Missing latest reply text falls back to incoming context, not older reply text. Cover accepted reply plus failed retry, scheduling, attachment-only/reaction receipts, literal markup, grouped latest delivery and unchanged Inbox/draft behavior.

Native row reminders are folder-specific presentation. Gate unread dots, pin marks and pin-first sorting on Inbox instead of deleting stored state while archiving or sending. Exercise Failed → Archive → Inbox → Sent with a pinned older conversation and verify restored reminders and unchanged storage. Selected native folder foreground is white in both themes; test a dark primary-foreground token explicitly rather than relying on the default browser test palette.

Sent must sort by outgoing activity, not the incoming message's age. Share outgoing selection between sorting and preview, merge accepted reply/reaction candidates, use scheduled time for deferred replies and the first accepted receipt time otherwise. Keep request timestamps intact for timeout logic. Add receipt sequence for equal-time ties and preserve metadata on same-rid request/receipt replay. Tests need opposite incoming/outgoing order, delayed confirmation of an earlier request, later failed/waiting attempts, reaction then reply at equal receipt times, duplicate requests/receipts, scheduled time and full reload.


### Reaction history and retries
The latest reaction attempt is not delivery history. Keep a separate confirmed snapshot after the existing exact-rid/target acceptance guard. A waiting or refused replacement must not remove the earlier Sent row or replace its preview. Clear snapshots when the exact destination changes. Regression covers retry, refusal, reload, mismatched receipt, replacement success and rebound identity; original target/draft tests remain in the affected gate. Duplicate successful reply receipts intentionally cannot be undone through false-closure correction: the existing sentOk guard protects delivered messages.


### Sent ordering after flattening
Sorting conversations before flattening is insufficient for flat source-filtered cards. Compute activity per message after search selects matching conversations, then sort that visible list. Share the receipt/schedule fallback with grouped views. The synthetic regression deliberately interleaves delivery order across two messages from one conversation and a third from another, checks search recovery and a later schedule.


### Target-only rebinding
Draft identity is intentionally looser than delivery identity. Clearing sends only when draftKey changed left accepted replies attached to a replaced target. Detach sends and answered markers under pendingReplyKey changes alongside reaction/archive state, leaving draft storage intact. Synthetic acceptance covers stale receipt replay, replacement Inbox eligibility, fresh exact-target receipt, reload, canceled original request and retained edited draft.


### Answered message contrast
Do not dim message content when its workflow becomes done. The previous shared tm-line.tm-done rule reduced contrast in Sent, history and archived content. Compare computed foreground in real themed renders, not only CSS token strings: actual host muted text differed from the default test palette. Regression checks chat/channel/mail, grouped/flat, light/dark and 360/834/1440 widths, preserving outgoing white text.


### Delayed delivery status
Sent sorting already used deliveredTs, but sentBlock still rendered request ts. This made delayed confirmations look old. Use the accepted timestamp for successful reply status in the shared chat/mail renderer, preserving request time for unresolved work and legacy fallback. Regression uses distinct request and receipt times, checks pending first, then accepted status and duplicate receipt stability for both sources. Journal timestamps are millisecond-rounded; use integral fixture seconds for exact assertions.


### Native successful status copy
Use one successful-delivery label and one age node. Removing the owner prefix from a confirmed owner reply is safe only when automatic replies still name the Hub. The shared chat/mail renderer preserves all non-success attribution and error text. Browser acceptance covers owner/automatic success, pending and scheduled attribution, first-receipt age and delivery icons. Actual synthetic flat Sent captures verify the same shared label on the served asset.

### Outgoing signatures and emphasis
Native Emphasis uses Unicode letter/number boundaries to distinguish standalone underscore markup from identifiers. Port that display rule to the shared outgoing renderer without a general HTML/Markdown parser. Construct DOM text and em nodes, preserving literal HTML, line breaks, unclosed runs and source payloads. The regression verifies pending/failed chat and mail rendering and uses Retry to prove the original text survives; successful flat Sent uses actual served assets and synthetic signatures. Close the fixture's initially open editor before testing Retry; otherwise its guard correctly hides that action.

### Flat card spacing
Measure from the previous card's final content to the next header, not only the list's computed gap. A 24px list gap plus two 12px card paddings and an empty action footer's 8px flex gap created 56px of blank space. Make the flat list the sole owner of separation and omit empty footers. Browser acceptance covers phone/tablet/desktop themes and nonempty archive Restore; use unsent archived messages for that fixture because delivered messages intentionally remain in Sent. Grouped media reconciliation handles absent footers through syncChildren.

### Flat search alignment
The search footer belongs to the same reading column as flat cards. Test its left/right edges and icon start at narrow, tablet and wide widths, then type a query and use Clear to verify filtering and returned focus. Scope the width/inset override to tm-flat so grouped list geometry stays intact. Await synthetic source rows before selecting dynamic source filters; otherwise a missing filter/card is fixture timing rather than a layout failure.

### Failed reply action names
The shared sentBlock action opens the editor; call it Edit reply in both visible and accessible text. A retry label is reserved for an action that submits the appropriate request. The existing chat/mail raw-text regression now checks the label and no-send outcome; exact original-request recovery tests remain separate. Native direct retry parity is still open and must not reuse unresolved requests as fresh sends.

### Recovering an old failure beside a newer draft
Do not call openCompose with an old attempt text while inheriting files from the current saved draft. Resume current text and files together. A pendingRid is not permission to replace that draft: the separate pending record still owns exact delivery identity. Browser regression covers chat text plus attachment, attachment-only email, a newer pending WhatsApp request, reload and no additional sends. Preserve failed history and reject stale conversation callbacks.

### Outgoing links and emphasis
Detect link spans against raw text before applying display-only underscore emphasis. Exclude URL-internal delimiter candidates, while retaining emphasis that encloses a link. Construct text nodes, anchors and em elements only; never parse HTML. Trim sentence punctuation and unbalanced closing brackets without altering balanced URL paths. Keep href and visible Unicode text separate through URL parsing. Reuse the renderer for all four outgoing/draft surfaces, with raw payloads held outside the DOM. Browser acceptance covers text safety, URL destinations, wrapping and recovery; pending/proposal/draft tests verify the other call sites.

Strip a leading email underscore only when it is the opener of a recognized emphasis run; otherwise it can be part of the address. End automatic URL candidates at common CJK/Arabic sentence punctuation so adjacent prose cannot become a destination. Keep Unicode path letters and percent-encoded punctuation. Unspaced em-dash prose is ambiguous and remains literal URL input.

### A refused guarded send cannot reuse the old held state
The visible failure clears delivery but leaves an old error and a token that may still look held. Track needsHold separately from that authoritative token. Reset the compose-start marker only after the matching definitive refusal is accepted; a new hold clears the old error but still blocks send until an increasing edit-version receipt arrives. Never do this for unknown delivery. Browser checks cover edit/no-edit resubmit, failed/blocked events, new request identity, current token, old late failures and a newer draft beside an unresolved attempt. When waiting for multiple failures, observe the specific attempt count rather than an already-present old failure card.

### Late delivery facts cannot undo accepted Sent
The feed reducer handled send_failed/send_blocked/scheduled/uncertain independently of the prior request state. An already accepted reply could therefore become failed or disappear from Sent. Reject non-success delivery facts for an accepted request before editorFact runs; make the guarded state machine terminal too, including repeated success receipts beside a newer draft. Keep target/id checks and ordinary pending-to-success handling unchanged. Regression covers guarded/external requests, six late event kinds, a newer draft and full journal replay after reload. Use a subsequent ordered owner echo as the browser-test barrier. Actual-static captures must assert visible content: cached hidden Sent DOM can otherwise falsely pass after the row disappears.

Receipt-first external success may have no preceding owner request and therefore no kind field. A later confirming duplicate must preserve that accepted state rather than require kind=send and downgrade it to unresolved. Hostile review found this adjacent case; a separate browser regression reproduces it without an owner echo or local pending ledger.

### Replay after the collector forgets a failed outcome
The collector keeps request tombstones indefinitely but bounds its detailed outcome cache. Replaying an evicted failed request returns unknown rather than inventing a disposition. A client that already read its definitive failure must preserve that journal evidence before editorFact runs. Guard only the same validated id/target/rid; do not infer that all unknown requests in a successfully retried conversation are settled. Still allow matching actual success. Reproduce failure → fresh retry → success → old unknown, reload the journal, and inject a different unknown request to prove it still blocks sending. Producer exceptions after transport begins must remain uncertain; that classification belongs to the collector owner.

### Compact toolbar surfaces

Native FolderBar uses 32px capsules and 16px icons. On the web, preserve 44px
interactive targets and inset only the painted surface. A pointer-transparent
pseudo-element keeps the entire target clickable without making the native
shape oversized. Scope icon dimensions to the trigger, not its descendant menu.
Check every folder, the extra failed state, both themes, and narrow list panes;
then open sort, compose and options from the rendered controls.

### Shared conversation and draft menu

Keep the draft instruction body as a persistent node when merging its menu into
conversation options. Feed repaint replaces the surrounding menu, so preserve
the active persistent descendant and textarea selection before falling back to
an action key for regenerated buttons. Close editor must close the parent menu
explicitly: the parent now survives after the editor is removed.

Older failed-reply editing tests must target the edit/resume action, not the first
button: direct Retry precedes it for chat. Reproduce stale selector failures on
the unchanged baseline before attributing them to an unrelated header change.

The detail menu key follows the exact conversation rather than its newest message ID: a newly arriving message must not collapse a private instruction mid-entry. Flat cards retain message-specific keys because several cards can belong to the same conversation. Their merged draft menu stays at the trailing edge with a readable width; sharing the narrower conversation-only menu sizing regresses the instruction field.

## Compact list timestamps without core interference
The core updates every `.ago` node to a verbose relative string. Compact Inbox list labels therefore use `.tm-age` and their own 30-second text-only refresh, also refreshed on view rendering. Keep delivery timestamps on the original core path. Calendar yesterday is computed by local date arithmetic, not a fixed 24-hour subtraction, and applies only after six elapsed hours, matching the native client. Tests cover boundaries, DST, invalid/missing dates, old years, exact-date tooltips and focus remaining in the same draft node across the timer tick.

## Media-only list previews
A generic concatenated media-kind string loses voice transcripts and filenames. Match native LetterRow: first attachment label then a14px type glyph, real caption text without a glyph,44px thumbnail with8px gap. Keep detail attachment labels/player behavior separate. Test photo/voice/transcript/video/file/caption rows and navigation without provider reads; capture explicit theme palettes, since browser media emulation alone does not override saved Hub themes.
