// The collector owns contact lookup and delivery. Closing/reloading never sends.
import { T } from "/static/js/ui-text.js";
import { replyText } from "./reply-text.js";

export function newMessage(hub) {
  const el = (...a) => hub.el(...a), states = new Map();
  const id = () => crypto.randomUUID();
  const contact = c => c && ["teams", "whatsapp", "telegram", "email"].includes(c.src)
    && typeof c.to === "string" && c.to.length <= 300 && c.to.startsWith(c.src + ":") && typeof c.name === "string";
  const source = c => ({ teams: "Teams", whatsapp: "WhatsApp", telegram: "Telegram", email: "Mail" })[c.src];
  const key = () => "hub.inbox.new.v1:" + ((hub.snapshot().sessions || []).find(s => s.kind === "hub")?.name || "hub");
  function state() {
    const k = key();
    if (!states.has(k)) {
      let saved; try { saved = JSON.parse(localStorage.getItem(k) || "null"); } catch { /* use a fresh draft */ }
      const s = { key: k, to: contact(saved?.to) ? saved.to : null, text: typeof saved?.text === "string" ? saved.text : "",
        subject: typeof saved?.subject === "string" ? saved.subject : "", pending: null, status: "", query: "", lookup: "", items: [], errors: "", looking: false };
      if (saved?.pending?.kind === "send_new" && typeof saved.pending.rid === "string" && typeof saved.pending.to === "string" && typeof saved.pending.text === "string") s.pending = saved.pending;
      // A reload cannot prove that an in-flight POST reached the collector.
      // Recovery is explicit and always reuses the original delivery id.
      s.uncertain = !!s.pending;
      s.pendingName = typeof saved?.pendingName === "string" ? saved.pendingName : s.to?.name;
      states.set(k, s);
    }
    return states.get(k);
  }
  function save(s) {
    try {
      if (!s.to && !s.text && !s.subject && !s.pending) localStorage.removeItem(s.key);
      else localStorage.setItem(s.key, JSON.stringify({to:s.to,text:s.text,subject:s.subject,pending:s.pending,pendingName:s.pendingName,uncertain:!!s.uncertain}));
      s.storageError = "";
    } catch { s.storageError = T("Не удалось сохранить черновик в браузере. Оставьте эту страницу открытой.", "This browser could not save the draft. Keep this page open."); }
    if (s.ui) { s.ui.storage.textContent = s.storageError || ""; s.ui.storage.hidden = !s.storageError; }
  }
  const button = (label, cls, action) => {
    const b = el("button", "btn " + cls, label); b.type = "button"; b.addEventListener("click", action); return b;
  };
  async function lookup(s) {
    clearTimeout(s.timer);
    const q = s.query.trim(); s.items = []; s.errors = "";
    if (q.length < 2) { s.lookup = ""; s.looking = false; draw(s); return; }
    const rid = s.lookup = id(); s.looking = true; draw(s);
    setTimeout(() => { if (s.lookup === rid && s.looking) { s.looking = false; s.errors = T("Поиск не ответил", "Contact search has not responded"); draw(s); } }, 30000);
    let result; try { result = await hub.postFeed(JSON.stringify({kind:"contacts",rid,q})); } catch { result = {error:"Contact search failed"}; }
    if (s.lookup === rid && result?.error) { s.looking = false; s.errors = result.error; draw(s); }
  }
  async function submit(s) {
    if (s.pending && !s.uncertain) return;
    // Read the actual fields, including browser autofill, at the send boundary.
    s.text = s.ui.text.value; s.subject = s.ui.subject.value; save(s);
    if (!s.pending) {
      if (!s.to) { s.status = T("Выберите адресата", "Choose a recipient"); draw(s); return; }
      if (!s.text.trim()) { s.status = T("Введите сообщение", "Enter a message"); s.ui.text.focus(); draw(s); return; }
      if (s.to.src === "email" && !s.subject.trim()) { s.status = T("Введите тему письма", "Enter a subject"); s.ui.subject.focus(); draw(s); return; }
      s.pending = {kind:"send_new",rid:id(),to:s.to.to,text:s.text,...(s.to.src === "email" ? {subject:s.subject} : {})};
      s.pendingName = s.to.name;
    }
    const pending = s.pending;
    s.uncertain = false; s.status = ""; save(s); draw(s);
    clearTimeout(s.sendTimer);
    const unknown = () => {
      if (s.pending !== pending) return;
      s.uncertain = true;
      s.status = T("Подтверждения нет. Повтор относится к исходному сообщению ниже.", "No confirmation yet. Retry refers to the original message below.");
      save(s); draw(s);
    };
    s.sendTimer = setTimeout(unknown, 30000);
    let result; try { result = await hub.postFeed(JSON.stringify(pending)); } catch { result = {error:true}; }
    // An interrupted HTTP acknowledgement is not a collector refusal. Retry the
    // same request id, which the collector records before contacting the source.
    if (s.pending === pending && result?.error) { clearTimeout(s.sendTimer); unknown(); }
  }
  function draw(s) {
    if (!s.ui) return;
    const u = s.ui;
    u.search.hidden = !!s.to; u.chosen.hidden = !s.to; u.results.hidden = !!s.to;
    u.chosen.replaceChildren();
    if (s.to) {
      const name = el("span", "", s.to.name), hint = el("span", "tm-new-hint", [source(s.to),s.to.hint].filter(Boolean).join(" · "));
      const person = el("div"); person.append(name, hint);
      const change = button(T("Изменить", "Change"), "quiet", () => { s.to = null; save(s); draw(s); u.search.focus(); });
      change.disabled = !!s.pending;
      u.chosen.append(person, change);
    }
    u.results.replaceChildren(...s.items.map(c => {
      const b = button("", "quiet tm-new-contact", () => { s.to = c; s.lookup = ""; s.looking = false; s.items = []; save(s); draw(s); u.text.focus(); });
      b.append(el("span", "", c.name), el("span", "tm-new-hint", [source(c), c.hint].filter(Boolean).join(" · "))); return b;
    }));
    if (s.looking) u.results.append(el("p", "", T("Поиск…", "Searching…")));
    else if (s.errors) {
      u.results.append(el("p", "", s.errors), button(T("Повторить поиск", "Retry search"), "quiet", () => lookup(s)));
    } else if (s.lookup && !s.items.length) u.results.append(el("p", "", T("Никого не найдено", "No contacts found")));
    u.search.setAttribute("aria-expanded", String(!s.to && !!s.lookup));
    u.pending.hidden = !s.pending;
    u.pending.replaceChildren();
    if (s.pending) {
      u.pending.append(el("b", "", T("Исходное сообщение: ", "Original message: ") + (s.pendingName || s.pending.to)));
      if (s.pending.subject) u.pending.append(el("p", "", s.pending.subject));
      u.pending.append(replyText(el,s.pending.text,"tm-pending-text","p"));
    }
    u.subjectRow.hidden = s.to?.src !== "email";
    u.send.disabled = !!s.pending && !s.uncertain;
    u.send.textContent = s.uncertain ? T("Повторить исходное", "Retry original message") : T("Отправить", "Send");
    u.status.textContent = s.status || (s.pending ? s.uncertain ? T("Доставка не подтверждена", "Delivery is unconfirmed") : T("Отправляется…", "Sending…") : "");
    u.status.hidden = !u.status.textContent;
    u.storage.textContent = s.storageError || ""; u.storage.hidden = !s.storageError;
  }
  function open() {
    const s = state();
    if (!s.ui) {
      const dialog = el("dialog", "tm-new"), form = el("form"), head = el("div", "tm-quick-head"), title = el("h2", "", T("Новое сообщение", "New message"));
      title.id = "tm-new-title-" + states.size; dialog.setAttribute("aria-labelledby", title.id);
      const close = button("", "quiet tm-new-close", () => dialog.close()); close.setAttribute("aria-label", T("Закрыть", "Close")); close.append(hub.icon("close")); head.append(title, close);
      const search = el("input", "tm-new-search"), chosen = el("div", "tm-new-chosen"), results = el("div", "tm-new-results");
      search.type = "search"; search.placeholder = T("Имя или адрес", "Name or address"); search.maxLength = 80; search.autocomplete = "off"; search.setAttribute("aria-label", T("Кому", "To"));
      results.id = "tm-new-results-" + states.size; results.setAttribute("aria-live", "polite"); results.setAttribute("aria-relevant", "additions text");
      search.setAttribute("aria-controls", results.id);
      chosen.setAttribute("role", "group"); chosen.setAttribute("aria-label", T("Кому", "To"));
      const text = el("textarea", "tm-new-text"), subject = el("input", "tm-new-subject");
      text.value = s.text; text.rows = 5; text.maxLength = 30000; text.name = "message";
      subject.value = s.subject; subject.maxLength = 200; subject.name = "subject"; subject.autocomplete = "off";
      const row = (label, control) => { const r = el("label", "tm-new-field"); r.append(el("span", "", label), control); return r; };
      const to = el("div", "tm-new-to"); to.append(chosen,search,results);
      const toRow = el("div", "tm-new-field"); toRow.append(el("span", "", T("Кому", "To")), to);
      const subjectRow = row(T("Тема", "Subject"), subject), status = el("p", "tm-new-status"); status.setAttribute("role", "status");
      const pending = el("div", "tm-new-pending"), storage = el("p", "tm-new-storage"); storage.setAttribute("role", "status");
      const send = el("button", "btn primary tm-new-send", T("Отправить", "Send")); send.type = "submit";
      form.append(toRow,subjectRow,row(T("Сообщение", "Message"),text),status,pending,storage,send); dialog.append(head,form); document.body.append(dialog);
      s.ui = {dialog,search,chosen,results,text,subject,subjectRow,status,pending,storage,send};
      for (const [node, field] of [[text,"text"],[subject,"subject"]]) node.addEventListener("input", () => { s[field] = node.value; save(s); });
      search.addEventListener("input", () => {
        s.query = search.value; s.lookup = ""; s.items = []; s.errors = ""; s.looking = false; clearTimeout(s.timer); draw(s);
        if (s.query.trim().length >= 2) s.timer = setTimeout(() => lookup(s), 500);
      });
      search.addEventListener("keydown", e => { if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); lookup(s); } });
      form.addEventListener("submit", e => { e.preventDefault(); submit(s); });
      dialog.addEventListener("keydown", e => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); dialog.close(); } });
      dialog.addEventListener("close", () => { clearTimeout(s.timer); save(s); document.querySelector('.tm-new-trigger')?.focus(); });
    }
    draw(s); if (!s.ui.dialog.open) s.ui.dialog.showModal();
    (s.to ? s.ui.text : s.ui.search).focus();
  }
  function fact(d) {
    const s = state();
    if (d.kind === "contacts" && d.rid === s.lookup && d.q === s.query.trim()) {
      s.items = (Array.isArray(d.items) ? d.items : []).filter(contact).slice(0,60); s.looking = false;
      s.errors = Object.entries(d.errors || {}).map(([name,error]) => `${name}: ${error}`).join(" · "); draw(s);
    }
    if (!["sent","send_failed"].includes(d.kind) || !s.pending || d.rid !== s.pending.rid || d.to !== s.pending.to) return;
    if (d.kind === "send_failed" && d.unresolved === true) {
      clearTimeout(s.sendTimer); s.uncertain = true;
      s.status = d.error || T("Итог отправки неизвестен. Проверьте переписку.", "Delivery outcome is unknown. Check the conversation.");
      save(s); draw(s); return;
    }
    const p = s.pending, same = s.to?.to === p.to && s.text === p.text && (p.subject || "") === (s.to?.src === "email" ? s.subject : "");
    clearTimeout(s.sendTimer);
    s.pending = null; s.uncertain = false;
    s.status = d.kind === "sent" ? T("Отправлено", "Sent") : d.error || T("Не удалось отправить", "Delivery refused");
    if (d.kind === "sent" && !same) s.status = T("Исходное сообщение отправлено. Новый текст остаётся черновиком.", "The original message was sent. Your new text remains a draft.");
    if (d.kind === "sent" && same) { s.to = null; s.text = s.subject = ""; if (s.ui) { s.ui.text.value = ""; s.ui.subject.value = ""; s.ui.dialog.close(); } }
    save(s); draw(s);
  }
  window.addEventListener("hashchange", () => { for (const s of states.values()) s.ui?.dialog.close(); });
  return {open, fact};
}
