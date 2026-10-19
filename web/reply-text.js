// Display only: delivery and recovery always retain the original string.
export function replyText(el, value, className = "tm-draft-text", tag = "div") {
  const raw=String(value || ""), body=el(tag,`${className} tm-rich-text`);
  const emphasis=[...raw.matchAll(/(?<![\p{L}\p{N}_])_([^_\n]+)_(?![\p{L}\p{N}_])/gu)]
    .map(m=>({start:m.index,end:m.index+m[0].length}));
  const links=[];
  const candidates=/(?<![\p{L}\p{N}])(?:https?:\/\/|mailto:|tel:)[^\s<>"'。，！？：；、؟،）】》」』]+|(?<![\w@])[-\w.+%]+@(?:[\w-]+\.)+[a-z]{2,}(?![a-z0-9@])/giu;
  for(const match of raw.matchAll(candidates)) {
    let start=match.index, end=start+match[0].length;
    // Only a recognized emphasis opener is markup. Unmatched or doubled
    // leading underscores can be real email-address characters.
    if(raw[start]==="_" && emphasis.some(e=>e.start===start))start++;
    // Drop sentence punctuation, unbalanced closing brackets, and an enclosing
    // emphasis delimiter. URL-internal underscores and balanced brackets stay.
    while(end>start) {
      const last=raw[end-1], text=raw.slice(start,end);
      if(/[.,;:!?…»]/u.test(last) || emphasis.some(e=>e.start<start && e.end===end)) {end--;continue;}
      const opening={")":"(","]":"[","}":"{"}[last];
      if(opening && [...text].filter(c=>c===last).length>[...text].filter(c=>c===opening).length) {end--;continue;}
      break;
    }
    const text=raw.slice(start,end);
    try {
      const url=new URL(/^(?:https?:|mailto:|tel:)/i.test(text) ? text : `mailto:${text}`);
      if(!["http:","https:","mailto:","tel:"].includes(url.protocol) || url.username || url.password || !url.pathname)continue;
      links.push({start,end,href:url.href});
    } catch { /* Unrecognized candidates remain literal text. */ }
  }
  const runs=emphasis.filter(e=>!links.some(l=>e.start>=l.start && e.start<l.end || e.end-1>=l.start && e.end-1<l.end));
  function append(parent,start,end) {
    let pos=start;
    for(const link of links) {
      if(link.start<start || link.end>end)continue;
      parent.append(raw.slice(pos,link.start));
      const a=el("a",null,raw.slice(link.start,link.end));
      a.href=link.href;a.target="_blank";a.rel="noopener noreferrer";
      parent.append(a);pos=link.end;
    }
    parent.append(raw.slice(pos,end));
  }
  let pos=0;
  for(const run of runs) {
    append(body,pos,run.start);
    const em=el("em");append(em,run.start+1,run.end-1);body.append(em);pos=run.end;
  }
  append(body,pos,raw.length);
  return body;
}
