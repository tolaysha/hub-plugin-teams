"""The process of the "Teams messages" extension (hub-up: HUB_STATE_DIR, PYTHONPATH to the hub code, HUB_EXTENSION).

Every POLL s it reads Teams (collect.py; the ms365 MCP client is mcp.py, one server process for the whole run) and
posts to the plugin channel one post per new message: {"kind": "msg", ...}. The list of team channels goes as
{"kind": "channels"} posts (in parts); which of them to read the owner picks in the tab — his post
{"kind": "watch", "ids"} (Choice). The owner replied later in the same conversation — a post {"kind": "answered", "id"}.
Reading failed FAIL_AFTER times in a row — {"kind": "status", "ok": false, "error"}, recovered —
{"kind": "status", "ok": true}: the tab shows it as a banner. No model.

Its own state (what is already posted, the time of the last good read) lives in <state>/ext-teams, not in the
extension folder: a file that changes every tick would reload open tabs (the page watches the mtime of extension
files)."""
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

sys.dont_write_bytecode = True   # no __pycache__ in the extension folder, for the same reason

from core import spool  # noqa: E402
from core.daemon import default_state_dir  # noqa: E402
from core.tools import from_owner  # noqa: E402

import collect  # noqa: E402

import mcp  # noqa: E402

# the plugin channel is the name without the author: from the catalog the plugin installs as "<account>:teams", the page writes to "teams"
NAME = os.environ.get("HUB_EXTENSION", "teams").split(":")[-1]
STATE = default_state_dir()
OWN = os.path.join(STATE, "ext-teams")
STATE_PATH = os.path.join(OWN, "state.json")
POLL = int(os.environ.get("TEAMS_POLL") or 60)
FIRST_BACK = timedelta(hours=24)   # first run: messages of the last day, so the tab is not empty
OVERLAP = timedelta(minutes=15)    # look back from the last read: Graph search indexes with a delay
FAIL_AFTER = 3
SEEN_MAX, OPEN_MAX = 3000, 500
POST_MAX = 2000
DIR_EVERY = 6 * 3600               # the team channel list is re-read and re-posted every 6 hours: the plugin channel
                                   # keeps the last 500 posts, old lists get pushed out by messages
SCAN_EVERY = 10 * 60               # every 10 minutes re-read the chats of the last day: the owner's reply or reaction to
SCAN_BACK = timedelta(hours=24)    # an already shown message, when the chat has no new messages


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
    """The error for the tab banner: the first line, without the tail of the ms365 server stderr."""
    text = (str(e).splitlines() or [type(e).__name__])[0]
    return re.sub(r"(server closed):.*", r"\1", text)[:160]


def post(data):
    text = json.dumps(data, ensure_ascii=False)
    if len(text) > POST_MAX and isinstance(data.get("text"), str):   # a channel post is up to 2000 characters: cut the text
        data = {**data, "text": data["text"][:max(0, len(data["text"]) - (len(text) - POST_MAX) - 1)] + "…"}
        text = json.dumps(data, ensure_ascii=False)
    if len(text) > POST_MAX:   # the core would not accept it; channel lists are split by directory_posts, so this should not happen
        print(f"teams: post {data.get('kind')} is longer than {POST_MAX} characters, not sent", file=sys.stderr, flush=True)
        return
    spool.put(os.path.join(STATE, "spool"), "ext.post", None,
              {"plugin": NAME, "text": text, "channel": "plugin", "owner": False, "sender": NAME}, src=f"ext:{NAME}")


