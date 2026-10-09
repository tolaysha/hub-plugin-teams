"""Процесс личного расширения «Teams сообщения» (hub-up: HUB_STATE_DIR, PYTHONPATH на код хаба, HUB_EXTENSION).

Раз в POLL с читает Teams (collect.py; клиент ms365 MCP — mcp.py, один
процесс сервера на всё время) и постит в канал плагина по посту на новое сообщение: {"kind": "msg", ...}. Список каналов
команд — постами {"kind": "channels"} (частями); какие из них читать, владелец выбирает во вкладке — его пост
{"kind": "watch", "ids"} (Choice). Владелец ответил
в той же переписке позже — пост {"kind": "answered", "id"}. Сбой чтения FAIL_AFTER раз подряд — {"kind": "status",
"ok": false, "error"}, восстановилось — {"kind": "status", "ok": true}: вкладка показывает это плашкой. Модели нет.

Своё состояние (что уже запощено, время последнего успешного чтения) — в <состояние>/ext-teams, не в папке
расширения: файл, который меняется каждый тик, перезагружал бы открытые вкладки (страница следит за mtime файлов
расширения)."""
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

sys.dont_write_bytecode = True   # без __pycache__ в папке расширения — та же причина

from core import spool  # noqa: E402
from core.daemon import default_state_dir  # noqa: E402
from core.tools import from_owner  # noqa: E402

import collect  # noqa: E402

import mcp  # noqa: E402

# канал плагина — имя без автора: из каталога плагин ставится как «<аккаунт>:teams», страница пишет в «teams»
NAME = os.environ.get("HUB_EXTENSION", "teams").split(":")[-1]
STATE = default_state_dir()
OWN = os.path.join(STATE, "ext-teams")
STATE_PATH = os.path.join(OWN, "state.json")
POLL = int(os.environ.get("TEAMS_POLL") or 60)
FIRST_BACK = timedelta(hours=24)   # первый запуск: сообщения за сутки, чтобы вкладка не была пустой
OVERLAP = timedelta(minutes=15)    # окно назад от прошлого чтения: поиск Graph индексирует с задержкой
FAIL_AFTER = 3
SEEN_MAX, OPEN_MAX = 3000, 500
POST_MAX = 2000
DIR_EVERY = 6 * 3600               # список каналов команд перечитываем и заново постим раз в 6 часов: канал плагина
                                   # хранит 500 последних постов, старые списки вытесняются сообщениями


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def load():
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save(st):
    os.makedirs(OWN, exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)
    os.replace(tmp, STATE_PATH)


def short(e):
    """Ошибка для плашки во вкладке: первая строка, без хвоста stderr сервера ms365."""
    text = (str(e).splitlines() or [type(e).__name__])[0]
    return re.sub(r"(сервер закрылся):.*", r"\1", text)[:160]


def post(data):
    text = json.dumps(data, ensure_ascii=False)
    if len(text) > POST_MAX and isinstance(data.get("text"), str):   # пост канала — до 2000 знаков: режем текст
        data = {**data, "text": data["text"][:max(0, len(data["text"]) - (len(text) - POST_MAX) - 1)] + "…"}
        text = json.dumps(data, ensure_ascii=False)
    if len(text) > POST_MAX:   # ядро такой не примет; списки каналов режет directory_posts — сюда не должно дойти
        print(f"teams: пост {data.get('kind')} длиннее {POST_MAX} знаков — не отправлен", file=sys.stderr, flush=True)
        return
    spool.put(os.path.join(STATE, "spool"), "ext.post", None,
              {"plugin": NAME, "text": text, "channel": "plugin", "owner": False, "sender": NAME}, src=f"ext:{NAME}")


