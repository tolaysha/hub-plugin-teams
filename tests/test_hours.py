"""Рабочие часы и перенос отказа гейта: общие примеры с клиентами (hours_cases.json — копия hub-ios
docs/send-model/cases.json) и ветки модели docs/send-model/lean: ночь, выходные, разные собеседники, перезапуск."""
import json
import os
import sys
import unittest
from datetime import datetime, timezone

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("HUB_STATE_DIR", "/tmp/teams-ext-test")
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.environ.get("HUB_CORE") or os.path.expanduser("~/projects/agents-hub-core"))

import hours  # noqa: E402
import main  # noqa: E402
import sources  # noqa: E402


class Cases(unittest.TestCase):
    def test_shared_examples(self):
        with open(os.path.join(HERE, "hours_cases.json"), encoding="utf-8") as f:
            data = json.load(f)
        for c in data["cases"]:
            r = hours.rule(data["rules"][c["rule"]])
            now = datetime.fromisoformat(c["now"])
            got = (hours.defer_to(r, now, c["why"]) if c["fn"] == "defer_to" else getattr(hours, c["fn"])(r, now))
            self.assertEqual(got.strftime("%Y-%m-%dT%H:%M"), c["want"], c)

    def test_rule_rejects_empty_window_and_flips_weekends_for_exceptions(self):
        self.assertIsNone(hours.clean({"from": "20:00", "to": "08:00"}))
        self.assertIsNone(hours.clean({"from": "8", "to": "25:00"}))
        self.assertEqual(hours.clean({"from": "9:30", "to": "24:00", "weekends": True}),
                         {"from": "09:30", "to": "24:00", "weekends": True})
        cfg = {"from": "08:00", "to": "20:00", "weekends": False, "except": {"wa:1": "Пабло"}}
        self.assertEqual(hours.rule(cfg, "wa:1"), (480, 1200, True))
        self.assertEqual(hours.rule(cfg, "wa:2"), (480, 1200, False))
        self.assertEqual(hours.rule(None), (480, 1200, False))

    def test_gate_refusals_are_recognised_and_other_errors_are_not(self):
        self.assertEqual(sources.held("Blocked: WhatsApp/Telegram are not sent between 23:00 and 08:00 ART. Send after 08:00"), "night")
        self.assertEqual(sources.held("Sunday — non-personal contacts wait until Mon 08:00"), "weekend")
        self.assertIsNone(sources.held("WhatsApp Web: page crashed"))


def utc(s):
    """Местное время машины «2026-10-13T05:31» → момент UTC, как его видит плагин."""
    return datetime.fromisoformat(s).astimezone(timezone.utc)


