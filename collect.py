"""Новые сообщения Teams для вкладки «Teams сообщения»: личка (все чужие), групповые чаты — только упоминание владельца
или ответ на его сообщение, выбранные каналы (во вкладке «Выбрать каналы»; по умолчанию — ни одного) — первые
сообщения тредов, остальные каналы — упоминания (поиском Graph).

Источник — ms365 MCP (клиент mcp.Mcp). Каждое сообщение — dict
{key, box, src, where, from, text, at, link, mention}; key — устойчивый короткий ключ (чат/канал + id сообщения), box —
переписка, где владелец может ответить (чат или тред канала): его ответ там позже сообщения — сообщение отвечено.
owner_last — {box: время последнего сообщения владельца}, функции дописывают его по ходу чтения."""
import hashlib
import html
import json
import re

DEFAULT_WATCH = ()   # (команда, канал) по умолчанию, пока во вкладке не выбрали свои; в общем плагине — ни одного
TEXT_MAX = 1200


def key(container, msg_id):
    return hashlib.sha1(f"{container}:{msg_id}".encode()).hexdigest()[:16]


def plain(body):
    """HTML тела Teams → текст: абзацы и переносы — строками, <at>Имя</at> → @Имя, эмодзи — их alt, цитаты ответа
    (<attachment>) убираем."""
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
    """Ответ с цитатой (attachment messageReference) на сообщение владельца."""
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


def fresh(m, cutoff, me):
    """Чужое обычное сообщение не старше cutoff (ISO, UTC): не системное, не удалённое, не владельца, есть автор."""
    who = sender(m)
    return (m.get("messageType") == "message" and not m.get("deletedDateTime") and who.get("id")
            and who["id"] != me and (m.get("createdDateTime") or "") > cutoff)


def mine(m, me, box, owner_last):
    if sender(m).get("id") == me and not m.get("deletedDateTime"):
        owner_last[box] = max(owner_last.get(box, ""), m.get("createdDateTime") or "")


def chats(mcp, cutoff, me, owner_last, top=30):
    out = []
    data = mcp.call("list-chats", {"$top": top, "$expand": "lastMessagePreview",
                                   "$orderby": "lastMessagePreview/createdDateTime desc"})
    for c in data.get("value", []):
        last = (c.get("lastMessagePreview") or {}).get("createdDateTime") or ""
        if last <= cutoff:
            continue
        dm = c.get("chatType") == "oneOnOne"
        msgs = mcp.call("list-chat-messages", {"chatId": c["id"], "top": 20, "orderby": "createdDateTime desc"})
        box = key(c["id"], "")
        for m in msgs.get("value", []):
            mine(m, me, box, owner_last)
            if not fresh(m, cutoff, me):
                continue
            mention = mentions_me(m, me)
            if not (dm or mention or replies_to_me(m, me)):
                continue
            text = plain((m.get("body") or {}).get("content"))
            if not text:
                continue
            out.append({"key": key(c["id"], m["id"]), "box": box, "src": "dm" if dm else "mention",
                        "where": "Личка" if dm else (c.get("topic") or "Групповой чат"),
                        "from": sender(m).get("displayName") or "", "text": text, "at": m["createdDateTime"],
                        "link": m.get("webUrl") or c.get("webUrl") or "", "mention": mention})
    return out


def directory(mcp):
    """{channelId: {"team", "teamId", "channel"}} — все каналы команд владельца: выбор во вкладке, имена упоминаний."""
    out = {}
    for t in mcp.call("list-joined-teams", {}).get("value", []):
        for ch in mcp.call("list-team-channels", {"teamId": t["id"]}).get("value", []):
            out[ch["id"]] = {"team": t.get("displayName") or "", "teamId": t["id"], "channel": ch.get("displayName") or ""}
    return out


def default_watch(channels):
    """Каналы по умолчанию — channelId из DEFAULT_WATCH, если он есть у владельца."""
    return [cid for cid, c in channels.items() if DEFAULT_WATCH and (c["team"], c["channel"]) == DEFAULT_WATCH]


def channel_posts(mcp, channel, info, cutoff, me, owner_last, top=10):
    """Выбранный канал. Треды идут по последней активности: смотрим верхние. Только первое сообщение треда (сам пост);
    ответы внутри треда — только с упоминанием владельца, как упоминание (владелец 09.10: «сообщения внутри поста не
    надо»). Ответы владельца в треде всё равно читаем — по ним пост помечается отвеченным."""
    team, label = info["teamId"], f"{info['team']} › {info['channel']}"
    out = []
    data = mcp.call("list-channel-messages", {"teamId": team, "channelId": channel, "top": top, "expand": "replies"})
    for root in data.get("value", []):
        subject = (root.get("subject") or "").strip()
        box = key(channel, root["id"])
        for m in [root] + list(root.get("replies") or []):
            mine(m, me, box, owner_last)
            mention = mentions_me(m, me)
            if not fresh(m, cutoff, me) or (m is not root and not mention):
                continue
            text = plain((m.get("body") or {}).get("content"))
            if not text:
                continue
            thread = subject or plain((root.get("body") or {}).get("content")).split("\n")[0][:80]
            out.append({"key": key(channel, m["id"]), "box": box, "src": "channel" if m is root else "mention",
                        "where": label + (f" · {thread}" if m is not root else ""),
                        "from": sender(m).get("displayName") or "", "text": text, "at": m["createdDateTime"],
                        "link": m.get("webUrl") or "", "mention": mention})
    return out


def channel_mentions(mcp, cutoff, me_mail, name, channels=None, skip=(), size=25):
    """Упоминания владельца в каналах — поиском Graph по его имени (обход всех каналов — десятки вызовов в минуту).
    Поиск находит и сообщения, где он просто участник, поэтому берём только те, где имя есть в самом тексте."""
    body = {"requests": [{"entityTypes": ["chatMessage"], "query": {"queryString": name}, "from": 0, "size": size}]}
    data = mcp.call("search-query", {"body": body})
    out = []
    for cont in (data.get("value") or [{}])[0].get("hitsContainers") or []:
        for h in cont.get("hits") or []:
            r = h.get("resource") or {}
            ch = r.get("channelIdentity") or {}
            mail = ((r.get("from") or {}).get("emailAddress") or {})
            if not ch.get("channelId") or ch["channelId"] in skip:   # чаты — в chats(), выбранные — в channel_posts()
                continue
            if (r.get("createdDateTime") or "") <= cutoff or (mail.get("address") or "").lower() == me_mail:
                continue
            summary = plain(h.get("summary"))
            if name.lower() not in summary.lower():
                continue
            c = (channels or {}).get(ch["channelId"])
            out.append({"key": key(ch["channelId"], r.get("id")), "box": None, "src": "mention",
                        "where": f"{c['team']} › {c['channel']}" if c else "Канал Teams",
                        "from": mail.get("name") or "", "text": summary, "at": r["createdDateTime"],
                        "link": r.get("webLink") or "", "mention": True})
    return out
