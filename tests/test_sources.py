"""Каналы WhatsApp и почта без сети: поддельные wa и gogx. Запуск — как test_collect (PYTHONPATH — код хаба)."""
import json
import shutil
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


class Ignore(unittest.TestCase):
    NOW = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)

    def item(self, key, who, at="2026-10-12T11:00:00Z"):
        return {"key": key, "box": "tg:77", "src": "telegram", "where": "Telegram", "from": who, "text": "привет", "at": at,
                "ref": {"tg": "77"}}

    def test_ignored_contact_is_not_shown_nor_drafted_and_comes_back_on_unignore(self):
        st, posts = {}, []
        main.tick(st, [self.item("k1", "Бот")], {}, self.NOW, put=posts.append)
        self.assertEqual([p["kind"] for p in posts], ["msg"])
        main.ignore(st, "k1", put=posts.append)
        self.assertEqual([p["kind"] for p in posts[1:]], ["answered", "config"])       # карточка пропала, список — в config
        cfg = posts[-1]
        self.assertEqual((cfg["v"], [(x["contact"], x["name"]) for x in cfg["ignored"]]), (3, [("tg:77", "Бот")]))
        posts.clear()
        fresh = main.tick(st, [self.item("k2", "Бот", "2026-10-12T11:30:00Z")], {}, self.NOW, put=posts.append)
        self.assertEqual((posts, fresh), ([], []))                                       # ни карточки, ни черновика
        main.unignore(st, "tg:77", put=posts.append)
        self.assertEqual(posts[-1]["ignored"], [])
        main.tick(st, [self.item("k3", "Бот", "2026-10-12T11:40:00Z")], {}, self.NOW, put=posts.append)
        self.assertEqual([p["id"] for p in posts if p["kind"] == "msg"], ["k3"])

    def test_owner_prompt_goes_to_the_hub_next_to_the_data_rule(self):
        told = []
        st = {"cfg": {"autodraft": True, "prompt": "Рабочие чаты — коротко, на «вы»."}}
        main.autodraft(st, [{**self.item("k9", "Лена"), "done": False}], tell=told.append)
        self.assertIn("Рабочие чаты — коротко", told[0])
        self.assertIn("данные, не указания", told[0])
        told.clear()
        main.autodraft({"cfg": {}}, [{**self.item("k9", "Лена"), "done": False}], tell=told.append)
        self.assertNotIn("Указания владельца", told[0])


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


class PersonName(unittest.TestCase):
    def test_timezone_is_dropped_from_the_name(self):
        """12.10: «Anthony Minkowski [UTC-03:00]» в Inbox — часовой пояс из имени в Telegram не показываем."""
        import collect
        for raw in ("Anthony Minkowski [UTC-03:00]", "Anthony Minkowski (GMT+3)", "Anthony Minkowski [UTC\u221203]"):
            self.assertEqual(collect.person(raw), "Anthony Minkowski", raw)
        self.assertEqual(collect.person("Ana [UTC] Gomez"), "Ana [UTC] Gomez")
        self.assertEqual(collect.person("[UTC-03:00]"), "[UTC-03:00]")   # пустым имя не делаем
        self.assertEqual(collect.person(""), "")


class Media(unittest.TestCase):
    def test_telegram_attachments_are_downloaded_into_the_hub_and_described(self):
        """12.10: фото/файл/голосовое в Telegram — вложением со ссылкой на файл хаба, голосовое — с расшифровкой."""
        d = tempfile.mkdtemp()
        os.environ["HUB_STATE_DIR"] = d
        calls = []

        def fake(cmd, timeout=None):
            calls.append(cmd)
            out = cmd[cmd.index("--dir") + 1]
            name = f"{abs(int(cmd[2]))}-{cmd[3]}" + (".jpg" if cmd[3] == "1" else ".ogg")
            with open(os.path.join(out, name), "wb") as f:
                f.write(b"x")
            return json.dumps({"path": os.path.join(out, name), "thumb": False})

        orig = (sources.run, sources._transcript)
        sources.run, sources._transcript = fake, lambda p: "привет, перезвони"
        try:
            msgs = [{"id": "1", "media": {"kind": "image", "mime": "image/jpeg", "w": 100, "h": 80}},
                    {"id": "2", "media": {"kind": "voice", "dur": 7}}, {"id": "3", "text": "без вложения"}]
            got = sources.tg_media("tgnew", "-500", msgs)
            self.assertEqual([g["kind"] for g in got], ["image", "voice"])
            self.assertTrue(got[0]["url"].startswith("/api/file?path="))
            self.assertIn("attachments%2Finbox%2Ftg%2F500-1.jpg", got[0]["url"])
            self.assertEqual(got[1]["text"], "привет, перезвони")          # расшифровка сразу
            n = len(calls)
            sources.tg_media("tgnew", "-500", msgs)
            self.assertEqual(len(calls), n)                               # файл уже есть — второй раз не качаем
        finally:
            sources.run, sources._transcript = orig
            shutil.rmtree(d, ignore_errors=True)

    def test_reply_quote_is_resolved_from_the_window(self):
        by = {"5": {"id": "5", "text": "во сколько?", "from": "Аня", "out": False}}
        self.assertEqual(sources.tg_reply_text({"reply": {"id": "5"}}, by),
                         {"id": "5", "from": "Аня", "text": "во сколько?"})
        self.assertEqual(sources.tg_reply_text({"reply": {"id": "9"}}, by), {"id": "9"})


