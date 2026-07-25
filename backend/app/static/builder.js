/* Magic Hour · the Builder tab. Its one job is asking the 100 questions.
 *
 * Output is a flat {question_text: answer} dict, which is the only input the
 * Identity Card and Voice Card compilers need. Nothing else in here is coupled to
 * anything downstream.
 *
 * Two views. One walks the questions, core first, because the 12 core answers are
 * what unlock a face and a voice. All shows the 100 in one scroll for someone who
 * already knows this person and wants four specific fields.
 *
 * Answers are held here until Save, then written in one PUT: each write bumps
 * canon_version and stales both compiled cards, so saving field by field would
 * recompile a character once per keystroke's worth of work.
 */

const BQ = {};                 // question id -> question
let IV = null;                 // the interview payload
let BCID = null;               // selected character
let BMODE = "one";             // one | all
let BI = 0;                    // cursor, One view
let DIRTY = {};                // question text -> typed, unsaved
let DRAFTS = {};               // question text -> model draft, untouched

/* Core first, then file order. Matches questions.next_unanswered on the server,
 * kept here so Back can walk the same order in reverse. */
function bqueue() {
  const all = IV.parts.flatMap((p) => p.questions);
  return [...all.filter((q) => q.is_core), ...all.filter((q) => !q.is_core)];
}

const bval = (q) => DIRTY[q.text] ?? DRAFTS[q.text] ?? q.answer ?? "";

/* Everything on screen the server does not have. Drafts count: they are unsaved
 * work like anything typed, so Save writes them and the dots show them as pending.
 * DRAFTS is separate only so an untouched draft can be styled as one. */
const bunsaved = () => ({ ...DRAFTS, ...DIRTY });

window.Builder = {
  /* Called on every tab click, so the tab is never stale after a Cast compile. */
  async enter() {
    if (!STORY?.characters?.length) return bdBar(), bdEmpty("No characters yet.");
    await bdOpen(BCID && STORY.characters.some((c) => c.id === BCID)
      ? BCID : STORY.characters[0].id);
  },
};

async function bdOpen(cid) {
  // Switching away with work on screen writes it first. It belongs to the
  // character you were on, and dropping it silently would lose typed answers.
  if (BCID && cid !== BCID && Object.keys(bunsaved()).length) await bdSave();
  if (cid !== BCID) { DIRTY = {}; DRAFTS = {}; BI = 0; }
  BCID = cid;
  IV = await api(`/characters/${cid}/interview`);
  for (const p of IV.parts) for (const q of p.questions) BQ[q.id] = q;
  const q = bqueue();
  if (!Object.keys(bunsaved()).length) BI = Math.max(0, q.findIndex((x) => !bval(x)));
  bdDraw();
}

/* ------------------------------------------------------------------- drawing */

function bdEmpty(msg) {
  $("#bdMain").innerHTML = `<div class="empty">${esc(msg)}</div>`;
}

/* Who you are answering as. A row, not a sidebar: this tab is one column of work
 * and a permanent 290px list would push the question off centre for no gain. */
function bdBar() {
  $("#bdBar").innerHTML = `<div class="bd-who">
    ${(STORY?.characters || []).map((c) => `
      <button class="bd-name ${c.id === BCID ? "on" : ""}" data-id="${c.id}">
        ${esc(c.name)}
        <span class="mono">${c.core_answered}/12</span>
      </button>`).join("")}
  </div>`;
  $$("#bdBar .bd-name").forEach((b) => b.onclick = () => bdOpen(b.dataset.id));
}

function bdDraw() {
  bdBar();
  const p = IV.progress;
  const pending = bunsaved();
  const n = Object.keys(pending).length;
  const core = bqueue().filter((q) => q.is_core);

  $("#bdMain").innerHTML = `
    <div class="bd-strip">
      <div class="bd-gate">
        ${core.map((q) => `<button class="bd-dot ${bval(q).trim() ? "on" : ""}
          ${(pending[q.text] || "").trim() ? "new" : ""}"
          data-q="${q.id}" title="${esc(q.text)}"></button>`).join("")}
      </div>
      <span class="tiny faint mono">${p.answered} of 100</span>
      <div class="bd-modes">
        <button class="${BMODE === "one" ? "on" : ""}" data-m="one">One</button>
        <button class="${BMODE === "all" ? "on" : ""}" data-m="all">All</button>
      </div>
      <span class="bd-push"></span>
      <input class="f bd-premise" id="bdPremise" placeholder="who is this person, in one line"
        value="${esc(IV.premise || "")}">
      <button class="act" id="bdDraft">Draft</button>
      <button class="act ${n ? "primary" : ""}" id="bdSaveAll" ${n ? "" : "disabled"}>
        ${n ? `Save ${n}` : "Save"}</button>
    </div>
    ${BMODE === "one" ? bdOne() : bdAll()}`;
  bdWire();
}

function bdOne() {
  const q = bqueue()[BI];
  if (!q) return `<div class="empty">All 100 answered.</div>`;
  return `
    <div class="panel lit pad bd-card">
      <div class="bd-qmeta">
        <span class="chip ${q.is_core ? "warn" : ""}">${q.is_core ? "core" : esc(q.part_label)}</span>
        <span class="tiny faint mono">${q.id} of 100</span>
        ${DRAFTS[q.text] ? `<span class="tiny faint">draft</span>` : ""}
      </div>
      <div class="bd-q">${esc(q.text)}</div>
      <textarea class="f ans ${DRAFTS[q.text] ? "draft" : ""}" data-q="${q.id}"
        rows="4" autofocus>${esc(bval(q))}</textarea>
      <div class="bd-acts">
        <button class="act" id="bdPrev" ${BI ? "" : "disabled"}>Back</button>
        <button class="act primary" id="bdNext">Next</button>
        <span class="tiny faint mono">Ctrl or Cmd and Enter</span>
      </div>
    </div>`;
}

