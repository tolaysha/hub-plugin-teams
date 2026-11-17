"""The "Teams messages" collector without a network: a fake ms365 MCP. Run: python3.12 -m unittest discover -s tests (from
the extension folder, PYTHONPATH — the hub code)."""
import os
import sys
import unittest
from datetime import datetime, timezone

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("HUB_STATE_DIR", "/tmp/teams-ext-test")

import collect  # noqa: E402
import main  # noqa: E402

ME = "me"
CUT = "2026-10-09T10:00:00Z"


def msg(mid, at, who, text, mentions=(), attachments=(), deleted=False, reacted_by=()):
    return {"reactions": [{"reactionType": "👍", "user": {"user": {"id": u}}} for u in reacted_by],
            "id": mid, "createdDateTime": at, "messageType": "message", "deletedDateTime": "x" if deleted else None,
            "from": {"user": {"id": who, "displayName": who.title()}} if who else None,
            "body": {"content": text}, "webUrl": f"https://t/{mid}",
            "mentions": [{"mentioned": {"user": {"id": u}}} for u in mentions], "attachments": list(attachments)}


class Fake:
    def __init__(self, chats=(), chat_msgs=None, channel=(), hits=()):
        self.chats, self.chat_msgs, self.channel, self.hits = list(chats), chat_msgs or {}, list(channel), list(hits)

    def call(self, tool, args):
        if tool == "list-chats":
            return {"value": self.chats}
        if tool == "list-chat-messages":
            return {"value": self.chat_msgs.get(args["chatId"], [])}
        if tool == "list-channel-messages":
            return {"value": self.channel}
        if tool == "search-query":
            return {"value": [{"hitsContainers": [{"hits": self.hits}]}]}
        raise AssertionError(tool)


def chat(cid, kind, last, topic=None):
    return {"id": cid, "chatType": kind, "topic": topic, "lastMessagePreview": {"createdDateTime": last}}


class Chats(unittest.TestCase):
    def test_dm_all_foreign_group_only_mentions_and_replies(self):
        ref = {"contentType": "messageReference", "content": '{"messageSender": {"user": {"id": "me"}}}'}
        fake = Fake([chat("d", "oneOnOne", "2026-10-09T10:05:00Z"), chat("g", "group", "2026-10-09T10:06:00Z", "Team chat"),
                     chat("old", "oneOnOne", "2026-10-09T09:00:00Z")],
                    {"d": [msg("1", "2026-10-09T10:01:00Z", "alex", "<p>hi&nbsp;<b>Sam</b></p>"),
                           msg("2", "2026-10-09T10:02:00Z", ME, "my reply"),
                           msg("3", "2026-10-09T09:59:00Z", "alex", "old")],
                     "g": [msg("4", "2026-10-09T10:03:00Z", "kate", "chit-chat"),
                           msg("5", "2026-10-09T10:04:00Z", "kate", '<at id="0">Owner</at> take a look', mentions=[ME]),
                           msg("6", "2026-10-09T10:05:00Z", "ivan", "yes", attachments=[ref]),
                           msg("7", "2026-10-09T10:06:00Z", "ivan", "x", mentions=[ME], deleted=True)]})
        last = {}
        out = collect.chats(fake, CUT, ME, last)
        self.assertEqual([(i["src"], i["text"]) for i in out],
                         [("dm", "hi Sam"), ("mention", "@Owner take a look"), ("mention", "yes")])
        self.assertEqual(out[0]["where"], "Direct message")
        self.assertEqual(out[1]["where"], "Team chat")
        self.assertEqual(last[collect.key("d", "")], "2026-10-09T10:02:00Z")


    def test_owner_reaction_is_an_answer(self):
        # the owner reacted: the message is handled, like a reply
        fake = Fake([chat("d", "oneOnOne", "2026-10-09T10:05:00Z")],
                    {"d": [msg("1", "2026-10-09T10:01:00Z", "alex", "look at the MR", reacted_by=[ME]),
                           msg("2", "2026-10-09T10:02:00Z", "alex", "and one more question", reacted_by=["kate"])]})
        reacted = set()
        out = collect.chats(fake, CUT, ME, {}, reacted=reacted)
        self.assertEqual([i["text"] for i in out], ["look at the MR", "and one more question"])
        self.assertEqual(reacted, {collect.key("d", "1")})

    def test_chatter_is_not_a_message(self):
        # reactions to messages are not shown as messages: laughter, emoji, "ok" in direct messages (Russian and English input)
        texts = ["ахахх)", "ахах)", "))", "👍", "ок", "Спасибо!", "<p>&nbsp;</p>", "да", "лол 😂", "haha", "Thanks!", "ok"]
        keep = ["да, сделаю завтра", "ок, а что с MR?", "100% )"]
        fake = Fake([chat("d", "oneOnOne", "2026-10-09T10:05:00Z")],
                    {"d": [msg(str(i), "2026-10-09T10:01:00Z", "alex", t) for i, t in enumerate(texts + keep)]})
        self.assertEqual([i["text"] for i in collect.chats(fake, CUT, ME, {})], keep)

    def test_older_chats_rechecked_for_answers_without_old_messages(self):
        # the owner's reaction or reply in a chat with no new messages: the chat is read on the recheck (scan), but the
        # old message does not become new
        fake = Fake([chat("d", "oneOnOne", "2026-10-09T08:00:00Z")],
                    {"d": [msg("1", "2026-10-09T08:00:00Z", "alex", "a question", reacted_by=[ME])]})
        reacted, last = set(), {}
        self.assertEqual(collect.chats(fake, CUT, ME, last, reacted=reacted), [])
        self.assertEqual(reacted, set())
        self.assertEqual(collect.chats(fake, CUT, ME, last, reacted=reacted, scan="2026-10-08T10:00:00Z"), [])
        self.assertEqual(reacted, {collect.key("d", "1")})


