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

/* Every function the WFM report path needs must be reachable at top level. */
const REQUIRED = ['formatInvestigation', 'renderInvestigationReport', 'secDesc', 'invEsc',
  'rcaRootCausePanel', 'rcaConfidenceCriticalityPanel', 'rcaWhyPanel', 'rcaEvidenceTablePanel',
  'rcaForecastResponsePanel', 'rcaDriverEvidencePanel', 'rcaActionPanel',
  'renderDecisionCard'];
for (const fn of REQUIRED) {
  const ok = typeof sandbox[fn] === 'function';
  if (!ok) failures++;
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${fn} is callable at top level`);
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
console.log(`\n  ${failures ? failures + ' FAILURE(S)' : 'all checks passed'} over ${cases} rendered response(s)`);
process.exit(failures ? 1 : 0);
