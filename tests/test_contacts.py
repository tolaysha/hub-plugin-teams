"""Кому написать (13.10): поиск собеседника по источникам и отправка новому по ключу из поиска."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import contacts  # noqa: E402


class Search(unittest.TestCase):
    def setUp(self):
        self._run = contacts.run
        self.calls = []

        def fake(cmd, timeout=0):
            self.calls.append(cmd)
            if "contacts" in cmd:
                return json.dumps([{"id": "77", "name": "Лена Иванова", "username": "lena"}])
            if "chats" in cmd:
                return json.dumps([{"chat_id": "5491@c.us", "name": "Лена"}, {"chat_id": "123@g.us", "name": "Лена и дети"}])
            return json.dumps({"threads": [{"from": "Лена <lena@example.com>"}, {"from": "Bot <no@x.io>"}]})
        contacts.run = fake

    def tearDown(self):
        contacts.run = self._run

    def test_each_source_gives_a_key_the_send_accepts(self):
        cfg = {"telegram": {}, "whatsapp": {"channels": ["whatsapp"], "labels": {"whatsapp": "Mint"}},
               "email": {"accounts": ["me@example.com"]}}
        items, errors = contacts.search("Лена", cfg)
        self.assertEqual(errors, [])
        self.assertEqual([(i["src"], i["to"]) for i in items],
                         [("telegram", "tg:77"), ("whatsapp", "wa:whatsapp:5491@c.us"),
                          ("whatsapp", "wa:whatsapp:123@g.us"), ("email", "mail:me@example.com:lena@example.com")])
        self.assertEqual(items[2]["hint"], "Mint · группа")

    def test_short_query_and_unconfigured_sources_search_nothing(self):
        self.assertEqual(contacts.search("a", {"telegram": {}}), ([], []))
        self.assertEqual(contacts.search("Лена", {}), ([], []))
        self.assertEqual(self.calls, [])

    def test_one_source_failing_does_not_break_the_rest(self):
        real = contacts.run

        def boom(cmd, timeout=0):
            if "contacts" in cmd:
                raise OSError("нет сессии")
            return real(cmd, timeout)
        contacts.run = boom
        items, errors = contacts.search("Лена", {"telegram": {}, "whatsapp": {}})
        self.assertEqual(len(errors), 1)
        self.assertEqual({i["src"] for i in items}, {"whatsapp"})

    def test_send_goes_by_key_with_files(self):
        cfg = {"email": {"cmd": "gogx"}, "telegram": {"send": "send"}, "whatsapp": {"send": "send"}}
        contacts.send("tg:77", "привет", cfg, files=["/a/1.png"])
        contacts.send("wa:whatsapp:5491@c.us", "привет", cfg)
        contacts.send("mail:me@example.com:lena@example.com", "текст", cfg, subject="Тема", files=["/a/2.pdf"])
        self.assertEqual(self.calls[0], ["send", "tg", "--to", "77", "--text", "привет", "--file", "/a/1.png"])
        self.assertEqual(self.calls[1], ["send", "wa", "--to", "5491@c.us", "--channel", "whatsapp", "--text", "привет"])
        self.assertEqual(self.calls[2], ["gogx", "gmail", "send", "--to", "lena@example.com", "--subject", "Тема",
                                         "--body", "текст", "-a", "me@example.com", "--attach", "/a/2.pdf"])
        with self.assertRaises(OSError):
            contacts.send("mail:me@example.com:a@b.c", "x", cfg)   # у письма нужна тема
        with self.assertRaises(OSError):
            contacts.send("teams:u1", "x", cfg, files=["/a/1.png"])   # файл в Teams вложением нельзя


if __name__ == "__main__":
    unittest.main()
