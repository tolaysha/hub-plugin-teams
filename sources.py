"""Другие каналы входящих рядом с Teams: WhatsApp, почта (владелец 10.10: «чтобы там были ещё WhatsApp и email, но
только то, что требует моего внимания; каналов будет больше»).

Канал — функция `read(cfg, now) -> (items, open_boxes)`, зарегистрированная `@source("имя")`. Включён, если в
`<состояние>/ext-teams/sources.json` есть ключ с его именем (`{"whatsapp": {...}, "email": {...}}`) — личные пути и
аккаунты лежат там, не в коде. items — те же dict, что у collect.py ({key, box, src, where, from, text, at, link,
mention}) плюс tier "A"|"B"; open_boxes — переписки, которые ждут владельца СЕЙЧАС: что было открыто и пропало из
списка — прочитано или отвечено, вкладка пометит «отвечено». Новый канал — ещё одна функция с `@source`, тип сообщения
src для вкладки — в SRC_LABELS страницы (web/main.js).

Что «требует внимания» — по правилам триажа Noe, в сокращении (`tier`): закрывающее «ок/спасибо» и рутинные
уведомления — C и во вкладку не попадают; срочное, штраф, блокировка, просрочка — A; живая переписка — B."""
import json
import os
import re
import subprocess
from datetime import datetime, timezone

SOURCES = {}
TIMEOUT = 90


def source(name, every=120):
    def reg(fn):
        SOURCES[name] = {"fn": fn, "every": every}
        return fn
    return reg


# --- что требует внимания (правила Noe: server.py _compute_tier, в сокращении) ---------------------------------------
IMMEDIATE = re.compile(
    r"\b(?:urgent(?:e)?|urgente|asap|immediately|inmediato|inmediatamente|deadline|vence (?:hoy|ma[nñ]ana)|"
    r"antes de (?:hoy|ma[nñ]ana)|срочно|сегодня до|дедлайн)\b|"
    r"payment (?:has )?(?:failed|declined|rejected)|pago (?:fallid|rechazad|declinad)|card declined|past due|overdue|"
    r"en mora|(?:service|account) (?:has been |was |is )?(?:blocked|suspended|disabled)|"
    r"(?:servicio|cuenta) (?:fue |est[aá] |ha sido )?(?:bloquead|suspendid|inhabilitad)|"
    r"intimaci[oó]n|citaci[oó]n|embargo|multa|final notice|[uú]ltimo aviso|"
    r"action required|acci[oó]n requerida|pending confirmation|requires? your (?:action|attention|response)",
    re.IGNORECASE)
ROUTINE = re.compile(
    r"\b(?:newsletter|digest|unsubscribe|darse de baja|webinar|product announcement|marketing update|"
    r"order status|shipping update|delivery update|refund|receipt|recibo|comprobante)\b|"
    r"(?:payment|pago|transferencia) (?:was |is |has been |fue |es |ya )?(?:received|successful|completed|approved|"
    r"recibid[oa]|exitos[oa]|completad[oa]|aprobad[oa])|(?:subscription|suscripci[oó]n) (?:has been |was )?"
    r"(?:cancel|renew|cancelad|renovad)|auto[- ]?renewal|renovaci[oó]n autom[aá]tica|"
    r"terms of service|privacy policy|t[eé]rminos de servicio",
    re.IGNORECASE)
ACK_WORDS = {"ok", "oka", "okey", "okay", "dale", "listo", "gracias", "gracia", "gracias!", "perfecto", "genial",
             "buenisimo", "buenísimo", "bien", "vale", "si", "sí", "sii", "claro", "thanks", "thx", "thank", "you",
             "good", "great", "спасибо", "ок", "окей", "хорошо", "ладно", "понял", "отлично", "супер", "да", "👍", "🙏"}
AUTOMATED = re.compile(
    r"no[-_.]?reply|do[-_.]?not[-_.]?reply|donotreply|mailer-daemon|postmaster|notifications?@|notify@|"
    r"newsletter|updates?@|info@|news@|marketing@|billing@|invoice|support@|team@|hello@|bounce", re.IGNORECASE)


def closing_ack(text):
    t = (text or "").strip().lower()
    if not t or len(t) > 80 or "?" in t or "http" in t:
        return False
    words = re.findall(r"[\w'🙏👍]+", t)
    if not words:
        return bool(re.search(r"[👍🙏❤️💗💖🫶🤝👌✅]", t))
    return all(w in ACK_WORDS for w in words)


def tier(text, *, automated=False, updates=False):
    """A — срочное; B — живая переписка, подождёт; C — не требует внимания (во вкладку не идёт)."""
    if closing_ack(text):
        return "C"
    if IMMEDIATE.search(text or ""):
        return "A"
    if automated or updates or ROUTINE.search(text or ""):
        return "C"
    return "B"


def iso_utc(dt):
    if dt.tzinfo is None:
        dt = dt.astimezone()   # без пояса — местное время машины
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(cmd, timeout=TIMEOUT):
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    if out.returncode:
        lines = [x for x in (out.stderr or out.stdout).splitlines() if x.strip()]
        raise OSError((lines[-1] if lines else f"код {out.returncode}")[:200])
    return out.stdout


def expand(p):
    return os.path.expanduser(p)


KIND_NAMES = {"ptt": ("голосовое", "голосовых"), "audio": ("аудио", "аудио"), "image": ("фото", "фото"),
              "video": ("видео", "видео"), "document": ("файл", "файлов"), "sticker": ("стикер", "стикеров"),
              "chat": ("текст", "текстовых"), "location": ("геопозиция", "геопозиций")}


