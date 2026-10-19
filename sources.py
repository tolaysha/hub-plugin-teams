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
import sys
import time
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
              "chat": ("текст", "текстовых"), "location": ("геопозиция", "геопозиций"),
              "call": ("звонок", "звонков")}


SERVICE_TYPES = {"e2e_notification", "notification_template", "gp2", "protocol", "ciphertext", "revoked"}


def waiting(r):
    """Сообщения чата, которые ждут владельца: непрочитанные входящие ПОСЛЕ его последнего ответа (то, на что он уже
    ответил, заново не поднимаем), без служебных. Времени нет (старая команда wa) — последние по счётчику."""
    n = r.get("unread") or 0
    msgs = [m for m in (r.get("messages") or []) if m.get("type") not in SERVICE_TYPES]
    after = r.get("out_last_t") or 0
    if after:
        msgs = [m for m in msgs if (m.get("t") or after + 1) > after]
    return msgs[-n:] if n else []


def work_group(cfg, cid, name, group):
    """Рабочая группа владельца (14.10, слово владельца: «analizar los grupos … escalar al inbox»): группа из списка
    groups в sources.json (имя или id чата). Её ветка разбирается целиком — всё после его последнего ответа, а не только
    непрочитанное и не только срочное; остальные группы — как раньше, только срочное."""
    gs = cfg.get("groups") or []
    return bool(group) and bool(gs) and (cid in gs or (name or "") in gs)


def team_wait(r):
    """Сколько сообщений рабочей группы ждут разбора: все входящие после его последнего ответа (прочитал — не значит
    ответил)."""
    after = r.get("out_last_t") or 0
    return len([m for m in r.get("messages") or [] if m.get("type") not in SERVICE_TYPES
                and not m.get("out") and (m.get("t") or after + 1) > after])


def unread_digest(messages, n, limit=600, preview="", authors=False):
    """Резюме непрочитанного: тексты последних n входящих по порядку, медиа без подписи — словом («голосовое»,
    «фото»). Текст есть только у сообщений из сохранённой копии треда; у самого свежего без копии — строка из
    списка чатов (preview); текстовые без текста пропускаются (сборщик дочитывает чат сам и без текста пункт не шлёт).
    Длинное обрезается с конца. Ничего не известно — пусто."""
    msgs = [m for m in (messages or []) if m.get("type") not in SERVICE_TYPES][-n:] if n else []
    parts, blind, last_who = [], 0, ""
    for i, m in enumerate(msgs):
        txt = " ".join((m.get("text") or "").split())
        if not txt and i == len(msgs) - 1 and not m.get("cached"):
            txt = " ".join((preview or "").split())
        if txt:
            who = (m.get("from") or m.get("author") or "").strip() if authors else ""
            if who and who != last_who:   # в группе — кто пишет, у первой реплики подряд
                txt = f"{who}: {txt}"
            last_who = who or last_who
            parts.append(txt)
            continue
        one = KIND_NAMES.get(m.get("type") or "", (m.get("type") or "", ""))[0]
        if one and one != "текст":
            parts.append(f"[{one}]")
        else:
            blind += 1
    if not parts:
        return ""
    out = " · ".join(parts)
    return out if len(out) <= limit else "…" + out[-(limit - 1):]


ICON_WORDS = (("keyboard-voice|mic|ptt", "голосовое"), ("videocam|video", "видео"), ("photo|image|camera", "фото"),
              ("description|document|file|insert-drive", "файл"), ("audio|music|headphones", "аудио"))


def clean_preview(text):
    """Строка превью из списка чатов WhatsApp для медиа приходит именем иконки с длительностью
    («ic-keyboard-voice-filled0:32», 14.10) — переводим в слово: «[голосовое 0:32]»; неизвестную иконку убираем."""
    text = (text or "").strip()

    def word(m):
        name = m.group(1).lower()
        for pat, w in ICON_WORDS:
            if re.search(pat, name):
                return f"[{w}]"
        return ""
    out = re.sub(r"(?:wds-)?ic-([a-z-]+?)(?:-(?:filled|outline|rounded|sharp))*(?![a-z-])", word, text, flags=re.I)
    out = re.sub(r"(\])\s*(\d{1,2}:\d{2})\b", r"\1 \2", out)   # «[голосовое]0:32» → «[голосовое 0:32]»
    out = re.sub(r"\]\s(\d{1,2}:\d{2})\b", r" \1]", out)
    return " ".join(out.split())


