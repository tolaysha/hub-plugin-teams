"""Новые сообщения Teams для вкладки «Teams сообщения»: личка (все чужие), групповые чаты — только упоминание владельца
или ответ на его сообщение, выбранные каналы (во вкладке «Выбрать каналы»; по умолчанию — ни одного) — первые
сообщения тредов, остальные каналы — упоминания (поиском Graph).

Источник — ms365 MCP (клиент mcp.Mcp). Каждое сообщение — dict
{key, box, src, where, from, text, at, link, mention}; key — устойчивый короткий ключ (чат/канал + id сообщения), box —
переписка, где владелец может ответить (чат или тред канала): его ответ там позже сообщения — сообщение отвечено.
owner_last — {box: время последнего сообщения владельца}, reacted — ключи сообщений с реакцией владельца (реакция —
тоже ответ); функции дописывают их по ходу чтения."""
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


_TZ = re.compile(r"\s*[\[(]\s*(?:UTC|GMT)\s*[+\-\u2212]\s*\d{1,2}(?::?\d{2})?\s*[\])]\s*")


_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp", "video/mp4": "mp4"}
HOSTED = re.compile(r"/hostedContents/([^/\"'?]+)/\$value")


def attachments(mcp, m, chat, keep=4):
    """Вложения сообщения Teams (13.10): картинки из тела (hostedContents) скачиваются Graph-вызовом в attachments хаба и
    отдаются как media[]; файлы-ссылки (SharePoint/OneDrive, attachments[].contentType == reference) — в links[]: байты
    за входом Microsoft, откроются в самом Teams. Не скачалось — вложения нет (сообщение остаётся)."""
    import os
    from urllib.parse import quote
    import sources
    media, links = [], []
    for hid in list(dict.fromkeys(HOSTED.findall((m.get("body") or {}).get("content") or "")))[:keep]:
        d = sources.media_dir("teams")
        base = hashlib.sha1(f"{chat}:{m.get('id')}:{hid}".encode()).hexdigest()[:20]
        have = next((f for f in os.listdir(d) if f.startswith(base + ".")), None)
        if have is None:
            path = os.path.join(d, base + ".png")   # расширение уточним по contentType ответа
            try:
                got = mcp.call("download-bytes-to-file",
                               {"target": f"/chats/{chat}/messages/{m['id']}/hostedContents/{hid}/$value", "outputPath": path})
                ext = _EXT.get(str(got.get("contentType") or "").split(";")[0].lower(), "png")
                if ext != "png" and os.path.exists(path):
                    os.replace(path, os.path.join(d, f"{base}.{ext}"))
                    path = os.path.join(d, f"{base}.{ext}")
                have = os.path.basename(path) if os.path.exists(path) else None
            except OSError:
                have = None
        if have:
            ext = have.rsplit(".", 1)[-1]
            mime = next((k for k, v in _EXT.items() if v == ext), "image/png")
            media.append({"id": f"teams:{m.get('id')}:{hid[:12]}", "kind": "video" if mime.startswith("video") else "image",
                          "name": have, "mime": mime, "url": "/api/file?path=" + quote(os.path.join(d, have), safe="")})
    for a in m.get("attachments") or []:
        if a.get("contentType") == "reference" and a.get("contentUrl"):
            links.append({"url": a["contentUrl"], "title": a.get("name") or "", "site": "Teams"})
    return media, links[:3]


def person(name):
    """Имя человека без часового пояса: «Anthony Minkowski [UTC-03:00]» → «Anthony Minkowski» (12.10)."""
    s = _TZ.sub(" ", name or "").strip()
    return s or (name or "")


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


def reacted_by(m, me):
    return any(((r.get("user") or {}).get("user") or {}).get("id") == me for r in m.get("reactions") or [])


# смех, эмодзи, «ок», «спасибо» — отклик на сообщение, не новое сообщение (владелец 12.10: «не надо реакции на
# сообщения показывать как сообщения»)
CHATTER = re.compile(r"(а?ха|a?ha|ах|ah)+[хh]*|х+|[ао]?ок(ей)?|ok(ay)?|спс|спасибо|пасиб\w*|благодарю|thanks?|thx|"
                     r"понял[аи]?|ясно|ага|угу|да|yes|yep|лол|lol|кек|ору|топ|огонь|супер|класс|круто")


def chatter(text):
    """Только смех, эмодзи, скобки и короткий отклик — без вопроса и дела."""
    words = [w for w in re.split(r"[\W_]+", text.lower()) if w]
    return len(words) <= 2 and all(CHATTER.fullmatch(w) for w in words)


