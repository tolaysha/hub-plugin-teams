// Provider receipts are distinct from the owner's local unread reminders.
export function providerReadState(hubName, storage = globalThis.localStorage) {
  const key = () => 'hub.inbox.provider-read.v1:' + hubName();
  const identity = m => JSON.stringify([m.id,m.target]);
  const supported = m => ['telegram','whatsapp','email'].includes(m?.src) && typeof m.target === 'string' && !!m.target;
  const cache=new Map(),limit=256*1024;
  function load() {
    const scope=key(),raw=storage.getItem(scope)||'[]',old=cache.get(scope);
    if(old?.raw===raw)return new Map(old.rows);
    const rows=JSON.parse(raw);
    if (!Array.isArray(rows) || rows.some(r=>!Array.isArray(r) || r.length!==2 || typeof r[0]!=='string' || !r[1] || typeof r[1].rid!=='string' || !['pending','read','failed','unknown'].includes(r[1].state))) throw Error('Invalid read history');
    cache.set(scope,{raw,rows});return new Map(rows);
  }
  function save(rows, admission=false) {
    let size=JSON.stringify([...rows]).length + (admission ? [...rows.values()].filter(r=>r.state==='pending').length*384 : 0);
    // Only settled success can be forgotten. Never evict an uncertain operation.
    if(admission)for(const [id,row] of rows) {
      if(size<=limit)break;
      if(row.state==='read') { size-=JSON.stringify([id,row]).length+1;rows.delete(id); }
    }
    if(size>limit)throw Error('Read history is full');
    storage.setItem(key(),JSON.stringify([...rows]));
  }
  return {
    supported,
    get(m) { try { return load().get(identity(m)) || null; } catch { return {state:'blocked',error:'Could not load read history. Your draft is retained.'}; } },
    begin(m,rid) {
      if(!supported(m))throw Error('Refresh this conversation before marking it read.');
      try {
        const rows=load(),old=rows.get(identity(m));
        if(old && old.state!=='pending')return null;
        // A transport acknowledgement cannot settle a provider operation. Replay only its original rid.
        const q={kind:'read',id:m.id,target:m.target,rid:old?.state==='pending' ? old.rid : rid};
        rows.set(identity(m),{rid:q.rid,state:'pending'});save(rows,true);return q;
      } catch { throw Error('Could not save the read request. No request was sent.'); }
    },
    accept(d) {
      if(!d.target || !d.id || !d.rid || !['read','read_failed'].includes(d.kind))return false;
      try {
        const rows=load(),id=identity(d),old=rows.get(id);
        if(!old || old.rid!==d.rid)return false;
        if(old.state==='read')return d.kind==='read';
        rows.set(id,d.kind==='read' ? {rid:d.rid,state:'read'} : {rid:d.rid,state:d.unresolved?'unknown':'failed',error:String(d.error||'Could not mark this conversation read.').slice(0,240)});
        save(rows);return true;
      } catch { return 'storage'; }
    }
  };
}