def media_summary(kinds, n):
    """Что пришло, когда у последнего нет текста: «4 голосовых, 2 фото» вместо счётчика (11.10, Иван: «мне надо не
    число, а про что он писал»). Без типов от `wa` — число и общие слова. Содержимое без открытия чата недоступно."""
    parts = []
    for k, c in sorted((kinds or {}).items(), key=lambda kv: -kv[1]):
        if k in SERVICE_TYPES:
            continue
        one, many = KIND_NAMES.get(k, (k, k))
        if k == "chat":   # 12.10: «1 текст» читалось как содержимое; чат читаем сами (wa_read) — сюда доходит, если не вышло
            one, many = "сообщение", "сообщения"
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
            cid, text = r.get("chat_id") or "", clean_preview(r.get("preview") or "")
            n = r.get("unread") or 0
            if not n and cid in _WA_OPENED and (r.get("out_last_t") or 0) < max(
                    [m.get("t") or 0 for m in r.get("messages") or []] or [0]):
                n = _WA_OPENED[cid]   # прочитали мы сами (текст, картинки), а не он — сообщение всё ещё ждёт ответа
            team = work_group(cfg, cid, r.get("name"), cid.endswith("@g.us"))
            if team:
                n = max(n, team_wait(r))
            if not cid or not n:
                continue   # всё прочитано или отвечено — внимания не требует
            wait = waiting({**r, "unread": n})
            def blind(ms):   # текстовые без текста; у последнего хватает строки из списка чатов
                return [m for k, m in enumerate(ms) if not (m.get("text") or "").strip()
                        and (m.get("type") or "chat") == "chat" and not (k == len(ms) - 1 and text and not m.get("cached"))]
            wait = [{**m, "text": _WA_TEXT[(cid, m.get("id"))], "cached": True,
                     **({"from": _WA_WHO[(cid, m["id"])]} if (cid, m.get("id")) in _WA_WHO else {})}
                    if not (m.get("text") or "").strip() and (cid, m.get("id")) in _WA_TEXT else m for m in wait]
            if blind(wait):
                wait = wa_read(cfg, ch, cmd, r, wait, n)   # текста нет в копии — дочитываем чат сами, владельца не просим
            if blind(wait):
                # 14.10, владелец: «не говорить мне, что они непрочитаны» — без текста пункт не выходит; чат перечитаем
                # в плашку не идёт: это не поломка, которую чинит владелец, — в лог плагина
                print(f"whatsapp: {labels.get(ch, ch)}: чат {r.get('name') or cid} не прочитан — повторю", file=sys.stderr,
                      flush=True)
                continue
            if r.get("messages") and not wait:
                continue   # после его ответа нового нет (или только служебное) — отвеченное не поднимаем
            voice = wa_voice(cfg, ch, cid, f"{ch}:{cid}:{(wait[-1].get('id') if wait else '') or r.get('last')}", wait)
            if voice:   # 14.10: расшифровка голосового — текст сообщения (по ней и срочность, и резюме)
                wait = [{**m, "text": voice[m["id"]]["text"], "cached": True}
                        if m.get("id") in voice and voice[m["id"]].get("text") else m for m in wait]
            digest = unread_digest(wait, len(wait), preview=text, **({"limit": 1200, "authors": True} if team else {}))
            if digest:
                text = digest
            elif not text:   # текста нет ни в копии, ни в списке чатов: что пришло — словами
                kinds = {}
                for m in wait:
                    kinds[m.get("type") or ""] = kinds.get(m.get("type") or "", 0) + 1
                text = media_summary(kinds or r.get("kinds"), len(wait) or n)
            group = cid.endswith("@g.us")
            t = tier(text)
            if t == "C" or (group and t != "A" and not team):
                continue
            last = datetime.fromisoformat(r["last"]) if r.get("last") else now
            box = f"wa:{ch}:{cid}"
            digits = re.sub(r"\D", "", cid.split("@")[0])
            boxes.add(box)
            # ключ — последнее ждущее сообщение: то же сообщение второй раз карточкой не станет
            mark = (wait[-1].get("id") if wait else "") or r.get("last")
            kinds = {m.get("type") for m in wait} | set((r.get("kinds") or {}) if not wait else ())
            media = wa_media(cfg, ch, cid, f"{box}:{mark}") if kinds & {"image", "sticker"} else []
            media = media + [v["media"] for v in voice.values()]
            if media:
                _WA_OPENED.setdefault(cid, n)   # wamedia открывал чат — счётчик непрочитанных обнулится
            if media and not any(m.get("body") or m.get("text") for m in wait):
                text = ""   # у картинки без подписи заглушек нет — клиент рисует вложение
            elif voice and not digest:
                text = "[голосовое]"
            items.append({"key": f"{box}:{mark}", "box": box, "src": "whatsapp", "tier": t, "unread": n,
                          **({"media": media} if media else {}),
                          "where": labels.get(ch, "WhatsApp") + (" · группа" if group else ""),
                          "from": r.get("name") or digits, "text": text[:1200], "at": iso_utc(last),
                          "link": f"https://wa.me/{digits}" if digits and not group and len(digits) <= 15 else "",
                          "mention": False, **({"team": True} if team else {}),
                          "ref": {"wa": ch, "to": cid, "cmd": cmd, "send": expand(cfg.get("send") or "~/.claude/bin/send"),
                                  **({"account": cfg["accounts"][ch]} if isinstance(cfg.get("accounts"), dict)
                                     and isinstance(cfg["accounts"].get(ch), str) else {}),
                                  **({"react": expand(cfg["react"]), "msg": (r.get("messages") or [{}])[-1].get("id")}
                                     if cfg.get("react") and (r.get("messages") or [{}])[-1].get("id") else {})}})
    if errors and not ok:
        raise OSError("; ".join(errors))
    return items, boxes, errors


_WA_OPENED = {}   # чат WhatsApp -> сколько ждало, когда мы его открыли сами: обнулённый нами счётчик — не «прочитал владелец»
_WA_READ = {}     # сообщение, ради текста которого чат открывали -> когда: не вышло — снова не раньше WA_READ_AGAIN
WA_READ_AGAIN = 10 * 60
_WA_TEXT = {}     # (чат, сообщение) -> текст, дочитанный из чата: копия треда может отстать от списка чатов
_WA_WHO = {}      # (чат, сообщение) -> автор (группы: кто пишет)


