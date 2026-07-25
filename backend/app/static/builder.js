/* Magic Hour · the character builder.
 *
 * The 100 questions, and the only input both card compilers need. Everything in
 * here produces one thing: a flat {question_text: answer} dict. That is the
 * contract with app/consistency.py and app/voice.py, so this file is free to
 * change how it asks without touching anything downstream.
 *
 * Two ways through the same 100. Interview walks them one at a time, core first,
 * because the 12 core answers are what unlock a face and a voice and nothing else
 * is worth doing until they exist. All 100 shows every part at once, because a
 * writer who already knows this person wants to type into the four fields they
 * care about and leave, not answer twelve questions to get to the thirteenth.
 *
 * Unsaved answers are held here and never partially written: one PUT per save,
 * because each write bumps canon_version and stales both compiled cards, so
 * saving one field at a time would recompile a character eight times to fill in
 * one part.
 */

const BQ = {};                 // question id -> question, filled on open
let IV = null;                 // the interview payload
let BCID = null;               // character id
let BMODE = "interview";
let BPART = null;              // open part in All 100 mode
let BI = 0;                    // interview cursor
let DIRTY = {};                // question text -> unsaved answer
let DRAFTS = {};               // question text -> model draft, unaccepted

/* Core first, then the rest in file order. The same policy the server uses in
 * questions.next_unanswered, kept here so prev and next can walk backwards too. */
function bqueue() {
  const all = IV.parts.flatMap((p) => p.questions);
  return [...all.filter((q) => q.is_core), ...all.filter((q) => !q.is_core)];
}

function bval(q) {
  return DIRTY[q.text] ?? DRAFTS[q.text] ?? q.answer ?? "";
}

/* Everything on screen that the server does not have yet, drafts included.
 *
 * A draft is unsaved work like anything else you typed, so Save writes it and the
 * gate shows it as unsaved. Keeping drafts out of this was worse than useless: the
 * dots filled in as though the answers were stored and the Save button stayed
 * disabled, so twelve drafted answers had no way to be accepted at all.
 *
 * DRAFTS stays a separate map only so an untouched draft can be styled as one. */
function bunsaved() {
  return { ...DRAFTS, ...DIRTY };
}

const bpct = (a, b) => (b ? Math.round(a / b * 100) : 0);

window.Builder = {
  async open(ch) {
    BCID = ch.id;
    IV = await api(`/characters/${ch.id}/interview`);
    for (const p of IV.parts) for (const q of p.questions) BQ[q.id] = q;
    if (BPART === null) BPART = IV.parts[0].key;
    // Land on the first thing that still needs an answer, not on question one,
    // which is almost always already answered and teaches nothing.
    const q = bqueue();
    if (!Object.keys(DIRTY).length) BI = Math.max(0, q.findIndex((x) => !bval(x)));
    bdDraw();
  },
  draw: bdDraw,
};

function bdDraw() {
  const p = IV.progress;
  const ch = IV.character;
  const unsaved = Object.keys(bunsaved()).length;
  $("#castWho").textContent = ch.name;
  $("#castDetail").innerHTML = `
    <div class="panel lit pad bd-head">
      <div class="bd-row">
        <button class="act primary" id="btnCompile">Compile cards</button>
        <button class="act" id="btnCast">Cast · sheet and fingerprint</button>
        <span class="chip ${p.ready_for_dialogue ? "ok" : "warn"}">
          ${p.core_done} of 12 core</span>
        <span class="chip">${p.answered} of 100</span>
        <span class="chip ${unsaved ? "warn" : ""}" id="bdUnsaved"
          style="${unsaved ? "" : "display:none"}">${unsaved} unsaved</span>
        <button class="act ${unsaved ? "primary" : ""}" id="bdSaveAll"
          ${unsaved ? "" : "disabled"}>Save</button>
      </div>
      ${bdGate()}
      <div class="bd-parts">
        ${IV.parts.map((pt) => {
          const v = p.by_part[pt.key];
          return `<button class="bd-part ${pt.key === BPART ? "on" : ""}" data-p="${pt.key}">
            <div class="meter"><i style="width:${bpct(v.done, v.total)}%"></i></div>
            <div class="tiny faint">${esc(v.label)}</div>
            <div class="tiny mono faint">${v.done}/${v.total}</div>
          </button>`;
        }).join("")}
      </div>
    </div>

    <div class="panel pad bd-draft">
      <div class="bd-row">
        <input class="f" id="bdPremise" placeholder="one line about who this person is: a night bus driver who never tells anyone she was a pianist"
          value="${esc(IV.premise || "")}">
        <button class="act" id="bdDraft">Draft the unanswered core</button>
      </div>
      <div class="tiny faint" style="margin-top:8px">
        Drafts land in the fields for you to edit, and nothing is written until you
        save. An answer the model invented and stored silently would become canon
        nobody decided, and every face and every line after it would be built on it.
      </div>
    </div>

    <div class="bd-modes">
      <button class="${BMODE === "interview" ? "on" : ""}" data-m="interview">Interview</button>
      <button class="${BMODE === "all" ? "on" : ""}" data-m="all">All 100</button>
    </div>

    ${BMODE === "interview" ? bdInterview() : bdAll()}

    ${ch.identity_card ? cardPanel(
      "Identity Card · frozen, pasted verbatim into every image prompt", [
      ["descriptor", ch.identity_card.descriptor],
      ["wardrobe", ch.identity_card.wardrobe],
      ["never", ch.identity_card.negative]], ch.sheet_url) : ""}
    ${ch.voice_card ? cardPanel(
      "Voice Card · frozen, injected verbatim into her sub-agent", [
      ["how she speaks", ch.voice_card.card],
      ["says", (ch.voice_card.phrases || []).join(" · ")],
      ["never says", (ch.voice_card.never_says || []).join(" · ")],
      ["samples", (ch.voice_card.samples || []).map((s) => `"${s}"`).join("\n")],
      ...Object.entries(ch.voice_card.register || {})]) : ""}`;
  bdWire();
}

