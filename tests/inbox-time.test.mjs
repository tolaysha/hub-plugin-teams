import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const {inboxAge}=await import('data:text/javascript,'+encodeURIComponent(readFileSync('web/inbox-time.js','utf8')));
process.env.TZ='America/Argentina/Buenos_Aires';
const now=new Date('2026-10-17T11:17:00Z').getTime();
const ago=(seconds,lang='en')=>inboxAge(now/1000-seconds,lang,now);
for(const [seconds,en,ru] of [[0,'now','сейчас'],[59,'now','сейчас'],[60,'1 min','1 мин'],[3599,'59 min','59 мин'],[3600,'1 h','1 ч'],[21600,'6 h','6 ч'],[21601,'6 h','6 ч'],[86400,'Yesterday','Вчера'],[172800,'2 d','2 дн'],[604799,'6 d','6 дн']]) {
  assert.equal(ago(seconds),en,seconds);assert.equal(ago(seconds,'ru'),ru,seconds);
}
assert.equal(ago(-300),'now');
const early=Date.parse('2026-10-17T04:00:00-03:00');
assert.equal(inboxAge(early/1000-21600,'en',early),'6 h');
assert.equal(inboxAge(early/1000-21601,'en',early),'Yesterday');
assert.equal(ago(604800),'10 Oct');assert.equal(ago(604800,'ru'),'10 окт.');
assert.equal(inboxAge(new Date('2025-10-17T11:17:00Z').getTime()/1000,'en',now),'17 Oct 2025');
for(const ts of [null,undefined,NaN,Infinity,0,-1,'invalid'])assert.equal(inboxAge(ts,'en',now),'');
// Calendar yesterday uses local dates, not a 24-hour subtraction across DST.
process.env.TZ='America/New_York';
assert.equal(inboxAge(Date.parse('2026-11-01T03:30:00-05:00')/1000,'en',Date.parse('2026-11-02T00:15:00-05:00')),'Yesterday');
assert.equal(inboxAge(Date.parse('2026-03-08T00:30:00-05:00')/1000,'en',Date.parse('2026-03-09T00:15:00-04:00')),'Yesterday');
console.log('Inbox list ages match native boundaries, local calendar days, DST, years and missing dates');