def wa_read(cfg, ch, cmd, r, wait, n):
    """Текста сообщения нет в сохранённой копии — читаем чат сами: `wa thread` (открывает чат во вкладке WhatsApp Web,
    синие галочки — слово 14.10: «Чё, я тебе должен чаты, что ли, открывать?»). Один раз на последнее ждущее сообщение;
    не вышло (нет вкладки) — как было, без текста."""
    cid = r.get("chat_id") or ""
    key = f"{ch}:{cid}:{(wait[-1].get('id') if wait else '') or r.get('last')}"
    if time.time() - _WA_READ.get(key, 0) < WA_READ_AGAIN or cfg.get("read") is False:
        return wait
    _WA_READ[key] = time.time()
    who = re.sub(r"\D", "", cid.split("@")[0]) if cid.endswith("@c.us") else (r.get("name") or "")
    try:
        got = json.loads(run([cmd, "thread", who, "--channel", ch, "--json", "--limit", "40"], timeout=120) or "{}")
    except (OSError, ValueError, subprocess.SubprocessError):
        return wait
    _WA_OPENED.setdefault(cid, n)
    body = {m.get("id"): (m.get("body") or "").strip() for m in got.get("messages") or [] if not m.get("out")}
    who = {m.get("id"): (m.get("author") or "").strip() for m in got.get("messages") or [] if m.get("author")}
    for mid, b in body.items():
        if b:
            _WA_TEXT[(cid, mid)] = b
            if who.get(mid):
                _WA_WHO[(cid, mid)] = who[mid]
    while len(_WA_TEXT) > 2000:
        _WA_WHO.pop(next(iter(_WA_TEXT)), None)
        _WA_TEXT.pop(next(iter(_WA_TEXT)))
    return [{**m, "text": body.get(m.get("id")) or m.get("text") or "", "cached": True,
             **({"from": who[m["id"]]} if who.get(m.get("id")) else {})} if body.get(m.get("id")) else m
            for m in wait]


# --- вложения сообщений (12.10, «фото, видео, файлы, голосовые — как в мессенджере») -----------------------------------
MEDIA_KEEP = 6
_WA_MEDIA = {}   # ключ поста -> вложения: чат ради картинок открываем один раз на сообщение (синие галочки — слово 13.10)   # у скольких последних сообщений с вложениями тянем файл; у остальных — только описание


def _state_dir():
    d = os.environ.get("HUB_STATE_DIR")
    if d:
        return d
    from core.daemon import default_state_dir
    return default_state_dir()


def wa_media(cfg, ch, cid, key):
    """Фото и стикеры WhatsApp: `wamedia` открывает чат (владелец 13.10: «синие галочки допустимы») и снимает blob-картинки
    отрисованной страницы. Видео и голосовые вне прокрутки не отдаются — их тут нет. Нет скрипта/вкладки — без вложений."""
    from urllib.parse import quote
    if cfg.get("media") is False:
        return []
    if key in _WA_MEDIA:
        return _WA_MEDIA[key]
    cmd = expand(cfg.get("media_cmd") or "~/.claude/bin/wamedia")
    got = []
    try:
        rows = json.loads(run([cmd, cid, "--dir", media_dir("wa"), "--channel", ch], timeout=120) or "[]")
        for m in rows:
            got.append({"id": f"wa:{cid}:{m['id']}", "kind": m.get("kind") or "image", "name": os.path.basename(m["path"]),
                        "mime": m.get("mime"), "w": m.get("w"), "h": m.get("h"),
                        "url": "/api/file?path=" + quote(m["path"], safe="")})
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        got = []
    _WA_MEDIA[key] = got
    return got


_WA_VOICE = {}   # ключ -> (когда, {id сообщения: {text, media}}): чат ради голосового открываем один раз на сообщение


def wa_voice(cfg, ch, cid, key, wait):
    """Голосовые WhatsApp среди ждущих: `wamedia --voice` скачивает файл через меню «Download» вкладки (владелец
    13.10: синие галочки для медиа допустимы; без прокрутки и без звука), расшифровка — голосовой модуль хаба.
    {id: {text, media}}; нет скрипта/вкладки/голоса — пусто, не вышедшее пробуем снова через WA_READ_AGAIN."""
    from urllib.parse import quote
    ids = [m["id"] for m in wait if m.get("id") and m.get("type") in ("ptt", "audio")]
    if not ids or cfg.get("media") is False or cfg.get("voice") is False:
        return {}
    got = _WA_VOICE.get(key)
    if got and (got[1] or time.time() - got[0] < WA_READ_AGAIN):
        return got[1]
    cmd = expand(cfg.get("media_cmd") or "~/.claude/bin/wamedia")
    out = {}
    try:
        rows = json.loads(run([cmd, cid, "--dir", media_dir("wa"), "--channel", ch, "--voice", "--only", ",".join(ids)],
                              timeout=180) or "[]")
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        print(f"whatsapp: голосовое {cid}: {e}", file=sys.stderr, flush=True)
        rows = []
    for m in rows:
        try:
            path = m["path"]
            play = _playable(path)
            item = {"id": f"wa:{cid}:{m['id']}", "kind": "voice", "name": os.path.basename(play), "mime": m.get("mime"),
                    "url": "/api/file?path=" + quote(play, safe="")}
            if play != path:
                item["mime"] = "audio/mp4"
            if m.get("dur"):
                item["dur"] = m["dur"]
            out[m["id"]] = {"text": _transcript(path).strip(), "media": item}
        except (KeyError, OSError):
            continue
    _WA_VOICE[key] = (time.time(), out)
    if out:
        _WA_OPENED.setdefault(cid, len(ids))
    return out