class ChannelPosts(unittest.TestCase):
    def test_only_thread_root_replies_only_when_mentioning_owner(self):
        # a chosen channel: only the first message of a thread, not the replies inside it
        old = msg("r", "2026-10-09T09:00:00Z", "maria", "<p>Odd amount</p><p>details</p>")
        old["replies"] = [msg("a", "2026-10-09T10:01:00Z", "alex", "looking"),
                          msg("m", "2026-10-09T10:01:30Z", "alex", "@Owner take a look", mentions=[ME]),
                          msg("b", "2026-10-09T10:02:00Z", ME, "ok")]
        new = msg("n", "2026-10-09T10:03:00Z", "olga", "New question")
        new["replies"] = [msg("c", "2026-10-09T10:04:00Z", "alex", "a reply in the thread")]
        last = {}
        info = {"teamId": "team", "team": "Company", "channel": "Support"}
        out = collect.channel_posts(Fake(channel=[new, old]), "chan", info, CUT, ME, last)
        self.assertEqual([(i["src"], i["text"]) for i in out], [("channel", "New question"), ("mention", "@Owner take a look")])
        self.assertEqual(out[0]["where"], "Company › Support")
        self.assertIn("Odd amount", out[1]["where"])
        self.assertEqual(last[collect.key("chan", "r")], "2026-10-09T10:02:00Z")


class Mentions(unittest.TestCase):
    def test_channel_hits_with_name_in_text_only(self):
        def hit(mid, chan, who, summary, at="2026-10-09T10:01:00Z", team="t", address=None):
            return {"summary": summary, "resource": {"id": mid, "createdDateTime": at, "webLink": "l",
                    "channelIdentity": {"channelId": chan, **({"teamId": team} if team else {})} if chan else None,
                    "from": {"emailAddress": {"name": who, "address": address or f"{who}@x"}}}}
        hits = [hit("1", "c1", "alex", "<c0>Owner</c0> have a look"), hit("2", "c1", "alex", "no name"),
                hit("3", None, "alex", "Owner in a chat"), hit("4", "sup", "alex", "Owner in Support"),
                hit("5", "c1", "me", "Owner himself"), hit("6", "c1", "alex", "Owner", at="2026-10-09T09:00:00Z"),
                # Workflows bot cards are not mentions; a chat in search also has a channelId (the chat id) but no
                # teamId — chats are read by chats()
                hit("7", "c1", "Workflows", "..., Owner ...", address="Workflows@teams.microsoft.com"),
                hit("8", "19:a_b@unq.gbl.spaces", "alex", "Owner in a direct chat", team=None)]
        out = collect.channel_mentions(Fake(hits=hits), CUT, "me@x", "Owner",
                                       {"c1": {"team": "Dev", "channel": "Backend", "teamId": "t"}}, skip={"sup"})
        self.assertEqual([(i["text"], i["where"]) for i in out], [("Owner have a look", "Dev › Backend")])


