import { readFileSync } from "fs";
// Черновик хаба (web/main.js: splitDraft): текст отдельно, заметка «Почему» отдельно — в правку и отправку идёт
// только текст. Запуск: node tests/draft.test.mjs web/main.js
const src = readFileSync(process.argv[2], "utf8");
const a = src.indexOf("export function splitDraft"), b = src.indexOf("\n}\n", a) + 2;
const splitDraft = new Function(src.slice(a, b).replace("export function", "function") + "; return splitDraft;")();
const cases = [
  ["Привет, посмотрю завтра.\n---\nПочему: просит глянуть MR, срочности нет", "Привет, посмотрю завтра.", "просит глянуть MR, срочности нет"],
  ["Просто текст", "Просто текст", ""],
  ["Строка\n---\nещё строка\n---\nWhy: because", "Строка\n---\nещё строка", "because"],
  ["Текст\n\n ---  \n\nпочему: так", "Текст", "так"],
  ["👍\n---\nПочему: хватит реакции", "👍", "хватит реакции"],
  ["a --- b", "a --- b", ""],
  ["Perfecto, confirmo mañana.\n---\nContext: The sender asks for tomorrow; acceptance is not confirmed.\nNext action: Review this draft and approve Send.",
   "Perfecto, confirmo mañana.", "Context: The sender asks for tomorrow; acceptance is not confirmed.\nNext action: Review this draft and approve Send."],
  ["---\nContext: The original recipient cannot be verified.\nNext action: Verify the source before preparing a reply.",
   "", "Context: The original recipient cannot be verified.\nNext action: Verify the source before preparing a reply."],
  ["\n---\nContext: Source history is unavailable; the promised date is unknown.\nNext action: Read the verified thread before committing to a date.",
   "", "Context: Source history is unavailable; the promised date is unknown.\nNext action: Read the verified thread before committing to a date."],
];
const whyLine = new Function(src.slice(src.indexOf("const WHY_LABEL"), src.indexOf("\n}\n", src.indexOf("export function whyLine")) + 2).replace("export function", "function") + "; return whyLine;")();
const whys = [
  ["Context: Алекс ждёт согласия на отдельный модуль.\nNext action: подтверди этот вариант.", "Алекс ждёт согласия на отдельный модуль. Подтверди этот вариант."],
  ["Контекст: Алекс ждёт согласия на отдельный модуль.\nСледующий шаг: Подтверди этот вариант.", "Алекс ждёт согласия на отдельный модуль. Подтверди этот вариант."],
  ["Почему: Алекс ждёт согласия; так и планировали.", "Алекс ждёт согласия; так и планировали."],
  ["Context: The sender asks for tomorrow; acceptance is not confirmed.\n\nNext action: Review this draft and approve Send", "The sender asks for tomorrow; acceptance is not confirmed. Review this draft and approve Send"],
  ["Просто фраза без метки", "Просто фраза без метки"],
  ["", ""],
];
let fail = 0;
for (const [input, want] of whys) {
  const got = whyLine(input);
  if (got !== want) { fail++; console.log("FAIL whyLine", JSON.stringify(input), JSON.stringify(got)); }
}
for (const [input, text, why] of cases) {
  const r = splitDraft(input);
  if (r.text !== text || r.why !== why) { fail++; console.log("FAIL", JSON.stringify(input), r); }
}
console.log(fail ? `FAIL ${fail}` : "ALL OK");
process.exitCode = fail ? 1 : 0;