def media_dir(src):
    """Куда класть: под attachments хаба — страница и клиенты отдают такие файлы сами (/api/file), чужие пути — нет."""
    d = os.path.join(_state_dir(), "attachments", "inbox", src)
    os.makedirs(d, exist_ok=True)
    return d


def _playable(path):
    """Голосовые Telegram приходят в ogg/opus — системный плеер iOS/macOS его не играет. Рядом кладём m4a (AAC),
    клиентам отдаём его; нет ffmpeg или не вышло — как есть."""
    if not path.lower().endswith((".ogg", ".oga", ".opus")):
        return path
    out = os.path.splitext(path)[0] + ".m4a"
    if os.path.exists(out):
        return out
    try:
        subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", path, "-vn", "-c:a", "aac", "-b:a", "48k", out],
                       timeout=60, check=True, capture_output=True)
    except (OSError, subprocess.SubprocessError):
        return path
    return out


def _transcript(path):
    """Расшифровка голосового сразу (Whisper / ChatGPT по настройкам хаба); рядом `.txt` — второй раз не гоняем.
    Пусто — голос не настроен или не вышло: клиент покажет один плеер."""
    side = path + ".txt"
    try:
        with open(side, encoding="utf-8") as f:
            return f.read()
    except OSError:
        pass
    try:
        from core import catalog
        from modules.voice import transcribe
        cfg = catalog.load_config(_state_dir())
        if not transcribe.enabled(cfg):
            return ""
        with open(path, "rb") as f:
            text = transcribe.transcribe(f.read(), cfg, suffix=os.path.splitext(path)[1] or ".ogg")
    except Exception as e:   # нет голоса, нет ffmpeg, лимит — расшифровки нет, переписка живёт
        print(f"teams: расшифровка {os.path.basename(path)}: {e}", flush=True)
        return ""
    with open(side, "w", encoding="utf-8") as f:
        f.write(text)
    return text


def tg_media(cmd, chat, msgs, keep=MEDIA_KEEP):
    """Вложения сообщений Telegram → список для клиентов: {id, kind, name, mime, size, dur, w, h, url, thumb, text}.
    Файл — в attachments хаба (`url` — /api/file); тяжёлый (>40 МБ) — миниатюра с thumb:true; не скачался — без url."""
    from urllib.parse import quote
    out, d = [], None
    with_media = [m for m in msgs if m.get("media")]
    for m in with_media[-keep:]:
        meta = dict(m["media"])
        item = {"id": f"tg:{chat}:{m.get('id')}", **meta}
        d = d or media_dir("tg")
        base = f"{abs(int(chat)) if str(chat).lstrip('-').isdigit() else chat}-{m.get('id')}"
        have = next((f for f in os.listdir(d) if f.startswith(base + ".") or f.startswith(base + "-thumb.")), None)
        if have is None:
            try:
                got = json.loads(run([cmd, "media", str(chat), str(m["id"]), "--dir", d], timeout=120) or "{}")
                have = os.path.basename(got.get("path") or "") or None
            except (OSError, ValueError, subprocess.TimeoutExpired):
                have = None
        if have:
            path = os.path.join(d, have)
            item["url"] = "/api/file?path=" + quote(path, safe="")
            item["thumb"] = "-thumb." in have
            if meta.get("kind") in ("voice", "audio") and not item["thumb"]:
                t = _transcript(path)
                if t:
                    item["text"] = t
                play = _playable(path)
                if play != path:
                    item["url"] = "/api/file?path=" + quote(play, safe="")
                    item["mime"] = "audio/mp4"
        out.append(item)
    return out


def tg_reply_text(m, by_id):
    """Цитата в ответе: текст и автор сообщения, на которое отвечают (если оно в окне)."""
    r = m.get("reply") or {}
    src = by_id.get(str(r.get("id")))
    if not src:
        return r or None
    return {"id": r.get("id"), "from": src.get("from") or ("вы" if src.get("out") else ""),
            "text": (src.get("text") or "")[:160]}


