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


SERVICE_TYPES = {"e2e_notification", "notification_template", "gp2", "protocol", "ciphertext", "revoked"}


def unread_digest(messages, n, limit=600):
    """Резюме непрочитанного: тексты последних n входящих по порядку, медиа без подписи — словом («🎤 голосовое»,
    «фото»); длинное обрезается с конца. Нет ни текста, ни медиа — пусто (тогда счётчик по типам)."""
    msgs = [m for m in (messages or []) if m.get("type") not in SERVICE_TYPES][-n:] if n else []
    parts = []
    for m in msgs:
        txt = " ".join((m.get("text") or "").split())
        if txt:
            parts.append(txt)
        else:
            one = KIND_NAMES.get(m.get("type") or "", (m.get("type") or "", ""))[0]
            if one and one != "текст":
                parts.append(f"[{one}]")
    if not any(not p.startswith("[") for p in parts) and not parts:
        return ""
    out = " · ".join(parts)
    return out if len(out) <= limit else "…" + out[-(limit - 1):]


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
            digest = unread_digest(r.get("messages"), n)   # о чём писали — тексты непрочитанных, не счётчик
            if digest:
                text = digest
            elif not text:   # последнее — медиа/голосовое: текста нет, но непрочитанное ждёт
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
                          "mention": False,
                          "ref": {"wa": ch, "to": cid, "cmd": cmd, "send": expand(cfg.get("send") or "~/.claude/bin/send"),
                                  **({"react": expand(cfg["react"]), "msg": (r.get("messages") or [{}])[-1].get("id")}
                                     if cfg.get("react") and (r.get("messages") or [{}])[-1].get("id") else {})}})
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
                          "link": f"https://mail.google.com/mail/u/{acct}/#inbox/{th['id']}", "mention": False,
                          "ref": {"mail": acct, "thread": th["id"], "subject": subject, "cmd": cmd}})
    if errors and not ok:
        raise OSError("; ".join(errors))
    return items, boxes, errors


# --- Ответ владельца из вкладки в WhatsApp и почту: теми же командами машины, что читают -----------------------------
def reply(ref, text):
    """WhatsApp — сообщением в тот же чат (команда send из sources.json: её ночные и прочие запреты действуют — отказ
    вернётся ошибкой во вкладку); почта — ответом всем в ту же цепочку."""
    if ref.get("wa"):
        return run([ref["send"], "wa", "--to", ref["to"], "--channel", ref["wa"], "--text", text], timeout=180)
    if ref.get("mail"):
        subject = ref.get("subject") or ""
        if not re.match(r"(?i)re:", subject):
            subject = "Re: " + subject
        return run([ref["cmd"], "gmail", "send", "--thread-id", ref["thread"], "--reply-all", "--subject", subject,
                    "--body", text, "-a", ref["mail"]], timeout=120)
    raise OSError("не знаю, куда отвечать на это сообщение")


def react(ref, emoji):
    """Реакция в WhatsApp — командой из sources.json (`"react": "<путь>"`): <команда> react <чат> --id <сообщение>
    --emoji <эмодзи> --channel <номер>."""
    if ref.get("wa") and ref.get("react") and ref.get("msg"):
        return run([ref["react"], "react", ref["to"], "--id", ref["msg"], "--emoji", emoji, "--channel", ref["wa"]],
                   timeout=120)
    raise OSError("на это сообщение реакцию поставить нельзя")


def history(ref, top=20):
    """Переписка для «всей переписки» во вкладке. WhatsApp — только сохранённая копия треда (`--cached`): живое чтение
    открыло бы чат и поставило синие галочки. Почта — письма цепочки: от кого, когда, начало текста."""
    if ref.get("wa"):
        who = ref["to"] if ref["to"].endswith("@g.us") else re.sub(r"\D", "", ref["to"].split("@")[0])
        try:
            data = json.loads(run([ref.get("cmd") or expand("~/.claude/bin/wa"), "thread", who, "--cached", "--json",
                                   "--limit", str(top), "--channel", ref["wa"]]))
        except OSError:
            return []   # копии нет — истории нет; чат ради неё не открываем
        out = []
        for m in data.get("messages") or []:
            try:
                at = iso_utc(datetime.strptime(m.get("when") or "", "%I:%M %p, %m/%d/%Y"))
            except ValueError:
                at = ""
            text = (m.get("body") or "").strip() or ("[медиа]" if m.get("media") else "")
            if text:
                out.append({"at": at, "from": m.get("author") or "", "me": bool(m.get("out")), "text": text})
        return out
    if ref.get("mail"):
        data = json.loads(run([ref["cmd"], "gmail", "thread", "get", ref["thread"], "-a", ref["mail"], "-j"]))
        out = []
        for m in (data.get("thread") or {}).get("messages") or []:
            heads = {h.get("name", "").lower(): h.get("value", "") for h in (m.get("payload") or {}).get("headers") or []}
            try:
                at = iso_utc(datetime.fromtimestamp(int(m.get("internalDate") or 0) / 1000, timezone.utc))
            except (ValueError, OSError):
                at = ""
            name = re.sub(r"\s*<[^>]*>\s*$", "", heads.get("from", "")).strip().strip('"')
            out.append({"at": at, "from": name, "me": "SENT" in (m.get("labelIds") or []),
                        "text": (m.get("snippet") or "").strip() or heads.get("subject", "")})
        return out[-top:]
    return []