def media_summary(kinds, n):
    """Что пришло, когда у последнего нет текста: «4 голосовых, 2 фото» вместо счётчика (11.10, Иван: «мне надо не
    число, а про что он писал»). Без типов от `wa` — число и общие слова. Содержимое без открытия чата недоступно."""
    parts = []
    for k, c in sorted((kinds or {}).items(), key=lambda kv: -kv[1]):
        one, many = KIND_NAMES.get(k, (k, k))
        parts.append(f"{c} {one if c == 1 else many}")
    return ", ".join(parts) if parts else f"Непрочитанных: {n} (фото, голосовое или файл)"


# --- WhatsApp: `wa new` — читает только список чатов открытой вкладки, ничего не открывает и не отмечает прочитанным ---
@source("whatsapp", every=120)
def whatsapp(cfg, now):
    """Чаты с непрочитанным входящим за сутки. Своя вкладка у каждого номера (channels в sources.json); номер без
    вкладки/входа — ошибка в плашке, остальные читаются. Группы — только срочное: иначе это шум."""
    cmd = expand(cfg.get("cmd") or "~/.claude/bin/wa")
    labels = cfg.get("labels") or {}
    items, boxes, errors, ok = [], set(), [], 0
    for ch in cfg.get("channels") or ["whatsapp"]:
        try:
            rows = json.loads(run([cmd, "new", "--channel", ch, "--hours", "24", "--json"]) or "[]")
        except (OSError, ValueError, subprocess.TimeoutExpired) as e:
            msg = re.sub(r"^(?:WhatsApp(?: Web)?:\s*)+", "", str(e))
            if "no open WhatsApp Web tab" in msg and "logged in as" in msg:
                msg = "в Chrome нет вкладки WhatsApp Web, залогиненной на этот номер"
            elif "no open WhatsApp Web tab" in msg:
                msg += " — открыта ли вкладка WhatsApp Web и включено ли View → Developer → Allow JavaScript from Apple Events"
            errors.append(f"{labels.get(ch, ch)}: {msg}")
            continue
        ok += 1
        for r in rows:
            cid, text = r.get("chat_id") or "", (r.get("preview") or "").strip()
            n = r.get("unread") or 0
            if not cid or not n:
                continue   # всё прочитано или отвечено — внимания не требует
            if not text:   # последнее — медиа/голосовое: текста нет, но непрочитанное ждёт
                text = media_summary(r.get("kinds"), n)
            group = cid.endswith("@g.us")
            t = tier(text)
            if t == "C" or (group and t != "A"):
                continue
            last = datetime.fromisoformat(r["last"]) if r.get("last") else now
            box = f"wa:{ch}:{cid}"
            digits = re.sub(r"\D", "", cid.split("@")[0])
            boxes.add(box)
            items.append({"key": f"{box}:{r.get('last')}", "box": box, "src": "whatsapp", "tier": t,
                          "where": labels.get(ch, "WhatsApp") + (" · группа" if group else ""),
                          "from": r.get("name") or digits, "text": text[:1200], "at": iso_utc(last),
                          "link": f"https://wa.me/{digits}" if digits and not group and len(digits) <= 15 else "",
                          "mention": False})
    if errors and not ok:
        raise OSError("; ".join(errors))
    return items, boxes, errors


# --- Почта: Gmail через gogx — непрочитанные входящие вне рассылок; тема и отправитель ----------------------------
@source("email", every=120)
def email(cfg, now):
    cmd = expand(cfg.get("cmd") or "~/.claude/bin/gogx")
    query = cfg.get("query") or ("is:unread in:inbox newer_than:7d -category:promotions -category:social "
                                 "-category:forums")
    items, boxes, errors, ok = [], set(), [], 0
    for acct in cfg.get("accounts") or []:
        try:
            data = json.loads(run([cmd, "gmail", "search", query, "--max", "40", "-a", acct, "-j"]))
        except (OSError, ValueError, subprocess.TimeoutExpired) as e:
            errors.append(f"{acct}: {e}")
            continue
        ok += 1
        for th in data.get("threads") or []:
            labels = th.get("labels") or []
            if "SENT" in labels and "UNREAD" not in labels:
                continue
            sender, subject = th.get("from") or "", (th.get("subject") or "").strip()
            addr = re.search(r"<([^>]+)>", sender)
            t = tier(subject, automated=bool(AUTOMATED.search(addr.group(1) if addr else sender)),
                     updates="CATEGORY_UPDATES" in labels)
            if t == "C" or not subject and not sender:
                continue
            try:
                at = iso_utc(datetime.strptime(th["date"], "%Y-%m-%d %H:%M"))
            except (KeyError, ValueError):
                at = iso_utc(now)
            box = f"mail:{acct}:{th['id']}"
            boxes.add(box)
            name = re.sub(r"\s*<[^>]*>\s*$", "", sender).strip().strip('"') or (addr.group(1) if addr else "")
            items.append({"key": f"{box}:{th.get('date')}:{th.get('messageCount')}", "box": box, "src": "email",
                          "tier": t, "where": "Почта" + (f" · {acct}" if len(cfg.get("accounts") or []) > 1 else ""),
                          "from": name or "—", "text": subject or "(без темы)", "at": at,
                          "link": f"https://mail.google.com/mail/u/{acct}/#inbox/{th['id']}", "mention": False})
    if errors and not ok:
        raise OSError("; ".join(errors))
    return items, boxes, errors