# --- Telegram: личный аккаунт, только чтение (`tgnew new` — копия сессии Telethon, прочитанным ничего не отмечает) --
@source("telegram", every=120)
def telegram(cfg, now):
    """Чаты с непрочитанным входящим за сутки; та же логика, что у WhatsApp. Группы — только срочное; заглушённые,
    каналы-рассылки и боты командой не отдаются. Ответ — `send tg` (ночной запрет и выходные действуют там)."""
    cmd = expand(cfg.get("cmd") or "~/.claude/bin/tgnew")
    try:
        rows = json.loads(run([cmd, "new", "--hours", "24", "--json"]) or "[]")
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        raise OSError(f"Telegram: {e}")
    items, boxes = [], set()
    for r in rows:
        cid, n = r.get("chat_id") or "", r.get("unread") or 0
        team = work_group(cfg, cid, r.get("name"), r.get("group"))
        if team:
            n = max(n, team_wait(r))
        if not cid or not n:
            continue
        wait = waiting({**r, "unread": n})
        if r.get("messages") and not wait:
            continue
        text = unread_digest(wait, len(wait), preview=r.get("preview") or "",
                             **({"limit": 1200, "authors": True} if team else {}))
        if not text:
            kinds = {}
            for m in wait:
                kinds[m.get("type") or ""] = kinds.get(m.get("type") or "", 0) + 1
            text = (r.get("preview") or "").strip() or media_summary(kinds, len(wait) or n)
        group = bool(r.get("group"))
        if group and wait and not team:   # в группе — кто написал (у рабочей — у каждой реплики)
            last = wait[-1]
            if last.get("from"):
                text = f"{last['from']}: {text}" if " · " not in text else text
        t = tier(text)
        if t == "C" or (group and t != "A" and not team):
            continue
        at = datetime.fromisoformat(r["last"]) if r.get("last") else now
        box = f"tg:{cid}"
        boxes.add(box)
        mark = (wait[-1].get("id") if wait else "") or r.get("last")
        user = r.get("username") or ""
        media = tg_media(cmd, cid, wait)
        if media and not any((m.get("text") or "").strip() for m in wait):
            text = ""   # 12.10: у медиа без подписи заглушки («[фото]», «1 сообщение без текста») не кладём — клиент рисует само вложение
        links = [m["link"] for m in wait if m.get("link")][-3:]
        items.append({"key": f"{box}:{mark}", "box": box, "src": "telegram", "tier": t, "unread": n,
                      "where": "Telegram" + (" · группа" if group else ""), "from": r.get("name") or cid,
                      "text": text[:1200], "at": iso_utc(at), "mention": False, **({"team": True} if team else {}),
                      **({"media": media} if media else {}), **({"links": links} if links else {}),
                      "link": f"https://t.me/{user}" if user else (f"tg://user?id={cid}" if not group else ""),
                      "ref": {"tg": cid, "cmd": cmd, "send": expand(cfg.get("send") or "~/.claude/bin/send")}})
    return items, boxes, []


# --- тело письма (12.10: «показана только тема — нет тела письма»), без цитат предыдущих писем --------------------
_QUOTE = re.compile(r"(?im)^(?:>.*|(?:on|el|em|am|le) .{3,200}(?:wrote|escribi[oó]|escreveu|schrieb|a [eé]crit).{0,60}:?\s*|"
                    r".{0,160}(?:написал[аи]?|писал[аи]?):\s*|"
                    r"-{2,}\s*(?:original|forwarded|mensaje reenviado|пересланное).*|_{5,}\s*)$")
_BODIES = {}


def _decode(data):
    import base64
    try:
        return base64.urlsafe_b64decode(str(data) + "=" * (-len(str(data)) % 4)).decode("utf-8", "replace")
    except (ValueError, TypeError):
        return ""


def message_text(payload):
    """Текст письма из payload Gmail: text/plain, иначе text/html без разметки; цитаты и подписи-хвосты обрезаны."""
    plain, html_ = [], []

    def walk(p):
        mt = (p.get("mimeType") or "").lower()
        data = (p.get("body") or {}).get("data")
        if data and mt == "text/plain":
            plain.append(_decode(data))
        elif data and mt == "text/html":
            html_.append(_decode(data))
        for c in p.get("parts") or []:
            walk(c)
    walk(payload or {})
    text = "\n".join(plain)
    if not text.strip() and html_:
        import html as H
        h = re.sub(r"(?is)<(script|style).*?</\1>", " ", "\n".join(html_))
        h = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", h)
        text = H.unescape(re.sub(r"<[^>]+>", " ", h))
    lines = []
    for ln in text.replace("\r", "").split("\n"):
        if _QUOTE.match(ln.strip()):
            if ln.strip().startswith(">"):
                continue
            if re.match(r"(?i)(?:-{2,}\s*(?:forwarded|mensaje reenviado|пересланное|original)|_{5,})", ln.strip()) \
                    and len(re.sub(r"(?i)obtener outlook.*|sent from.*|enviado desde.*", "", " ".join(lines)).strip()) < 40:
                continue   # «Fw:» без своих слов — само пересланное и есть содержание письма
            break   # «El … escribió:» — дальше только цитата
        lines.append(" ".join(ln.split()))
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return out


def mail_thread(cmd, acct, thread_id, count):
    """Письма цепочки [{from, at, me, text}] с телом; кеш на (цепочка, число писем)."""
    key = (acct, thread_id, count)
    if key in _BODIES:
        return _BODIES[key]
    data = json.loads(run([cmd, "gmail", "thread", "get", thread_id, "-a", acct, "-j"]))
    out = []
    for m in (data.get("thread") or {}).get("messages") or []:
        heads = {h.get("name", "").lower(): h.get("value", "") for h in (m.get("payload") or {}).get("headers") or []}
        try:
            at = iso_utc(datetime.fromtimestamp(int(m.get("internalDate") or 0) / 1000, timezone.utc))
        except (ValueError, OSError):
            at = ""
        out.append({"at": at, "from": re.sub(r"\s*<[^>]*>\s*$", "", heads.get("from", "")).strip().strip('"'),
                    "me": "SENT" in (m.get("labelIds") or []), "text": message_text(m.get("payload")) or (m.get("snippet") or "").strip(),
                    "subject": heads.get("subject", ""), "id": m.get("id"), "files": mail_files(m.get("payload"))})
    if len(_BODIES) > 200:
        _BODIES.clear()
    _BODIES[key] = out
    return out