class Tick(unittest.TestCase):
    def item(self, k, at, box="b"):
        return {"key": k, "box": box, "src": "dm", "where": "Direct message", "from": "P", "text": "t", "at": at,
                "link": "l", "mention": False}

    def test_posts_new_once_and_marks_answered_later(self):
        st, out, now = {}, [], datetime(2026, 10, 9, 11, tzinfo=timezone.utc)
        main.tick(st, [self.item("k1", "2026-10-09T10:01:00Z"), self.item("k1", "2026-10-09T10:01:00Z")], {}, now, out.append)
        self.assertEqual([(p["kind"], p["id"], p["answered"]) for p in out], [("msg", "k1", False)])
        main.tick(st, [self.item("k1", "2026-10-09T10:01:00Z")], {"b": "2026-10-09T10:05:00Z"}, now, out.append)
        self.assertEqual([p["kind"] for p in out], ["msg", "answered"])
        self.assertEqual(st["open"], {})
        self.assertEqual(st["last_ok"], "2026-10-09T11:00:00Z")

    def test_already_answered_message_comes_answered_without_second_post(self):
        st, out = {}, []
        main.tick(st, [self.item("k2", "2026-10-09T10:01:00Z")], {"b": "2026-10-09T10:02:00Z"},
                  datetime(2026, 10, 9, 11, tzinfo=timezone.utc), out.append)
        self.assertEqual([(p["kind"], p["answered"]) for p in out], [("msg", True)])

    def test_reaction_answers_new_and_open_messages(self):
        st, out, now = {}, [], datetime(2026, 10, 9, 11, tzinfo=timezone.utc)
        main.tick(st, [self.item("k1", "2026-10-09T10:01:00Z"), self.item("k2", "2026-10-09T10:02:00Z")], {}, now,
                  out.append, reacted={"k2"})
        self.assertEqual([(p["id"], p["answered"]) for p in out], [("k1", False), ("k2", True)])
        main.tick(st, [], {}, now, out.append, reacted={"k1"})
        self.assertEqual([(p["kind"], p["id"]) for p in out[2:]], [("answered", "k1")])
        self.assertEqual(st["open"], {})



