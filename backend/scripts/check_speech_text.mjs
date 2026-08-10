/* Regression test for the spoken-text normaliser in backend/static/speech.js.
 *
 * These are the exact strings the engine emits, so a change that reintroduces
 * "二零二六杠零八杠零九 一四比零零" fails the build rather than the demo.
 *
 *   node backend/scripts/check_speech_text.mjs
 */

import { pathToFileURL } from 'node:url';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const speechPath = resolve(here, '../static/speech.js');
const { speakableText, splitClauses } = await import(pathToFileURL(speechPath).href);

const today = new Date('2026-08-08T00:00:00Z');

const cases = [
  ['2026-08-09 14:00', '八月九日下午两点'],
  ['2026-08-09 09:00', '八月九日上午九点'],
  ['2026-08-09 09:30', '八月九日上午九点半'],
  ['2025-12-31 23:45', '二零二五年十二月三十一日晚上十一点四十五分'],
  ['2026-07-30', '七月三十日'],
  ['2026-07', '二零二六年七月'],
  ['12:00', '中午十二点'],
  ['00:15', '凌晨十二点十五分'],
  ['126.50元', '一百二十六块五毛'],
  ['68.00元', '六十八块'],
  ['56.80元', '五十六块八毛'],
  // 有意修改：这一条原先期望「五块五分」，而那是把缺陷本身钉住了。
  //
  // 角为 0、分不为 0 时省掉"零"，听者会解析成"五块五"= 5.50 元。它恰好落在复述确认
  // 链上：后端让老人把金额说一遍，她重复她听到的，于是 teach_back 判 mismatch，
  // 应用再告诉她"您说的是 5.5 元，账单是 5.05 元"——把自己说错的账算在她头上。
  // 零在中文数字里是位缺失的标记，不能省。
  ['5.05元', '五块零五分'],
  ['100元', '一百块'],
  // 千位以上不退回裸数字。1200.00元 曾念成"1200块"，而 7 位以上会被"号码逐位念"
  // 那条规则接手：1000000.00元 变成"一零零零零零零块"。
  ['1200.00元', '一千二百块'],
  ['1005.00元', '一千零五块'],
  ['1000000.00元', '一百万块'],
  // 负号不能丢：退款、冲正、余额为负都会走到这里，老人听到的不能是一个正数。
  ['-68.40元', '负六十八块四毛'],
  // 不足一块就不说"零块"：中文里 0.50 元就是"五毛"。
  ['0.50元', '五毛'],
  // Whole messages the engine really produces.
  [
    '请确认：预约2026-08-09 14:00，第一医院骨科王医生。',
    '请确认：预约八月九日下午两点，第一医院骨科王医生。',
  ],
  [
    '查到2026-07的电费是126.50元，截止日期是2026-07-30。',
    '查到二零二六年七月的电费是一百二十六块五毛，截止日期是七月三十日。',
  ],
  // Care-voice answers (care_voice.py). Bare HH:MM dose times and the
  // orientation reply must not reach the synthesiser as digits.
  [
    '今天还没有服药记录。按计划要吃3次，时间是08:00、12:00、20:00。',
    '今天还没有服药记录。按计划要吃3次，时间是上午八点、中午十二点、晚上八点。',
  ],
  [
    '今天是8月8日，星期六，现在09:05。',
    '今天是8月8日，星期六，现在上午九点五分。',
  ],
  [
    '接下来有1件事：明天09:00复诊。',
    '接下来有1件事：明天上午九点复诊。',
  ],
  // Phone-shaped values must be read digit by digit, not as a cardinal.
  ['尾号1111', '尾号一一一一'],
  ['号码尾号8899。', '号码尾号八八九九。'],
  ['13900001111', '一三九零零零零一一一一'],
  // A quantity of the same magnitude is NOT a digit run: 148 is a blood
  // pressure and "一百四十八" is the correct reading, so it stays untouched.
  ['收缩压148', '收缩压148'],
  ['还能吃大约30天', '还能吃大约30天'],
  // Units a synthesiser spells out letter by letter or skips.
  ['血压148mmHg', '血压148毫米汞柱'],
  ['体温36.5℃', '体温36.5摄氏度'],
  ['依从率80%', '依从率百分之80'],
  // Decorative pairs are dropped from the spoken copy only.
  ['请确认：在提醒您“复诊”。', '请确认：在提醒您复诊。'],
  ['李慧（女儿）的号码', '李慧女儿的号码'],
  // An ellipsis is a beat, not dots.
  ['我在听……您慢慢说', '我在听，您慢慢说'],
];

let failed = 0;
for (const [input, expected] of cases) {
  const actual = speakableText(input, today);
  if (actual !== expected) {
    failed += 1;
    console.error(`FAIL  ${input}\n  期望 ${expected}\n  实际 ${actual}`);
  }
}

// A machine-formatted value must never survive into speech.
const leftovers = cases
  .map(([input]) => speakableText(input, today))
  .filter(text => /\d{4}-\d{2}|\d{1,2}:\d{2}|\d+\.\d+\s*元/.test(text));
if (leftovers.length) {
  failed += leftovers.length;
  console.error(`FAIL  仍有未转换的机器格式：${leftovers.join(' | ')}`);
}

// Long sentences must break into clauses so delivery is not one flat run.
const clauses = splitClauses(speakableText(cases.at(-1)[0], today));
if (clauses.length < 2) {
  failed += 1;
  console.error(`FAIL  长句未分句：${JSON.stringify(clauses)}`);
}

if (failed) {
  console.error(`\nFAIL speech_text_v6: ${failed} 项`);
  process.exit(1);
}
console.log(`PASS speech_text_v6: ${cases.length} 项朗读文本断言通过`);
