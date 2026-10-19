// Collector protocol v1. No transport or trusted-author inference lives here.
const valid = (t) => t?.v === 1 && typeof t.version === "string" && Number.isInteger(t.edit_version);
const same = (a, b) => valid(a) && valid(b) && a.version === b.version && a.edit_version === b.edit_version;
export function boundedRequest(q) {
  if (JSON.stringify(q).length > 1900) throw Error("Shorten the instruction or reply before sending.");
  return q;
}
export class InboxEditor {
  constructor(message, editor, text = "") {
    this.id = message.id; this.post = message.post; this.editor = editor;
    this.token = message.inbox; this.text = text; this.instruction = "";
    this.revision = 0; this.control = null; this.request = null; this.proposal = null;
    this.delivery = null; this.error = ""; this.needsHold = false; this.changed = false;
  }
  edit(text) { this.text = text; this.revision++; }
  direct(text) { this.instruction = text; this.revision++; }
  observe(message) {
    if (message.post !== this.post || valid(message.inbox) && valid(this.token) && message.inbox.version !== this.token.version) {
      this.changed = true;
      this.error = "The conversation changed. Review the current message before continuing.";
    }
  }
  hold(rid, token = this.token, action = "hold") {
    if (this.changed) throw Error("The conversation changed. Review the current message before continuing.");
    if (this.control || this.delivery) throw Error("Wait for the current request to be confirmed.");
    if (!valid(token)) throw Error("The current conversation is unavailable. Refresh Inbox.");
    if (valid(this.token) && (token.version !== this.token.version || token.edit_version < this.token.edit_version))
      throw Error("The editor changed. Reopen the current conversation.");
    const q = boundedRequest({ kind: "draft_control", id: this.id, rid, inbox: token, editor: this.editor, action });
    this.control = { rid, token, action }; this.error = "";
    return q;
  }
  ready() {
    if (this.changed) throw Error("The conversation changed. Review the current message before continuing.");
    if (this.error) throw Error(this.error);
    if (this.control || this.delivery) throw Error("Wait for the current request to be confirmed.");
    if (this.needsHold || !valid(this.token) || !this.token.held || this.token.holder !== this.editor)
      throw Error("Confirm this editor before continuing.");
  }
  revise(rid) {
    this.ready();
    if (!this.instruction.trim()) throw Error("Enter your private draft instruction.");
    const q = boundedRequest({ kind: "ask", what: "draft", id: this.id, post: this.post, rid, inbox: this.token,
      editor: this.editor, instruction: this.instruction, draft: this.text });
    this.proposal = null;
    this.request = { rid, revision: this.revision, token: this.token };
    this.control = { rid, token: this.token, action: "hold", revision: true };
    return q;
  }
  send(rid, text, {at, target} = {}) {
    this.ready();
    if (!text.trim()) throw Error("Write your reply first.");
    const q = boundedRequest({ kind: "send", id: this.id, rid, inbox: this.token, editor: this.editor, text, ...(at ? {at} : {}), ...(target ? {target} : {}) });
    this.delivery = { rid, token: this.token, text, target, state: "queued" };
    return q;
  }
  // Called only for collector-authored facts by the feed adapter.
  receive(d) {
    if (d.id && d.id !== this.id) return false;
    if (d.kind === "draft_state" && this.control?.rid === d.rid) {
      const c = this.control, t = d.inbox;
      if (this.changed || !valid(t) || t.version !== c.token.version || t.edit_version <= c.token.edit_version
          || valid(this.token) && (t.version !== this.token.version || t.edit_version <= this.token.edit_version)
          || t.held !== (c.action === "hold") || (t.held && t.holder !== this.editor)) {
        this.error = "The editor confirmation does not match this conversation."; return false;
      }
      this.token = t; this.control = null; this.error = ""; this.needsHold = false; return true;
    }
    if (["draft_control_failed", "ask_failed", "revision_rejected"].includes(d.kind)
        && (this.control?.rid === d.rid || this.request?.rid === d.rid)) {
      this.control = null; this.error = d.error || "The current request was refused."; return true;
    }
    if (d.kind === "draft_proposal" && this.request?.rid === d.rid && d.post === this.post
        && d.editor === this.editor && d.requires_apply === true && same(d.inbox, this.token)
        && [d.text, d.context, d.next_action].every((x) => typeof x === "string")) {
      this.proposal = { ...d, revision: this.request.revision }; return true;
    }
    if (!this.delivery || this.delivery.rid !== d.rid) return false;
    if (this.delivery.target && d.target !== this.delivery.target) return false;
    if (this.delivery.state === "sent") return false;
    if (d.kind === "send_duplicate" && d.version === this.delivery.token.version && d.state === "sent" && d.receipt?.id) {
      this.delivery.state = "sent"; this.text = ""; this.error = ""; return true;
    }
    if (d.kind === "sent" && same(d.submitted_inbox, this.delivery.token) && d.receipt?.id) {
      this.delivery.state = "sent"; this.text = ""; this.token = d.inbox; this.error = ""; return true;
    }
    if (["send_blocked", "send_failed"].includes(d.kind) && !d.unresolved) {
      this.delivery = null; this.needsHold = true;
      this.error = d.error || "The reply was not sent."; return true;
    }
    if (["send_uncertain", "send_duplicate", "scheduled"].includes(d.kind) || d.kind==="send_failed" && d.unresolved) {
      this.delivery.state = d.kind === "scheduled" ? "scheduled" : "unresolved";
      this.error = d.error || "Delivery is awaiting confirmation. The draft is retained."; return true;
    }
    return false;
  }
  apply() {
    this.ready();
    if (!this.proposal || this.proposal.revision !== this.revision || !same(this.proposal.inbox, this.token))
      throw Error("Your reply or instruction changed. Revise the draft again.");
    this.text = this.proposal.text; this.revision++;
    const applied = this.proposal; this.proposal = null; return applied;
  }
}