class Channels(unittest.TestCase):
    CH = {"c1": {"team": "Company", "teamId": "t1", "channel": "Support"},
          "c2": {"team": "Dev", "teamId": "t2", "channel": "Backend"}}

    def setUp(self):   # the shared plugin has no default channel; the test sets one itself
        self.saved, collect.DEFAULT_WATCH = collect.DEFAULT_WATCH, ("Company", "Support")

    def tearDown(self):
        collect.DEFAULT_WATCH = self.saved

    def test_no_default_channel_out_of_the_box(self):
        collect.DEFAULT_WATCH = ()
        self.assertEqual(collect.default_watch(self.CH), [])

    def test_directory_in_parts_with_default_in_first(self):
        sig, posts = main.directory_posts(self.CH, collect.default_watch(self.CH), budget=10)
        self.assertEqual([(p["part"], p["of"], p["sig"]) for p in posts], [(0, 2, sig), (1, 2, sig)])
        self.assertEqual(posts[0]["items"], [[main.channel_key("c1"), "Company", "Support"]])
        self.assertEqual(posts[0]["default"], [main.channel_key("c1")])
        self.assertNotIn("default", posts[1])

    def test_directory_parts_fit_a_post_even_with_long_names(self):
        # 20 channels with long names in one part made a post longer than 2000 and a KeyError in post()
        ch = {f"c{i}": {"team": "Команда " + "я" * 90, "teamId": "t", "channel": "Канал " + "ы" * 90} for i in range(60)}
        _, posts = main.directory_posts(ch, [])
        self.assertTrue(all(len(main.json.dumps(p, ensure_ascii=False)) <= main.POST_MAX for p in posts))
        self.assertEqual(sum(len(p["items"]) for p in posts), 60)

    def test_directory_not_reposted_on_every_restart(self):
        # the channel keeps 500 posts: the channel list on every hub restart pushed messages out
        class Dir:
            def call(self, tool, args):
                return {"value": [{"id": "t1", "displayName": "Company"}]} if tool == "list-joined-teams" else \
                    {"value": [{"id": "c1", "displayName": "Support"}]}
        st, out = {}, []
        r = main.Reader()
        r.mcp = Dir()
        r.refresh(st, ["k"], out.append)
        self.assertEqual([p["kind"] for p in out], ["channels", "watching"])
        r2 = main.Reader()   # a restart: the same state, list and choice — no post
        r2.mcp = Dir()
        r2.refresh(st, ["k"], out.append)
        self.assertEqual(len(out), 2)
        r2.refresh(st, ["k", "m"], out.append)   # the choice changed — post
        self.assertEqual(len(out), 4)
        st["dir_at"] -= main.DIR_EVERY   # long ago — post again (the old list was pushed out of the channel)
        r3 = main.Reader()
        r3.mcp = Dir()
        r3.refresh(st, ["k", "m"], out.append)
        self.assertEqual(len(out), 6)

    def test_watched_is_owner_choice_or_default(self):
        r = main.Reader()
        r.channels = self.CH
        self.assertEqual(r.watched(None), ["c1"])
        self.assertEqual(r.watched([main.channel_key("c2")]), ["c2"])
        self.assertEqual(r.watched([]), [])

    def test_choice_takes_latest_owner_watch_post_only(self):
        import json
        import tempfile

        def ev(text, seq=0, **data):
            return json.dumps({"seq": seq, "type": "ext.post", "data": {"plugin": "teams", "text": json.dumps(text), **data}})
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            f.write(ev({"kind": "watch", "ids": ["a"]}, owner=True, channel="web") + "\n")
            f.write(ev({"kind": "watch", "ids": ["x"]}, channel="session", sender="hub") + "\n")   # not the owner
            f.write(ev({"kind": "watch", "ids": ["y"]}, channel="plugin", sender="teams") + "\n")  # the plugin itself
            # owner:true from another plugin's process is not the owner (the core: owner is True and his channel)
            f.write(ev({"kind": "watch", "ids": ["z"]}, owner=True, channel="plugin", sender="x") + "\n")
        c = main.Choice(f.name)
        self.assertEqual(c.poll(), ["a"])
        with open(f.name, "a") as g:
            g.write(ev({"kind": "watch", "ids": ["b", "c"]}, owner=True, channel="web") + "\n")
            g.write('{"type": "ext.post", "data": {"plu')   # an unfinished line — read it later
        self.assertEqual(c.poll(), ["b", "c"])
        with open(f.name, "a") as g:   # the core rejected the owner's next post — the choice stays as it was
            g.write('ignored"}}\n' + ev({"kind": "watch", "ids": ["bad"]}, seq=7, owner=True, channel="web") + "\n")
            g.write(json.dumps({"type": "core.rejected", "data": {"of": 7, "type": "ext.post"}}) + "\n")
        self.assertEqual(c.poll(), ["b", "c"])
        os.unlink(f.name)

    def test_choice_survives_journal_rotation_through_state(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            f.write("{}\n")
        self.assertEqual(main.Choice(f.name, ["saved"]).poll(), ["saved"])
        os.unlink(f.name)


class Safety(unittest.TestCase):
    def test_status_error_drops_ms365_stderr_tail(self):
        e = OSError("ms365: server closed: token=secret-abc debug dump")
        self.assertEqual(main.short(e), "ms365: server closed")

    def test_non_text_oversized_post_is_dropped_not_raised(self):
        sent = []
        orig = main.spool.put
        main.spool.put = lambda *a, **k: sent.append(a)
        try:
            main.post({"kind": "channels", "items": [["x" * 3000]]})
        finally:
            main.spool.put = orig
        self.assertEqual(sent, [])


if __name__ == "__main__":
    unittest.main()
