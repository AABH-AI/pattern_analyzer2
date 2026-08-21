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

/* ---- PAGE-WIDE: the column must not be referenced by any live code -------------------------
 * The per-card checks further down render `renderDecisionCard` and catch leaks THERE. They cannot
 * catch a leak anywhere else on the page -- and that is exactly what happened: the Decision Card was
 * clean while the worklist queue card, the filter panel, the dashboard filter and the field glossary
 * all still showed `Projection_plan_name`. A user searching the page for "plan" found them and
 * reasonably concluded the change had not landed.
 *
 * So this scans the WHOLE file, with comments stripped, because a comment cannot reach the screen but
 * a template literal can.
 */
{
  const noComments = html
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '');
  const refs = [...noComments.matchAll(/.{0,60}Projection[_ ]?plan.{0,60}/gi)]
    .map(m => m[0].trim().replace(/\s+/g, ' '));
  if (refs.length) {
    failures++;
    console.log(`  FAIL  ${refs.length} live reference(s) to Projection_plan_name remain in the page:`);
    refs.forEach(r => console.log(`          ${r}`));
  } else {
    console.log('  PASS  no live reference to Projection_plan_name anywhere in the page');
  }
}

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
      /* ctx carries a PLAN VINTAGE and a forecaster on purpose.
       *
       * The first version of this guard passed `{target:{fields:{}}}` and then asserted that no plan
       * name appeared in the output -- which it never could, because nothing supplied one. The check
       * passed while being incapable of failing. Verified by re-injecting the removed
       * "Plan measured against" block: the guard stayed green.
       *
       * Feeding a plan name in means any renderer that reads `Projection_plan_name` leaks it into the
       * markup and the assertions below catch it. The forecaster is supplied too, so the block that
       * legitimately survives still renders and is exercised. */
      const probeCtx = { target: { fields: {
        Projection_plan_name: 'FY27 May Projection',
        Forecaster: 'Test Owner',
      } } };
      const out = sandbox.renderDecisionCard(resp, probeCtx);
      const bad = Object.entries(CARD_PANELS).filter(([, t]) => !t(out)).map(([n]) => n);
      if (out.includes('>undefined<')) bad.push('a literal "undefined" reached the markup');
      if (out.includes('>null<')) bad.push('a literal "null" reached the markup');
      if (/>None</.test(out)) bad.push('a Python "None" reached the markup');

      /* REPETITION. A reader reported the holiday name and its sentence appearing 10-12 times on one
       * card, and a captured output confirmed it: 13 / 12 / 14 printings of three names, one sentence
       * 7 times. Nothing caught it, because every panel was individually correct -- the same measured
       * fact is stored in 19 places and four sections each legitimately report it. So the assertion
       * has to be about the WHOLE rendered card, not any one panel.
       *
       * Two separate faults are guarded here. A name repeated INSIDE one list was a real data bug
       * (raw spellings printed beside their own canonical form, and one event spanning two dates
       * printed twice). A sentence repeated ACROSS panels is a presentation fault, handled by
       * sayOnce. Both show up as counts on the finished card. */
      const vis = out.replace(/<[^>]+>/g, ' ').replace(/&[a-zA-Z#0-9]+;/g, ' ')
                     .replace(/\s+/g, ' ').trim();
      const holBlk = (resp.holiday_response || {});
      const holNames = [...new Set([].concat(
        (holBlk.holidays_in_target_week || {}).canonical_names || [],
        (holBlk.recent_holidays_affecting_target_week || {}).canonical_names || []))];
      const NAME_CAP = 6;
      for (const nm of holNames) {
        if (!nm || nm.length < 6) continue;
        const c = vis.split(nm).length - 1;
        if (c > NAME_CAP) {
          bad.push(`holiday "${nm}" printed ${c}x on one card (cap ${NAME_CAP})`);
        }
      }
      // The same name twice inside one comma list is always wrong, whatever the cap.
      for (const nm of holNames) {
        if (!nm || nm.length < 6) continue;
        // Plain string search: no regex, so no escaping to get wrong.
        if (vis.indexOf(nm + ', ' + nm) >= 0) {
          bad.push(`holiday "${nm}" listed twice consecutively in one list`);
        }
      }
      /* Set RENDER_REPEAT_REPORT=1 to print the actual counts rather than only cap breaches.
         Useful for showing a before/after on a specific card without a second harness -- the last
         three attempts at a standalone sandbox each failed on a different global this one already
         sets up correctly. */
      if (process.env.RENDER_REPEAT_REPORT) {
        const counts = holNames.map(n => [n, vis.split(n).length - 1])
                               .filter(([, c]) => c > 0).sort((a, b) => b[1] - a[1]);
        const tot = counts.reduce((a, [, c]) => a + c, 0);
        if (tot) {
          console.log(`  REPORT ${key}`);
          for (const [n, c] of counts) console.log(`           ${c}x  ${n}`);
          console.log(`           ---- ${tot} name printing(s)`);
        }
      }
      /* MARKER-ONLY ROWS. The dedup passes replace a repeated sentence with "(as above)", which is
         right inside a sentence or a table cell that must stay populated and wrong as an entire list
         item -- a Limitations panel shipped with one real line and five "(as above)" bullets, which
         is noisier than the repetition it replaced. The row itself is the noise. */
      const markerLi = (out.match(
        /<li[^>]*>(?:\s|<[^>]*>)*(?:\(as above\)|Same as stated above\.?)(?:\s|<\/[^>]*>)*<\/li>/gi
      ) || []).length;
      if (markerLi) bad.push(`${markerLi} list item(s) contain nothing but an "(as above)" marker`);

      /* NO SECTION LOST to the tab layout. The layout buckets each inv-card block into a group by
         matching its title; a section whose name no pattern covers must still be reachable, so it
         falls through to Reference rather than vanishing. This asserts the count in equals the count
         out, because silently losing a panel is far worse than showing it under the wrong tab. */
      const blocksOut = (out.match(/<div class="inv-card"/g) || []).length;
      const titlesOut = (out.match(/class="rtitle"/g) || []).length;
      if (blocksOut && titlesOut && titlesOut > blocksOut) {
        bad.push(`${titlesOut} section title(s) but only ${blocksOut} card block(s) rendered`);
      }
      const tabBtns = (out.match(/data-cardtabbtn=/g) || []).length;
      const tabPanels = (out.match(/data-cardtab=/g) || []).length;
      if (tabBtns !== tabPanels) {
        bad.push(`tab strip has ${tabBtns} button(s) but ${tabPanels} panel(s)`);
      }
      if (tabBtns && blocksOut < 6) {
        bad.push(`tab layout rendered but only ${blocksOut} card block(s) survived`);
      }
      if (process.env.RENDER_REPEAT_REPORT && tabBtns) {
        const labels = [...out.matchAll(/data-cardtabbtn="([^"]+)"/g)].map(m => m[1]);
        console.log(`           tabs: ${labels.join(', ')}   (${blocksOut} section blocks)`);
      }

      const SENT_CAP = 3;
      const seenS = {};
      for (const sn of vis.split(/(?<=[.!?])\s+/)) {
        const t = sn.trim();
        if (t.length < 55) continue;
        seenS[t] = (seenS[t] || 0) + 1;
      }
      const worst = Object.entries(seenS).filter(([, n]) => n > SENT_CAP)
                          .sort((a, b) => b[1] - a[1]);
      if (process.env.RENDER_REPEAT_REPORT) {
        const top = Object.entries(seenS).sort((a, b) => b[1] - a[1])[0];
        if (top) console.log(`           worst repeated sentence: ${top[1]}x`);
        const backrefs = (out.match(/holidays named above/g) || []).length;
        const asabove = (out.match(/as above|Same as stated above/g) || []).length;
        console.log(`           back-references: ${backrefs}   as-above markers: ${asabove}`
                    + `   Statistical Profile: ${/Statistical Profile/.test(out) ? 'yes' : 'no'}`);
      }
      if (worst.length) {
        bad.push(`${worst.length} sentence(s) repeated more than ${SENT_CAP}x on one card, worst `
                 + `${worst[0][1]}x: "${worst[0][0].slice(0, 60)}..."`);
      }

      /* Panel ORDER, not just presence. The reading order is a deliberate decision -- headline,
       * then the ranked reasons, then the formal cause -- and it is set by one concatenation
       * expression that is easy to reorder by accident while every "is the panel there" check
       * still passes. */
      const titles = [...out.matchAll(/class="rtitle"[^>]*>([^<]+)</g)].map(m => m[1].trim());
      const at = (re) => titles.findIndex(t => re.test(t));
      const iSummary = at(/Executive Summary/i);
      const iWhy = at(/Why This Happened/i);
      const iRoot = at(/^Root Cause$/i);
      if (iSummary >= 0 && iWhy >= 0 && iWhy !== iSummary + 1) {
        bad.push(`"Why This Happened" must come immediately after "Executive Summary" `
          + `(found at ${iWhy + 1}, summary at ${iSummary + 1})`);
      }
      if (iWhy >= 0 && iRoot >= 0 && iWhy > iRoot) {
        bad.push('"Why This Happened" must come BEFORE "Root Cause"');
      }

      /* The E-number and strength chips were removed from the Why bullets on purpose: "E5" is
       * meaningless without the Evidence Index open, and a strength label invites the reader to
       * weigh bullets when the ORDER already does that. Both remain on the response and in the
       * Evidence Index, so this asserts the chips are gone AND that traceability survived. */
      const whyStart = out.indexOf('Why This Happened');
      if (whyStart >= 0) {
        const nextTitle = out.indexOf('class="rtitle"', whyStart + 10);
        const whyBlock = out.slice(whyStart, nextTitle > 0 ? nextTitle : undefined);
        if (/background:#eef2f7;color:#1f4e79[^>]*>E\d+</.test(whyBlock)) {
          bad.push('an E-number chip is back on the Why bullets');
        }
        if (/>(Very Strong|Strong|Moderate|Very Weak|Weak)</.test(whyBlock)) {
          bad.push('a strength chip is back on the Why bullets');
        }
      }
      if (!/>E1</.test(out)) {
        bad.push('the Evidence Index no longer lists E1 -- removing the chips must not cost traceability');
      }

      /* `Projection_plan_name` is treated by this engine as NON-EXISTENT, so neither the column name
       * nor a plan-vintage VALUE may reach the rendered card. Checking the column name alone would
       * miss the case that actually matters -- a value like "FY27 May Projection" printed in prose. */
      if (/Projection_plan_name/.test(out)) {
        bad.push('the column name "Projection_plan_name" reached the rendered card');
      }
      const vintage = out.match(/FY\d\d\s+\w+\s+Projection/);
      if (vintage) {
        bad.push(`a plan-vintage value reached the rendered card: "${vintage[0]}"`);
      }
      if (/Plan measured against/.test(out)) {
        bad.push('the "Plan measured against" block is back');
      }
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
