// List labels follow native When.ago; delivery sentences keep their full timestamps.
export function inboxAge(ts, lang='en', now=Date.now()) {
  if(typeof ts!=='number' || !Number.isFinite(ts) || ts<=0)return '';
  const date=new Date(ts*1000), current=new Date(now);
  if(!Number.isFinite(date.getTime()) || !Number.isFinite(current.getTime()))return '';
  const ru=lang==='ru', seconds=Math.max(0,(now-date.getTime())/1000);
  if(seconds<60)return ru?'сейчас':'now';
  const yesterday=new Date(current);yesterday.setDate(yesterday.getDate()-1);
  if(seconds>21600 && date.toDateString()===yesterday.toDateString())return ru?'Вчера':'Yesterday';
  if(seconds<3600)return `${Math.floor(seconds/60)} ${ru?'мин':'min'}`;
  if(seconds<86400)return `${Math.floor(seconds/3600)} ${ru?'ч':'h'}`;
  if(seconds<604800)return `${Math.floor(seconds/86400)} ${ru?'дн':'d'}`;
  const parts=new Intl.DateTimeFormat(ru?'ru-RU':'en-GB',{day:'numeric',month:'short',...(date.getFullYear()!==current.getFullYear()?{year:'numeric'}:{})}).formatToParts(date);
  return ['day','month','year'].map(type=>parts.find(p=>p.type===type)?.value).filter(Boolean).join(' ');
}
