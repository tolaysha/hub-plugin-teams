import { readFileSync } from "fs";
import assert from "node:assert/strict";
// Подпись черновика (web/main.js: signed): только близким (коллектор пометил sign), посторонним — без подписи (Иван m398582).
// Запуск: node tests/signature.test.mjs web/main.js
const src = readFileSync(process.argv[2], "utf8");
const line = src.split("\n").find((l) => l.startsWith("const signed = "));
assert.ok(line, "web/main.js: const signed");
const signed = new Function("signature", line.replace("const signed = ", "return ") )("🤖 _Хаб, вычитано Иваном_");
assert.equal(signed("Привет", { sign: true }), "Привет\n\n🤖 _Хаб, вычитано Иваном_", "близкому — с подписью");
assert.equal(signed("Привет", { sign: false }), "Привет", "постороннему — без подписи");
assert.equal(signed("Привет", {}), "Привет", "нет признака — без подписи");
assert.equal(signed("Привет\n\n🤖 _Хаб, вычитано Иваном_", { sign: true }), "Привет\n\n🤖 _Хаб, вычитано Иваном_", "подпись не удваивается");
console.log("signature: ok");