def mail_files(payload):
    """Вложения письма [{name, mime, size, att}]: файлы и картинки в теле; мелкие картинки-подписи (логотипы,
    трекеры — inline до 30 КБ) не считаем."""
    out = []

    def walk(p):
        body = p.get("body") or {}
        name, att = p.get("filename") or "", body.get("attachmentId")
        if att and (name or (p.get("mimeType") or "").startswith("image/")):
            heads = {h.get("name", "").lower(): h.get("value", "") for h in p.get("headers") or []}
            size = int(body.get("size") or 0)
            if not (heads.get("content-id") and size < 30000 and (p.get("mimeType") or "").startswith("image/")):
                out.append({"name": name or f"image-{abs(hash(att)) % 10**6}", "mime": p.get("mimeType") or "", "size": size, "att": att})
        for c in p.get("parts") or []:
            walk(c)
    walk(payload or {})
    return out


def mail_media(cmd, acct, msg, keep=MEDIA_KEEP, limit=40 << 20):
    """Вложения письма — файлами в attachments хаба (`url` — /api/file), как у Telegram; тяжёлое и лишнее — без файла."""
    from urllib.parse import quote
    d = media_dir("mail")
    out = []
    for f in (msg.get("files") or [])[:keep]:
        name = re.sub(r"[^\w.\- ]+", "_", f["name"])[:80] or "file"
        path = os.path.join(d, f"{msg['id']}-{name}")
        item = {"id": f"mail:{msg['id']}:{__import__('hashlib').md5(f['att'].encode()).hexdigest()[:10]}", "kind": ("image" if f["mime"].startswith("image/") else
                "video" if f["mime"].startswith("video/") else "audio" if f["mime"].startswith("audio/") else "file"),
                "name": f["name"], "mime": f["mime"], "size": f["size"]}
        if f["size"] <= limit:
            if not os.path.exists(path):
                try:
                    run([cmd, "gmail", "attachment", msg["id"], f["att"], "-a", acct, "--out", path], timeout=120)
                except (OSError, subprocess.SubprocessError):
                    pass
            if os.path.exists(path) and os.path.getsize(path):
                item["url"] = "/api/file?path=" + quote(path, safe="")
        out.append(item)
    return out


URL = re.compile(r"https?://[^\s<>\"')\]]+")


# --- Почта: Gmail через gogx — непрочитанные входящие вне рассылок; тема и отправитель ----------------------------
@source("email", every=120)
def email(cfg, now):
    cmd = expand(cfg.get("cmd") or "~/.claude/bin/gogx")
    query = cfg.get("query") or ("is:unread in:inbox newer_than:7d -category:promotions -category:social "
                                 "-category:forums")
    items, boxes, errors, ok, fetched = [], set(), [], 0, 0
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
            body, media = "", []
            if fetched < 15:   # тело нового письма — не только тема (владелец 12.10); цепочки без нового кешируются
                fetched += 1
                try:
                    msgs = [m for m in mail_thread(cmd, acct, th["id"], th.get("messageCount")) if not m["me"]]
                    body = (msgs[-1]["text"] if msgs else "")[:1000]
                    if msgs and msgs[-1].get("files"):
                        media = mail_media(cmd, acct, msgs[-1])
                except (OSError, ValueError, subprocess.TimeoutExpired):
                    body = ""
            links = [{"url": u.rstrip(".,;")} for u in dict.fromkeys(URL.findall(body))
                     if not re.search(r"(?i)\.(png|gif|jpe?g)(\?|$)|gstatic\.com|aka\.ms/", u)][:3]
            items.append({"key": f"{box}:{th.get('date')}:{th.get('messageCount')}", "box": box, "src": "email",
                          "tier": t, "unread": "UNREAD" in labels, "where": "Почта" + (f" · {acct}" if len(cfg.get("accounts") or []) > 1 else ""),
                          "from": name or "—", "text": (subject or "(без темы)") + (f"\n\n{body}" if body else ""),
                          "at": at, **({"links": links} if links else {}), **({"media": media} if media else {}),
                          "link": f"https://mail.google.com/mail/u/0/?authuser={acct}#inbox/{th['id']}", "mention": False,
                          "contact": f"mail:{(addr.group(1) if addr else sender).lower()}",
                          "ref": {"mail": acct, "thread": th["id"], "subject": subject, "cmd": cmd}})
    if errors and not ok:
        raise OSError("; ".join(errors))
    return items, boxes, errors


# --- Ответ владельца из вкладки в WhatsApp и почту: теми же командами машины, что читают -----------------------------
# Отказы команды send — человеческим текстом, не именами переменных (владелец 12.10: «показывать ошибку понятно»)
HUMAN = [
    (re.compile(r"TELEGRAM_API_(ID|HASH)|api_id|api_hash", re.I), "Telegram не подключён на этом компьютере (нет ключей входа) — отправить не вышло"),
    (re.compile(r"Telethon session|session not found|not authorized|AuthKey", re.I), "Telegram не авторизован на этом компьютере — отправить не вышло"),
    (re.compile(r"between 2[23]:00 and 08:00|quiet hours|night", re.I), "С 23:00 до 08:00 по Аргентине WhatsApp и Telegram не отправляются — повтори после 08:00"),
    (re.compile(r"weekend|Saturday|Sunday|held", re.I), "В выходные это сообщение не отправляется — повтори в понедельник"),
    (re.compile(r"FloodWait|flood", re.I), "Telegram просит подождать — повтори через несколько минут"),
    (re.compile(r"timed? ?out|timeout", re.I), "Не дождались ответа от сервиса — повтори"),
]


