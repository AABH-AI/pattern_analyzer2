/*
 * Execute the console's REAL renderer against REAL captured responses.
 * =====================================================================
 *
 *   node results/check_ui_render.js
 *
 * WHY THIS EXISTS
 * ---------------
 * `rca_console.html` has no build step and no test framework, so a front-end mistake is only found
 * by opening the page. One did reach the user: the decision-layer panels called `secDesc()`, which
 * was a `const` declared INSIDE `renderInvestigationReport`, so the top-level panel functions could
 * not see it. The ReferenceError replaced the entire report with "Could not render this report".
 *
 * A grep cannot catch that -- the identifier exists, just not in the right scope. Calling the
 * renderer can. This script loads every <script> block from the page into a minimal DOM stub, then
 * runs formatInvestigation() + renderInvestigationReport() over the captured live API responses in
 * results/live-validation-*.json and asserts that each expected panel is present in the output.
 *
 * It is deliberately NOT a browser: nothing here proves how the page looks. It proves the renderer
 * executes and emits the panels, which is the failure mode that actually took the report down.
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(ROOT, 'rca_console.html'), 'utf8');
const scripts = [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)].map(m => m[1]);

/* A DOM stub with enough surface for the file to LOAD. Handlers are never fired. */
const el = () => ({
  style: {}, dataset: {}, children: [],
  classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
  addEventListener() {}, removeEventListener() {}, appendChild() {}, remove() {},
  setAttribute() {}, getAttribute() { return null; }, removeAttribute() {},
  querySelector() { return el(); }, querySelectorAll() { return []; },
  insertAdjacentHTML() {}, focus() {}, blur() {}, click() {}, scrollIntoView() {},
  get innerHTML() { return ''; }, set innerHTML(v) {},
  get textContent() { return ''; }, set textContent(v) {},
  get value() { return ''; }, set value(v) {},
});
const sandbox = {
  console,
  document: {
    getElementById() { return el(); }, querySelector() { return el(); },
    querySelectorAll() { return []; }, createElement() { return el(); },
    addEventListener() {}, removeEventListener() {},
    body: el(), documentElement: el(), readyState: 'complete', title: '',
  },
  navigator: { userAgent: 'node', clipboard: { writeText() { return Promise.resolve(); } } },
  location: { href: '', search: '', hash: '' },
  localStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
  sessionStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
  fetch: () => Promise.reject(new Error('no network in this check')),
  setTimeout, clearTimeout, setInterval, clearInterval,
  requestAnimationFrame: (f) => (f && 0),
  addEventListener() {}, removeEventListener() {},
  alert() {}, confirm() { return false; }, prompt() { return null; },
  matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
  URL, Blob: class {}, Intl,
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
sandbox.self = sandbox;
vm.createContext(sandbox);

let failures = 0;
let loaded = 0;
for (const [i, src] of scripts.entries()) {
  try { vm.runInContext(src, sandbox, { filename: `rca_console.block${i}.js` }); loaded++; }
  catch (e) { failures++; console.log(`  FAIL  script block ${i} threw on load: ${e.message}`); }
}
console.log(`  ${loaded === scripts.length ? 'PASS' : 'FAIL'}  all ${scripts.length} script block(s) load`);

/* Every function EITHER report path needs must be reachable at top level.
 *
 * The Decision Card panels are listed here for the same reason `secDesc` is: they are top-level
 * functions called from inside renderDecisionCard, and one of them being out of scope would replace
 * the entire card with an error box. Asserting they are callable is the cheap half of the check;
 * actually running them over real responses, below, is the half that catches a bad property read.
 */
const REQUIRED = ['formatInvestigation', 'renderInvestigationReport', 'invEsc',
  'renderDecisionCard', 'renderSpecStatus',
  'cardWhyPanel', 'cardCriticalityPanel', 'cardForecastResponsePanel', 'cardCalendarPanel',
  'cardDriverPanel', 'cardEvidenceIndexPanel', 'cardSecDesc', 'cardTitle', 'cardPct', 'cardNum'];

/* Panels belonging to the WFM engine upgrade, which lives on the `test` branch. This branch is the
 * FC Decision Card upgrade and deliberately carries NO WFM changes (section 1 of the brief), so
 * their absence here is correct and must not fail the run. They are reported so that running this
 * guard on a branch that HAS them still checks them. */
const WFM_UPGRADE_ONLY = ['secDesc', 'rcaRootCausePanel', 'rcaConfidenceCriticalityPanel',
  'rcaWhyPanel', 'rcaEvidenceTablePanel', 'rcaForecastResponsePanel', 'rcaDriverEvidencePanel',
  'rcaActionPanel'];

for (const fn of REQUIRED) {
  const ok = typeof sandbox[fn] === 'function';
  if (!ok) failures++;
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${fn} is callable at top level`);
}
const wfmPresent = WFM_UPGRADE_ONLY.filter(fn => typeof sandbox[fn] === 'function');
if (wfmPresent.length === WFM_UPGRADE_ONLY.length) {
  console.log(`  PASS  all ${WFM_UPGRADE_ONLY.length} WFM-upgrade panels callable at top level`);
} else if (wfmPresent.length === 0) {
  console.log(`  n/a   WFM-upgrade panels absent — correct for the FC-only branch`);
} else {
  failures++;
  console.log(`  FAIL  WFM-upgrade panels only PARTLY present (${wfmPresent.join(', ')}) — a partial `
    + `port is the scope error that caused "secDesc is not defined"`);
}

/* Render every captured live response. */
const captures = fs.readdirSync(path.join(ROOT, 'results'))
  .filter(f => /^live-validation-.*\.json$/.test(f));
if (!captures.length) {
  console.log('  SKIP  no results/live-validation-*.json captures found');
}
const PANELS = {
  'Root Cause': (o) => o.includes('>Root Cause<'),
  // the heading is authored as "Confidence &amp; Criticality", so match either form
  'Confidence & Criticality': (o) => /Confidence &(?:amp;)? Criticality/.test(o),
  'Why This Happened': (o) => o.includes('Why This Happened'),
  'Statistical Evidence': (o) => o.includes('Statistical Evidence'),
  'Forecast Response Diagnostic': (o) => o.includes('Forecast Response Diagnostic'),
  'WFM Action': (o) => o.includes('WFM Action'),
};
let cases = 0;
for (const file of captures) {
  const live = JSON.parse(fs.readFileSync(path.join(ROOT, 'results', file), 'utf8'));
  for (const [key, resp] of Object.entries(live)) {
    // A deterministic-fallback capture has no decision panels to render; skip those rather than
    // assert panels that legitimately are not there.
    if (!resp.root_cause_sentence) continue;
    cases++;
    try {
      const f = sandbox.formatInvestigation(resp, {});
      const out = sandbox.renderInvestigationReport(f, { target: { fields: {} } });
      const bad = Object.entries(PANELS).filter(([, test]) => !test(out)).map(([n]) => n);
      if (out.includes('>undefined<')) bad.push('a literal "undefined" reached the markup');
      if (bad.length) {
        failures++;
        console.log(`  FAIL  ${file} :: ${key} -> missing: ${bad.join(', ')}`);
      } else {
        console.log(`  PASS  ${file} :: ${key} (${out.length.toLocaleString()} chars)`);
      }
    } catch (e) {
      failures++;
      console.log(`  FAIL  ${file} :: ${key} -> renderer threw ${e.constructor.name}: ${e.message}`);
    }
  }
}
/* ---- The FC Decision Card (?mode=spec) ----------------------------------------------------
 * Same principle, different renderer. These captures come from the offline rig
 * (results/_offline_cache/spec-offline-results.json) and from any live spec capture, and they are
 * put through the REAL renderDecisionCard.
 *
 * The panel list below is the acceptance criteria from section 39 expressed as assertions: a card
 * that renders but silently drops Criticality or Forecast Response has not met the brief, and only
 * running it can tell.
 */
const CARD_PANELS = {
  'Executive Decision Card': (o) => o.includes('Executive Decision Card'),
  'Root Cause': (o) => o.includes('>Root Cause<'),
  'Why This Happened': (o) => o.includes('Why This Happened'),
  'Confidence (never collapsed)': (o) => /Confidence/.test(o),
  'Criticality': (o) => o.includes('Criticality'),
  'Evidence': (o) => o.includes('>Evidence<'),
  'Forecast Response': (o) => o.includes('Forecast Response'),
  'Calendar Context': (o) => o.includes('Calendar Context'),
  'Driver Evidence': (o) => o.includes('Driver Evidence'),
  'Hypotheses Considered': (o) => o.includes('Hypotheses Considered'),
  'Evidence Index': (o) => o.includes('Evidence Index'),
  'Recommendations': (o) => o.includes('Recommendations'),
  'Limitations': (o) => o.includes('Limitations'),
};
const specFiles = [];
const offlineCard = path.join(ROOT, 'results', '_offline_cache', 'spec-offline-results.json');
if (fs.existsSync(offlineCard)) specFiles.push(offlineCard);
for (const f of fs.readdirSync(path.join(ROOT, 'results'))) {
  if (/^spec-.*response\.json$/.test(f) || /^live-spec-.*\.json$/.test(f)) {
    specFiles.push(path.join(ROOT, 'results', f));
  }
}
if (!specFiles.length) console.log('  SKIP  no ?mode=spec captures found to render');

let cardCases = 0;
for (const file of specFiles) {
  let parsed;
  try { parsed = JSON.parse(fs.readFileSync(file, 'utf8')); }
  catch (e) { failures++; console.log(`  FAIL  ${path.basename(file)} is not valid JSON: ${e.message}`); continue; }
  // A capture file is either {key: response, ...} or ONE response object. Detecting that by
  // `decision_card` alone was wrong: a single response with no card (in-band, or stopped early) got
  // treated as a map, and every one of its own top-level keys was rendered as if it were a separate
  // response. Look for the fields every response carries instead.
  const looksLikeOneResponse = ['decision_card', 'forecast_summary', 'engine', 'investigation_meta',
    'root_cause'].some(k => k in parsed);
  const entries = looksLikeOneResponse
    ? [[path.basename(file), parsed]]
    : Object.entries(parsed).filter(([, v]) => v && typeof v === 'object' && !Array.isArray(v));
  for (const [key, resp] of entries) {
    if (!resp || typeof resp !== 'object') continue;
    // No card is a legitimate outcome (inside the +/-5% threshold, or stopped early). That path has
    // its OWN renderer and is asserted separately rather than skipped.
    if (!resp.decision_card) {
      cardCases++;
      try {
        const out = sandbox.renderSpecStatus(resp, { target: { fields: {} } });
        const ok = out && out.length > 100;
        if (!ok) { failures++; console.log(`  FAIL  ${path.basename(file)} :: ${key} -> renderSpecStatus produced nothing`); }
        else console.log(`  PASS  ${path.basename(file)} :: ${key} (no card -> status renderer, ${out.length.toLocaleString()} chars)`);
      } catch (e) {
        failures++;
        console.log(`  FAIL  ${path.basename(file)} :: ${key} -> renderSpecStatus threw ${e.constructor.name}: ${e.message}`);
      }
      continue;
    }
    cardCases++;
    try {
      const out = sandbox.renderDecisionCard(resp, { target: { fields: {} } });
      const bad = Object.entries(CARD_PANELS).filter(([, t]) => !t(out)).map(([n]) => n);
      if (out.includes('>undefined<')) bad.push('a literal "undefined" reached the markup');
      if (out.includes('>null<')) bad.push('a literal "null" reached the markup');
      if (/>None</.test(out)) bad.push('a Python "None" reached the markup');
      if (bad.length) {
        failures++;
        console.log(`  FAIL  ${path.basename(file)} :: ${key} -> ${bad.join(', ')}`);
      } else {
        console.log(`  PASS  ${path.basename(file)} :: ${key} (card, ${out.length.toLocaleString()} chars)`);
      }
    } catch (e) {
      failures++;
      console.log(`  FAIL  ${path.basename(file)} :: ${key} -> renderDecisionCard threw ${e.constructor.name}: ${e.message}`);
      if (e.stack) console.log('        ' + e.stack.split('\n').slice(1, 3).join('\n        '));
    }
  }
}

console.log(`\n  ${failures ? failures + ' FAILURE(S)' : 'all checks passed'} over ${cases} WFM report(s) `
  + `and ${cardCases} Decision Card(s)`);
process.exit(failures ? 1 : 0);