class Choice:
    """Какие каналы выбрал владелец во вкладке: его последний принятый ядром пост {"kind": "watch", "ids": [ключи
    каналов]} в канале плагина. Читаем журнал сами с места остановки, построчно, — только посты этого плагина (весь
    views.Reader здесь не нужен). Владелец — как в ядре (core.tools.from_owner: owner is True и его канал); пост,
    который ядро отклонило (за ним в журнале core.rejected с of = его seq), не считается. Выбор хранится и в
    состоянии процесса (ids при создании) — после ротации журнала старого поста в нём уже нет."""

    def __init__(self, path, ids=None):
        self.path, self.offset, self.ino, self.ids, self.before = path, 0, None, ids, ids
        self.recent = []   # [(seq, ids)] — последние принятые на вид посты: ядро может отклонить следом

    def poll(self):
        try:
            ino = os.stat(self.path).st_ino
            if ino != self.ino:   # журнал начат заново (journal.rotate) — читать с начала
                self.ino, self.offset = ino, 0
            with open(self.path, "rb") as f:
                f.seek(self.offset)
                for line in f:
                    if not line.endswith(b"\n"):   # строка дописывается — дочитаем в следующий раз
                        break
                    self.offset += len(line)
                    self.line(line)
        except OSError:
            pass
        return self.ids

    def line(self, line):
        if b"core.rejected" in line and self.recent:
            try:
                ev = json.loads(line)
            except ValueError:
                return
            of = (ev.get("data") or {}).get("of")
            if ev.get("type") == "core.rejected" and any(seq == of for seq, _ in self.recent):
                self.recent = [r for r in self.recent if r[0] != of]
                self.ids = self.recent[-1][1] if self.recent else self.before
            return
        if b"ext.post" not in line or b"watch" not in line:
            return
        try:
            ev = json.loads(line)
            d = ev.get("data") or {}
            body = json.loads(d.get("text") or "")
        except (ValueError, TypeError):
            return
        if ev.get("type") != "ext.post" or d.get("plugin") != NAME or not from_owner(d):
            return
        if isinstance(body, dict) and body.get("kind") == "watch" and isinstance(body.get("ids"), list):
            if not self.recent:
                self.before = self.ids
            self.recent = (self.recent + [(ev.get("seq"), [str(x) for x in body["ids"]][:500])])[-20:]
            self.ids = self.recent[-1][1]


def channel_key(cid):
    return collect.key(cid, "")


def directory_posts(channels, defaults, budget=1500):
    """Список каналов для выбора во вкладке — частями по длине (пост до 2000 знаков): [ключ, команда, канал]."""
    items = sorted([[channel_key(cid), c["team"][:120], c["channel"][:120]] for cid, c in channels.items()],
                   key=lambda x: (x[1], x[2]))
    sig = collect.key(json.dumps(items, ensure_ascii=False), "")[:8]
    parts, cur, size = [], [], 0
    for it in items:
        n = len(json.dumps(it, ensure_ascii=False)) + 2
        if cur and size + n > budget:
            parts.append(cur)
            cur, size = [], 0
        cur.append(it)
        size += n
    parts = parts + [cur] if cur or not parts else parts
    return sig, [{"kind": "channels", "sig": sig, "part": n, "of": len(parts), "items": part,
                  **({"default": [channel_key(c) for c in defaults]} if n == 0 else {})} for n, part in enumerate(parts)]


class Reader:
    """Один процесс ms365 MCP, пока он жив; упал — новый на следующем тике."""

    def __init__(self):
        self.mcp = None
        self.channels, self.listed = {}, 0

    def connect(self, st):
        self.mcp = mcp.Mcp()
        if not st.get("me"):
            u = self.mcp.call("get-current-user", {})
            st["me"] = {"id": u["id"], "mail": (u.get("mail") or u.get("userPrincipalName") or "").lower(),
                        "name": ((u.get("displayName") or "").split() or [""])[0]}

    def close(self):
        if self.mcp:
            self.mcp.close()
        self.mcp = None

    def refresh(self, st, choice, put):
        """Каналы команд — при старте и раз в DIR_EVERY: посты «channels» во вкладку и рядом {"kind": "watching"} —
        какие каналы читаем сейчас. Тот же набор — и когда поменялся выбор: страница видит ровно то, что читает
        процесс, даже когда пост владельца «watch» вытеснен из канала (500 постов)."""
        stale = not self.channels or time.time() - self.listed >= DIR_EVERY
        if stale:
            self.channels, self.listed = collect.directory(self.mcp), time.time()
        if stale or st.get("posted_choice") != choice:
            _, posts = directory_posts(self.channels, collect.default_watch(self.channels))
            for p in posts:
                put(p)
            put({"kind": "watching", "ids": [channel_key(c) for c in self.watched(choice)]})
            st["posted_choice"] = choice

    def watched(self, ids):
        """channelId выбранных каналов: выбор владельца (ключи) или канал по умолчанию."""
        if ids is None:
            return collect.default_watch(self.channels)
        want = set(ids)
        return [cid for cid in self.channels if channel_key(cid) in want]

    def read(self, st, cutoff, choice, now, put=None):
        """Сообщения и {box: ответ владельца}. Какие каналы с какого времени читаем — в self.next_since: в состояние
        его кладёт main только после удачного чтения (иначе новый канал потерял бы свои сутки)."""
        if not self.mcp:
            self.connect(st)
        self.refresh(st, choice, put or post)
        me, owner_last = st["me"], {}
        items = collect.chats(self.mcp, cutoff, me["id"], owner_last)
        watched = self.watched(choice)
        since = st.get("watch_since") or {}   # ключ канала → с какого времени следим
        for cid in watched:
            k = channel_key(cid)
            # только что выбранный канал — его посты за сутки, дальше — как все (от прошлого чтения)
            own_cut = cutoff if k in since else iso(now - FIRST_BACK)
            items += collect.channel_posts(self.mcp, cid, self.channels[cid], own_cut, me["id"], owner_last)
        self.next_since = {channel_key(cid): since.get(channel_key(cid)) or iso(now) for cid in watched}
        if me["name"]:
            items += collect.channel_mentions(self.mcp, cutoff, me["mail"], me["name"], self.channels, skip=set(watched))
        return items, owner_last