class Choice:
    """Which channels the owner picked in the tab: his last post accepted by the core {"kind": "watch", "ids": [channel
    keys]} in the plugin channel. We read the journal ourselves from where we stopped, line by line, only this plugin's
    posts (the whole views.Reader is not needed here). The owner is as in the core (core.tools.from_owner: owner is True
    and his channel); a post the core rejected (followed in the journal by core.rejected with of = its seq) does not
    count. The choice is also kept in the process state (ids at creation): after a journal rotation the old post is gone."""

    def __init__(self, path, ids=None):
        self.path, self.offset, self.ino, self.ids, self.before = path, 0, None, ids, ids
        self.recent = []   # [(seq, ids)]: the latest posts that look accepted; the core may reject them right after

    def poll(self):
        try:
            ino = os.stat(self.path).st_ino
            if ino != self.ino:   # the journal was started anew (journal.rotate): read from the start
                self.ino, self.offset = ino, 0
            with open(self.path, "rb") as f:
                f.seek(self.offset)
                for line in f:
                    if not line.endswith(b"\n"):   # the line is still being written: read it next time
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
    """The channel list to pick from in the tab, split by length (a post is up to 2000 characters): [key, team, channel]."""
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
    """One ms365 MCP process while it lives; if it dies, a new one on the next tick."""

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
        """Team channels, at start and every DIR_EVERY: "channels" posts for the tab and next to them
        {"kind": "watching"} — which channels we read now. The same set also when the choice changed: the page sees
        exactly what the process reads, even when the owner's "watch" post was pushed out of the channel (500 posts).
        A process restart (every hub restart) does not re-post the list if it is the same and was posted less than
        DIR_EVERY ago: otherwise the lists pushed messages out of the channel."""
        if not self.channels or time.time() - self.listed >= DIR_EVERY:
            self.channels, self.listed = collect.directory(self.mcp), time.time()
        sig, posts = directory_posts(self.channels, collect.default_watch(self.channels))
        if sig != st.get("dir_sig") or time.time() - st.get("dir_at", 0) >= DIR_EVERY or st.get("posted_choice") != choice:
            for p in posts:
                put(p)
            put({"kind": "watching", "ids": [channel_key(c) for c in self.watched(choice)]})
            st.update(posted_choice=choice, dir_sig=sig, dir_at=time.time())

    def watched(self, ids):
        """channelId of the chosen channels: the owner's choice (keys) or the default channel."""
        if ids is None:
            return collect.default_watch(self.channels)
        want = set(ids)
        return [cid for cid in self.channels if channel_key(cid) in want]

    def read(self, st, cutoff, choice, now, put=None):
        """Messages, {box: the owner's reply} and the keys of messages with his reaction. Which channels we read from
        what time is in self.next_since: main puts it into the state only after a good read (otherwise a new channel
        would lose its first day)."""
        if not self.mcp:
            self.connect(st)
        self.refresh(st, choice, put or post)
        me, owner_last, reacted = st["me"], {}, set()
        scan = None
        if time.time() - st.get("scan_at", 0) >= SCAN_EVERY:
            scan, st["scan_at"] = iso(now - SCAN_BACK), time.time()
        items = collect.chats(self.mcp, cutoff, me["id"], owner_last, reacted=reacted, scan=scan)
        watched = self.watched(choice)
        since = st.get("watch_since") or {}   # channel key -> since when we watch it
        for cid in watched:
            k = channel_key(cid)
            # a channel just picked: its posts of the last day, after that like all others (from the last read)
            own_cut = cutoff if k in since else iso(now - FIRST_BACK)
            items += collect.channel_posts(self.mcp, cid, self.channels[cid], own_cut, me["id"], owner_last,
                                           reacted=reacted)
        self.next_since = {channel_key(cid): since.get(channel_key(cid)) or iso(now) for cid in watched}
        if me["name"]:
            items += collect.channel_mentions(self.mcp, cutoff, me["mail"], me["name"], self.channels, skip=set(watched))
        return items, owner_last, reacted


def tick(st, items, owner_last, now, put=post, reacted=()):
    """New messages go to the channel (oldest first); the ones the owner answered (a later reply in the same
    conversation or his reaction to the message itself) get marked. Changes st."""
    seen = set(st.get("seen") or [])
    opened = st.setdefault("open", {})   # key -> [box, at]: posted, not answered yet
    fresh, keys = [], set()
    for i in sorted(items, key=lambda i: i["at"]):
        if i["key"] in seen or i["key"] in keys:   # a channel message with a mention is found twice: take the first
            continue
        keys.add(i["key"])
        fresh.append(i)
    for i in fresh:
        done = (bool(i.get("box")) and owner_last.get(i["box"], "") > i["at"]) or i["key"] in reacted   # already answered
        put({"kind": "msg", "id": i["key"], "answered": done,
             **{k: i[k] for k in ("src", "where", "from", "text", "at", "link", "mention")}})
        st.setdefault("seen", []).append(i["key"])
        if i.get("box") and not done:
            opened[i["key"]] = [i["box"], i["at"]]
    for k, (box, at) in list(opened.items()):
        if owner_last.get(box, "") > at or k in reacted:
            put({"kind": "answered", "id": k})
            del opened[k]
    st["seen"] = st.get("seen", [])[-SEEN_MAX:]
    while len(opened) > OPEN_MAX:   # the oldest first (insertion order)
        del opened[next(iter(opened))]
    st["last_ok"] = iso(now)
    return fresh


def main():
    st, reader = load(), Reader()
    choice = Choice(os.path.join(STATE, "journal.jsonl"), st.get("watch"))
    print(f"teams: start, polling every {POLL} s, state {OWN}", file=sys.stderr, flush=True)
    while True:
        now = datetime.now(timezone.utc)
        last = st.get("last_ok")
        cutoff = iso((datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) - OVERLAP)
                     if last else now - FIRST_BACK)
        try:
            st["watch"] = choice.poll()
            items, owner_last, reacted = reader.read(st, cutoff, st["watch"], now)
            st["watch_since"] = reader.next_since
        except Exception as e:   # noqa: BLE001 — the process lives on; a failure shows as a tab banner after FAIL_AFTER
            reader.close()
            st["fails"] = st.get("fails", 0) + 1
            print(f"{iso(now)} teams: failure {st['fails']}: {e}", file=sys.stderr, flush=True)
            if st["fails"] == FAIL_AFTER:
                # to the plugin channel (all sessions read it): the first line of the error, without the tail of the ms365 server stderr
                post({"kind": "status", "ok": False, "error": short(e), "at": iso(now)})
            save(st)
            time.sleep(POLL)
            continue
        if st.get("fails", 0) >= FAIL_AFTER:
            post({"kind": "status", "ok": True, "at": iso(now)})
        st["fails"] = 0
        fresh = tick(st, items, owner_last, now, reacted=reacted)
        if fresh:
            print(f"{iso(now)} teams: {len(fresh)} new", file=sys.stderr, flush=True)
        save(st)
        time.sleep(POLL)


if __name__ == "__main__":
    main()