/* The gate. Twelve dots, one per core question, because "5 of 12" tells you how
 * far you are and this tells you which ones are missing and lets you go there. */
function bdGate() {
  const core = bqueue().filter((q) => q.is_core);
  const pending = bunsaved();
  const waiting = core.filter((q) => (pending[q.text] || "").trim()).length;
  return `<div class="bd-gate">
    ${core.map((q) => {
      const has = Boolean(bval(q).trim());
      return `<button class="bd-dot ${has ? "on" : ""}
        ${(pending[q.text] || "").trim() ? "new" : ""}"
        data-q="${q.id}" title="${esc(q.text)}"></button>`;
    }).join("")}
    <span class="tiny faint" style="margin-left:8px">
      ${waiting
        ? `${waiting} core ${waiting === 1 ? "answer is" : "answers are"} written `
          + `here and not saved yet. Amber means the server does not have it.`
        : IV.progress.ready_for_dialogue
          ? "all 12 core answered, this character can speak"
          : "the 12 core answers are what compile a voice. Click a dot to answer it."}
    </span>
  </div>`;
}

function bdInterview() {
  const q = bqueue()[BI];
  if (!q) return `<div class="empty">All 100 answered.</div>`;
  // "filled in", not "answered": this counts what is on screen, and the chip above
  // counts what the server has. Calling both of them answered read as a bug when a
  // fresh character showed 12 filled in and 0 of 100 in the same glance.
  const n = bqueue().filter((x) => bval(x).trim()).length;
  return `
    <div class="panel lit pad bd-one">
      <div class="bd-qmeta">
        <span class="chip ${q.is_core ? "warn" : ""}">${q.is_core ? "core" : esc(q.part_label)}</span>
        <span class="tiny faint mono">question ${q.id} of 100 · ${n} filled in</span>
        <span class="tiny faint" style="margin-left:auto">
          ${DRAFTS[q.text] ? "drafted, not saved" : q.answer ? "answered" : ""}</span>
      </div>
      <div class="bd-q">${esc(q.text)}</div>
      <textarea class="f ans ${DRAFTS[q.text] ? "draft" : ""}" data-q="${q.id}"
        rows="4" placeholder="in their own words, first person">${esc(bval(q))}</textarea>
      <div class="bd-row" style="margin-top:11px">
        <button class="act" id="bdPrev" ${BI ? "" : "disabled"}>Back</button>
        <button class="act primary" id="bdNext">Save and next</button>
        <button class="act" id="bdSkip">Skip</button>
        <span class="tiny faint">Ctrl or Cmd and Enter saves and moves on.</span>
      </div>
    </div>`;
}