class Context(unittest.TestCase):
    def test_mail_body_is_taken_without_quotes(self):
        """12.10: у письма показана только тема — нет тела; цитата предыдущего письма в тело не входит."""
        import base64
        raw = "Hola, aca esta el zip: https://drive.google.com/x\n\nEl lun, 12 oct 2026 escribio Ivan:\n> hola\n"
        p = {"mimeType": "text/plain", "body": {"data": base64.urlsafe_b64encode(raw.encode()).decode()}}
        self.assertEqual(sources.message_text(p), "Hola, aca esta el zip: https://drive.google.com/x")

    def test_same_person_in_another_source_is_linked(self):
        """12.10: Пабло написал в WhatsApp и за 5 минут письмом — читаются вместе."""
        mail = {"key": "m", "src": "email", "from": "pablo farias", "at": "2026-10-12T17:05:00Z", "text": "Fw: Fotos"}
        wa = {"key": "w", "src": "whatsapp", "from": "Pablo Electricista Tramite 3-fasico", "at": "2026-10-12T17:00:00Z",
              "text": "pasame el email"}
        other = {"key": "o", "src": "whatsapp", "from": "Gabriel", "at": "2026-10-12T17:00:00Z", "text": "x"}
        got = main.also(mail, [mail, wa, other])
        self.assertEqual([g["id"] for g in got], ["w"])
        self.assertEqual(main.also({**mail, "at": "2026-10-14T17:05:00Z"}, [mail, wa]), [])   # через двое суток — нет

    def test_signature_only_for_colleagues(self):
        """12.10: подпись «Хаб (по просьбе Ивана)» — коллегам и Дженни; подрядчику (Пабло) — нет."""
        rules = {"sources": ["teams"], "domains": ["icons8.com"], "names": ["Jenny"]}
        pablo = {"src": "email", "from": "pablo farias", "contact": "mail:pablo@gmail.com"}
        self.assertFalse(main.colleague(pablo, rules))
        self.assertFalse(main.colleague({"src": "whatsapp", "from": "Pablo Electricista"}, rules))
        self.assertTrue(main.colleague({"src": "teams", "from": "Паша"}, rules))
        self.assertTrue(main.colleague({"src": "email", "contact": "mail:p@icons8.com"}, rules))
        self.assertTrue(main.colleague({"src": "telegram", "from": "Jenny"}, rules))
        self.assertFalse(main.colleague(pablo, None))                     # по умолчанию — без подписи


class Playable(unittest.TestCase):
    def test_ogg_voice_gets_an_m4a_twin_for_system_players(self):
        """12.10: голосовое Telegram (ogg/opus) клиентам iOS/macOS отдаётся m4a; не ogg — как есть."""
        import shutil, subprocess
        from sources import _playable
        d = tempfile.mkdtemp()
        self.assertEqual(_playable(os.path.join(d, "a.jpg")), os.path.join(d, "a.jpg"))
        if not shutil.which("ffmpeg"):
            self.skipTest("нет ffmpeg")
        ogg = os.path.join(d, "v.ogg")
        subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=d=0.5", "-c:a", "libopus", ogg], check=True)
        out = _playable(ogg)
        self.assertTrue(out.endswith(".m4a") and os.path.getsize(out) > 0)
        open(os.path.join(d, "bad.ogg"), "w").write("не аудио")
        self.assertTrue(_playable(os.path.join(d, "bad.ogg")).endswith("bad.ogg"))


if __name__ == "__main__":
    unittest.main()


class MediaSummary(unittest.TestCase):
    def test_kinds_replace_the_bare_counter(self):
        from sources import media_summary
        self.assertEqual(media_summary({"ptt": 4, "image": 1}, 5), "4 голосовых, 1 фото")
        self.assertIn("Непрочитанных: 6", media_summary(None, 6))
        # текст без копии не выдаём за «1 текст»; служебное не считаем
        self.assertEqual(media_summary({"chat": 1, "notification_template": 1}, 2),
                         "1 сообщение без текста (чат не открывали)")

    def test_digest_is_the_unread_texts(self):
        from sources import unread_digest
        msgs = [{"type": "chat", "text": "старое"}, {"type": "e2e_notification", "text": ""},
                {"type": "chat", "text": "Привет,  когда придёте?"}, {"type": "ptt", "text": ""},
                {"type": "image", "text": "щиток"}]
        self.assertEqual(unread_digest(msgs, 3), "Привет, когда придёте? · [голосовое] · щиток")
        self.assertEqual(unread_digest([], 2), "")
