"""Кому написать: поиск собеседника по источникам и отправка новому (не из Inbox) — посты владельца {"kind":
"contacts", rid, q[, src]} и {"kind": "send_new", rid, to, text[, files, subject]}.

Адрес собеседника — строка-ключ `<src>:<…>`, её отдаёт поиск, её же принимает отправка:
  tg:<chat_id|@логин>    wa:<канал>:<chat_id>    mail:<ящик>:<адрес>    teams:<userId>
Поиск ничего никому не отправляет и чаты не открывает (WhatsApp — список чатов страницы, Telegram — только чтение)."""
import json
import re
import subprocess

import sources
from sources import expand, run

LIMIT = 15


def search(q, cfg, mcp=None, only=None):
    """[{src, to, name, hint}] по источникам, у каждого — свой сбой не мешает остальным."""
    q = (q or "").strip()[:80]
    out, errors = [], []
    if len(q) < 2:
        return out, errors
    for src, fn in (("telegram", _telegram), ("whatsapp", _whatsapp), ("email", _email), ("teams", _teams)):
        if only and only != src:
            continue
        try:
            got = fn(q, cfg, mcp)
        except Exception as e:  # noqa: BLE001 — один источник не должен ломать поиск по остальным
            errors.append(f"{src}: {e}"[:200])
            continue
        out += [{"src": src, **g} for g in got[:LIMIT]]
    return out, errors


def _telegram(q, cfg, mcp):
    c = cfg.get("telegram")
    if c is None:
        return []
    data = json.loads(run([expand(c.get("cmd") or "~/.claude/bin/tgnew"), "contacts", q], timeout=60))
    return [{"to": f"tg:{d['id']}", "name": d["name"], "hint": ("@" + d["username"]) if d.get("username") else
             ("группа" if d.get("group") else "")} for d in data]


def _whatsapp(q, cfg, mcp):
    c = cfg.get("whatsapp")
    if c is None:
        return []
    cmd, out = expand(c.get("cmd") or "~/.claude/bin/wa"), []
    for ch in c.get("channels") or ["whatsapp"]:
        for d in json.loads(run([cmd, "chats", q, "--channel", ch, "--json"], timeout=60)):
            out.append({"to": f"wa:{ch}:{d['chat_id']}", "name": d.get("name") or d["chat_id"],
                        "hint": (c.get("labels") or {}).get(ch, "") + (" · группа" if d["chat_id"].endswith("@g.us") else "")})
    return out


def _email(q, cfg, mcp):
    c = cfg.get("email")
    if c is None:
        return []
    cmd, out, seen = expand(c.get("cmd") or "~/.claude/bin/gogx"), [], set()
    needle = q.casefold()
    for acct in c.get("accounts") or []:
        query = f'from:"{q}" OR to:"{q}"' if " " in q or "@" in q else f"from:{q} OR to:{q}"
        data = json.loads(run([cmd, "gmail", "search", query, "--max", "30", "-a", acct, "-j"], timeout=60))
        for th in data.get("threads") or []:
            for who in re.split(r",\s*(?=[^,]*<)", th.get("from") or ""):
                m = re.search(r"<([^>]+)>", who)
                addr = (m.group(1) if m else who).strip().lower()
                name = re.sub(r"\s*<[^>]*>\s*$", "", who).strip().strip('"')
                if "@" not in addr or addr in seen or needle not in (name + " " + addr).casefold() or addr == acct:
                    continue
                seen.add(addr)
                out.append({"to": f"mail:{acct}:{addr}", "name": name or addr, "hint": addr})
    return out


def _teams(q, cfg, mcp):
    if mcp is None:
        return []
    safe = q.replace('"', " ")
    data = mcp.call("list-users", {"search": f'"displayName:{safe}" OR "mail:{safe}"', "ConsistencyLevel": "eventual",
                                   "top": LIMIT, "select": "id,displayName,mail"})
    return [{"to": f"teams:{u['id']}", "name": u.get("displayName") or u.get("mail") or "", "hint": u.get("mail") or ""}
            for u in data.get("value") or [] if u.get("id")]


def send(to, text, cfg, mcp=None, me=None, files=(), subject=""):
    """Отправка новому собеседнику по ключу из поиска. Кидает OSError с причиной."""
    kind, _, rest = to.partition(":")
    fl = [x for f in files for x in ("--file", f)]
    if kind == "tg" and rest:
        send_cmd = expand((cfg.get("telegram") or {}).get("send") or "~/.claude/bin/send")
        return run([send_cmd, "tg", "--to", rest, "--text", text, *fl], timeout=180)
    if kind == "wa" and rest.count(":") >= 1:
        ch, _, chat = rest.partition(":")
        send_cmd = expand((cfg.get("whatsapp") or {}).get("send") or "~/.claude/bin/send")
        return run([send_cmd, "wa", "--to", chat, "--channel", ch, "--text", text, *fl], timeout=180)
    if kind == "mail" and rest.count(":") >= 1:
        acct, _, addr = rest.partition(":")
        if not subject.strip():
            raise OSError("у нового письма нужна тема")
        cmd = expand((cfg.get("email") or {}).get("cmd") or "~/.claude/bin/gogx")
        return run([cmd, "gmail", "send", "--to", addr, "--subject", subject.strip()[:200], "--body", text, "-a", acct,
                    *[x for f in files for x in ("--attach", f)]], timeout=180)
    if kind == "teams" and rest:
        if files:
            raise OSError("в Teams файл вложением не уйдёт — пришли ссылкой на него")
        if mcp is None or not me:
            raise OSError("Teams не подключён")
        user = "https://graph.microsoft.com/v1.0/users('{}')"
        chat = mcp.call("create-chat", {"body": {"chatType": "oneOnOne", "members": [
            {"@odata.type": "#microsoft.graph.aadUserConversationMember", "roles": ["owner"],
             "user@odata.bind": user.format(me)},
            {"@odata.type": "#microsoft.graph.aadUserConversationMember", "roles": ["owner"],
             "user@odata.bind": user.format(rest)}]}})
        from collect import html_body
        return mcp.call("send-chat-message", {"chatId": chat["id"], "body": html_body(text)}, empty_ok=True)
    raise OSError("не знаю, кому писать")
