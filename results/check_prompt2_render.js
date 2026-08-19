/* Render the calendar panel from a live response and assert the prompt2 clauses reach the SCREEN.
 *
 * WHY THIS EXISTS. On the previous round the new evidence was verified in the API response, the card
 * panels silently filtered it out, and the page never changed -- the user found it, not a test. A
 * check that greps rendered HTML is the only one that answers "does the reader actually see it".
 *
 * The assertions are CONDITIONAL on the payload, because clause F is conditional by design:
 *   in-week holidays present   -> an in-week table, and NO "no holiday occurs directly" sentence
 *   in-week holidays absent    -> "Holidays in this week: None." AND that sentence
 *   adjacent holidays present  -> an adjacent table
 * An unconditional check failed on both queues for opposite reasons, which is how this shape was
 * arrived at.
 *
 *   node results/check_prompt2_render.js <response.json> [more.json ...]
 */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.dirname(__dirname);
const files = process.argv.slice(2).filter(f => fs.existsSync(f));
if (!files.length) {
  console.log('  SKIP  no response json given; pass one or more live-response files');
  process.exit(0);
}

const html = fs.readFileSync(path.join(ROOT, 'rca_console.html'), 'utf8');
const blocks = [...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const sandbox = {
  console, document: { getElementById: () => null, querySelector: () => null,
                       querySelectorAll: () => [], createElement: () => ({ style: {} }) },
  location: { protocol: 'file:' }, navigator: { userAgent: 'node' },
  localStorage: { getItem: () => null, setItem: () => {} },
  setTimeout, clearTimeout, alert: () => {}, fetch: () => Promise.reject(new Error('no net')),
};
sandbox.window = sandbox; sandbox.globalThis = sandbox; sandbox.self = sandbox;
vm.createContext(sandbox);
for (let i = 0; i < blocks.length; i++) {
  try { vm.runInContext(blocks[i], sandbox, { filename: `block${i}.js` }); } catch (e) {}
}
if (typeof sandbox.cardCalendarPanel !== 'function') {
  console.error('  FAIL  cardCalendarPanel is not in scope'); process.exit(1);
}

let failures = 0;
for (const f of files) {
  const resp = JSON.parse(fs.readFileSync(f, 'utf8'));
  const sections = (resp.decision_card || {}).sections || {};
  const cal = sections['14_calendar_context'] || {};
  const iw = cal.holidays_in_target_week || {};
  const ad = cal.recent_holidays_affecting_target_week || {};
  const text = (sandbox.cardCalendarPanel(sections) || '')
    .replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();

  const q = ((resp.queue || {}).Forecast_name) || path.basename(f);
  console.log(`\n  ${q}   in-week=${iw.count} adjacent=${ad.count}  (${text.length} chars rendered)`);

  const checks = [
    // Always required.
    ['F  in-week statement present',        () => /Holidays in this week:/.test(text)],
    ['F  adjacent statement present',       () => /Recent holidays potentially affecting this week/.test(text)],
    ['D  weekday column shown',             () => /Weekday/.test(text)],
    ['E  raw source names kept for audit',  () => /Source name\(s\)/.test(text)],
    ['C  three weekend states tabled',      () => /Weekend question/.test(text)],
    ['C  daily-demand row present',         () => /Daily weekend demand effect/.test(text)],
    ['C  weekly-structure row present',     () => /Weekly calendar structure/.test(text)],
    ['K  weekday outcomes tabled',          () => /Weekly outcome by the weekday/.test(text)],
    ['A  the limitation is still stated',   () => /cannot be isolated from fiscal-week totals/.test(text)],
    // Conditional on the payload -- clause F is conditional by design.
    [(iw.count > 0 ? 'F  in-week table shown (holidays present)'
                   : 'F  in-week reads None (no holidays)'),
     () => (iw.count > 0 ? /In this fiscal week/.test(text)
                         : /Holidays in this week: None\./.test(text))],
    [(iw.count > 0 ? 'F  "no holiday directly" sentence ABSENT'
                   : 'F  "no holiday directly" sentence PRESENT'),
     () => (iw.count > 0 ? !/No holiday occurs directly in this fiscal week/.test(text)
                         : /No holiday occurs directly in this fiscal week/.test(text))],
    [(ad.count > 0 ? 'F  adjacent table shown' : 'F  adjacent reads none'),
     () => (ad.count > 0 ? /impact window reaches it/.test(text)
                         : /affecting this week: none/i.test(text))],
    // Prohibitions.
    ['F  adjacent holidays NOT listed as in-week',
     () => !new RegExp('Holidays in this week: (?!None)' +
                       ((ad.canonical_names || [])[0] || '\\u0000').slice(0, 12)).test(text)],
    ['no "undefined" rendered',            () => !/undefined/.test(text)],
  ];

  for (const [label, fn] of checks) {
    let ok = false;
    try { ok = !!fn(); } catch (e) { ok = false; }
    if (!ok) failures++;
    console.log('    ' + (ok ? 'PASS ' : 'FAIL ') + label);
  }
  const m = text.match(/Holidays in this week:[^.]*\./);
  if (m) console.log('    -> ' + m[0]);
}

console.log('\n  ' + (failures === 0
  ? 'all prompt2 render checks passed over ' + files.length + ' response(s)'
  : failures + ' prompt2 render check(s) FAILED'));
process.exit(failures === 0 ? 0 : 1);