function bdAll() {
  const pt = IV.parts.find((p) => p.key === BPART) || IV.parts[0];
  return `
    <div class="panel pad">
      <div class="eyebrow">${esc(pt.label)} · ${pt.count} questions, ${pt.core_count} core</div>
      ${pt.questions.map((q) => `
        <div class="bd-item ${bval(q).trim() ? "done" : ""}">
          <div class="bd-ilab">
            <span class="tiny mono faint">${q.id}</span>
            ${q.is_core ? `<span class="chip warn">core</span>` : ""}
          </div>
          <div style="flex:1">
            <div class="tiny" style="margin-bottom:6px">${esc(q.text)}</div>
            <textarea class="f ans ${DRAFTS[q.text] ? "draft" : ""}" data-q="${q.id}"
              rows="2" placeholder="·">${esc(bval(q))}</textarea>
          </div>
        </div>`).join("")}
    </div>`;
}

/* ---------------------------------------------------------------- interaction */

function bdWire() {
  $$("#castDetail .ans").forEach((t) => {
    t.oninput = () => {
      const q = BQ[t.dataset.q];
      const v = t.value;
      if (v === (q.answer || "")) delete DIRTY[q.text];
      else DIRTY[q.text] = v;
      delete DRAFTS[q.text];        // touched, so it is yours now, not a draft
      t.classList.remove("draft");
      const n = Object.keys(bunsaved()).length;
      const chip = $("#bdUnsaved");
      chip.textContent = `${n} unsaved`;
      chip.style.display = n ? "" : "none";
      $("#bdSaveAll").disabled = !n;
      $("#bdSaveAll").classList.toggle("primary", Boolean(n));
    };
    t.onkeydown = (e) => {
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        BMODE === "interview" ? bdStep(1, true) : bdSave();
      }
    };
  });

  $$("#castDetail .bd-part").forEach((b) => b.onclick = () => {
    BPART = b.dataset.p; BMODE = "all"; bdDraw();
  });
  $$("#castDetail .bd-modes button").forEach((b) => b.onclick = () => {
    BMODE = b.dataset.m; bdDraw();
  });
  $$("#castDetail .bd-dot").forEach((b) => b.onclick = () => {
    BMODE = "interview";
    BI = bqueue().findIndex((q) => q.id === +b.dataset.q);
    bdDraw();
  });

  const nx = $("#bdNext");
  if (nx) {
    nx.onclick = () => bdStep(1, true);
    $("#bdSkip").onclick = () => bdStep(1, false);
    $("#bdPrev").onclick = () => bdStep(-1, false);
  }
  $("#bdSaveAll").onclick = bdSave;
  $("#bdDraft").onclick = bdDrafting;
  $("#btnCompile").onclick = () => bdRun("compile");
  $("#btnCast").onclick = () => bdRun("cast");
}

async function bdStep(d, saveFirst) {
  if (saveFirst && Object.keys(bunsaved()).length) { await bdSave(); return; }
  BI = Math.min(bqueue().length - 1, Math.max(0, BI + d));
  bdDraw();
  $("#castDetail .ans")?.focus();
}

/* One PUT for everything unsaved. The server merges, bumps canon_version once and
 * stales both cards once, which is the whole reason answers are batched. */
async function bdSave() {
  const answers = {};
  for (const [k, v] of Object.entries(bunsaved())) if (v.trim()) answers[k] = v.trim();
  if (!Object.keys(answers).length) { DIRTY = {}; DRAFTS = {}; bdDraw(); return; }
  $("#bdSaveAll").disabled = true;
  await api(`/characters/${BCID}/answers`,
    { method: "PUT", body: JSON.stringify({ answers }) });
  DIRTY = {};
  DRAFTS = {};
  trace("answers", `${Object.keys(answers).length} saved · canon bumped`, "done");
  await load();                        // the cards and the bible both move
  IV = await api(`/characters/${BCID}/interview`);
  for (const p of IV.parts) for (const q of p.questions) BQ[q.id] = q;
  if (BMODE === "interview") {
    const q = bqueue();
    const at = q.findIndex((x) => !bval(x));
    if (at >= 0) BI = at;
  }
  bdDraw();
}

async function bdDrafting() {
  const btn = $("#bdDraft");
  btn.disabled = true;
  IV.premise = $("#bdPremise").value.trim();
  $$("#itabs button")[1].click();
  await sse(`/characters/${BCID}/draft`,
    { premise: IV.premise, part: BMODE === "all" ? BPART : null },
    { data: (e) => { DRAFTS = { ...DRAFTS, ...(e.drafts || {}) }; } });
  btn.disabled = false;
  bdDraw();
}

async function bdRun(what) {
  const btn = what === "compile" ? $("#btnCompile") : $("#btnCast");
  btn.disabled = true;
  $$("#itabs button")[1].click();
  await sse(`/characters/${BCID}/${what}`, {}, {
    run_end: async () => { await load(); await Builder.open(IV.character); },
  });
  btn.disabled = false;
}