def here(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%dT%H:%M")


class Gate(unittest.TestCase):
    """Команда send с гейтом: gate(now) → None (ушло) | "night" | "weekend" | Exception."""

    def setUp(self):
        self.sent, self.out, self.answer = [], [], None
        self.real = (sources.reply, main.save)

        def reply(ref, text, files=None, reply_to=None, quote=None):
            if isinstance(self.answer, Exception):
                raise self.answer
            if self.answer:
                raise sources.Held(self.answer, "не сейчас")
            self.sent.append(text)
        sources.reply = reply
        main.save = lambda st: None
        self.st = {"refs": {"k1": {"wa": "whatsapp", "to": "1@c.us"}, "k2": {"wa": "whatsapp", "to": "2@c.us"}},
                   "who": {"k1": {"contact": "wa:1", "from": "Пабло"}, "k2": {"contact": "wa:2", "from": "Лена"}}}

    def tearDown(self):
        sources.reply, main.save = self.real

    class R:
        mcp = None

        def close(self):
            pass

    def go(self, queue, now, answer=None):
        self.answer = answer
        main.send_replies(self.st, self.R(), queue, self.out.append, now=utc(now))

    def kinds(self):
        return [p["kind"] for p in self.out]

    def test_send_now_at_night_is_scheduled_for_the_morning_not_failed(self):
        self.go([{"id": "k1", "rid": "r1", "text": "Claro"}], "2026-10-13T05:31", "night")
        self.assertEqual(self.kinds(), ["scheduled"])
        self.assertEqual((here(self.out[0]["at"]), self.out[0]["held"]), ("2026-10-13T08:00", "night"))
        self.go([], "2026-10-13T07:59", "night")              # до времени попытки нет
        self.assertEqual(self.kinds(), ["scheduled"])
        self.go([], "2026-10-13T08:00")
        self.assertEqual((self.sent, self.kinds()), (["Claro"], ["scheduled", "sent", "answered"]))

    def test_later_really_waits_and_survives_restart(self):
        at = main.iso(utc("2026-10-13T08:00"))
        q = [{"id": "k1", "rid": "r1", "text": "Утром", "at": at}]
        self.go(q, "2026-10-13T05:31", "night")
        self.assertEqual((self.sent, self.kinds()), ([], ["scheduled"]))
        self.st = json.loads(json.dumps(self.st))             # перезапуск: состояние с диска, журнал читается заново
        self.go(q, "2026-10-13T07:00", "night")
        self.assertEqual((self.sent, self.kinds()), ([], ["scheduled"]))
        self.go(q, "2026-10-13T08:00")
        self.go(q, "2026-10-13T08:01")
        self.assertEqual((self.sent, self.kinds()), (["Утром"], ["scheduled", "sent", "answered"]))

    def test_past_time_goes_now_and_night_moves_it(self):
        q = [{"id": "k1", "rid": "r1", "text": "x", "at": main.iso(utc("2026-10-13T05:31"))}]
        self.go(q, "2026-10-13T05:31", "night")               # случай 13.10: время = сейчас, ночь
        self.assertEqual((self.kinds(), here(self.out[0]["at"])), (["scheduled"], "2026-10-13T08:00"))

    def test_weekend_differs_by_contact(self):
        self.st["hours"] = {"from": "08:00", "to": "20:00", "weekends": False, "except": {"wa:2": "Лена"}}
        self.go([{"id": "k1", "rid": "r1", "text": "a"}, {"id": "k2", "rid": "r2", "text": "b"}], "2026-10-17T23:30", "night")
        self.assertEqual([here(p["at"]) for p in self.out], ["2026-10-19T08:00", "2026-10-18T08:00"])
        self.go([], "2026-10-18T08:00", "weekend")            # воскресенье: гейт держит и её — на понедельник
        self.assertEqual((self.kinds()[-1], here(self.out[-1]["at"]), self.out[-1]["held"]),
                         ("scheduled", "2026-10-19T08:00", "weekend"))
        self.st = json.loads(json.dumps(self.st))
        self.go([], "2026-10-19T08:00")
        self.assertEqual((sorted(self.sent), self.st["later"]), (["a", "b"], {}))
        self.assertNotIn("send_failed", self.kinds())

    def test_real_errors_stay_errors(self):
        self.go([{"id": "k1", "rid": "r1", "text": "a"}], "2026-10-13T12:00", OSError("Не дождались ответа от сервиса — повтори"))
        self.go([{"id": "нет", "rid": "r2", "text": "a"}], "2026-10-13T12:00")
        self.assertEqual(self.kinds(), ["send_failed", "send_failed"])

    def test_gate_that_never_opens_is_told_after_cap(self):
        self.go([{"id": "k1", "rid": "r1", "text": "a"}], "2026-10-13T05:31", "night")
        for _ in range(hours.CAP):
            at = self.st.get("later", {}).get("r1", {}).get("at")
            if at:
                self.go([], here(at), "night")
        self.assertEqual((self.kinds().count("scheduled"), self.kinds()[-1], self.st["later"]), (hours.CAP - 1, "send_failed", {}))

    def test_cancel_of_held_never_goes(self):
        q = [{"id": "k1", "rid": "r1", "text": "a"}]
        self.go(q, "2026-10-13T05:31", "night")
        self.go(q + [{"cancel": "r1"}], "2026-10-13T06:00", "night")
        self.go(q + [{"cancel": "r1"}], "2026-10-13T08:00")
        self.assertEqual((self.sent, self.kinds()), ([], ["scheduled", "canceled"]))

    def test_owner_sets_hours_and_exceptions(self):
        c = main.Choice("/nonexistent")
        def owner(body):
            c.line(json.dumps({"type": "ext.post", "seq": 1, "data": {"plugin": main.NAME, "owner": True, "channel": "web",
                                                                         "text": json.dumps(body)}}).encode() + b"\n")
        owner({"kind": "hours", "from": "09:00", "to": "18:00", "weekends": False})
        owner({"kind": "hours", "from": "19:00", "to": "18:00"})      # пустое окно — остаётся прежнее
        owner({"kind": "hours_for", "id": "k2", "weekends": True})
        main.settings(self.st, c, self.out.append)
        main.send_replies(self.st, self.R(), c.take_sends(), self.out.append)
        h = self.out[-1]["hours"]
        self.assertEqual((h["from"], h["to"], h["weekends"], h["except"]), ("09:00", "18:00", False, [{"contact": "wa:2", "name": "Лена"}]))
        main.hours_for(self.st, "k2", None, self.out.append)          # «как у всех»
        self.assertEqual(self.out[-1]["hours"]["except"], [])


if __name__ == "__main__":
    unittest.main()
