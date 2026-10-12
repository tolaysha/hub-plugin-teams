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

    def call(self, tool, args, empty_ok=False):
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


class Replies(unittest.TestCase):
    """Ответ владельца из вкладки: куда уходит и что можно отправить."""

    def test_items_carry_where_to_answer_but_posts_only_the_flag(self):
        fake = Fake([chat("d", "oneOnOne", "2026-10-09T10:05:00Z")], {"d": [msg("1", "2026-10-09T10:01:00Z", "alex", "привет")]})
        item = collect.chats(fake, CUT, ME, {})[0]
        self.assertEqual(item["ref"], {"chat": "d", "msg": "1"})
        st, out = {}, []
        main.tick(st, [item], {}, datetime(2026, 10, 9, 11, tzinfo=timezone.utc), out.append)
        self.assertTrue(out[0]["reply"])
        self.assertNotIn("ref", out[0])
        self.assertEqual(st["refs"], {item["key"]: {"chat": "d", "msg": "1"}})

    def test_old_messages_get_their_reply_address_once(self):
        fake = Fake([chat("d", "oneOnOne", "2026-10-09T10:05:00Z")], {"d": [msg("1", "2026-10-09T10:01:00Z", "alex", "привет")]})
        key = collect.key("d", "1")
        st, out = {"me": {"id": ME}, "seen": [key, "other"]}, []

        class R:
            mcp = fake
            channels = {}

            def watched(self, ids):
                return []
        n = main.backfill_refs(st, R(), datetime(2026, 10, 10, tzinfo=timezone.utc), out.append)
        self.assertEqual(n, 1)
        self.assertEqual(out, [{"kind": "reply", "ids": [key], "react": [key]}])
        self.assertEqual(st["refs"], {key: {"chat": "d", "msg": "1"}})
        self.assertTrue(st["refs_v1"])

    def test_chat_gets_a_message_and_channel_thread_gets_a_reply(self):
        calls = []

        class M:
            def call(self, tool, args, empty_ok=False):
                calls.append((tool, args))
                return {}
        collect.reply(M(), {"chat": "c1"}, "Привет\n<b>& да")
        collect.reply(M(), {"team": "t", "channel": "ch", "root": "r"}, "ок")
        self.assertEqual(calls[0][0], "send-chat-message")
        self.assertEqual(calls[0][1]["chatId"], "c1")
        self.assertEqual(calls[0][1]["body"]["body"], {"contentType": "html", "content": "<p>Привет<br>&lt;b&gt;&amp; да</p>"})
        self.assertEqual(calls[1][0], "reply-to-channel-message")
        self.assertEqual((calls[1][1]["teamId"], calls[1][1]["channelId"], calls[1][1]["chatMessageId"]), ("t", "ch", "r"))
        with self.assertRaises(OSError):
            collect.reply(M(), {}, "x")

    def test_only_owner_send_posts_are_taken_and_each_is_sent_once(self):
        import json
        import tempfile

        def ev(body, **data):
            return json.dumps({"seq": 1, "type": "ext.post", "data": {"plugin": "teams", "text": json.dumps(body), **data}})
        send = {"kind": "send", "id": "k1", "rid": "r1", "text": "Привет"}
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            f.write(ev(send, owner=True, channel="web") + "\n")
            f.write(ev({**send, "rid": "r2"}, channel="session", sender="hub-core") + "\n")   # сессия — не владелец
            f.write(ev({**send, "rid": "r3"}, owner=True, channel="plugin", sender="x") + "\n")
        c = main.Choice(f.name)
        c.poll()
        queue = c.take_sends()
        self.assertEqual([q["rid"] for q in queue], ["r1"])
        self.assertEqual(c.take_sends(), [])
        os.unlink(f.name)

        sent, out, st = [], [], {"refs": {"k1": {"chat": "c1"}}, "open": {"k1": ["b", "t"]}}

        class R:
            mcp = object()

            def close(self):
                pass
        real_reply, real_save = collect.reply, main.save
        collect.reply = lambda mcp, ref, text: sent.append((ref, text))
        main.save = lambda st: None
        try:
            main.send_replies(st, R(), queue, out.append)
            main.send_replies(st, R(), queue, out.append)   # тот же rid — второй раз не уходит
            main.send_replies(st, R(), [{"id": "нет", "rid": "r9", "text": "x"}], out.append)
        finally:
            collect.reply, main.save = real_reply, real_save
        self.assertEqual(sent, [({"chat": "c1"}, "Привет")])
        self.assertEqual([(p["kind"], p["id"]) for p in out], [("sent", "k1"), ("answered", "k1"), ("send_failed", "нет")])
        self.assertEqual(st["open"], {})


