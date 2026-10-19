// Browser preferences only; provider read state and message delivery are separate.
export function conversationPins(scope, storage) {
  const normalize = id => {
    try { const value = JSON.parse(id); if (Array.isArray(value) && value.length===2 && ['dm','mention','channel'].includes(value[0])) return JSON.stringify(['teams',value[1]]); } catch {}
    return id;
  };
  const cache = new Map(), snapshots = new Map();
  const store = () => storage ?? globalThis.localStorage;
  const key = () => 'hub.inbox.pinned.v1:' + scope();
  function current(strict = false) {
    const name = key();
    try {
      const raw = store().getItem(name) || '[]';
      if (!cache.has(name) || snapshots.get(name) !== raw) {
        const value = JSON.parse(raw);
        if (!Array.isArray(value) || value.some(v => typeof v !== 'string')) throw Error('Invalid pins');
        cache.set(name, new Set(value.map(normalize)));
        snapshots.set(name, raw);
      }
    } catch { if (strict) return null; /* Keep the last readable session state. */ }
    if (!cache.has(name)) cache.set(name, new Set());
    return cache.get(name);
  }
  return {
    has(id) { return current().has(id); },
    toggle(id) {
      const previous = current(true);
      if (!previous) return false;
      const next = new Set(previous);
      next.has(id) ? next.delete(id) : next.add(id);
      try { const raw = JSON.stringify([...next]); store().setItem(key(), raw); snapshots.set(key(), raw); } catch { return false; }
      cache.set(key(), next);
      return true;
    },
  };
}
