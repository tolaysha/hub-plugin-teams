"""Каналы WhatsApp и почта без сети: поддельные wa и gogx. Запуск — как test_collect (PYTHONPATH — код хаба)."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("HUB_STATE_DIR", "/tmp/teams-ext-test")

import main  # noqa: E402
import sources  # noqa: E402

NOW = datetime(2026, 10, 10, 15, 0, tzinfo=timezone.utc)


def fake_run(table):
    def run(cmd, timeout=90):
        for key, out in table.items():
            if key in " ".join(cmd):
                if isinstance(out, Exception):
                    raise out
                return json.dumps(out)
        raise OSError("нет такой команды")
    return run


class Tier(unittest.TestCase):
    def test_closing_ack_and_receipts_do_not_ask_for_attention(self):
        self.assertEqual(sources.tier("Gracias!"), "C")
        self.assertEqual(sources.tier("Your Evernote refund is on its way"), "C")
        self.assertEqual(sources.tier("Pago rechazado, cuenta suspendida"), "A")
        self.assertEqual(sources.tier("Podés pasar mañana a las 10?"), "B")


class WhatsApp(unittest.TestCase):
    def setUp(self):
        self._run = sources.run

    def tearDown(self):
        sources.run = self._run

    def test_only_unread_personal_chats_with_substance(self):
        sources.run = fake_run({"new": [
            {"chat_id": "5491100000001@c.us", "name": "Лена", "new": 2, "unread": 2, "last": "2026-10-10T11:30-03:00",
             "preview": "Привет, пришлёшь договор до вечера?"},
            {"chat_id": "5491100000002@c.us", "name": "Паша", "new": 1, "unread": 0, "last": "2026-10-10T11:00-03:00",
             "preview": "Я уже ответил"},                                           # прочитано — нет
            {"chat_id": "5491100000003@c.us", "name": "Мастер", "new": 1, "unread": 1, "last": "2026-10-10T10:00-03:00",
             "preview": "Gracias!"},                                                 # закрывающее — нет
            {"chat_id": "120363@g.us", "name": "Соседи", "new": 9, "unread": 9, "last": "2026-10-10T10:00-03:00",
             "preview": "Кто идёт на собрание?"},                                    # группа без срочного — нет
        ]})
        items, boxes, errors = sources.whatsapp({"channels": ["whatsapp"]}, NOW)
        self.assertEqual([i["from"] for i in items], ["Лена"])
        self.assertEqual(items[0]["src"], "whatsapp")
        self.assertEqual(items[0]["at"], "2026-10-10T14:30:00Z")
        self.assertEqual(boxes, {"wa:whatsapp:5491100000001@c.us"})
        self.assertEqual(errors, [])

    def test_card_is_the_text_of_new_messages_after_owner_reply_only(self):
        """12.10: в карточке был счётчик («4 текстовых»), а после ответа владельца поднималось уже отвеченное."""
        def m(mid, t, text="", cached=True, kind="chat"):
            return {"id": mid, "t": t, "type": kind, "text": text, "cached": cached}
        chat = {"chat_id": "5491100000005@c.us", "name": "Мастер", "new": 4, "unread": 3, "last": "2026-10-10T11:36-03:00",
                "out_last_t": 150, "preview": "Hoy nos vemos como siempre?", "kinds": {"chat": 4},
                "messages": [m("a", 100, "Buen día!"), m("b", 200, "Llego a las 16"), m("c", 300, cached=False),
                             m("s", 310, kind="notification_template"), m("d", 400, cached=False)]}
        sources.run = fake_run({"new": [chat]})
        items, _, _ = sources.whatsapp({"channels": ["whatsapp"]}, NOW)
        self.assertEqual(items[0]["text"], "[ещё 1 без текста] · Llego a las 16 · Hoy nos vemos como siempre?")
        self.assertNotIn("Buen día", items[0]["text"])            # на это он уже ответил
        self.assertTrue(items[0]["key"].endswith(":d"))           # ключ — последнее ждущее сообщение
        sources.run = fake_run({"new": [{**chat, "last": "2026-10-10T11:40-03:00", "messages": chat["messages"] + [
            m("s2", 500, kind="gp2")]}]})
        again, _, _ = sources.whatsapp({"channels": ["whatsapp"]}, NOW)
        self.assertEqual(again[0]["key"], items[0]["key"])        # служебное событие второй карточкой не станет
        sources.run = fake_run({"new": [{**chat, "out_last_t": 450}]})
        self.assertEqual(sources.whatsapp({"channels": ["whatsapp"]}, NOW)[0], [])   # ответил после всех — не поднимаем

    def test_unread_media_without_text_still_shows(self):
        sources.run = fake_run({"new": [
            {"chat_id": "5491100000004@c.us", "name": "Электрик", "new": 3, "unread": 1,
             "last": "2026-10-10T09:12-03:00", "preview": ""}]})
        items, _, _ = sources.whatsapp({"channels": ["whatsapp"]}, NOW)
        self.assertEqual([i["from"] for i in items], ["Электрик"])
        self.assertIn("1", items[0]["text"])

    def test_one_number_unreadable_is_a_warning_all_unreadable_is_a_failure(self):
        sources.run = fake_run({"--channel a": [], "--channel b": OSError("no tab")})
        _, _, errors = sources.whatsapp({"channels": ["a", "b"]}, NOW)
        self.assertEqual(len(errors), 1)
        sources.run = fake_run({"--channel": OSError("Chrome off")})
        with self.assertRaises(OSError):
            sources.whatsapp({"channels": ["a", "b"]}, NOW)


class Telegram(unittest.TestCase):
    def setUp(self):
        self._run = sources.run

    def tearDown(self):
        sources.run = self._run

    def test_personal_chat_card_groups_quiet_and_reply_goes_through_send(self):
        sources.run = fake_run({"new": [
            {"chat_id": "3123499", "name": "Лена", "unread": 2, "group": False, "last": "2026-10-10T11:30-03:00",
             "preview": "Пришлёшь договор?", "out_last_t": 0,
             "messages": [{"id": "10", "text": "Привет", "type": "chat", "out": False, "t": 1},
                          {"id": "11", "text": "Пришлёшь договор?", "type": "chat", "out": False, "t": 2}]},
            {"chat_id": "-100500", "name": "Соседи", "unread": 3, "group": True, "last": "2026-10-10T10:00-03:00",
             "preview": "Кто идёт?", "out_last_t": 0,
             "messages": [{"id": "5", "text": "Кто идёт?", "type": "chat", "out": False, "t": 1, "from": "Ира"}]},
            {"chat_id": "77", "name": "Вася", "unread": 1, "group": False, "last": "2026-10-10T10:00-03:00",
             "preview": "спасибо", "out_last_t": 0,
             "messages": [{"id": "9", "text": "спасибо", "type": "chat", "out": False, "t": 1}]},
        ]})
        items, boxes, errors = sources.telegram({}, NOW)
        self.assertEqual([i["from"] for i in items], ["Лена"])   # группа без срочного и «спасибо» — нет
        self.assertEqual(items[0]["src"], "telegram")
        self.assertEqual(items[0]["text"], "Привет · Пришлёшь договор?")
        self.assertEqual(boxes, {"tg:3123499"})
        calls = []
        sources.run = lambda cmd, timeout=0: calls.append(cmd) or ""
        sources.reply(items[0]["ref"], "Да, вечером")
        self.assertEqual(calls[0][1:], ["tg", "--to", "3123499", "--text", "Да, вечером"])

    def test_send_refusals_are_human_text(self):
        # 12.10: «Not sent: send failed: TELEGRAM_API_ID / TELEGRAM_API_HASH not set» в интерфейсе — именами переменных
        self.assertNotIn("TELEGRAM_API", sources.human("send failed: TELEGRAM_API_ID / TELEGRAM_API_HASH not set"))
        self.assertIn("Telegram", sources.human("send failed: TELEGRAM_API_ID / TELEGRAM_API_HASH not set"))
        self.assertIn("08:00", sources.human("Blocked: WhatsApp/Telegram are not sent between 23:00 and 08:00 ART."))
        self.assertEqual(sources.human("send failed: что-то своё"), "что-то своё")
        sources.run = lambda cmd, timeout=0: (_ for _ in ()).throw(OSError("send failed: TELEGRAM_API_ID not set"))
        with self.assertRaises(OSError) as c:
            sources.reply({"tg": "1", "send": "send"}, "x")
        self.assertNotIn("TELEGRAM_API", str(c.exception))


class Email(unittest.TestCase):
    def setUp(self):
        self._run = sources.run

    def tearDown(self):
        sources.run = self._run

    def test_human_mail_in_automated_noise_out(self):
        sources.run = fake_run({"gmail search": {"threads": [
            {"id": "t1", "date": "2026-10-10 10:02", "from": "Hostex <postmaster@mail.hostex.io>",
             "subject": "New pending confirmation reservation - Terrazzo", "labels": ["UNREAD", "CATEGORY_UPDATES"], "messageCount": 1},
            {"id": "t2", "date": "2026-10-10 10:02", "from": "Evernote <no-reply@mail.evernote.com>",
             "subject": "Your Evernote subscription has been cancelled", "labels": ["UNREAD", "CATEGORY_UPDATES"], "messageCount": 1},
            {"id": "t3", "date": "2026-10-09 18:00", "from": "Marina <marina@example.com>",
             "subject": "Re: сроки по ремонту", "labels": ["UNREAD", "INBOX"], "messageCount": 3},
        ]}})
        items, boxes, errors = sources.email({"accounts": ["me@example.com"]}, NOW)
        self.assertEqual(sorted(i["from"] for i in items), ["Hostex", "Marina"])   # «ждёт подтверждения» — срочное
        self.assertEqual({i["tier"] for i in items if i["from"] == "Hostex"}, {"A"})
        self.assertTrue(all(i["link"].startswith("https://mail.google.com/") for i in items))
        self.assertEqual(len(boxes), 2)


class Flow(unittest.TestCase):
    def test_gone_from_the_list_is_answered_and_a_newer_message_supersedes(self):
        posts = []
        st, now = {}, NOW
        item = {"key": "k1", "box": "wa:whatsapp:1@c.us", "src": "whatsapp", "where": "W", "from": "A", "text": "?",
                "at": "2026-10-10T10:00:00Z", "link": "", "mention": False, "tier": "B"}
        main.tick(st, [item], {}, now, put=posts.append)
        self.assertEqual(posts[-1]["id"], "k1")
        newer = dict(item, key="k2", at="2026-10-10T12:00:00Z")
        main.tick(st, [newer], {}, now, put=posts.append)
        self.assertIn({"kind": "answered", "id": "k1"}, posts)   # прежняя карточка этой переписки устарела
        main.tick(st, [], {"wa:whatsapp:1@c.us": "2026-10-10T13:00:00Z"}, now, put=posts.append)
        self.assertIn({"kind": "answered", "id": "k2"}, posts)   # переписка прочитана/отвечена


if __name__ == "__main__":
    unittest.main()


class MediaSummary(unittest.TestCase):
    def test_kinds_replace_the_bare_counter(self):
        from sources import media_summary
        self.assertEqual(media_summary({"ptt": 4, "image": 1}, 5), "4 голосовых, 1 фото")
        self.assertIn("Непрочитанных: 6", media_summary(None, 6))

    def test_digest_is_the_unread_texts(self):
        from sources import unread_digest
        msgs = [{"type": "chat", "text": "старое"}, {"type": "e2e_notification", "text": ""},
                {"type": "chat", "text": "Привет,  когда придёте?"}, {"type": "ptt", "text": ""},
                {"type": "image", "text": "щиток"}]
        self.assertEqual(unread_digest(msgs, 3), "Привет, когда придёте? · [голосовое] · щиток")
        self.assertEqual(unread_digest([], 2), "")