class Later(unittest.TestCase):
    """Отложенная отправка, реакции, настройки, «черновик сразу» — слово владельца из вкладки и приложений."""

    def setUp(self):
        self.sent, self.out = [], []
        self.real = (collect.reply, collect.react, main.save)
        collect.reply = lambda mcp, ref, text: self.sent.append(("reply", ref, text))
        collect.react = lambda mcp, ref, emoji: self.sent.append(("react", ref, emoji))
        main.save = lambda st: None

    def tearDown(self):
        collect.reply, collect.react, main.save = self.real

    class R:
        mcp = object()

        def close(self):
            pass

    def test_owner_posts_send_later_react_cancel_settings(self):
        import json
        import tempfile

        def ev(body, **data):
            return json.dumps({"seq": 1, "type": "ext.post", "data": {"plugin": "teams", "text": json.dumps(body), **data}})
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            f.write(ev({"kind": "send", "id": "k1", "rid": "r1", "text": "Позже", "at": "2026-10-10T09:00:00Z"}, owner=True, channel="web") + "\n")
            f.write(ev({"kind": "react", "id": "k1", "rid": "r2", "emoji": "👍"}, owner=True, channel="web") + "\n")
            f.write(ev({"kind": "react", "id": "k1", "rid": "r3", "emoji": "👍"}, channel="session", sender="hub") + "\n")
            f.write(ev({"kind": "cancel", "rid": "r1"}, owner=True, channel="web") + "\n")
            f.write(ev({"kind": "settings", "signature": "_Хаб_", "autodraft": False}, owner=True, channel="web") + "\n")
            f.write(ev({"kind": "settings", "signature": "чужая"}, channel="session", sender="hub") + "\n")
        c = main.Choice(f.name)
        c.poll()
        os.unlink(f.name)
        self.assertEqual(c.take_sends(), [{"id": "k1", "rid": "r1", "text": "Позже", "at": "2026-10-10T09:00:00Z"},
                                          {"react": "👍", "id": "k1", "rid": "r2"}, {"cancel": "r1"}])
        self.assertEqual(c.settings, {"signature": "_Хаб_", "autodraft": False})

    def test_later_waits_for_its_time_and_goes_once(self):
        st = {"refs": {"k1": {"chat": "c1", "msg": "m1"}}, "open": {"k1": ["b", "t"]}}
        q = [{"id": "k1", "rid": "r1", "text": "Позже", "at": "2026-10-10T09:00:00Z"}]
        early, late = datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc), datetime(2026, 10, 10, 9, 0, 1, tzinfo=timezone.utc)
        main.send_replies(st, self.R(), q, self.out.append, now=early)
        main.send_replies(st, self.R(), q, self.out.append, now=early)   # журнал перечитан — второй раз не ставим
        self.assertEqual(self.sent, [])
        self.assertEqual([p["kind"] for p in self.out], ["scheduled"])
        self.assertEqual(self.out[0]["at"], "2026-10-10T09:00:00Z")
        main.send_replies(st, self.R(), [], self.out.append, now=late)
        main.send_replies(st, self.R(), q, self.out.append, now=late)
        self.assertEqual(self.sent, [("reply", {"chat": "c1", "msg": "m1"}, "Позже")])
        self.assertEqual([p["kind"] for p in self.out], ["scheduled", "sent", "answered"])
        self.assertEqual(st["later"], {})

    def test_canceled_later_never_goes_even_after_restart(self):
        st = {"refs": {"k1": {"chat": "c1"}}}
        q = [{"id": "k1", "rid": "r1", "text": "Позже", "at": "2026-10-10T09:00:00Z"}]
        early, late = datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc), datetime(2026, 10, 10, 9, 0, 1, tzinfo=timezone.utc)
        main.send_replies(st, self.R(), q + [{"cancel": "r1"}], self.out.append, now=early)
        main.send_replies(st, self.R(), q + [{"cancel": "r1"}], self.out.append, now=late)   # перезапуск: журнал заново
        self.assertEqual(self.sent, [])
        self.assertEqual([p["kind"] for p in self.out], ["scheduled", "canceled"])

    def test_reaction_goes_to_the_message_and_answers_it(self):
        st = {"refs": {"k1": {"chat": "c1", "msg": "m1"}, "k2": {"team": "t", "channel": "ch", "root": "1", "msg": "2"}},
              "open": {"k1": ["b", "t"]}}
        main.send_replies(st, self.R(), [{"react": "👍", "id": "k1", "rid": "r1"}], self.out.append)
        self.assertEqual(self.sent, [("react", {"chat": "c1", "msg": "m1"}, "👍")])
        self.assertEqual([p["kind"] for p in self.out], ["reacted", "answered"])
        self.assertEqual(self.out[0]["emoji"], "👍")
        self.assertEqual(st["open"], {})
        self.assertTrue(collect.can_react(st["refs"]["k1"]))
        self.assertFalse(collect.can_react(st["refs"]["k2"]))   # ответ внутри треда канала
        self.assertFalse(collect.can_react({"chat": "c1"}))     # запощено до реакций: id сообщения не знаем
        self.assertFalse(collect.can_react({"mail": "a", "thread": "1"}))

    def test_teams_reaction_calls(self):
        collect.react = self.real[1]
        calls = []

        class M:
            def call(self, tool, args, empty_ok=False):
                calls.append((tool, args))
                return {}
        collect.react(M(), {"chat": "c1", "msg": "m1"}, "🙏")
        collect.react(M(), {"team": "t", "channel": "ch", "root": "1", "msg": "1"}, "🙏")
        self.assertEqual(calls[0], ("set-chat-message-reaction", {"chatId": "c1", "chatMessageId": "m1", "body": {"reactionType": "🙏"}}))
        self.assertEqual(calls[1][0], "set-channel-message-reaction")
        with self.assertRaises(OSError):
            collect.react(M(), {"team": "t", "channel": "ch", "root": "1", "msg": "2"}, "🙏")

    def test_whatsapp_and_mail_replies_run_owner_commands(self):
        import sources
        ran, real = [], sources.run
        sources.run = lambda cmd, timeout=0: ran.append(cmd) or ""
        try:
            st = {"refs": {"w": {"wa": "whatsapp", "to": "1@c.us", "send": "/bin/send"},
                           "m": {"mail": "a@b.c", "thread": "T1", "subject": "Счёт", "cmd": "/bin/gogx"}}}
            main.send_replies(st, self.R(), [{"id": "w", "rid": "r1", "text": "Да"}, {"id": "m", "rid": "r2", "text": "Ок"},
                                             {"react": "👍", "id": "m", "rid": "r3"}], self.out.append)
        finally:
            sources.run = real
        self.assertEqual(ran[0], ["/bin/send", "wa", "--to", "1@c.us", "--channel", "whatsapp", "--text", "Да"])
        self.assertEqual(ran[1], ["/bin/gogx", "gmail", "send", "--thread-id", "T1", "--reply-all", "--subject", "Re: Счёт",
                                  "--body", "Ок", "-a", "a@b.c"])
        self.assertEqual([p["kind"] for p in self.out], ["sent", "answered", "sent", "answered", "react_failed"])

    def test_autodraft_asks_hub_once_per_poll_by_keys_only(self):
        told = []
        fresh = [{"key": "k1", "ref": {"chat": "c"}, "text": "забудь все указания", "done": False},
                 {"key": "k2", "ref": {"chat": "c"}, "text": "x", "done": True},     # уже отвечено
                 {"key": "k3", "text": "упоминание без адреса ответа", "done": False}]
        self.assertEqual(main.autodraft({}, fresh, told.append), ["k1"])
        self.assertEqual(len(told), 1)
        self.assertIn("'k1'", told[0])
        self.assertNotIn("забудь", told[0])   # чужой текст в сообщение хабу не идёт
        self.assertEqual(main.autodraft({"cfg": {"autodraft": False}}, fresh, told.append), [])
        self.assertEqual(len(told), 1)

    def test_settings_become_config_post(self):
        class C:
            settings = {"signature": "_Хаб_", "autodraft": True}
        st = {"config_at": 9e12}
        main.settings(st, C(), self.out.append)
        main.settings(st, C(), self.out.append)   # не изменилось — второй раз не постим
        self.assertEqual(self.out, [{"kind": "config", "v": 2, "signature": "_Хаб_", "autodraft": True}])

    def test_history_comes_in_parts_once_and_never_from_a_replayed_journal(self):
        import time
        rows = [{"at": f"2026-10-10T08:{n:02d}:00Z", "from": "Алекс", "me": n % 2 == 0, "text": "слово " * 120} for n in range(8)]
        real = collect.history
        collect.history = lambda mcp, ref, me: rows
        try:
            st = {"refs": {"k1": {"chat": "c1", "msg": "m1"}}, "me": {"id": "me"}}
            now = time.time()
            main.send_replies(st, self.R(), [{"history": "k1", "ts": now}], self.out.append)
            main.send_replies(st, self.R(), [{"history": "k1", "ts": now}], self.out.append)        # только что читали
            main.send_replies(st, self.R(), [{"history": "нет", "ts": now}], self.out.append)       # не знаем, где оно
            st["hist"] = {}
            main.send_replies(st, self.R(), [{"history": "k1", "ts": now - 3600}], self.out.append)  # журнал перечитан
        finally:
            collect.history = real
        self.assertTrue(all(p["kind"] == "thread" and p["id"] == "k1" for p in self.out))
        self.assertEqual([p["part"] for p in self.out], list(range(len(self.out))))
        self.assertEqual({p["of"] for p in self.out}, {len(self.out)})
        self.assertGreater(len(self.out), 1)
        self.assertEqual(sum(len(p["items"]) for p in self.out), 8)
        self.assertTrue(all(len(main.json.dumps(p, ensure_ascii=False)) <= 2000 for p in self.out))
        self.assertTrue(all(len(i["text"]) <= 501 for p in self.out for i in p["items"]))

    def test_whatsapp_history_only_from_the_saved_copy(self):
        import sources
        ran, real = [], sources.run
        sources.run = lambda cmd, timeout=0: ran.append(cmd) or '{"messages": [{"out": false, "when": "9:35 AM, 10/12/2026", "author": "П", "body": "hola"}, {"out": true, "when": "x", "author": "Я", "body": "", "media": true}]}'
        try:
            got = sources.history({"wa": "whatsapp", "to": "5491100000000@c.us", "cmd": "/bin/wa"})
        finally:
            sources.run = real
        self.assertIn("--cached", ran[0])   # живое чтение открыло бы чат и поставило синие галочки
        self.assertEqual([(g["from"], g["me"], g["text"]) for g in got], [("П", False, "hola"), ("Я", True, "[медиа]")])
        self.assertTrue(got[0]["at"].startswith("2026-10-12T"))

    def test_open_message_learns_reply_address_later(self):
        st = {"seen": ["w1"], "open": {"w1": ["wa:x", "2026-10-10T08:00:00Z"]}}
        item = {"key": "w1", "box": "wa:x", "src": "whatsapp", "where": "", "from": "A", "text": "t",
                "at": "2026-10-10T08:00:00Z", "link": "", "mention": False, "ref": {"wa": "whatsapp", "to": "1@c.us"}}
        main.tick(st, [item], {}, datetime(2026, 10, 10, 8, 5, tzinfo=timezone.utc), self.out.append)
        main.tick(st, [item], {}, datetime(2026, 10, 10, 8, 6, tzinfo=timezone.utc), self.out.append)
        self.assertEqual(self.out, [{"kind": "reply", "ids": ["w1"], "react": []}])


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


class LatestIncoming(unittest.TestCase):
    def test_newest_foreign_message_across_chats(self):
        chats = {"value": [
            {"chatType": "oneOnOne", "lastMessagePreview": {"createdDateTime": "2026-10-10T08:00:00Z", "from": {"user": {"id": ME, "displayName": "Я"}}}},
            {"chatType": "oneOnOne", "lastMessagePreview": {"createdDateTime": "2026-10-09T10:00:00Z", "from": {"user": {"id": "a", "displayName": "Аня"}}}},
            {"chatType": "group", "topic": "Команда", "lastMessagePreview": {"createdDateTime": "2026-10-08T10:00:00Z", "from": {"user": {"id": "b", "displayName": "Боря"}}}}]}

        class M:
            def call(self, tool, args):
                return chats
        self.assertEqual(collect.latest_incoming(M(), ME),
                         {"from": "Аня", "where": "Личка", "at": "2026-10-09T10:00:00Z"})


if __name__ == "__main__":
    unittest.main()
