/* The home page and the interview.
 *
 * Three screens, one at a time: land, ask, done. The asking screen shows exactly
 * one question, because the reason the tabs are confusing on a first visit is
 * that they show everything at once and none of it is a place to start.
 *
 * Nothing is staged. Every answer is written when it is given, so closing the tab
 * halfway loses nothing and reopening resumes at the first unanswered question.
 */

(function home() {
  "use strict";

  const q = (s, r = document) => r.querySelector(s);
  const qa = (s, r = document) => [...r.querySelectorAll(s)];
  const clean = (s) => String(s ?? "").replace(/[&<>"]/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  const api = async (path, opts) => {
    const r = await fetch("/api" + path, {
      ...opts,
      headers: opts?.body ? { "Content-Type": "application/json" } : undefined,
    });
    // The interview writes canon, so it is behind the same guard as every other
    // router. This page carries no Google token of its own, so when auth is
    // switched on in production the honest thing is to send the filmmaker to the
    // app to sign in rather than to show an empty form that silently fails on
    // every answer. With auth off, which is the local and demo case, this never
    // fires.
    if (r.status === 401) { needsSignIn(); throw new Error("sign in required"); }
    if (!r.ok) throw new Error(`${r.status} ${(await r.text()).slice(0, 200)}`);
    return r.json();
  };

  function needsSignIn() {
    show("landing");
    q("#goStart").hidden = true;
    q("#goResume").hidden = true;
    q("#others").innerHTML = "";
    q("#landingNote").innerHTML =
      `Sign in first. <button class="linky" id="toSignIn"
        style="text-decoration:underline">Open the app</button> and come back.`;
    const b = q("#toSignIn");
    if (b) b.onclick = () => { location.href = "/"; };
  }

  let S = null;              // interview state from the server
  let i = 0;                 // which step is on screen
  const suggested = {};      // axis key -> suggestion, offered but not yet saved

  /* ---------------------------------------------------------------- screens */

  function show(name) {
    for (const s of ["landing", "ask", "done"]) q("#" + s).hidden = s !== name;
  }

  /* ------------------------------------------------------------------- land */

  async function land() {
    let list = { stories: [], active: null };
    try { list = await api("/interview/stories"); } catch { /* offline */ }
    try { S = await api("/interview"); } catch { /* offline */ }

    const note = q("#landingNote");
    const resume = q("#goResume");
    if (S && S.answered > 0) {
      resume.hidden = false;
      resume.textContent = `Continue ${S.story.title}`;
      note.textContent = `${S.answered} of ${S.total} answered.`;
    } else {
      resume.hidden = true;
      note.textContent = S ? `${S.total} questions. You can stop at any point.` : "";
    }

    // Every other film on the machine, so starting a new one never strands the
    // one that was open.
    const others = (list.stories || []).filter((s) => s.id !== list.active);
    const box = q("#others");
    box.innerHTML = others.length
      ? `<div class="tiny faint" style="margin-bottom:8px">Or open</div>` +
        others.map((s) => `
          <button class="linky row" data-id="${clean(s.id)}">
            <span class="t">${clean(s.title)}</span>
            <span class="tiny faint">${s.counts.characters} cast · ${s.counts.scenes} scenes</span>
          </button>`).join("")
      : "";
    qa("#others .row").forEach((b) => b.onclick = async () => {
      S = await api("/interview/activate", {
        method: "POST", body: JSON.stringify({ story_id: b.dataset.id }),
      });
      land();
    });
    show("landing");
  }

  q("#goStart").onclick = async () => {
    // A fresh film, and every tab points at it from here on.
    S = await api("/interview/new", { method: "POST", body: JSON.stringify({}) });
    i = 0;
    show("ask");
    render();
  };

  q("#goResume").onclick = () => {
    i = Math.max(0, S.steps.findIndex((s) => !s.answered));
    show("ask");
    render();
  };

  q("#quit").onclick = land;
  q("#toBible").onclick = () => { location.href = "/"; };
  q("#doneBible").onclick = () => { location.href = "/"; };
  q("#doneMore").onclick = () => {
    i = Math.max(0, S.steps.findIndex((s) => !s.answered));
    show("ask");
    render();
  };

  /* -------------------------------------------------------------- one question */

  function step() { return S?.steps?.[i]; }

  function render() {
    const s = step();
    if (!s) return finish();

    q("#who").textContent = s.who || "";
    q("#qText").textContent = s.question;
    q("#qHint").textContent = s.hint || "";

    const long = s.kind === "long" || s.kind === "list";
    const input = q("#qInput"), area = q("#qArea");
    input.hidden = long;
    area.hidden = !long;
    const field = long ? area : input;
    field.placeholder = s.placeholder || "";
    field.value = s.value || suggested[s.id] || "";
    if (s.kind === "list") area.rows = 4;
    setTimeout(() => field.focus(), 30);

    q("#skip").hidden = s.id === "story:title";
    q("#saved").textContent = "";
    q("#count").textContent = `${S.answered} of ${S.total}`;
    drawSections(s.section);
    drawSuggestions();
  }

  function drawSections(current) {
    q("#secs").innerHTML = (S.sections || []).map((sec) => `
      <div class="step ${sec.key === current ? "on" : ""} ${sec.done >= sec.total && sec.total ? "full" : ""}">
        <span class="dot"></span>
        <span class="nm">${clean(sec.label)}</span>
        <span class="of">${sec.done}/${sec.total}</span>
      </div>`).join("");
  }

  /* What the opening sentence became. Shown once, on the axis questions it
   * filled, so nothing arrives without the filmmaker having seen where it came
   * from. Suggestions are offered in the field and saved only when accepted. */
  function drawSuggestions() {
    const box = q("#suggesting");
    const keys = Object.keys(suggested);
    const s = step();
    if (!keys.length || !s || s.section !== "look" || s.id === "look:freeform") {
      box.hidden = true;
      return;
    }
    box.hidden = false;
    box.innerHTML = `<div class="tiny faint" style="margin-bottom:10px">
        Suggested from your description. Edit anything, and nothing is saved
        until you continue past it.</div>` +
      keys.map((k) => `
        <div class="row"><span class="k">${clean(k)}</span>
          <span class="v">${clean(suggested[k])}</span></div>`).join("");
  }

  function value() {
    const s = step();
    const long = s.kind === "long" || s.kind === "list";
    return (long ? q("#qArea") : q("#qInput")).value.trim();
  }

  async function save(v) {
    const s = step();
    const btn = q("#next");
    btn.disabled = true;
    try {
      S = await api("/interview/answer", {
        method: "POST", body: JSON.stringify({ id: s.id, value: v }),
      });
      q("#saved").textContent = "saved";
      setTimeout(() => { const el = q("#saved"); if (el) el.textContent = ""; }, 1400);
      if (s.suggests && v) await suggest(v);
    } catch (err) {
      q("#saved").textContent = String(err.message).slice(0, 80);
    } finally {
      btn.disabled = false;
    }
  }

  /* Turn the description into the seven axes. Writes nothing: the values land in
   * the fields ahead, and each one is saved when the filmmaker continues past
   * it. Inference does not become canon on its own. */
  async function suggest(description) {
    q("#saved").textContent = "reading that";
    try {
      const r = await api("/bible/style/compile", {
        method: "POST", body: JSON.stringify({ description }),
      });
      if (!r.ok) return;
      for (const [k, v] of Object.entries(r.axes || {})) {
        if (v) suggested["look:" + k] = v;
      }
      // Keyed by axis for display, by step id for prefill.
      for (const [k, v] of Object.entries(r.axes || {})) {
        if (v) suggested[k] = v;
      }
    } catch { /* the form still works by hand */ }
  }

  async function advance(store_ = true) {
    const s = step();
    if (!s) return finish();
    const v = value();
    if (store_ && v && v !== s.value) await save(v);
    if (store_ && !v && !s.optional && s.id === "story:title") return;   // needs a name

    const at = S.steps.findIndex((x) => x.id === s.id);
    i = (at === -1 ? i : at) + 1;
    if (i >= S.steps.length) return finish();
    render();
  }

  q("#next").onclick = () => advance(true);
  q("#skip").onclick = () => advance(false);
  q("#back").onclick = () => { if (i > 0) { i--; render(); } };

  q("#qInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); advance(true); }
  });
  q("#qArea").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); advance(true); }
  });

  /* ------------------------------------------------------------------- done */

  async function finish() {
    try { S = await api("/interview"); } catch { /* keep what we have */ }
    let story = null;
    try { story = await api("/story"); } catch { /* counts are optional */ }

    q("#doneTitle").textContent = S.story.title || "Your film";
    q("#doneLine").textContent = S.story.logline || "";
    const c = story?.counts || {};
    q("#doneFacts").innerHTML = [
      [S.answered, "questions answered"],
      [c.characters ?? 0, "characters, each with a compiled voice"],
      [c.scenes ?? 0, "scenes"],
      [story ? "" : null, ""],
    ].filter(([n]) => n !== null && n !== "").map(([n, l]) => `
      <div class="row"><span class="n">${clean(n)}</span><span class="l">${clean(l)}</span></div>`
    ).join("");
    show("done");
  }

  /* ------------------------------------------------------------------ field */

  (function stars() {
    const c = q("#stars");
    if (!c || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const x = c.getContext("2d");
    let pts = [];
    const size = () => {
      c.width = innerWidth; c.height = innerHeight;
      pts = Array.from({ length: Math.round(innerWidth * innerHeight / 11000) }, () => ({
        x: Math.random() * c.width, y: Math.random() * c.height,
        r: Math.random() * 1.05 + 0.2, p: Math.random() * Math.PI * 2,
        s: Math.random() * 0.0006 + 0.00014,
      }));
    };
    addEventListener("resize", size); size();
    (function tick(t) {
      x.clearRect(0, 0, c.width, c.height);
      for (const p of pts) {
        x.globalAlpha = 0.24 + 0.46 * (0.5 + 0.5 * Math.sin(p.p + t * p.s));
        x.fillStyle = p.y / c.height > 0.72 ? "#F7D9A6" : "#DCE6FF";
        x.beginPath(); x.arc(p.x, p.y, p.r, 0, 7); x.fill();
      }
      requestAnimationFrame(tick);
    })(0);
  })();

  land();
})();