/* All 100 in one scroll, grouped. No part picker and no seven meters: the heading
 * carries the count and scrolling is a cheaper control than a row of tabs. */
function bdAll() {
  return IV.parts.map((pt) => {
    const done = pt.questions.filter((q) => bval(q).trim()).length;
    return `
      <div class="panel pad bd-part">
        <div class="bd-phead">
          <span class="eyebrow" style="margin:0">${esc(pt.label)}</span>
          <span class="tiny faint mono">${done} of ${pt.count}</span>
        </div>
        ${pt.questions.map((q) => `
          <div class="bd-item ${bval(q).trim() ? "done" : ""}">
            <div class="bd-ilab">
              <span class="tiny mono faint">${q.id}</span>
              ${q.is_core ? `<span class="bd-core">core</span>` : ""}
            </div>
            <div class="bd-ifield">
              <div class="tiny bd-itext">${esc(q.text)}</div>
              <textarea class="f ans ${DRAFTS[q.text] ? "draft" : ""}" data-q="${q.id}"
                rows="2" placeholder="·">${esc(bval(q))}</textarea>
            </div>
          </div>`).join("")}
      </div>`;
  }).join("");
}

/* --------------------------------------------------------------- interaction */

function bdWire() {
  $$("#bdMain .ans").forEach((t) => {
    t.oninput = () => {
      const q = BQ[t.dataset.q];
      if (t.value === (q.answer || "")) delete DIRTY[q.text];
      else DIRTY[q.text] = t.value;
      delete DRAFTS[q.text];              // touched, so it is yours now
      t.classList.remove("draft");
      const n = Object.keys(bunsaved()).length;
      const b = $("#bdSaveAll");
      b.textContent = n ? `Save ${n}` : "Save";
      b.disabled = !n;
      b.classList.toggle("primary", Boolean(n));
      bdDot(q, t.value);
    };
    t.onkeydown = (e) => {
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        BMODE === "one" ? bdNext() : bdSave();
      }
    };
  });

  $$("#bdMain .bd-dot").forEach((b) => b.onclick = () => {
    BMODE = "one";
    BI = bqueue().findIndex((q) => q.id === +b.dataset.q);
    bdDraw();
  });
  $$("#bdMain .bd-modes button").forEach((b) => b.onclick = () => {
    BMODE = b.dataset.m; bdDraw();
  });
  if ($("#bdNext")) {
    $("#bdNext").onclick = bdNext;
    $("#bdPrev").onclick = () => { BI = Math.max(0, BI - 1); bdDraw(); };
  }
  $("#bdSaveAll").onclick = bdSave;
  $("#bdDraft").onclick = bdDrafting;
  $("#bdMain .ans")?.focus();
}

/* Live dot for the question being typed, without redrawing the field under the
 * cursor: a full redraw on input would lose the caret every keystroke. */
function bdDot(q, v) {
  if (!q.is_core) return;
  const dot = $(`#bdMain .bd-dot[data-q="${q.id}"]`);
  if (!dot) return;
  dot.classList.toggle("on", Boolean(v.trim()));
  dot.classList.toggle("new", Boolean(v.trim()) && v !== (q.answer || ""));
}

/* Next means save what is here, then move on. Two buttons for one intent is the
 * kind of thing that makes people stop halfway through 100 questions. */
async function bdNext() {
  if (Object.keys(bunsaved()).length) return bdSave();
  BI = Math.min(bqueue().length - 1, BI + 1);
  bdDraw();
}

async function bdSave() {
  const answers = {};
  for (const [k, v] of Object.entries(bunsaved())) if (v.trim()) answers[k] = v.trim();
  DIRTY = {}; DRAFTS = {};
  if (!Object.keys(answers).length) {
    BI = Math.min(bqueue().length - 1, BI + 1);
    return bdDraw();
  }
  $("#bdSaveAll").disabled = true;
  await api(`/characters/${BCID}/answers`,
    { method: "PUT", body: JSON.stringify({ answers }) });
  trace("saved", `${Object.keys(answers).length} answer(s) · canon bumped`, "done");
  await load();                          // Cast and the bible both move
  IV = await api(`/characters/${BCID}/interview`);
  for (const p of IV.parts) for (const q of p.questions) BQ[q.id] = q;
  if (BMODE === "one") {
    const at = bqueue().findIndex((x) => !bval(x));
    if (at >= 0) BI = at;
  }
  bdDraw();
}

/* Drafts land in the fields unwritten. Nothing here is stored until Save, because
 * an answer the model invented and stored silently would be canon nobody decided,
 * and every face and every line after it would be built on it. */
async function bdDrafting() {
  const btn = $("#bdDraft");
  btn.disabled = true;
  IV.premise = $("#bdPremise").value.trim();
  await sse(`/characters/${BCID}/draft`, { premise: IV.premise },
    { data: (e) => { DRAFTS = { ...DRAFTS, ...(e.drafts || {}) }; } });
  btn.disabled = false;
  bdDraw();
}

/* The tab's own entry point. app.js owns navigation and knows nothing about this
 * surface, so the refresh hangs off the same click. */
$(".tab[data-s=\"build\"]").addEventListener("click", () => Builder.enter());