def fresh(m, cutoff, me):
    """Чужое обычное сообщение не старше cutoff (ISO, UTC): не системное, не удалённое, не владельца, есть автор."""
    who = sender(m)
    return (m.get("messageType") == "message" and not m.get("deletedDateTime") and who.get("id")
            and who["id"] != me and (m.get("createdDateTime") or "") > cutoff)


def mine(m, me, box, owner_last):
    if sender(m).get("id") == me and not m.get("deletedDateTime"):
        owner_last[box] = max(owner_last.get(box, ""), m.get("createdDateTime") or "")


def chats(mcp, cutoff, me, owner_last, top=30, reacted=None, scan=None):
    """Чаты с новыми сообщениями. scan — раньше cutoff: заодно перечитать чаты с сообщениями не старше scan, чтобы
    увидеть ответ или реакцию владельца на уже показанное (новых сообщений из них не берём)."""
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
            media, links = attachments(mcp, m, c["id"])
            if not text and not media and not links:
                continue
            if text and not media and not (mention or reply) and chatter(text):   # «да» цитатой на его вопрос — ответ
                continue
            out.append({"key": key(c["id"], m["id"]), "box": box, "src": "dm" if dm else "mention",
                        "where": "Личка" if dm else (c.get("topic") or "Групповой чат"),
                        "from": sender(m).get("displayName") or "", "text": text, "at": m["createdDateTime"],
                        **({"media": media} if media else {}), **({"links": links} if links else {}),
                        "link": m.get("webUrl") or c.get("webUrl") or "", "mention": mention,
                        "ref": {"chat": c["id"], "msg": m["id"]}})   # ref — куда отвечать и на что ставить реакцию (в посте не уходит)
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


def channel_posts(mcp, channel, info, cutoff, me, owner_last, top=10, reacted=None):
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
                        "link": m.get("webUrl") or "", "mention": mention,
                        "ref": {"team": team, "channel": channel, "root": root["id"], "msg": m["id"]}})
    return out


def bot(mail):
    """Отправитель — приложение (Workflows, Power Automate, боты): адреса нет или он на teams.microsoft.com."""
    address = (mail.get("address") or "").lower()
    return not address or address.endswith("@teams.microsoft.com") or (mail.get("name") or "") in ("Workflows", "Power Automate")


def channel_mentions(mcp, cutoff, me_mail, name, channels=None, skip=(), size=25):
    """Упоминания владельца в каналах — поиском Graph по его имени (обход всех каналов — десятки вызовов в минуту).
    Поиск находит и сообщения, где он просто участник, поэтому берём только те, где имя есть в самом тексте. Чаты
    (у них в поиске channelId — это id чата, а teamId нет) читает chats(); боты (Workflows и др., адрес
    @teams.microsoft.com) — карточки со списком людей, не упоминания (владелец 12.10: «из воркфлоу не надо»)."""
    body = {"requests": [{"entityTypes": ["chatMessage"], "query": {"queryString": name}, "from": 0, "size": size}]}
    data = mcp.call("search-query", {"body": body})
    out = []
    for cont in (data.get("value") or [{}])[0].get("hitsContainers") or []:
        for h in cont.get("hits") or []:
            r = h.get("resource") or {}
            ch = r.get("channelIdentity") or {}
            mail = ((r.get("from") or {}).get("emailAddress") or {})
            if not ch.get("channelId") or not ch.get("teamId") or ch["channelId"] in skip:   # выбранные — в channel_posts()
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
                        "where": f"{c['team']} › {c['channel']}" if c else "Канал Teams",
                        "from": mail.get("name") or "", "text": summary, "at": r["createdDateTime"],
                        "link": r.get("webLink") or "", "mention": True,
                        # куда отвечать: поиск отдаёт канал и сообщение; корень треда — replyToId (иначе само сообщение —
                        # корень). Без адреса запись была без «Ответить» и реакции (владелец 12.10, бот Workflows)
                        **({"ref": {"team": c["teamId"], "channel": ch["channelId"],
                                    "root": r.get("replyToId") or r.get("id"), "msg": r.get("id")}}
                           if c and c.get("teamId") and r.get("id") else {})})
    return out


def html_body(text):
    """Текст ответа → тело сообщения Teams: обычный текст Graph портит, поэтому html с экранированием."""
    return {"body": {"contentType": "html",
                     "content": "<p>" + html.escape(text.strip()).replace("\n", "<br>") + "</p>"}}


def reply(mcp, ref, text):
    """Ответ владельца в ту же переписку: чат — новым сообщением в чат, канал — ответом в тред (root)."""
    body = html_body(text)
    if ref.get("chat"):
        return mcp.call("send-chat-message", {"chatId": ref["chat"], "body": body}, empty_ok=True)
    if ref.get("team") and ref.get("channel") and ref.get("root"):
        return mcp.call("reply-to-channel-message", {"teamId": ref["team"], "channelId": ref["channel"],
                                                     "chatMessageId": ref["root"], "body": body}, empty_ok=True)
    raise OSError("не знаю, куда отвечать на это сообщение")