def human(message):
    msg = str(message or "")
    for rx, text in HUMAN:
        if rx.search(msg):
            return text
    return re.sub(r"^(?:send failed|Blocked|Not sent):\s*", "", msg).strip() or "не отправлено"


class Held(OSError):
    """Команда отправки отказала, ничего не отправив: ночь или выходной. Не ошибка — плагин перенесёт (main.hold)."""

    def __init__(self, why, text):
        super().__init__(text)
        self.why = why


def held(message):
    """Отказ гейта команды send → «night» / «weekend»; любая другая ошибка → None."""
    msg = str(message or "")
    if HUMAN[2][0].search(msg):
        return "night"
    return "weekend" if HUMAN[3][0].search(msg) else None


def reply(ref, text, files=None, reply_to=None, quote=None):
    try:
        return _reply(ref, text, files or [], reply_to, quote)
    except OSError as e:
        why = held(e)
        if why:
            raise Held(why, human(e)) from None
        raise OSError(human(e)) from None


def _reply(ref, text, files=(), reply_to=None, quote=None):
    """WhatsApp — сообщением в тот же чат (команда send из sources.json: её ночные и прочие запреты действуют — отказ
    вернётся ошибкой во вкладку); почта — ответом всем в ту же цепочку; файлы — вложениями (--file). Ответ на
    конкретное сообщение: Telegram — настоящим ответом (--reply-to), WhatsApp — цитатой текстом."""
    fl = [x for f in files for x in ("--file", f)]
    if ref.get("wa"):
        if reply_to and quote:
            text = f"> {' '.join(quote.split())[:300]}\n{text}"
        return run([ref["send"], "wa", "--to", ref["to"], "--channel", ref["wa"], "--text", text, *fl], timeout=180)
    if ref.get("tg"):
        rt = ["--reply-to", reply_to] if reply_to and str(reply_to).isdigit() else []
        return run([ref["send"], "tg", "--to", ref["tg"], "--text", text, *fl, *rt], timeout=180)
    if ref.get("mail"):
        subject = ref.get("subject") or ""
        if not re.match(r"(?i)re:", subject):
            subject = "Re: " + subject
        return run([ref["cmd"], "gmail", "send", "--thread-id", ref["thread"], "--reply-all", "--subject", subject,
                    "--body", text, "-a", ref["mail"], *[x for f in files for x in ("--attach", f)]], timeout=180)
    raise OSError("не знаю, куда отвечать на это сообщение")


def react(ref, emoji, msg=None):
    """Реакция в WhatsApp — командой из sources.json (`"react": "<путь>"`): <команда> react <чат> --id <сообщение>
    --emoji <эмодзи> --channel <номер>; Telegram — tgnew react. msg — id конкретного сообщения переписки (иначе то,
    на которое пришёл пост)."""
    if ref.get("wa") and ref.get("react") and (msg or ref.get("msg")):
        return run([ref["react"], "react", ref["to"], "--id", msg or ref["msg"], "--emoji", emoji, "--channel", ref["wa"]],
                   timeout=120)
    if ref.get("tg") and (msg or ref.get("msg")) and str(msg or ref.get("msg")).isdigit():
        return run([ref.get("cmd") or expand("~/.claude/bin/tgnew"), "react", ref["tg"], str(msg or ref["msg"]),
                    "--emoji", emoji], timeout=60)
    raise OSError("на это сообщение реакцию поставить нельзя")


def page(items, top, before=None, search=None):
    """Страница переписки из полного списка по времени: старше сообщения `before` (id), с текстом `search`; последние top."""
    if before:
        ids = [str(i.get("id")) for i in items]
        if str(before) in ids:
            items = items[:ids.index(str(before))]
    if search:
        q = search.casefold()
        items = [i for i in items if q in (i.get("text") or "").casefold() or q in (i.get("from") or "").casefold()]
    return items[-top:]


def amend(ref, msg, text=None):
    """Правка (text) или удаление (text=None) своего отправленного. Telegram — Telethon (только свои сообщения);
    WhatsApp и почта — нельзя: у WhatsApp нет такого канала, письмо не вернуть."""
    if ref.get("tg") and str(msg).isdigit():
        cmd = ref.get("cmd") or expand("~/.claude/bin/tgnew")
        if text is None:
            return run([cmd, "delete", ref["tg"], str(msg)], timeout=60)
        return run([cmd, "edit", ref["tg"], str(msg), "--text", text], timeout=60)
    if ref.get("wa"):
        raise OSError("в WhatsApp отправленное отсюда не поправить")
    if ref.get("mail"):
        raise OSError("отправленное письмо не вернуть")
    raise OSError("это сообщение изменить нельзя")


def mark_read(ref):
    """Пометить прочитанным в источнике — только по явной кнопке владельца. Telegram — прочитано до конца чата; почта —
    снимается метка UNREAD с цепочки; WhatsApp — чат открывается (отправитель увидит синие галочки: слово Ивана 13.10)."""
    if ref.get("tg"):
        return run([ref.get("cmd") or expand("~/.claude/bin/tgnew"), "read", ref["tg"]], timeout=60)
    if ref.get("mail"):
        return run([ref["cmd"], "gmail", "thread", "modify", ref["thread"], "--remove", "UNREAD", "-a", ref["mail"]],
                   timeout=60)
    if ref.get("wa"):
        who = ref["to"] if ref["to"].endswith("@g.us") else re.sub(r"\D", "", ref["to"].split("@")[0])
        return run([ref.get("cmd") or expand("~/.claude/bin/wa"), "thread", who, "--limit", "1", "--channel", ref["wa"]],
                   timeout=120)
    raise OSError("в Teams прочитанным пометить нельзя: Graph этого не даёт")


