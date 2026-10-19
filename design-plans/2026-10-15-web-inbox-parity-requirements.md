# Web Inbox parity

Owner m333740 reports missing controls, mixed old design, repeated refresh and trapped navigation.
The shared client design is HubbaHub v5 with file 22, Inbox prompt and action,
etag 1792090255859803. Native d332010 owns no plugin-web source. Existing collector
management work owns the protocol; this slice changes only its web consumer.

- Use the real shared composer when composerTransport:1 is present. Preserve old-page compatibility.
- Keep list/detail navigation, thread reading, exact draft, selection and explicit close usable at phone/tablet/desktop widths.
- Group by source conversation identity, never display name; unknown identities stay separate.
- A current editor acquires an acknowledged CAS hold. Navigation never releases it.
- Private instructions remain private, including intentional empty drafts.
- Bind proposals to item/post/request/editor/source revision. Explicit Apply cannot overwrite newer local edits.
- Whole-Inbox instructions retain exact owner text and use collector manage, independent of visible pagination. Dispatch is not completion.
- Queued, refused, uncertain and receipt-confirmed delivery remain distinct. Preserve replies until an actual matching receipt.
- Preserve source restrictions. The guarded collector currently supports text-only Teams chat replies; omit unsupported attachment controls.
- Keep a bounded history scroller and visible reply field. Reuse the shared icon pack, type, surfaces and 44px controls.
- Verify real renderer with synthetic journal/source events, then coordinate exact integration/activation and actual live acceptance separately.

## Exact-message controls recovered from native (2026-10-17)
- Native0597a826 iPhone54 menu: Copy, Hand This Message to Hub, Draft Reply to This Message.
- Right-click, long press, and keyboard access must act on the selected message, not the newest item in its conversation.
- Work prefills the Hub composer with the selected quote; it never sends automatically or discards a reply draft.
- Historical Draft uses the native ask protocol: original source post plus trusted thread-post location, provider message id, sender and time. Display row ids are never collector ids.
- Rebinding, navigation and dismissal cannot apply an old menu to a different message. Copy tests use an isolated fake clipboard.
- Render phone/tablet/desktop in actual light/dark themes and retain normal scrolling, text selection and keyboard focus.

## Native send options (recovered 2026-10-18)
- Pinned Mac menu-inbox-send-options and iPhone34 expose five controls: Send now, remembered Send and Archive, next contact working start, custom later, Weekends Too. Reuse native placement and order; whole menu must remain reachable with the keyboard open.
- Weekends Too reads the trusted collector configuration for this exact contact, not an optimistic local toggle. Changing it requires the current target and correlated collector capability; HTTP acceptance is not confirmation. Persist original id/contact/target/rid/value before sending and use the same request for explicit retry after reload.
- Wrong receipts, revoked capabilities, stale controls and changed destinations cannot mutate a replacement conversation. Preserve newer reply drafts. Unknown or refused setting changes stay visible.
- Send and Archive and its remembered default are implemented, including confirmed archive/Restore and newer-draft preservation. Exact full-screen visual parity and actual Safari verification remain separate acceptance work.

## Refused and uncertain replies (2026-10-18)
- A definitive guarded failure must allow the owner to edit and resend from the still-open composer after fresh collector confirmation. The old held token alone is not sufficient admission.
- Keep older failed history, newer drafts, exact destination and current revision. A delayed old failure must not affect a newer delivery.
- A reply already confirmed as Sent stays confirmed when delayed refusal, scheduling or reconciliation facts arrive for that same request. Keep this result through journal replay and do not erase a newer draft.
- An uncertain outcome keeps its original request identity and explicit reconciliation path; editing a newer draft must never turn it into a fresh duplicate send.
- Native chat's separate direct Retry remains a distinct feature from editing and submitting again.

## Native context and action comparison (2026-10-18)
- Pinned0597a826 Letter.origin renders provider plus distinct supplied place once. Teams DM must not read “Teams · Личка · Личка”; Telegram must not repeat its own name.
- Shared row actions use one icon size at each layout width: existing22px labelled and28px compact. Keep44px targets. Verify360–1440 including tablet single-pane widths.
- Pinned native reset feed at402×874 and1240×780 is the content baseline. Preserve mock photo bytes through a same-origin blob URL when capturing actual live static UI with intercepted APIs. Compare both themes; fixture parity alone is not pixel parity.

## Direct retry acceptance (2026-10-18)
- Definitively failed chat replies have a separate Retry action; mail retains editing recovery. Retry the exact failed text and attachments with a fresh request ID and current destination, without inheriting scheduling or archive intent.
- Guarded retries require fresh hold confirmation; intervening edits, navigation or changed conversation identity cancel submission. Recheck admission inside the pending-record Web Lock.
- Preserve newer local/cross-tab drafts and failed history. Transfer only an untouched old pending tombstone; clear it only on the matching accepted receipt. Refused storage causes no transport.
- A lost retry acknowledgment persists the new request; reload never sends automatically and explicit reconciliation reuses that exact request. Existing uncertain outcomes never become fresh Retry requests.
- Compare the pinned native failed-bubble controls, with at least 44px hit targets on phone/tablet/desktop. Functional acceptance does not imply exact screen parity.

## Media list preview target (pinned0597a826)
- LetterRow uses the first attachment label followed by its14px media-type glyph when no message text exists. Audio prefers transcript, otherwise voice label plus m:ss duration; files use their name.
- Collapse preview newlines; preserve two-line clamp and outgoing folder preview priority. Thumbnails are44px squares, radius8, gap8; explicit video/file thumbnails are valid too.
- Source tests and synthetic captures do not prove actual Safari or complete native pixel parity.
