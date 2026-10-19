// Collector-owned working hours. Calendar dates are resolved in the Hub zone;
// labels are formatted in the device zone. Never assume the browser is the Hub.
const minute = value => {
  const m=typeof value==='string' && /^(\d{1,2}):(\d{2})$/.exec(value.trim());
  if(!m || +m[2]>59)return null;
  const n=+m[1]*60 + +m[2];return n<=1440 ? n : null;
};
const civil = p => Date.UTC(p.year,p.month-1,p.day,p.hour||0,p.minute||0);
export function workingHours(config) {
  if(!config || typeof config!=='object')return null;
  const start=minute(config.from),end=minute(config.to);
  if(start===null || end===null || start>=end)return null;
  let format=null,offset=null;
  if(typeof config.tz==='string' && config.tz)try {
    format=new Intl.DateTimeFormat('en-GB-u-ca-iso8601-nu-latn',{timeZone:config.tz,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'});
    format.format(0);
  } catch { format=null; }
  if(!format) {
    if(typeof config.utc!=='number' || !Number.isInteger(config.utc) || Math.abs(config.utc)>14*60)return null;
    offset=config.utc*60000;
  }
  const exceptions=new Set((Array.isArray(config.except) ? config.except : []).filter(e=>typeof e?.contact==='string').map(e=>e.contact));
  return {start,end,weekends:config.weekends===true,exceptions,format,offset};
}
function parts(rule,ms) {
  if(rule.format)return Object.fromEntries(rule.format.formatToParts(new Date(ms)).filter(p=>p.type!=='literal').map(p=>[p.type,Number(p.value)]));
  const d=new Date(ms+rule.offset);
  return {year:d.getUTCFullYear(),month:d.getUTCMonth()+1,day:d.getUTCDate(),hour:d.getUTCHours(),minute:d.getUTCMinutes()};
}
function resolve(rule,wall,after) {
  if(!rule.format)return wall-rule.offset>after ? wall-rule.offset : null;
  // Enumerate the offsets on both sides of a transition. This resolves an
  // overlap to its first future occurrence and a gap forward by its duration.
  const offsets=new Set();
  for(const h of [-36,-24,-12,0,12,24,36]) {
    const probe=wall+h*3600000;offsets.add(civil(parts(rule,probe))-probe);
  }
  const candidates=[...offsets].map(offset=>({at:wall-offset,delta:civil(parts(rule,wall-offset))-wall})).filter(x=>x.at>after);
  const exact=candidates.filter(x=>x.delta===0).sort((a,b)=>a.at-b.at);
  if(exact.length)return exact[0].at;
  // If a real occurrence existed but is past, do not reinterpret it as a gap.
  if([...offsets].some(offset=>civil(parts(rule,wall-offset))===wall))return null;
  return candidates.filter(x=>x.delta>0 && x.delta<=86400000).sort((a,b)=>a.delta-b.delta || a.at-b.at)[0]?.at ?? null;
}
export function nextWorkingStart(rule,contact,now=new Date()) {
  const after=now.getTime();if(!rule || !Number.isFinite(after))return null;
  const p=parts(rule,after),today=Date.UTC(p.year,p.month-1,p.day);
  const weekends=rule.weekends!==rule.exceptions.has(contact);
  const allowed=wall=>weekends || ![0,6].includes(new Date(wall).getUTCDay());
  for(let day=0;day<9;day++) {
    const date=today+day*86400000;
    if(!allowed(date) || day===0 && p.hour*60+p.minute>=rule.start)continue;
    const at=resolve(rule,date+rule.start*60000,after);
    if(at!==null && allowed(civil(parts(rule,at))))return new Date(at);
  }
  return null;
}
export function workingStartLabel(at,now=new Date(),timeZone) {
  const fmt=options=>new Intl.DateTimeFormat('en-GB',{...options,...(timeZone ? {timeZone} : {})});
  const date=fmt({year:'numeric',month:'2-digit',day:'2-digit'});
  const p=d=>Object.fromEntries(date.formatToParts(d).filter(x=>x.type!=='literal').map(x=>[x.type,Number(x.value)]));
  const day=(civil(p(at))-civil(p(now)))/86400000;
  const name=day===0 ? 'today' : day===1 ? 'tomorrow' : fmt({weekday:'long'}).format(at);
  return 'Send '+name+' at '+fmt({hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(at);
}

// A settings acknowledgement is not a receipt. Keep the original request until
// the collector settles it, including after reload or a lost HTTP response.
export function recipientWeekendState(hubName,storage=globalThis.localStorage) {
  // The setting belongs to a contact, even when its newest inbound message or
  // target changes. Only the persisted original payload is ever replayed.
  const key=m=>'hub.inbox.weekend.v1:'+JSON.stringify([hubName(),m.contact]);
  function load(m) {
    const raw=storage.getItem(key(m));if(!raw)return null;
    const r=JSON.parse(raw),q=r?.q;
    if(!['pending','ok','failed','unknown'].includes(r?.state) || q?.kind!=='hours_for' || typeof q.rid!=='string' || !q.rid || typeof q.id!=='string' || !q.id || q.contact!==m.contact || typeof q.target!=='string' || !q.target || typeof q.weekends!=='boolean')throw Error('Invalid weekend request');
    return r;
  }
  return {
    get(m) {try{return load(m);}catch{return {state:'blocked',error:'Weekend change history is unreadable. No new change was sent.'};}},
    begin(m,on,rid) {
      if(!m?.contact || !m?.target || !m?.id || typeof on!=='boolean')throw Error('Reopen this conversation before changing weekends.');
      try {
        const old=load(m);
        if(['pending','unknown'].includes(old?.state))return old.q;
        const q={kind:'hours_for',id:m.id,contact:m.contact,target:m.target,rid,weekends:on};
        storage.setItem(key(m),JSON.stringify({q,state:'pending'}));return q;
      } catch {throw Error('Could not save the weekend change. No change was sent.');}
    },
    accept(d) {
      // Call only for trusted collector facts; the receipt never rewrites config.
      if(!d?.contact || !['hours_set','hours_failed'].includes(d?.kind))return false;
      try {
        const old=load(d),q=old?.q;
        if(!['pending','unknown'].includes(old?.state) || ['id','contact','target','rid'].some(k=>!q[k] || q[k]!==d[k]))return false;
        if(d.kind==='hours_set' && (d.requested!==q.weekends || typeof d.weekends!=='boolean'))return false;
        storage.setItem(key(d),JSON.stringify({...old,state:d.kind==='hours_set'?'ok':d.unresolved?'unknown':'failed',actual:d.weekends,error:String(d.error||'Weekend change was refused.').slice(0,240)}));return true;
      } catch {return 'storage';}
    }
  };
}
