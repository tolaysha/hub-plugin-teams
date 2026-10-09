"""Сборщик «Teams сообщения» без сети: поддельный ms365 MCP. Запуск: python3.12 -m unittest discover -s tests (из папки
расширения, PYTHONPATH — код хаба)."""
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


def msg(mid, at, who, text, mentions=(), attachments=(), deleted=False):
    return {"id": mid, "createdDateTime": at, "messageType": "message", "deletedDateTime": "x" if deleted else None,
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
        fake = Fake([chat("d", "oneOnOne", "2026-10-09T10:05:00Z"), chat("g", "group", "2026-10-09T10:06:00Z", "Команда"),
                     chat("old", "oneOnOne", "2026-10-09T09:00:00Z")],
                    {"d": [msg("1", "2026-10-09T10:01:00Z", "alex", "<p>привет&nbsp;<b>Иван</b></p>"),
                           msg("2", "2026-10-09T10:02:00Z", ME, "мой ответ"),
                           msg("3", "2026-10-09T09:59:00Z", "alex", "старое")],
                     "g": [msg("4", "2026-10-09T10:03:00Z", "kate", "болтовня"),
                           msg("5", "2026-10-09T10:04:00Z", "kate", '<at id="0">Owner</at> глянь', mentions=[ME]),
                           msg("6", "2026-10-09T10:05:00Z", "ivan", "да", attachments=[ref]),
                           msg("7", "2026-10-09T10:06:00Z", "ivan", "x", mentions=[ME], deleted=True)]})
        last = {}
        out = collect.chats(fake, CUT, ME, last)
        self.assertEqual([(i["src"], i["text"]) for i in out],
                         [("dm", "привет Иван"), ("mention", "@Owner глянь"), ("mention", "да")])
        self.assertEqual(out[0]["where"], "Личка")
        self.assertEqual(out[1]["where"], "Команда")
        self.assertEqual(last[collect.key("d", "")], "2026-10-09T10:02:00Z")


class ChannelPosts(unittest.TestCase):
    def test_only_thread_root_replies_only_when_mentioning_owner(self):
        # владелец 09.10: «из саппорта только первое сообщение… сообщения внутри поста не надо»
        old = msg("r", "2026-10-09T09:00:00Z", "maria", "<p>Странная сумма</p><p>подробности</p>")
        old["replies"] = [msg("a", "2026-10-09T10:01:00Z", "alex", "смотрим"),
                          msg("m", "2026-10-09T10:01:30Z", "alex", "@Owner глянь", mentions=[ME]),
                          msg("b", "2026-10-09T10:02:00Z", ME, "ок")]
        new = msg("n", "2026-10-09T10:03:00Z", "olga", "Новый вопрос")
        new["replies"] = [msg("c", "2026-10-09T10:04:00Z", "alex", "ответ в треде")]
        last = {}
        info = {"teamId": "team", "team": "Company", "channel": "Support"}
        out = collect.channel_posts(Fake(channel=[new, old]), "chan", info, CUT, ME, last)
        self.assertEqual([(i["src"], i["text"]) for i in out], [("channel", "Новый вопрос"), ("mention", "@Owner глянь")])
        self.assertEqual(out[0]["where"], "Company › Support")
        self.assertIn("Странная сумма", out[1]["where"])
        self.assertEqual(last[collect.key("chan", "r")], "2026-10-09T10:02:00Z")


class Mentions(unittest.TestCase):
    def test_channel_hits_with_name_in_text_only(self):
        def hit(mid, chan, who, summary, at="2026-10-09T10:01:00Z"):
            return {"summary": summary, "resource": {"id": mid, "createdDateTime": at, "webLink": "l",
                    "channelIdentity": {"channelId": chan} if chan else None,
                    "from": {"emailAddress": {"name": who, "address": f"{who}@x"}}}}
        hits = [hit("1", "c1", "alex", "<c0>Owner</c0> посмотри"), hit("2", "c1", "alex", "без имени"),
                hit("3", None, "alex", "Owner в чате"), hit("4", "sup", "alex", "Owner в Support"),
                hit("5", "c1", "me", "Owner сам"), hit("6", "c1", "alex", "Owner", at="2026-10-09T09:00:00Z")]
        out = collect.channel_mentions(Fake(hits=hits), CUT, "me@x", "Owner",
                                       {"c1": {"team": "Dev", "channel": "Backend", "teamId": "t"}}, skip={"sup"})
        self.assertEqual([(i["text"], i["where"]) for i in out], [("Owner посмотри", "Dev › Backend")])


class Tick(unittest.TestCase):
    def item(self, k, at, box="b"):
        return {"key": k, "box": box, "src": "dm", "where": "Личка", "from": "P", "text": "t", "at": at,
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



class Channels(unittest.TestCase):
    CH = {"c1": {"team": "Company", "teamId": "t1", "channel": "Support"},
          "c2": {"team": "Dev", "teamId": "t2", "channel": "Backend"}}

    def setUp(self):   # в общем плагине канала по умолчанию нет; тест задаёт его сам
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
        # ревью 09.10: 20 каналов с длинными именами в одной части — пост длиннее 2000, KeyError в post()
        ch = {f"c{i}": {"team": "Команда " + "я" * 90, "teamId": "t", "channel": "Канал " + "ы" * 90} for i in range(60)}
        _, posts = main.directory_posts(ch, [])
        self.assertTrue(all(len(main.json.dumps(p, ensure_ascii=False)) <= main.POST_MAX for p in posts))
        self.assertEqual(sum(len(p["items"]) for p in posts), 60)

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
            f.write(ev({"kind": "watch", "ids": ["x"]}, channel="session", sender="hub") + "\n")   # не владелец
            f.write(ev({"kind": "watch", "ids": ["y"]}, channel="plugin", sender="teams") + "\n")  # сам плагин
            # ревью 09.10: owner:true из чужого процесса плагина — не владелец (ядро: owner is True и его канал)
            f.write(ev({"kind": "watch", "ids": ["z"]}, owner=True, channel="plugin", sender="x") + "\n")
        c = main.Choice(f.name)
        self.assertEqual(c.poll(), ["a"])
        with open(f.name, "a") as g:
            g.write(ev({"kind": "watch", "ids": ["b", "c"]}, owner=True, channel="web") + "\n")
            g.write('{"type": "ext.post", "data": {"plu')   # недописанная строка — дочитаем потом
        self.assertEqual(c.poll(), ["b", "c"])
        with open(f.name, "a") as g:   # ядро отклонило следующий пост владельца — выбор остаётся прежним
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
        e = OSError("ms365: сервер закрылся: token=secret-abc debug dump")
        self.assertEqual(main.short(e), "ms365: сервер закрылся")

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
