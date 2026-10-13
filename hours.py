"""Рабочие часы отправки: когда ответ владельца может уйти и какое разрешённое время ближайшее.

Правило — окно дня [from, to) и «можно ли в выходные»; у собеседника из `except` выходные наоборот. Считаем по часам
машины хаба. Формальная модель и доказательства («ближайшее», «строго позже», «перенос сдвигает вперёд») —
hub-ios docs/send-model/lean/SendModel/Hours.lean; там же зеркало для клиентов (Sources/InboxHours.swift). Общие
примеры для обеих реализаций — hub-ios docs/send-model/cases.json.
"""
import os
import re
from datetime import datetime, timedelta, timezone

DEFAULT = {"from": "08:00", "to": "20:00", "weekends": False}
GATE_OPENS = 8 * 60   # команда send не шлёт WhatsApp и Telegram до 08:00
CAP = 8               # отказов гейта подряд, после которых говорим владельцу: правила не дают отправить вовсе


def minutes(hhmm):
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", str(hhmm or "").strip())
    if not m or int(m.group(2)) > 59 or int(m.group(1)) * 60 + int(m.group(2)) > 1440:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))


def clean(body):
    """Настройки владельца → правило; None, если окно пустое или не разобралось (такое не принимаем)."""
    a, b = minutes((body or {}).get("from")), minutes((body or {}).get("to"))
    if a is None or b is None or not a < b:
        return None
    return {"from": f"{a // 60:02d}:{a % 60:02d}", "to": f"{b // 60:02d}:{b % 60:02d}",
            "weekends": (body or {}).get("weekends") is True}


def rule(cfg, contact=None):
    """(start, stop, weekends) для собеседника: общее правило, у исключений выходные наоборот."""
    base = clean(cfg) or DEFAULT
    weekends = base["weekends"] != (contact is not None and contact in ((cfg or {}).get("except") or {}))
    return minutes(base["from"]), minutes(base["to"]), weekends


def tz_name():
    """Пояс машины именем IANA (клиент считает пункт меню в поясе хаба); не узнали — пусто, клиент возьмёт utc."""
    name = os.environ.get("TZ") or ""
    if not name:
        try:
            name = os.path.realpath("/etc/localtime").split("/zoneinfo/", 1)[1]
        except (OSError, IndexError):
            name = ""
    return name if re.fullmatch(r"[A-Za-z_]+(/[A-Za-z_+\-0-9]+)+", name) else ""


def local(now=None):
    return (now or datetime.now(timezone.utc)).astimezone()


def _day_ok(weekends, d):
    return weekends or d.weekday() < 5


def _next_day(weekends, d):
    while not _day_ok(weekends, d):
        d += timedelta(days=1)
    return d


def _at(d, minute):
    return d.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(minutes=minute)


def allowed(r, t):
    start, stop, weekends = r
    m = t.hour * 60 + t.minute
    return _day_ok(weekends, t) and start <= m < stop


def next_start(r, t):
    """Ближайшее начало рабочих часов строго после t."""
    start, _, weekends = r
    if _day_ok(weekends, t) and t.hour * 60 + t.minute < start:
        return _at(t, start)
    return _at(_next_day(weekends, t + timedelta(days=1)), start)


def next_allowed(r, t):
    return t if allowed(r, t) else next_start(r, t)


def after_gate(t, why):
    """Когда гейт откроется: после ночи — ближайшие 08:00, после выходных — 08:00 ближайшего буднего дня."""
    if why == "weekend":
        return _at(_next_day(False, t + timedelta(days=1)), GATE_OPENS)
    return _at(t if t.hour * 60 + t.minute < GATE_OPENS else t + timedelta(days=1), GATE_OPENS)


def defer_to(r, t, why):
    """Куда перенести отказанное гейтом: первое время после его открытия, разрешённое и правилом собеседника."""
    return next_allowed(r, after_gate(t, why))