def edit(mcp, ref, msg, text):
    """Правка своего сообщения в чате Teams (Graph PATCH). Удаление через этот сервер недоступно (нет softDelete)."""
    if ref.get("chat") and msg:
        return mcp.call("update-chat-message", {"chatId": ref["chat"], "chatMessageId": msg,
                                                "body": {"body": {"contentType": "html", "content": html_body(text)}}},
                        empty_ok=True)
    raise OSError("это сообщение изменить нельзя")


def can_react(ref):
    """На что можно поставить реакцию: сообщение чата и первое сообщение треда канала (ответу в треде Graph реакцию
    этим вызовом не ставит); WhatsApp — когда в sources.json задана команда реакции."""
    ref = ref or {}
    if ref.get("wa"):
        return bool(ref.get("react"))
    if ref.get("tg"):
        return True
    if ref.get("chat"):
        return bool(ref.get("msg"))
    return bool(ref.get("root")) and ref.get("msg") == ref.get("root")


def react(mcp, ref, emoji, msg=None):
    """Реакция владельца на сообщение: эмодзи как есть (Graph: reactionType — символ Unicode). msg — id конкретного
    сообщения чата (из переписки), иначе то, на которое пришёл пост."""
    body = {"reactionType": emoji}
    if ref.get("chat") and (msg or ref.get("msg")):
        return mcp.call("set-chat-message-reaction", {"chatId": ref["chat"], "chatMessageId": msg or ref["msg"],
                                                      "body": body}, empty_ok=True)
    if ref.get("team") and ref.get("channel") and ref.get("root") and ref.get("msg") == ref["root"]:
        return mcp.call("set-channel-message-reaction", {"teamId": ref["team"], "channelId": ref["channel"],
                                                         "chatMessageId": ref["root"], "body": body}, empty_ok=True)
    raise OSError("на это сообщение реакцию поставить нельзя")


def history(mcp, ref, me, top=20, before_at=None, search=None):
    """Переписка вокруг сообщения — для «всей переписки» во вкладке: последние сообщения чата или тред канала (первое
    сообщение и ответы). Чтение через Graph ничего не отмечает прочитанным. [{at, from, me, text}] по времени."""
    if ref.get("chat"):
        args = {"chatId": ref["chat"], "top": top}
        if search:   # поиск Graph по тексту чата; с filter не сочетается
            args["search"] = '"' + search.replace('"', " ") + '"'
        else:
            args["orderby"] = "createdDateTime desc"
            if before_at:   # листание вверх: сообщения старше последнего показанного
                args["filter"] = f"createdDateTime lt {before_at}"
        rows = mcp.call("list-chat-messages", args).get("value", [])
    elif ref.get("team") and ref.get("channel") and ref.get("root"):
        args = {"teamId": ref["team"], "channelId": ref["channel"], "chatMessageId": ref["root"]}
        rows = [mcp.call("get-channel-message", args)] + mcp.call("list-channel-message-replies", {**args, "top": top}).get("value", [])
    else:
        return []
    out = []
    for m in rows:
        who, text = sender(m), plain((m.get("body") or {}).get("content"))
        if m.get("messageType") != "message" or m.get("deletedDateTime") or not who.get("id") or not text:
            continue
        out.append({"at": m.get("createdDateTime") or "", "from": who.get("displayName") or "", "me": who["id"] == me,
                    "text": text, **({"id": str(m["id"])} if m.get("id") else {})})
    return sorted(out, key=lambda x: x["at"])[-top:]


def latest_incoming(mcp, me, top=30):
    """Самое свежее чужое сообщение среди последних чатов (по превью) — доказательство во вкладке, что чтение идёт, а
    нового просто нет: {from, where, at} или None."""
    data = mcp.call("list-chats", {"$top": top, "$expand": "lastMessagePreview",
                                   "$orderby": "lastMessagePreview/createdDateTime desc"})
    best = None
    for c in data.get("value", []):
        p = c.get("lastMessagePreview") or {}
        who = ((p.get("from") or {}).get("user") or {})
        at = p.get("createdDateTime") or ""
        if not at or not who.get("id") or who["id"] == me or p.get("deletedDateTime"):
            continue
        if best is None or at > best["at"]:
            best = {"from": who.get("displayName") or "",
                    "where": "Личка" if c.get("chatType") == "oneOnOne" else (c.get("topic") or "Групповой чат"),
                    "at": at}
    return best