def verified_wa_history(ref, data):
    """Validate the source-v1 cache contract before publishing any row.

    Expected account comes from the collector's channel configuration, never from
    returned data. Legacy rows remain on disk but cannot be used as thread context.
    """
    def peer(value):
        return str(value or "").replace("@s.whatsapp.net", "@c.us")
    want, account = peer(ref.get("to")), ref.get("account")
    rows = data.get("messages") if isinstance(data, dict) else None
    if (not re.fullmatch(r"\d+@(c\.us|g\.us|lid)", want)
            or not isinstance(account, str) or not re.fullmatch(r"\d+", account)
            or not isinstance(rows, list) or peer(data.get("chat_id")) != want):
        raise OSError("Unverified WhatsApp history identity")
    ids = set()
    for row in rows:
        source = (row.get("source") or {}) if isinstance(row, dict) else {}
        if not isinstance(source, dict):
            raise OSError("Unverified WhatsApp history identity")
        raw = str(source.get("raw_id") or "").split("_")
        if (not isinstance(row, dict) or source.get("version") != 1
                or source.get("channel") != ref["wa"] or source.get("account") != account
                or peer(source.get("peer")) != want or len(raw) not in (3, 4)
                or raw[0] not in ("true", "false") or peer(raw[1]) != want
                or not raw[2] or raw[2] != row.get("id") or row.get("id") in ids
                or (raw[0] == "true") != row.get("out")):
            raise OSError("Unverified WhatsApp history identity")
        try:
            stamp = datetime.fromisoformat(source.get("captured_at") or "")
            if stamp.utcoffset() is None:
                raise ValueError("timezone required")
        except (ValueError, TypeError):
            raise OSError("Unverified WhatsApp history identity") from None
        ids.add(row["id"])
    return rows


def history(ref, top=20, before=None, search=None):
    """Переписка для «всей переписки» во вкладке. WhatsApp — только сохранённая копия треда (`--cached`): живое чтение
    открыло бы чат и поставило синие галочки. Почта — письма цепочки: от кого, когда, начало текста."""
    if ref.get("wa"):
        who = ref["to"] if ref["to"].endswith("@g.us") else re.sub(r"\D", "", ref["to"].split("@")[0])
        data = json.loads(run([ref.get("cmd") or expand("~/.claude/bin/wa"), "thread", who, "--cached", "--json",
                               "--limit", str(500 if before or search else top), "--channel", ref["wa"]]))
        out = []
        for m in verified_wa_history(ref, data):
            try:
                at = iso_utc(datetime.strptime(m.get("when") or "", "%I:%M %p, %m/%d/%Y"))
            except ValueError:
                at = ""
            text = (m.get("body") or "").strip() or ("[медиа]" if m.get("media") else "")
            if text:
                out.append({"at": at, "from": m.get("author") or "", "me": bool(m.get("out")), "text": text,
                            "source": m["source"],
                            **({"id": str(m["id"])} if m.get("id") else {})})
        return page(out, top, before, search)   # копия треда целиком: листание и поиск — по ней
    if ref.get("tg"):
        extra = (["--before", str(before)] if before and str(before).isdigit() else []) + \
                (["--search", search] if search else [])
        try:
            data = json.loads(run([ref.get("cmd") or expand("~/.claude/bin/tgnew"), "thread", ref["tg"], "--limit",
                                   str(top), "--json", *extra]))
        except (OSError, ValueError):
            return []
        msgs = data.get("messages") or []
        by_id = {str(m.get("id")): m for m in msgs}
        got = {}
        for it in tg_media(ref.get("cmd") or expand("~/.claude/bin/tgnew"), ref["tg"], msgs):
            got[it["id"].rsplit(":", 1)[-1]] = it
        out = []
        for m in msgs:
            e = {"at": iso_utc(datetime.fromtimestamp(m["t"], timezone.utc)), "from": m.get("from") or "",
                 "me": bool(m.get("out")), "text": m.get("text") or "", **({"id": str(m["id"])} if m.get("id") else {})}
            if str(m.get("id")) in got:
                e["media"] = [got[str(m["id"])]]
            elif m.get("media"):
                e["media"] = [{**m["media"], "id": f"tg:{ref['tg']}:{m.get('id')}"}]   # без файла: описание
            if not e["text"] and not e.get("media"):
                e["text"] = f"[{KIND_NAMES.get(m.get('type'), ('медиа',))[0]}]"
            if m.get("link"):
                e["links"] = [m["link"]]
            for k in ("reactions", "fwd", "edited"):
                if m.get(k):
                    e[k] = m[k]
            if m.get("reply"):
                e["reply"] = tg_reply_text(m, by_id)
            out.append(e)
        return out
    if ref.get("mail"):
        out = [{"at": m["at"], "from": m["from"], "me": m["me"], "text": m["text"] or m.get("subject", "")}
               for m in mail_thread(ref["cmd"], ref["mail"], ref["thread"], None)]
        return page(out, top, None, search)
    return []