def tick(st, items, owner_last, now, put=post):
    """Новое — в канал (по возрастанию времени), отвеченное владельцем — пометить. Меняет st."""
    seen = set(st.get("seen") or [])
    opened = st.setdefault("open", {})   # key → [box, at]: запощено, ещё не отвечено
    fresh, keys = [], set()
    for i in sorted(items, key=lambda i: i["at"]):
        if i["key"] in seen or i["key"] in keys:   # сообщение канала с упоминанием находится дважды — берём первое
            continue
        keys.add(i["key"])
        fresh.append(i)
    for i in fresh:
        done = bool(i.get("box")) and owner_last.get(i["box"], "") > i["at"]   # уже ответил — сразу отвеченным
        put({"kind": "msg", "id": i["key"], "answered": done,
             **{k: i[k] for k in ("src", "where", "from", "text", "at", "link", "mention")}})
        st.setdefault("seen", []).append(i["key"])
        if i.get("box") and not done:
            opened[i["key"]] = [i["box"], i["at"]]
    for k, (box, at) in list(opened.items()):
        if owner_last.get(box, "") > at:
            put({"kind": "answered", "id": k})
            del opened[k]
    st["seen"] = st.get("seen", [])[-SEEN_MAX:]
    while len(opened) > OPEN_MAX:   # самые старые — первыми (порядок вставки)
        del opened[next(iter(opened))]
    st["last_ok"] = iso(now)
    return fresh


def main():
    st, reader = load(), Reader()
    choice = Choice(os.path.join(STATE, "journal.jsonl"), st.get("watch"))
    print(f"teams: старт, опрос раз в {POLL} с, состояние {OWN}", file=sys.stderr, flush=True)
    while True:
        now = datetime.now(timezone.utc)
        last = st.get("last_ok")
        cutoff = iso((datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) - OVERLAP)
                     if last else now - FIRST_BACK)
        try:
            st["watch"] = choice.poll()
            items, owner_last = reader.read(st, cutoff, st["watch"], now)
            st["watch_since"] = reader.next_since
        except Exception as e:   # noqa: BLE001 — процесс живёт дальше; сбой — плашкой во вкладке после FAIL_AFTER
            reader.close()
            st["fails"] = st.get("fails", 0) + 1
            print(f"{iso(now)} teams: сбой {st['fails']}: {e}", file=sys.stderr, flush=True)
            if st["fails"] == FAIL_AFTER:
                # в канал плагина (его читают все сессии) — первая строка ошибки, без хвоста stderr сервера ms365
                post({"kind": "status", "ok": False, "error": short(e), "at": iso(now)})
            save(st)
            time.sleep(POLL)
            continue
        if st.get("fails", 0) >= FAIL_AFTER:
            post({"kind": "status", "ok": True, "at": iso(now)})
        st["fails"] = 0
        fresh = tick(st, items, owner_last, now)
        if fresh:
            print(f"{iso(now)} teams: новых {len(fresh)}", file=sys.stderr, flush=True)
        save(st)
        time.sleep(POLL)


if __name__ == "__main__":
    main()
