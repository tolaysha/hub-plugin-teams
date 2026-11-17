"""New Teams messages for the "Teams messages" tab: direct messages (everything from others), group chats only when the
owner is mentioned or his message is replied to, chosen channels ("Choose channels" in the tab; none by default) — the
first messages of threads, the other channels — mentions (through Graph search).

The source is the ms365 MCP (the mcp.Mcp client). Each message is a dict
{key, box, src, where, from, text, at, link, mention}; key is a stable short key (chat/channel + message id), box is the
conversation where the owner can reply (a chat or a channel thread): his reply there after the message means it is
answered. owner_last is {box: time of the owner's last message}, reacted is the keys of messages with the owner's
reaction (a reaction is an answer too); the functions fill them in while reading."""
import hashlib
import html
import json
import re

DEFAULT_WATCH = ()   # (team, channel) by default until the owner picks in the tab; none in the shared plugin
TEXT_MAX = 1200


def key(container, msg_id):
    return hashlib.sha1(f"{container}:{msg_id}".encode()).hexdigest()[:16]


def plain(body):
    """Teams body HTML -> text: paragraphs and line breaks become lines, <at>Name</at> -> @Name, emoji -> their alt,
    reply quotes (<attachment>) are dropped."""
    s = body or ""
    s = re.sub(r"<attachment[^>]*>.*?</attachment>", "", s, flags=re.S)
    s = re.sub(r"<emoji[^>]*alt=\"([^\"]*)\"[^>]*>(?:</emoji>)?", r"\1", s)
    s = re.sub(r"<at[^>]*>(.*?)</at>", r"@\1", s, flags=re.S)
    s = re.sub(r"<br\s*/?>|</p>|</div>|</li>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s).replace("\xa0", " ")
    s = "\n".join(" ".join(line.split()) for line in s.splitlines())
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s if len(s) <= TEXT_MAX else s[:TEXT_MAX].rstrip() + "…"


def sender(m):
    return ((m.get("from") or {}).get("user") or {})


def mentions_me(m, me):
    return any(((x.get("mentioned") or {}).get("user") or {}).get("id") == me for x in m.get("mentions") or [])


def replies_to_me(m, me):
    """A quoted reply (attachment messageReference) to the owner's message."""
    for a in m.get("attachments") or []:
        if a.get("contentType") != "messageReference":
            continue
        try:
            ref = json.loads(a.get("content") or "{}")
        except ValueError:
            continue
        if ((ref.get("messageSender") or {}).get("user") or {}).get("id") == me:
            return True
    return False


def reacted_by(m, me):
    return any(((r.get("user") or {}).get("user") or {}).get("id") == me for r in m.get("reactions") or [])


# laughter, emoji, "ok", "thanks": a reaction to a message, not a new message (reactions to messages are not shown as
# messages). The Russian words match Russian chat input.
CHATTER = re.compile(r"(а?ха|a?ha|ах|ah)+[хh]*|х+|[ао]?ок(ей)?|ok(ay)?|спс|спасибо|пасиб\w*|благодарю|thanks?|thx|"
                     r"понял[аи]?|ясно|ага|угу|да|yes|yep|лол|lol|кек|ору|топ|огонь|супер|класс|круто")


def chatter(text):
    """Only laughter, emoji, brackets and a short reaction, with no question and nothing to do."""
    words = [w for w in re.split(r"[\W_]+", text.lower()) if w]
    return len(words) <= 2 and all(CHATTER.fullmatch(w) for w in words)


def fresh(m, cutoff, me):
    """Someone else's ordinary message newer than cutoff (ISO, UTC): not a system one, not deleted, not the owner's, has an author."""
    who = sender(m)
    return (m.get("messageType") == "message" and not m.get("deletedDateTime") and who.get("id")
            and who["id"] != me and (m.get("createdDateTime") or "") > cutoff)


def mine(m, me, box, owner_last):
    if sender(m).get("id") == me and not m.get("deletedDateTime"):
        owner_last[box] = max(owner_last.get(box, ""), m.get("createdDateTime") or "")


def chats(mcp, cutoff, me, owner_last, top=30, reacted=None, scan=None):
    """Chats with new messages. scan is earlier than cutoff: also re-read chats with messages newer than scan, to see
    the owner's reply or reaction to an already shown message (no new messages are taken from them)."""
    out = []
    data = mcp.call("list-chats", {"$top": top, "$expand": "lastMessagePreview",
                                   "$orderby": "lastMessagePreview/createdDateTime desc"})
    for c in data.get("value", []):
        last = (c.get("lastMessagePreview") or {}).get("createdDateTime") or ""
        if last <= min(cutoff, scan or cutoff):
            continue
        dm = c.get("chatType") == "oneOnOne"
        msgs = mcp.call("list-chat-messages", {"chatId": c["id"], "top": 20, "orderby": "createdDateTime desc"})
        box = key(c["id"], "")
        for m in msgs.get("value", []):
            mine(m, me, box, owner_last)
            if reacted is not None and reacted_by(m, me):
                reacted.add(key(c["id"], m["id"]))
            if not fresh(m, cutoff, me):
                continue
            mention, reply = mentions_me(m, me), replies_to_me(m, me)
            if not (dm or mention or reply):
                continue
            text = plain((m.get("body") or {}).get("content"))
            if not text or (not (mention or reply) and chatter(text)):   # a quoted "yes" to his question is an answer
                continue
            out.append({"key": key(c["id"], m["id"]), "box": box, "src": "dm" if dm else "mention",
                        "where": "Direct message" if dm else (c.get("topic") or "Group chat"),
                        "from": sender(m).get("displayName") or "", "text": text, "at": m["createdDateTime"],
                        "link": m.get("webUrl") or c.get("webUrl") or "", "mention": mention})
    return out


def directory(mcp):
    """{channelId: {"team", "teamId", "channel"}}: all channels of the owner's teams, for the choice in the tab and the names of mentions."""
    out = {}
    for t in mcp.call("list-joined-teams", {}).get("value", []):
        for ch in mcp.call("list-team-channels", {"teamId": t["id"]}).get("value", []):
            out[ch["id"]] = {"team": t.get("displayName") or "", "teamId": t["id"], "channel": ch.get("displayName") or ""}
    return out


def default_watch(channels):
    """Default channels: the channelId of DEFAULT_WATCH, if the owner has it."""
    return [cid for cid, c in channels.items() if DEFAULT_WATCH and (c["team"], c["channel"]) == DEFAULT_WATCH]


def channel_posts(mcp, channel, info, cutoff, me, owner_last, top=10, reacted=None):
    """A chosen channel. Threads come by latest activity: we look at the top ones. Only the first message of a thread
    (the post itself); replies inside the thread only with a mention of the owner, as a mention. The owner's replies in
    the thread are read anyway: they mark the post as answered."""
    team, label = info["teamId"], f"{info['team']} › {info['channel']}"
    out = []
    data = mcp.call("list-channel-messages", {"teamId": team, "channelId": channel, "top": top, "expand": "replies"})
    for root in data.get("value", []):
        subject = (root.get("subject") or "").strip()
        box = key(channel, root["id"])
        for m in [root] + list(root.get("replies") or []):
            mine(m, me, box, owner_last)
            if reacted is not None and reacted_by(m, me):
                reacted.add(key(channel, m["id"]))
            mention = mentions_me(m, me)
            if not fresh(m, cutoff, me) or (m is not root and not mention):
                continue
            text = plain((m.get("body") or {}).get("content"))
            if not text or (not mention and chatter(text)):
                continue
            thread = subject or plain((root.get("body") or {}).get("content")).split("\n")[0][:80]
            out.append({"key": key(channel, m["id"]), "box": box, "src": "channel" if m is root else "mention",
                        "where": label + (f" · {thread}" if m is not root else ""),
                        "from": sender(m).get("displayName") or "", "text": text, "at": m["createdDateTime"],
                        "link": m.get("webUrl") or "", "mention": mention})
    return out


def bot(mail):
    """The sender is an app (Workflows, Power Automate, bots): no address or one on teams.microsoft.com."""
    address = (mail.get("address") or "").lower()
    return not address or address.endswith("@teams.microsoft.com") or (mail.get("name") or "") in ("Workflows", "Power Automate")


def channel_mentions(mcp, cutoff, me_mail, name, channels=None, skip=(), size=25):
    """Mentions of the owner in channels, through Graph search by his name (going over all channels would be dozens of
    calls a minute). Search also finds messages where he is just a participant, so only those with the name in the text
    itself are taken. Chats (in search their channelId is the chat id and there is no teamId) are read by chats(); bots
    (Workflows and the like, an @teams.microsoft.com address) post cards with lists of people, not mentions."""
    body = {"requests": [{"entityTypes": ["chatMessage"], "query": {"queryString": name}, "from": 0, "size": size}]}
    data = mcp.call("search-query", {"body": body})
    out = []
    for cont in (data.get("value") or [{}])[0].get("hitsContainers") or []:
        for h in cont.get("hits") or []:
            r = h.get("resource") or {}
            ch = r.get("channelIdentity") or {}
            mail = ((r.get("from") or {}).get("emailAddress") or {})
            if not ch.get("channelId") or not ch.get("teamId") or ch["channelId"] in skip:   # chosen ones go through channel_posts()
                continue
            if bot(mail):
                continue
            if (r.get("createdDateTime") or "") <= cutoff or (mail.get("address") or "").lower() == me_mail:
                continue
            summary = plain(h.get("summary"))
            if name.lower() not in summary.lower():
                continue
            c = (channels or {}).get(ch["channelId"])
            out.append({"key": key(ch["channelId"], r.get("id")), "box": None, "src": "mention",
                        "where": f"{c['team']} › {c['channel']}" if c else "Teams channel",
                        "from": mail.get("name") or "", "text": summary, "at": r["createdDateTime"],
                        "link": r.get("webLink") or "", "mention": True})
    return out
