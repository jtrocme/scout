/* Scout — front end. Plain JS, no build step. */
(function () {
  const $app = document.getElementById("app");
  const ROLES = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"];
  const ROLE_FR = { TOP: "Top", JUNGLE: "Jungle", MIDDLE: "Mid", BOTTOM: "ADC", UTILITY: "Support" };
  const ROLE_PLURAL = { TOP: "tops", JUNGLE: "junglers", MIDDLE: "mids", BOTTOM: "ADC", UTILITY: "supports" };
  const DD = "https://ddragon.leagueoflegends.com/cdn";
  let R = null; // current report

  // ---------- small utils ----------
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode */ } },
  };
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const md = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
  const NB = " ";
  const pct = (x) => (x == null ? "–" : Math.round(x * 100) + NB + "%");
  const num = (x, nd = 1) => (x == null || isNaN(x) ? "–" : Number(x).toFixed(nd).replace(".", ","));
  const signed = (x, nd = 0) => (x == null ? "–" : (x >= 0 ? "+" : "−") + num(Math.abs(x), nd));
  const sgnCls = (x, t = 0) => (x == null ? "" : x > t ? "good" : x < -t ? "bad" : "");
  const ord = (n) => (n === 1 ? "1<sup>er</sup>" : n + "<sup>e</sup>");
  const date = (ms) => { if (!ms) return "–"; const d = new Date(ms); return d.toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" }); };
  const dateLong = (ms) => new Date(ms).toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" });
  const mmss = (s) => { if (s == null) return "–"; s = Math.round(s); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
  const wr = (w, g) => {
    if (w == null) return `<span class="muted">–</span>`;
    const c = g < 3 ? "muted" : w >= 0.55 ? "good" : w <= 0.45 ? "bad" : "";
    return `<span class="${c}">${pct(w)}</span>`;
  };
  async function api(path, opts) {
    const r = await fetch(path, opts);
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || `Erreur ${r.status}`);
    return r.json();
  }

  // ---------- static lookups ----------
  const champInfo = (id) => (R && R.static.champs[id]) || [String(id), "?", []];
  const champImg = (id, cls = "ic") => (id == null ? "" : `<img class="${cls}" src="${DD}/${R.static.version}/img/champion/${champInfo(id)[0]}.png" alt="" loading="lazy">`);
  const champ = (id, cls) => (id == null ? "–" : `<span class="champ">${champImg(id, cls)}${esc(champInfo(id)[1])}</span>`);
  const champN = (id, n) => `<span class="champ">${champImg(id, "ic sm")}${esc(champInfo(id)[1])}<span class="x">×${n}</span></span>`;
  const itemName = (id) => (R.static.items[id] || id);
  const itemImg = (id) => `<img class="ic sm" src="${DD}/${R.static.version}/img/item/${id}.png" alt="" loading="lazy">`;
  const rune = (id) => { const r = R.static.runes[id]; return r ? `<img class="ic sm" src="${DD}/img/${r[1]}" alt="" loading="lazy" style="background:none">${esc(r[0])}` : id; };
  const spellImg = (id) => { const s = R.static.spells[id]; return s ? `<img class="ic sm" src="${DD}/${R.static.version}/img/spell/${s[1]}.png" alt="" title="${esc(s[0])}" loading="lazy">` : ""; };
  const spellName = (id) => (R.static.spells[id] || [id])[0];
  const played = (list) => `<span class="chips">${(list || []).map(([c, n]) => champN(c, n)).join("")}</span>`;

  // ---------- theme ----------
  const applyTheme = (t) => { if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme; };
  applyTheme(store.get("theme", null));
  document.getElementById("theme").onclick = () => {
    const dark = document.documentElement.dataset.theme
      ? document.documentElement.dataset.theme === "dark"
      : matchMedia("(prefers-color-scheme: dark)").matches;
    const t = dark ? "light" : "dark";
    store.set("theme", t); applyTheme(t);
  };

  // ---------- router ----------
  let poller = null;
  async function route() {
    clearInterval(poller);
    const h = location.hash.slice(1) || "/";
    window.scrollTo(0, 0);
    try {
      if (h.startsWith("/job/")) return renderJob(h.slice(5));
      if (h.startsWith("/r/")) return await renderReport(decodeURIComponent(h.slice(3)));
      if (h === "/reports") return await renderReports();
      if (h.startsWith("/draft")) {
        const f = h.slice(7);
        return await (f ? renderDraft(decodeURIComponent(f)) : renderDraftPicker());
      }
      if (h.startsWith("/h2h")) {
        const parts = h.slice(4).split("/").filter(Boolean).map(decodeURIComponent);
        return await (parts.length >= 2 ? renderH2H(parts[0], parts[1]) : renderH2HPicker(parts[0]));
      }
      return await renderHome();
    } catch (e) {
      console.error(e);
      $app.innerHTML = `<p class="err">Impossible d'afficher cette page : ${esc(e.message)}</p><p><a href="#/">Retour</a></p>`;
    }
  }
  window.addEventListener("hashchange", route);

  // =====================================================================
  // Home: the team sheet
  // =====================================================================
  async function renderHome() {
    const last = store.get("lastForm", {});
    const p = last.players || {};
    $app.innerHTML = `
      <div class="home">
        <div>
          <h1>Nouvelle analyse</h1>
          <form id="f" autocomplete="off">
            <div class="sheet">
              ${ROLES.map((r) => `
                <div class="sheet-row">
                  <label for="p-${r}">${ROLE_FR[r]}</label>
                  <input id="p-${r}" name="${r}" value="${esc(p[r] || "")}" placeholder="Pseudo#TAG" spellcheck="false">
                </div>`).join("")}
            </div>
            <div class="opts">
              <label class="field"><span>Équipe</span><input name="team" value="${esc(last.team || "")}" placeholder="Équipe adverse"></label>
              <label class="field"><span>Serveur</span>
                <select name="region">${["euw", "eune", "na", "kr", "br", "lan", "las", "oce", "tr", "jp", "me"].map((r) => `<option ${r === (last.region || "euw") ? "selected" : ""}>${r}</option>`).join("")}</select></label>
              <label class="field"><span>Période</span>
                <select name="days">${[[30, "30 jours"], [60, "60 jours"], [90, "90 jours"], [120, "120 jours"], [180, "180 jours"]].map(([v, l]) => `<option value="${v}" ${v === (last.days || 90) ? "selected" : ""}>${l}</option>`).join("")}</select></label>
              <label class="field"><span>Games max / joueur</span>
                <select name="maxGames">${[30, 60, 100, 150, 250, 400].map((v) => `<option ${v === (last.maxGames || 150) ? "selected" : ""}>${v}</option>`).join("")}</select></label>
              <label class="field"><span>Détection de smurfs</span>
                <select name="smurf">${[["off", "Non"], ["quick", "Rapide"], ["normal", "Normale"], ["deep", "Poussée"]].map(([v, l]) => `<option value="${v}" ${v === (last.smurf || "normal") ? "selected" : ""}>${l}</option>`).join("")}</select></label>
              <label class="field check"><input type="checkbox" name="timelines" ${last.timelines === false ? "" : "checked"}><span>Timelines (positions, early, pathing · ×2 requêtes)</span></label>
            </div>
            <div class="go">
              <button class="btn" type="submit">Lancer</button>
              <span id="keystate" class="keystate">Clé : vérification…</span>
            </div>
            <div id="err" class="err"></div>
          </form>
        </div>
        <aside class="folder">
          <h3>Rapports</h3>
          <div id="recent" class="muted small">…</div>
        </aside>
      </div>`;

    const f = document.getElementById("f");
    f.onsubmit = async (ev) => {
      ev.preventDefault();
      const fd = new FormData(f);
      const body = {
        players: Object.fromEntries(ROLES.map((r) => [r, (fd.get(r) || "").trim()])),
        team: fd.get("team"), region: fd.get("region"),
        days: +fd.get("days"), maxGames: +fd.get("maxGames"), smurf: fd.get("smurf"),
        timelines: !!fd.get("timelines"),
      };
      const bad = Object.entries(body.players).filter(([, v]) => v && !v.includes("#"));
      if (bad.length) { document.getElementById("err").textContent = `Format Pseudo#TAG attendu : ${bad.map(([r]) => ROLE_FR[r]).join(", ")}`; return; }
      store.set("lastForm", body);
      f.querySelector("button").disabled = true;
      try {
        const { job } = await api("/api/analyze", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
        location.hash = `#/job/${job}`;
      } catch (e) {
        document.getElementById("err").textContent = e.message;
        f.querySelector("button").disabled = false;
      }
    };

    api("/api/reports").then((list) => {
      const el = document.getElementById("recent");
      if (!el) return;
      el.innerHTML = list.length ? `<ul>${list.slice(0, 10).map((r) => reportLi(r, "refresh")).join("")}</ul>` : `<p class="empty">Aucun rapport.</p>`;
      bindReportActions(el, () => {});
    }).catch(() => {});
    api(`/api/status?region=${last.region || "euw"}`).then((s) => {
      const el = document.getElementById("keystate");
      if (!el) return;
      if (!s.ok) { el.className = "keystate bad"; el.textContent = s.error; return; }
      el.textContent = s.dev ? "Clé dev · 100 req / 2 min" : `Clé prod · ${Math.round(s.perSecond)} req/s`;
    }).catch(() => {});
  }

  // actions: "" (none), "refresh" (compact, home page) or "all" (Rapports page)
  const reportLi = (r, actions = "") => `<li class="${actions ? "with-actions" : ""}"><a href="#/r/${encodeURIComponent(r.file)}">
      <div class="t">${esc(r.team)}</div>
      <div class="s">${r.generated ? dateLong(r.generated) : ""} · ${esc((r.region || "").toUpperCase())} · ${esc((r.players || []).join(", "))}</div></a>
      ${actions === "refresh" ? `<button class="linklike icon" data-refresh="${esc(r.file)}" data-team="${esc(r.team)}" title="Rafraîchir ce rapport" aria-label="Rafraîchir ${esc(r.team)}">↻</button>` : ""}
      ${actions === "all" ? `<span class="row-actions"><a class="linklike" href="#/draft/${encodeURIComponent(r.file)}">Draft</a>
        <button class="linklike" data-refresh="${esc(r.file)}" data-team="${esc(r.team)}">Rafraîchir</button>
        <button class="linklike" data-fullrefresh="${esc(r.file)}" data-team="${esc(r.team)}" title="Retélécharge toutes les games">Complet</button>
        <button class="linklike" data-rename="${esc(r.file)}" data-team="${esc(r.team)}">Renommer</button>
        <button class="linklike danger" data-delete="${esc(r.file)}" data-team="${esc(r.team)}">Supprimer</button></span>` : ""}</li>`;

  // rename / delete, shared by the list and the report page
  async function renameReport(file, current) {
    const team = prompt("Nouveau nom de l'équipe :", current || "");
    if (team == null || !team.trim() || team.trim() === current) return false;
    await api(`/api/reports/${encodeURIComponent(file)}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ team: team.trim() }) });
    return true;
  }
  async function deleteReport(file, team) {
    if (!confirm(`Supprimer définitivement le rapport « ${team} » ? (les games en cache sont conservées)`)) return false;
    await api(`/api/reports/${encodeURIComponent(file)}`, { method: "DELETE" });
    return true;
  }
  async function refreshReport(file, team) {
    if (!confirm(`Relancer l'analyse de « ${team} » avec les mêmes joueurs et réglages ? Le rapport sera remplacé par la version à jour (les games déjà téléchargées restent en cache).`)) return;
    const { job } = await api(`/api/reports/${encodeURIComponent(file)}/refresh`, { method: "POST" });
    location.hash = `#/job/${job}`;
  }
  async function fullRefreshReport(file, team) {
    if (!confirm(`Rafraîchissement complet de « ${team} » : toutes les games sont retéléchargées (cache ignoré) puis le rapport est reconstruit avec la version actuelle de l'analyse.\n\nÀ utiliser si le rapport date d'une ancienne version ou d'une autre clé API. Beaucoup plus long qu'un rafraîchissement normal (plusieurs minutes, jusqu'à ~20 min avec une clé dev). Continuer ?`)) return;
    const { job } = await api(`/api/reports/${encodeURIComponent(file)}/refresh`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ full: true }) });
    location.hash = `#/job/${job}`;
  }
  function bindReportActions(root, after) {
    root.querySelectorAll("[data-refresh]").forEach((b) => (b.onclick = async (e) => {
      e.preventDefault();
      try { await refreshReport(b.dataset.refresh, b.dataset.team); } catch (err) { alert(err.message); }
    }));
    root.querySelectorAll("[data-fullrefresh]").forEach((b) => (b.onclick = async (e) => {
      e.preventDefault();
      try { await fullRefreshReport(b.dataset.fullrefresh, b.dataset.team); } catch (err) { alert(err.message); }
    }));
    root.querySelectorAll("[data-rename]").forEach((b) => (b.onclick = async (e) => {
      e.preventDefault();
      try { if (await renameReport(b.dataset.rename, b.dataset.team)) after("rename"); } catch (err) { alert(err.message); }
    }));
    root.querySelectorAll("[data-delete]").forEach((b) => (b.onclick = async (e) => {
      e.preventDefault();
      try { if (await deleteReport(b.dataset.delete, b.dataset.team)) after("delete"); } catch (err) { alert(err.message); }
    }));
  }

  async function renderReports() {
    const list = await api("/api/reports");
    $app.innerHTML = `<div class="folder" style="max-width:860px">
      <h1 style="margin-bottom:14px">Rapports</h1>
      ${list.length ? `<ul>${list.map((r) => reportLi(r, "all")).join("")}</ul>` : `<p class="empty">Aucun rapport.</p>`}</div>`;
    bindReportActions($app, () => renderReports());
  }

  // =====================================================================
  // Job progress
  // =====================================================================
  function renderJob(id) {
    $app.innerHTML = `<div class="progress"><h1>Analyse en cours</h1>
      <div class="bar"><i id="pbar" style="width:2%"></i></div><div id="pinfo" class="muted small"></div>
      <div id="pplayers" class="ptable"></div><div id="plog" class="log"></div></div>`;
    const tick = async () => {
      let j;
      try { j = await api(`/api/jobs/${id}`); } catch { clearInterval(poller); $app.innerHTML = `<p class="err">Cette analyse n'existe plus (le serveur a redémarré ?).</p>`; return; }
      const pr = j.progress || {};
      if (j.status === "done") { clearInterval(poller); location.hash = `#/r/${encodeURIComponent(j.report)}`; return; }
      if (j.status === "error") {
        clearInterval(poller);
        document.querySelector(".progress h1").textContent = "Erreur";
        document.getElementById("pinfo").innerHTML = `<span class="err">${esc(j.error)}</span> <a href="#/">Retour</a>`;
      }
      const total = pr.total || 0, done = pr.done || 0;
      const frac = total ? Math.min(1, done / total) : 0.03;
      document.getElementById("pbar").style.width = `${Math.max(3, frac * 100)}%`;
      const eta = pr.eta ? ` · estimation ≈ ${Math.max(1, Math.round(pr.eta / 60))} min` : "";
      document.getElementById("pinfo").textContent = `${Math.floor(j.elapsed / 60)} min ${j.elapsed % 60} s${eta}`;
      document.getElementById("pplayers").innerHTML = Object.entries(pr.players || {}).map(([n, s]) => `<div><span>${esc(n)}</span><span class="muted">${esc(s.games || "")} games</span></div>`).join("");
      document.getElementById("plog").innerHTML = (pr.log || []).slice(-14).map((l) => `<div><time>${new Date(l.t * 1000).toLocaleTimeString("fr-FR")}</time>${esc(l.msg)}</div>`).join("");
    };
    tick();
    poller = setInterval(tick, 1500);
  }

  // =====================================================================
  // Report
  // =====================================================================
  async function renderReport(file) {
    $app.innerHTML = `<p class="muted">Chargement…</p>`;
    R = upgrade(await api(`/api/reports/${encodeURIComponent(file)}`));
    const P = R.players;
    const SM = R.smurfPlayers || [];
    const smurfsOf = (p) => SM.filter((x) => x.smurfOf && x.smurfOf.role === p.role);
    const toc = [
      ["ensemble", "Vue d'ensemble"],
      ...P.flatMap((p) => [[pid(p), `${ROLE_FR[p.role]} · ${p.name}`], ...smurfsOf(p).map((x) => [pid(x), `↳ smurf · ${x.name}`])]),
      R.botlane ? ["botlane", "Botlane"] : null,
      ["premades", "Premades"],
      R.stack ? ["compos", "Compos en équipe"] : null,
      R.smurf && R.smurf.enabled ? ["smurfs", "Détection de smurfs"] : null,
    ].filter(Boolean);

    $app.innerHTML = `<div class="report">
      <nav class="toc" id="toc">
        ${toc.map(([id, l]) => `<a href="#${id}" data-target="${id}">${esc(l)}</a>`).join("")}
        <div class="tools noprint">
          <button class="btn ghost" onclick="window.print()">Imprimer / PDF</button>
          <a class="btn ghost" href="#/h2h/${encodeURIComponent(file)}">Face à face…</a>
          <a class="btn ghost" href="#/draft/${encodeURIComponent(file)}">Draft contre eux</a>
          <button class="btn ghost" data-refresh="${esc(file)}" data-team="${esc(R.team)}">Rafraîchir</button>
          <button class="btn ghost" data-fullrefresh="${esc(file)}" data-team="${esc(R.team)}" title="Retélécharge toutes les games et reconstruit le rapport">Rafraîchissement complet</button>
          <div class="row-actions">
            <button class="linklike" data-rename="${esc(file)}" data-team="${esc(R.team)}">Renommer</button>
            <button class="linklike danger" data-delete="${esc(file)}" data-team="${esc(R.team)}">Supprimer</button>
          </div>
        </div>
      </nav>
      <div id="doc">
        ${R.outdated ? `<p class="err">Rapport créé par une ancienne version : certaines sections (signaux, smurfs analysés, face à face) sont vides. <button class="linklike" data-refresh="${esc(file)}" data-team="${esc(R.team)}">Rafraîchis le rapport</button> — les games sont en cache, c'est rapide.</p>` : ""}
        ${R.stats && R.stats.staleRefetched ? `<p class="caption">${R.stats.staleRefetched} games du cache venaient d'une autre clé API et ont été retéléchargées.</p>` : ""}
        ${overview()}
        ${P.map((p) => playerPage(p) + smurfsOf(p).map(playerPage).join("")).join("")}
        ${R.botlane ? botlanePage() : ""}
        ${premadesPage()}
        ${R.stack ? compsPage() : ""}
        ${R.smurf && R.smurf.enabled ? smurfPage() : ""}
        <p class="muted small">${dateLong(R.generated)} · ${R.stats.games} games · ${R.stats.requests} requêtes API (${R.stats.cacheHits} en cache) · Data Dragon ${esc(R.static.version)}</p>
      </div>
    </div>`;

    document.querySelectorAll("#toc a[data-target]").forEach((a) => {
      a.onclick = (e) => { e.preventDefault(); document.getElementById(a.dataset.target).scrollIntoView({ behavior: "smooth", block: "start" }); };
    });
    hydrateMaps();
    spyToc();
    bindReportActions(document.querySelector(".report"), (what) => {
      if (what === "delete") location.hash = "#/reports";
      else renderReport(file);
    });
  }

  // Reports made by an older version lack some fields: fill them so the page still renders.
  function upgrade(rep) {
    rep.outdated = !(rep.version >= 2);
    rep.smurfPlayers = rep.smurfPlayers || [];
    rep.botlaneSignals = rep.botlaneSignals || [];
    rep.teamBans = rep.teamBans || [];
    rep.players.forEach((p) => {
      p.signals = p.signals || [];
      p.objPart = p.objPart ?? (p.metrics ? p.metrics.objPart : null);
      p.surrender = p.surrender || { throws: 0, ahead20: 0, comebacks: 0, behind20: 0, ffLoss: null };
      p.log = p.log || [];
    });
    return rep;
  }

  const pid = (p) => (p.smurfOf ? `s-${p.role.toLowerCase()}-${p.puuid.slice(0, 8)}` : `p-${p.role.toLowerCase()}`);

  function spyToc() {
    const links = [...document.querySelectorAll("#toc a[data-target]")];
    const obs = new IntersectionObserver((entries) => {
      entries.forEach((en) => {
        if (en.isIntersecting) links.forEach((l) => l.classList.toggle("on", l.dataset.target === en.target.id));
      });
    }, { rootMargin: "-20% 0px -70% 0px" });
    links.forEach((l) => { const s = document.getElementById(l.dataset.target); if (s) obs.observe(s); });
  }

  // ---------- overview ----------
  function soloRank(p) {
    const r = (p.ranks || []).find((x) => x.queue === "SoloQ") || (p.ranks || [])[0];
    return r ? `${r.queue} : ${esc(r.label)} <span class="sec">(${pct(r.wr)} sur ${r.g} games)</span>` : `<span class="muted">non classé</span>`;
  }

  function overview() {
    const P = R.players;
    const SM = R.smurfPlayers || [];
    const queues = [...new Set(P.flatMap((p) => Object.keys(p.queues)))].join(" + ");
    const row = (p, smurf) => `<tr class="${smurf ? "subrow" : ""}">
          <td>${smurf ? "↳ " : ""}<a href="#" onclick="document.getElementById('${pid(p)}').scrollIntoView({behavior:'smooth'});return false">${esc(p.name)}<span class="muted">#${esc(p.tag)}</span></a>${smurf ? ` <span class="flag">smurf ${p.smurfOf.score}</span>` : ""}</td>
          <td>${smurf ? "" : ROLE_FR[p.role]}</td>
          <td>${soloRank(p)}</td>
          <td class="n">${p.games}</td>
          <td class="n">${wr(p.wr, p.games)}</td>
          <td class="n">${num(p.kda.ratio, 2)}</td>
          <td class="n ${p.role === "UTILITY" ? "muted" : sgnCls(p.early.gd15, 50)}">${signed(p.early.gd15)}</td>
          <td class="n">${num(p.early.deaths14)}</td>
          <td><span class="chips">${p.champions.slice(0, 3).map((c) => champ(c.champ, "ic sm")).join("")}</span></td>
        </tr>`;
    const sigRows = [...P, ...SM].flatMap((p) => p.signals.filter((x) => x.tone !== "info").slice(0, 3).map((x) => [p, x]));
    return `<section class="page cover" id="ensemble">
      <h1>${esc(R.team)}</h1>
      <p class="meta">${dateLong(R.generated)} · ${esc(queues)} · ${R.params.days} j · ${esc(R.region.toUpperCase())}</p>
      <p class="legend">GD / CSD / XPD : écart avec le vis-à-vis à 15 min · WR vert ≥ 55 %, rouge ≤ 45 % (≥ 3 games) · ↳ smurf : compte secondaire probable (score ≥ 80), analysé comme un titulaire.</p>

      <div class="tbl-wrap"><table>
        <tr><th>Joueur</th><th>Rôle</th><th>Rang</th><th class="n">G</th><th class="n">WR</th><th class="n">KDA</th><th class="n">GD@15</th><th class="n">Morts &lt;14</th><th>Champions</th></tr>
        ${P.map((p) => row(p, false) + SM.filter((x) => x.smurfOf.role === p.role).map((x) => row(x, true)).join("")).join("")}
      </table></div>

      <div class="two">
        <div>
          <div class="sub"><h3>Bans conseillés</h3></div>
          ${R.teamBans.length ? `<table><tr><th>#</th><th>Champion</th><th>Joueur</th><th class="n">G</th><th class="n">WR</th><th class="n">30 j</th></tr>
            ${R.teamBans.map((b, i) => `<tr><td>${i + 1}</td><td>${champ(b.champ)}</td><td>${esc(b.player)}</td><td class="n">${b.g}</td><td class="n">${wr(b.wr, b.g)}</td><td class="n">${b.g30}</td></tr>`).join("")}</table>`
            : `<p class="empty">Aucun candidat.</p>`}
        </div>
        <div>
          <div class="sub"><h3>Signaux clés</h3></div>
          ${sigRows.length ? `<table><tr><th>Joueur</th><th>Indicateur</th><th class="n">Valeur</th><th>Contexte</th></tr>${sigRows.map(([p, x]) => `<tr class="sig t-${x.tone}"><td>${esc(p.name)}</td><td>${sigLabel(x)}</td><td class="n"><b>${esc(x.value)}</b></td><td class="sec">${esc(x.ctx || "")}</td></tr>`).join("")}</table>` : `<p class="empty">–</p>`}
        </div>
      </div>
    </section>`;
  }

  const sigLabel = (x) => `${esc(x.label)}${x.champ != null ? " " + champ(x.champ, "ic sm") : ""}`;
  function signalsTable(list) {
    if (!list.length) return `<p class="empty">Aucun signal marquant.</p>`;
    const cats = [...new Set(list.map((x) => x.cat))];
    const sorted = cats.flatMap((c) => list.filter((x) => x.cat === c));
    const half = Math.ceil(sorted.length / 2);
    const col = (rows) => `<table class="signals"><tr><th></th><th>Indicateur</th><th class="n">Valeur</th><th>Contexte</th></tr>
      ${rows.map((x) => `<tr class="sig t-${x.tone}"><td class="cat">${esc(x.cat)}</td><td>${sigLabel(x)}</td><td class="n"><b>${esc(x.value)}</b></td><td class="sec">${esc(x.ctx || "")}</td></tr>`).join("")}</table>`;
    return `<div class="two">${col(sorted.slice(0, half))}${sorted.length > half ? col(sorted.slice(half)) : "<div></div>"}</div>`;
  }

  // ---------- player ----------
  const rk = () => "";
  const med = () => "";
  const kv = (k, v, extra = "") => `<div class="kv"><span class="k">${k}</span><span class="v">${v}${extra}</span></div>`;

  function playerPage(p) {
    const e = p.early, s = p.style;
    const spells = p.spells.map(([ids, n]) => `${ids.map(spellImg).join("")}${ids.map(spellName).join(" + ")} <span class="muted">(${n})</span>`).join(" · ");
    const ranks = (p.ranks || []).map((r) => `<span>${esc(r.queue)} <b>${esc(r.label)}</b> <span class="muted">${pct(r.wr)} · ${r.g} g</span></span>`).join("");
    const q = p.queues;
    const qline = (label) => q[label] ? `${q[label].g}g · ${wr(q[label].wr, q[label].g)}` : `<span class="muted">–</span>`;
    const focusNote = p.focusGames !== p.games ? `<span class="muted small">stats de jeu : ${p.focusGames} games ${ROLE_FR[p.role]} / ${p.games}</span>` : "";
    const sm = p.smurfOf;

    return `<section class="page ${sm ? "smurf-page" : ""}" id="${pid(p)}">
      <div class="phead">
        <div>
          <div class="kicker">${sm ? `Smurf probable de <b>${esc(sm.name)}</b> · score ${sm.score}/100 · ` : ""}${ROLE_FR[p.role]}${p.level ? ` · niv. ${p.level}` : ""}</div>
          <h2>${esc(p.name)}<span class="tag">#${esc(p.tag)}</span></h2>
          <div class="line">${ranks || `<span class="muted">Non classé</span>`}</div>
          <div class="line"><span>${spells || "–"}</span></div>
        </div>
      </div>

      <div class="sub"><h3>Signaux</h3></div>
      ${signalsTable(p.signals)}

      <div class="banline">
        <span class="lbl">Bans</span>
        ${p.bans.length ? p.bans.map((b) => `<span>${champ(b.champ)} <span class="muted small">${b.g} g · ${pct(b.wr)}</span></span>`).join("") : `<span class="muted">–</span>`}
        ${p.rising.length ? `<span class="lbl" style="margin-left:18px">En hausse</span>${p.rising.map((r) => `<span>${champ(r.champ)} <span class="muted small">${r.g30} g / 30 j</span></span>`).join("")}` : ""}
      </div>

      ${sm && p.combined ? `<div class="sub"><h3>Pool combiné</h3><span class="muted">${esc(sm.name)} + ${esc(p.name)}</span></div>
        <div class="tbl-wrap"><table><tr><th>Champion</th><th class="n">G total</th><th class="n">WR total</th><th class="n">G main</th><th class="n">WR main</th><th class="n">G smurf</th><th class="n">WR smurf</th></tr>
        ${p.combined.map((c) => `<tr><td>${champ(c.champ)}</td><td class="n"><b>${c.g}</b></td><td class="n">${wr(c.wr, c.g)}</td><td class="n">${c.gMain || "–"}</td><td class="n">${c.gMain ? wr(c.wrMain, c.gMain) : "–"}</td><td class="n">${c.gSmurf || "–"}</td><td class="n">${c.gSmurf ? wr(c.wrSmurf, c.gSmurf) : "–"}</td></tr>`).join("")}</table></div>` : ""}

      <div class="sub"><h3>Chiffres</h3>${focusNote}</div>
      <div class="blocks">
        <div class="blk"><h4>Bilan</h4>
          ${kv("Games", p.games)}
          ${kv("Winrate", wr(p.focusWr, p.focusGames), rk(p, "wr"))}
          ${kv("KDA", `<span class="sec">${num(p.kda.k)}/${num(p.kda.d)}/${num(p.kda.a)}</span> ${num(p.kda.ratio, 2)}`, rk(p, "kda"))}
          ${kv("SoloQ", qline("SoloQ"))}
          ${kv("Flex", qline("Flex"))}
          ${kv("Ranked 5 stack", qline("Ranked 5 stack"))}
          ${kv("10 dernières", `${p.last10.w}/${p.last10.g} <span class="sec">· série ${p.streak.n} ${p.streak.win ? "V" : "D"}</span>`)}
        </div>
        <div class="blk"><h4>Early game (à 15 min)</h4>
          ${kv("Écart d'or", `<span class="${sgnCls(e.gd15, 50)}">${signed(e.gd15)}</span>`, rk(p, "gd15"))}
          ${kv("Écart de CS", `<span class="${sgnCls(e.csd15, 2)}">${signed(e.csd15)}</span>`, rk(p, "csd15"))}
          ${kv("Écart d'XP", `<span class="${sgnCls(e.xpd15, 50)}">${signed(e.xpd15)}</span>`, rk(p, "xpd15"))}
          ${kv(p.role === "JUNGLE" ? "Games avec avance" : "Lanes gagnées", pct(e.lanesWon), rk(p, "lanesWon"))}
          ${kv("First blood", pct(e.fb), rk(p, "fb"))}
          ${kv("Solo kills / game", num(e.soloKills), rk(p, "soloKills"))}
          ${kv("Morts avant 14 min", num(e.deaths14), rk(p, "deaths14"))}
          ${kv(p.role === "JUNGLE" ? "… dont vs jungler adverse" : "… dont sur gank", num(e.deathsGank14), rk(p, "deathsGank14"))}
        </div>
        <div class="blk"><h4>Style de jeu</h4>
          ${kv("Participation aux kills", pct(s.kp), rk(p, "kp"))}
          ${kv("Part des dégâts de l'équipe", pct(s.dmgShare), rk(p, "dmgShare"))}
          ${kv("Dégâts / min", num(s.dpm, 0), rk(p, "dpm"))}
          ${kv("CS / min", num(s.csm), rk(p, "csm"))}
          ${kv("Vision / min", num(s.vspm, 2), rk(p, "vspm"))}
          ${kv("Pinks / game", num(s.pinks), rk(p, "pinks"))}
          ${kv("Participation aux objectifs", pct(p.objPart), rk(p, "objPart"))}
        </div>
        <div class="blk"><h4>Durée des games</h4>
          ${kv("Durée moyenne", `${num(p.duration.avg, 0)} min`)}
          ${kv("WR games < 25 min", `${wr(p.duration.short.wr, p.duration.short.g)} <span class="sec">(${p.duration.short.g}g)</span>`)}
          ${kv("WR games > 32 min", `${wr(p.duration.long.wr, p.duration.long.g)} <span class="sec">(${p.duration.long.g}g)</span>`)}
          ${kv("Côté bleu", `${wr(p.side.blue.wr, p.side.blue.g)} <span class="sec">(${p.side.blue.g}g)</span>`)}
          ${kv("Côté rouge", `${wr(p.side.red.wr, p.side.red.g)} <span class="sec">(${p.side.red.g}g)</span>`)}
          ${kv("Temps passé mort", pct(s.timeDead))}
        </div>
      </div>

      <div class="sub"><h3>Détail de l'early</h3></div>
      <div class="detail">
        <div>
          ${kv("Écart d'or à 10 min", `<span class="${sgnCls(e.gd10, 50)}">${signed(e.gd10)}</span>`, med(p, "gd10", (v) => signed(v)))}
          ${kv("Écart de CS à 10 min", `<span class="${sgnCls(e.csd10, 1)}">${signed(e.csd10, 1)}</span>`, med(p, "csd10", (v) => signed(v, 1)))}
          ${kv("CS à 10 min", num(e.cs10, 0), med(p, "cs10", (v) => num(v, 0)))}
          ${kv(p.role === "JUNGLE" ? "Kills sur le jungler adverse (< 14 min)" : "Kills sur le vis-à-vis (< 14 min)", num(e.killsOnOpp14), med(p, "killsOnOpp14", num))}
          ${kv("Tué en 1v1 avant 14 min", num(e.deaths1v1_14), med(p, "deaths1v1_14", num))}
        </div>
        <div>
          ${kv(p.role === "JUNGLE" ? "… dont par le jungler adverse" : "… dont par le vis-à-vis", num(e.deaths1v1Opp14), med(p, "deaths1v1Opp14", num))}
          ${kv("Morts en 1v1 (toute la game)", num(e.deaths1v1), med(p, "deaths1v1", num))}
          ${kv("Morts avant 6 min", num(e.deaths6, 2), med(p, "deaths6", (v) => num(v, 2)))}
          ${kv("Première mort (moyenne)", e.firstDeath ? `${num(e.firstDeath / 60, 0)} min` : "–", med(p, "firstDeath", (v) => num(v / 60, 0) + " min"))}
          ${kv("Aucune mort avant 14 min", pct(e.noDeath14), med(p, "noDeath14", pct))}
        </div>
        <div>
          ${kv("Donne le first blood", pct(e.gaveFB), med(p, "gaveFB", pct))}
          ${kv("WR en avance à 15 min", `${wr(e.wrAhead15, e.gAhead15)} <span class="sec">(${e.gAhead15}g)</span>`, med(p, "wrAhead15", pct))}
          ${kv("WR en retard à 15 min", `${wr(e.wrBehind15, e.gBehind15)} <span class="sec">(${e.gBehind15}g)</span>`, med(p, "wrBehind15", pct))}
          ${kv("Niveau 6", e.lvl6 ? mmss(e.lvl6) : "–", e.lvl6Diff != null ? `<span class="med">(${signed(e.lvl6Diff)} s vs vis-à-vis)</span>` : "")}
          ${kv("Premier retour en base", e.firstBack ? mmss(e.firstBack) : "–")}
          ${p.role !== "JUNGLE" && p.role !== "UTILITY" ? kv("Plaques prises / game", num(e.plates)) : ""}
        </div>
      </div>

      ${championsTable(p)}
      ${matchupTables(p)}
      ${movementSection(p)}
      ${extrasSection(p)}
    </section>`;
  }

  function championsTable(p) {
    return `<div class="sub"><h3>Champions</h3><span class="muted">toutes ses games de la période · 30 j = games sur les 30 derniers jours</span></div>
    <div class="tbl-wrap"><table>
      <tr><th>Champion</th><th class="n">G</th><th class="n">WR</th><th class="n">30 j</th><th>KDA</th><th class="n">CS/m</th><th class="n">Dmg/m</th><th class="n">KP</th>
      <th class="n">GD@15</th><th class="n">CSD@15</th><th>Rune (la + jouée)</th><th>1<sup>er</sup> item (le + acheté)</th><th class="n">Dernière</th></tr>
      ${p.champions.map((c) => `<tr>
        <td>${champ(c.champ)}</td><td class="n">${c.g}</td><td class="n">${wr(c.wr, c.g)}</td><td class="n">${c.g30 || `<span class="muted">0</span>`}</td>
        <td><b>${num(c.kda, 2)}</b> <span class="sec">(${num(c.k)}/${num(c.d)}/${num(c.a)})</span></td>
        <td class="n">${num(c.csm)}</td><td class="n">${num(c.dpm, 0)}</td><td class="n">${pct(c.kp)}</td>
        <td class="n ${sgnCls(c.gd15, 50)}">${signed(c.gd15)}</td><td class="n ${sgnCls(c.csd15, 2)}">${signed(c.csd15)}</td>
        <td>${c.rune ? `${rune(c.rune[0])} <span class="sec">${c.rune[1]}/${c.rune[2]}</span>` : "–"}</td>
        <td>${c.item ? `${itemImg(c.item[0])}${esc(itemName(c.item[0]))} <span class="sec">${c.item[1]}/${c.item[2]}</span>` : "–"}</td>
        <td class="n">${date(c.last)}</td></tr>`).join("")}
    </table></div>`;
  }

  function vsTable(rows, head, keyFn) {
    if (!rows.length) return `<p class="empty">Pas assez de games.</p>`;
    return `<div class="tbl-wrap"><table><tr><th>${head}</th><th class="n">G</th><th class="n">WR</th><th class="n">KDA</th><th class="n">GD@15</th><th>Il joue</th></tr>
      ${rows.map((r) => `<tr><td>${keyFn(r.key)}</td><td class="n">${r.g}</td><td class="n">${wr(r.wr, r.g)}</td><td class="n">${num(r.kda, 2)}</td>
      <td class="n ${sgnCls(r.gd15, 50)}">${signed(r.gd15)}</td><td>${played(r.played)}</td></tr>`).join("")}</table></div>`;
  }

  function matchupTables(p) {
    return `<div class="two">
      <div><div class="sub"><h3>Contre quel vis-à-vis</h3><span class="muted">au moins 2 games</span></div>${vsTable(p.vsOpp, "Vis-à-vis", (k) => champ(k))}</div>
      <div><div class="sub"><h3>Contre quel type de champion</h3></div>${vsTable(p.vsClass, "Classe adverse", esc)}</div>
    </div>`;
  }

  // ---------- movement / maps ----------
  let mapId = 0;
  const MAPS = {};
  function mapSlot(kind, data, opts, caption) {
    const id = `map${++mapId}`;
    MAPS[id] = { kind, data, opts };
    return `<div class="mapbox"><div id="${id}"></div><figcaption>${caption}</figcaption></div>`;
  }
  function hydrateMaps() {
    Object.entries(MAPS).forEach(([id, m]) => {
      const el = document.getElementById(id);
      if (!el) return;
      const fig = m.kind === "events" ? RiftMaps.eventMap(R.static.version, m.data, m.opts) : RiftMaps.heatMap(R.static.version, m.data, m.opts);
      el.appendChild(fig);
      delete MAPS[id];
    });
  }
  const bars = (rows, total) => rows.map(([label, n, extra]) => `<tr><td>${esc(label)}</td><td class="n">${n}</td>
      <td><div class="barcell"><i style="width:${Math.round(100 * n / Math.max(total, 1))}px"></i><span>${pct(n / Math.max(total, 1))}${extra ? " · " + extra : ""}</span></div></td></tr>`).join("");

  function eventCounts(evs) {
    const c = { k: 0, a: 0, d: 0 };
    evs.forEach((e) => c[e[3]]++);
    return `<span class="dot-k">●</span> ${c.k} · <span class="dot-a">○</span> ${c.a} · <span class="dot-d">✕</span> ${c.d}`;
  }

  function movementSection(p) {
    const mv = p.movement;
    if (!mv || !mv.games) return `<p class="muted small">Pas de timeline disponible : positions et pathing non calculés.</p>`;
    const ev = mv.events || [];
    const ev07 = ev.filter((e) => e[0] < 420), ev714 = ev.filter((e) => e[0] >= 420);
    const zoneRows = (mv.zoneTable || []).map((z) => `<tr><td>${esc(z.zone)}</td><td class="n good">${z.k}</td><td class="n">${z.a}</td><td class="n bad">${z.d}</td></tr>`).join("");
    const totals = ev.reduce((a, e) => (a[e[3]]++, a), { k: 0, a: 0, d: 0 });
    const killMaps = `<div class="sub"><h3>Kills, assists et morts avant 14 min</h3></div>
      <div class="three" style="grid-template-columns:1fr 1fr 1.1fr">
        ${mapSlot("events", ev07, {}, `0 à 7 min · ${eventCounts(ev07)}`)}
        ${mapSlot("events", ev714, {}, `7 à 14 min · ${eventCounts(ev714)}`)}
        <div><div class="tbl-wrap"><table><tr><th>Zone</th><th class="n">Kills</th><th class="n">Assists</th><th class="n">Morts</th></tr>${zoneRows}</table></div>
        <p class="caption">${totals.k} K · ${totals.a} A · ${totals.d} M · ${mv.games} games · positions brutes, sans miroir</p></div>
      </div>`;
    const pos = mv.positions || [];
    const heat = (from, to) => pos.filter((x) => x[0] >= from && x[0] <= to).map((x) => [x[1], x[2], x[3]]);
    const heatmaps = `<div class="maps" style="margin-top:12px">
        ${mapSlot("heat", heat(1, 6), {}, "1 à 6 min")}
        ${mapSlot("heat", heat(7, 14), {}, "7 à 14 min")}
      </div><p class="caption">1 position / min / game · côté rouge mis en miroir (base en bas à gauche)</p>`;
    const zt = mv.zoneTime || [];
    const ztTotal = zt.reduce((a, z) => a + z[1], 0);
    const timeTable = `<div class="tbl-wrap"><table><tr><th>Zone</th><th class="n">Minutes</th><th></th></tr>${bars(zt.map((z) => [z[0], z[1]]), ztTotal)}</table></div>`;

    if (p.role === "JUNGLE") {
      const side = mv.startSide || [];
      const sideTotal = side.reduce((a, s) => a + s[1], 0);
      return `<div class="sub"><h2 style="font-size:24px">Pathing jungle</h2></div>
        <div class="figures">
          <div class="fig"><div class="v">${mv.games}</div><div class="k">games avec timeline</div></div>
          <div class="fig"><div class="v">${pct(mv.invade1)}</div><div class="k">invade niveau 1</div></div>
          <div class="fig"><div class="v">${pct(mv.enemyJg6)}</div><div class="k">dans la jungle adverse avant 6 min</div></div>
          <div class="fig"><div class="v">${pct(mv.scuttle34)}</div><div class="k">au scuttle à 3-4 min</div></div>
          <div class="fig"><div class="v">${pct(mv.back35)}</div><div class="k">back entre 3 et 5 min</div></div>
          ${mv.firstTakedown && mv.firstTakedown[0] ? `<div class="fig"><div class="v">${esc(mv.firstTakedown[0][0])}</div><div class="k">1<sup>er</sup> kill/assist, vers ${num(mv.firstTakedown[0][2])} min</div></div>` : ""}
          ${p.jungle ? `<div class="fig"><div class="v">${num(p.jungle.jgCs10, 0)}</div><div class="k">camps tués avant 10 min</div></div>
          <div class="fig"><div class="v">${num(p.jungle.enemyCamps)}</div><div class="k">camps adverses volés / game</div></div>` : ""}
        </div>
        ${killMaps}
        <div class="three" style="grid-template-columns:repeat(4,minmax(0,1fr));gap:0 22px">
          <div><div class="sub"><h3>Côté de départ</h3></div><table><tr><th>Côté</th><th class="n">G</th><th></th></tr>${bars(side, sideTotal)}</table>
            <p class="caption">Par champion : ${(mv.startSideByChamp || []).map(([c, s, n, t]) => `${champInfo(c)[1]} ${s} ${n}/${t}`).join(" · ")}</p></div>
          <div><div class="sub"><h3>Où est-il à 3:00 ?</h3></div><table><tr><th>Zone</th><th class="n">G</th><th></th></tr>${bars(mv.at3 || [], mv.games)}</table></div>
          <div><div class="sub"><h3>Et à 4:00 ?</h3></div><table><tr><th>Zone</th><th class="n">G</th><th></th></tr>${bars(mv.at4 || [], mv.games)}</table></div>
          <div><div class="sub"><h3>Première lane visitée</h3><span class="muted">2-10 min</span></div><table><tr><th>Lane</th><th class="n">G</th><th></th></tr>
            ${bars((mv.firstLane || []).map(([l, n, m]) => [l.replace("Lane ", ""), n, `≈ ${num(m, 0)} min`]), mv.games)}</table></div>
        </div>
        <div class="sub"><h3>Où il passe son temps</h3><span class="muted">positions de 1 à 14 min</span></div>
        <div class="two"><div>${heatmaps}</div><div>${timeTable}</div></div>`;
    }

    let head = "", extra = "";
    if (p.role === "MIDDLE") {
      const o = mv.outside || {};
      head = `<div class="sub"><h2 style="font-size:24px">Roams</h2></div><div class="figures">
        <div class="fig"><div class="v">${mv.games}</div><div class="k">games avec positions</div></div>
        <div class="fig"><div class="v">${pct(mv.roamRate)}</div><div class="k">roam entre 3 et 14 min</div></div>
        <div class="fig"><div class="v">${mv.firstRoam ? num(mv.firstRoam, 0) + " min" : "–"}</div><div class="k">1<sup>er</sup> roam (moyenne)</div></div>
        <div class="fig"><div class="v">${o.of ? pct(o.n / o.of) : "–"} <span class="muted small">(${o.n || 0}/${o.of || 0})</span></div><div class="k">kills/assists hors mid</div></div>
        <div class="fig"><div class="v">${o.top || 0}</div><div class="k">… côté top</div></div>
        <div class="fig"><div class="v">${o.bot || 0}</div><div class="k">… côté bot</div></div></div>`;
      extra = `<div class="two"><div><div class="sub"><h3>Destination du premier roam</h3><span class="muted">3-14 min</span></div>
        <table><tr><th>Côté</th><th class="n">G</th><th></th></tr>${bars(mv.roamDest || [], mv.games)}</table>
        <p class="caption">Roam : position en lane top/bot, Drake ou Nashor entre 3 et 14 min</p></div>
        <div><div class="sub"><h3>Où il passe son temps</h3><span class="muted">3 à 14 min</span></div>${timeTable}</div></div>`;
    } else if (p.role === "UTILITY") {
      head = `<div class="sub"><h2 style="font-size:24px">Déplacements avant 15 min</h2></div><div class="figures">
        <div class="fig"><div class="v">${mv.games}</div><div class="k">games avec positions</div></div>
        <div class="fig"><div class="v">${pct(mv.roamRate)}</div><div class="k">roam avant 14 min</div></div>
        <div class="fig"><div class="v">${mv.firstRoam ? num(mv.firstRoam, 0) + " min" : "–"}</div><div class="k">1<sup>er</sup> roam (moyenne)</div></div>
        <div class="fig"><div class="v">${pct(mv.enemyJungleTime)}</div><div class="k">temps en jungle adverse</div></div>
        <div class="fig"><div class="v">${pct(mv.riverBotTime)}</div><div class="k">temps rivière bot</div></div></div>`;
      extra = `<div class="two"><div><div class="sub"><h3>Destination du premier roam</h3></div>
        <table><tr><th>Zone</th><th class="n">G</th><th></th></tr>${bars(mv.roamDest || [], mv.games)}</table>
        <p class="caption">Roam : mid, top, rivière top ou jungle côté top entre 3 et 14 min</p></div>
        <div><div class="sub"><h3>Répartition de son temps</h3><span class="muted">3 à 14 min</span></div>${timeTable}</div></div>`;
    } else {
      head = `<div class="sub"><h2 style="font-size:24px">Positions avant 15 min</h2></div><div class="figures">
        <div class="fig"><div class="v">${mv.games}</div><div class="k">games avec positions</div></div>
        <div class="fig"><div class="v">${pct(mv.roamRate)}</div><div class="k">quitte sa lane avant 14 min</div></div>
        <div class="fig"><div class="v">${mv.firstRoam ? num(mv.firstRoam, 0) + " min" : "–"}</div><div class="k">1<sup>re</sup> sortie (moyenne)</div></div></div>`;
      extra = `<div class="two"><div><div class="sub"><h3>Où il passe son temps</h3><span class="muted">3 à 14 min</span></div>${timeTable}</div>
        <div><div class="sub"><h3>Sorties de lane</h3></div><table><tr><th>Vers</th><th class="n">G</th><th></th></tr>${bars(mv.roamDest || [], mv.games)}</table></div></div>`;
    }
    return `${head}${heatmaps}${extra}${killMaps}`;
  }

  // ---------- extras ----------
  function extrasSection(p) {
    const obj = p.objectives || {};
    const objName = { DRAGON: "Drakes", HORDE: "Grubs", RIFTHERALD: "Héraut", BARON_NASHOR: "Nashor", ATAKHAN: "Atakhan" };
    const objRows = Object.entries(objName).filter(([k]) => obj[k]).map(([k, l]) => `<tr><td>${l}</td><td class="n">${obj[k].team}</td><td class="n">${obj[k].me}</td><td class="n">${pct(obj[k].part)}</td><td class="n">${obj[k].enemy}</td></tr>`).join("");
    const su = p.surrender;
    return `<div class="three">
        <div><div class="sub"><h3>Objectifs</h3></div>
          ${objRows ? `<table><tr><th></th><th class="n">Équipe</th><th class="n">Avec lui</th><th class="n">Part.</th><th class="n">Adv.</th></tr>${objRows}</table>` : `<p class="empty">–</p>`}</div>
        <div><div class="sub"><h3>Gestion de partie</h3></div>
          ${kv("Avances perdues (+3k @20)", `${su.throws}/${su.ahead20}`)}
          ${kv("Remontées (−3k @20)", `${su.comebacks}/${su.behind20}`)}
          ${kv("Défaites en FF", pct(su.ffLoss))}
          ${kv("Vision vs vis-à-vis", p.style.visionAdv != null ? signed(p.style.visionAdv * 100) + NB + "%" : "–")}
          ${kv("Games à son rôle", `${p.roleGames}/${p.games}`)}
          ${kv("Autres rôles", Object.entries(p.roles).filter(([r]) => r !== p.role && ROLE_FR[r]).sort((x, y) => y[1] - x[1]).map(([r, n]) => `${ROLE_FR[r]} ×${n}`).join(", ") || "–")}
        </div>
        <div><div class="sub"><h3>Picks cachés</h3><span class="muted">maîtrise ≥ 50k, 0 ranked</span></div>
          ${(p.pocket || []).length ? `<table><tr><th>Champion</th><th class="n">Points</th><th class="n">Dernière</th></tr>${p.pocket.map((m) => `<tr><td>${champ(m.champ)}</td><td class="n">${Math.round(m.points / 1000)}k</td><td class="n">${date(m.last)}</td></tr>`).join("")}</table>` : `<p class="empty">Aucun.</p>`}</div>
      </div>
      <div class="sub"><h3>Maîtrises</h3><span class="muted">toutes files</span></div>
      <div class="tbl-wrap"><table><tr><th>Champion</th><th class="n">Points</th><th class="n">Niveau</th><th class="n">Dernière</th><th class="n">Ranked (période)</th></tr>
        ${(p.masteryTop || []).map((m) => { const c = p.champions.find((x) => x.champ === m.champ); return `<tr><td>${champ(m.champ)}</td><td class="n">${Math.round(m.points / 1000)}k</td><td class="n">${m.level ?? "–"}</td><td class="n">${date(m.last)}</td><td class="n">${c ? `${c.g} g · ${wr(c.wr, c.g)}` : `<span class="muted">0</span>`}</td></tr>`; }).join("")}</table></div>`;
  }

  // ---------- botlane ----------
  function botlanePage() {
    const b = R.botlane;
    return `<section class="page" id="botlane"><h2>Botlane</h2>
      <p class="meta">ADC : <b>${esc(b.adc)}</b> · Support : <b>${esc(b.sup)}</b> <span class="muted">(rôles imposés)</span></p>
      ${(R.botlaneSignals || []).length ? `<table class="signals" style="max-width:560px">${R.botlaneSignals.map((x) => `<tr class="sig t-${x.tone}"><td>${esc(x.label)}</td><td class="n"><b>${esc(x.value)}</b></td></tr>`).join("")}</table>` : ""}
      <div class="figures">
        <div class="fig"><div class="v">${b.duo.g}</div><div class="k">games en duo</div></div>
        <div class="fig"><div class="v">${wr(b.duo.wr, b.duo.g)}</div><div class="k">WR duo</div></div>
        <div class="fig"><div class="v">${wr(b.adcSolo.wr, b.adcSolo.g)} <span class="muted small">(${b.adcSolo.g})</span></div><div class="k">WR de l'ADC sans lui</div></div>
        <div class="fig"><div class="v">${wr(b.supSolo.wr, b.supSolo.g)} <span class="muted small">(${b.supSolo.g})</span></div><div class="k">WR du support sans lui</div></div>
        <div class="fig"><div class="v ${sgnCls(b.botGd15, 50)}">${signed(b.botGd15)}</div><div class="k">GD bot à 15 min</div></div>
      </div>
      <div class="sub"><h3>Duos les plus joués</h3></div>
      ${b.pairs.length ? `<div class="tbl-wrap"><table><tr><th>ADC + Support</th><th class="n">G</th><th class="n">WR</th><th class="n">KDA ADC</th><th class="n">GD@15 ADC</th></tr>
        ${b.pairs.map((x) => `<tr><td>${champ(x.adc)} + ${champ(x.sup)}</td><td class="n">${x.g}</td><td class="n">${wr(x.wr, x.g)}</td><td class="n">${num(x.kda, 2)}</td><td class="n ${sgnCls(x.gd15, 50)}">${signed(x.gd15)}</td></tr>`).join("")}</table></div>` : `<p class="empty">Aucune game en duo.</p>`}
      <div class="two">
        <div><div class="sub"><h3>Duo vs type de support adverse</h3></div>${vsTable(b.duoVsSup, "Support adverse", esc)}</div>
        <div><div class="sub"><h3>Duo vs type d'ADC adverse</h3></div>${vsTable(b.duoVsAdc, "ADC adverse", esc)}</div>
      </div>
      <div class="sub"><h3>Duo vs combinaison botlane adverse</h3></div>${vsTable(b.duoVsCombo, "ADC + support adverses", esc)}
      <div class="two">
        <div><div class="sub"><h3>${esc(b.adc)} (toutes ses games ADC) vs type de support</h3></div>${vsTable(b.adcVsSup, "Support adverse", esc)}</div>
        <div><div class="sub"><h3>${esc(b.sup)} (toutes ses games support) vs type d'ADC</h3></div>${vsTable(b.supVsAdc, "ADC adverse", esc)}</div>
      </div>
    </section>`;
  }

  // ---------- premades ----------
  function premadesPage() {
    const pm = R.premades;
    const groups = Object.entries(pm.groups || {}).sort((a, b) => b[0] - a[0]).map(([n, g]) => `<b>${n} joueurs</b> × ${g} games`).join(", ");
    return `<section class="page" id="premades"><h2>Premades</h2>
      <div class="sub"><h3>Joueurs de la liste qui jouent ensemble</h3></div>
      ${pm.pairs.length ? `<div class="tbl-wrap"><table><tr><th>Joueur</th><th>Avec</th><th class="n">G</th><th class="n">WR</th></tr>
        ${pm.pairs.map((x) => `<tr><td>${esc(x.a)}</td><td>${esc(x.b)}</td><td class="n">${x.g}</td><td class="n">${wr(x.wr, x.g)}</td></tr>`).join("")}</table></div>
        <p class="caption">Groupes de 3 joueurs de la liste ou plus dans la même équipe : ${groups || "aucun"}.</p>` : `<p class="empty">Ils ne jouent jamais ensemble sur la période.</p>`}
      <div class="sub"><h3>Partenaires réguliers hors liste</h3><span class="muted">au moins 3 games ensemble</span></div>
      ${pm.regulars.length ? `<div class="tbl-wrap"><table><tr><th>Joueur</th><th class="n">G</th><th class="n">WR</th><th>Avec</th><th>Rôle</th><th class="n">Niveau</th></tr>
        ${pm.regulars.map((x) => `<tr><td>${esc(x.name)}</td><td class="n">${x.g}</td><td class="n">${wr(x.wr, x.g)}</td>
          <td>${x.with.map((w) => `${esc(w)} <span class="x">×${x.withCount[w]}</span>`).join(", ")}</td><td>${esc(x.roles.join(", "))}</td><td class="n">${x.level ?? "–"}</td></tr>`).join("")}</table></div>` : `<p class="empty">Personne.</p>`}
    </section>`;
  }

  // ---------- comps ----------
  function compsPage() {
    const s = R.stack;
    const queues = Object.entries(s.queues).map(([q, n]) => `${q} ${n}`).join(", ");
    const sizes = Object.entries(s.sizes).sort((a, b) => b[0] - a[0]).map(([n, g]) => `${n} joueurs : ${g}`).join(", ");
    const topDuo = s.duos[0];
    const comp = (list) => `<span class="comp">${list.map(([c, mine]) => `<img src="${DD}/${R.static.version}/img/champion/${champInfo(c)[0]}.png" class="${mine ? "" : "out"}" title="${esc(champInfo(c)[1])}" alt="">`).join("")}</span>`;
    return `<section class="page" id="compos"><h2>Compos en équipe</h2>
      <p class="meta"><b>${s.n} games</b> avec 3 joueurs de la liste ou plus dans la même équipe (${sizes}) · ${s.wins} V – ${s.n - s.wins} D (${wr(s.wr, s.n)}) · ${esc(queues)} · dernière le ${date(s.last)}</p>
      <p class="caption">Toutes positions confondues · en gris : joueurs hors liste.</p>
      <div class="two">
        <div><div class="sub"><h3>Champions joués en équipe</h3></div>
          <table><tr><th>Rôle</th><th>Joueur</th><th>Champions</th></tr>
          ${ROLES.filter((r) => s.players[r]).map((r) => { const x = s.players[r]; return `<tr><td>${ROLE_FR[r]}</td>
            <td><b>${esc(x.name)}</b><div class="sec">${x.g} games${x.otherRoles.length ? " · aussi " + x.otherRoles.map(([rr, n]) => `${rr} ×${n}`).join(", ") : ""}</div></td>
            <td>${played(x.champs)}</td></tr>`; }).join("")}</table></div>
        <div><div class="sub"><h3>Duos qui reviennent</h3></div>
          ${s.duos.length ? `<table><tr><th>Duo</th><th>Champions</th><th class="n">G</th><th class="n">WR</th></tr>${s.duos.map((d) => `<tr><td>${esc(d.roles)}</td><td>${champ(d.a, "ic sm")} ${champ(d.b, "ic sm")}</td><td class="n">${d.g}</td><td class="n">${wr(d.wr, d.g)}</td></tr>`).join("")}</table>` : `<p class="empty">Aucun duo de champions répété.</p>`}
          <div class="sub"><h3>Leurs bans en équipe</h3></div>
          ${s.bans.length ? played(s.bans) : `<p class="empty">–</p>`}
          <div class="sub"><h3>Picks réservés à l'équipe</h3></div>
          ${s.reserved.length ? s.reserved.map((x) => `<div class="kv"><span class="k">${champ(x.champ, "ic sm")} ${esc(x.player)}</span><span class="v">${x.g} games en stack (${x.w} V)${x.outside ? `, ${x.outside} fois sans la team` : ", jamais sans la team"}</span></div>`).join("") : `<p class="empty">Aucun.</p>`}
        </div>
      </div>
      <div class="three">
        <div><div class="sub"><h3>Profil de compo</h3><span class="muted">champions par game selon leur classe principale</span></div>
          <table><tr><th>Classe</th><th class="n">Eux</th><th class="n">En face</th></tr>${s.profile.map((x) => `<tr><td>${esc(x.cls)}</td><td class="n"><b>${num(x.us)}</b></td><td class="n muted">${num(x.them)}</td></tr>`).join("")}</table></div>
        <div><div class="sub"><h3>Dégâts et durée</h3></div>
          <p>Physiques <b>${pct(s.dmg[0])}</b> · magiques <b>${pct(s.dmg[1])}</b> · bruts <b>${pct(s.dmg[2])}</b></p>
          <table><tr><th>Durée</th><th class="n">G</th><th class="n">WR</th></tr>${s.durations.map((d) => `<tr><td>${d.label}</td><td class="n">${d.g}</td><td class="n">${wr(d.wr, d.g)}</td></tr>`).join("")}</table></div>
        <div><div class="sub"><h3>Objectifs</h3></div>
          <table><tr><th></th><th class="n">En 1<sup>er</sup></th><th class="n">Par game</th></tr>${s.objectives.map((o) => `<tr><td>${o.label}</td><td class="n">${pct(o.first)}</td><td class="n">${num(o.perGame)}</td></tr>`).join("")}</table></div>
      </div>
      <div class="sub"><h3>Dernières games en stack</h3></div>
      <div class="tbl-wrap"><table><tr><th>Date</th><th>File</th><th></th><th class="n">Durée</th><th>Leur compo (top → support)</th><th>En face</th></tr>
        ${s.recent.map((g) => `<tr><td>${date(g.start)}</td><td>${esc(g.queue)}</td><td class="wl ${g.win ? "good" : "bad"}">${g.win ? "V" : "D"}</td><td class="n">${Math.round(g.duration / 60)} min</td><td>${comp(g.us)}</td><td>${comp(g.them.map(([c]) => [c, true]))}</td></tr>`).join("")}</table></div>
    </section>`;
  }

  // ---------- smurfs ----------
  const hm = (ms) => new Date(ms).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
  function nearCell(s) {
    if (!s.nearMisses) return `<span class="muted" title="rapport antérieur : rafraîchis-le">–</span>`;
    const n = s.nearCount ?? s.nearMisses.length;
    if (!n) return `<span class="muted">0</span>`;
    const tip = (s.nearMisses || []).map((x) => `${date(x.start)} : ${x.smurfAfter ? "main" : "smurf"} finit ${hm(x.end)} → ${x.smurfAfter ? "smurf" : "main"} commence ${hm(x.start)} (${x.gap} min)`).join("\n");
    return `<b class="${n >= 2 ? "bad" : ""}" title="${esc(tip)}">${n}</b><div class="sec">${s.nearTight || 0} ≤ 15 min · ${s.nearClose != null ? s.nearClose - (s.nearTight || 0) : "–"} ≤ 30 · ${s.nearClose != null ? n - s.nearClose : "–"} ≤ 60</div>`;
  }
  function smurfPage() {
    const sm = R.smurf;
    const ROLE_NAME = { TOP: "Top", JUNGLE: "Jungle", MIDDLE: "Mid", BOTTOM: "ADC", UTILITY: "Support" };
    const deep = new Set((R.smurfPlayers || []).map((x) => x.puuid));
    const blocks = ROLES.filter((r) => sm.players && sm.players[r]).map((r) => {
      const x = sm.players[r];
      const rows = x.suspects.map((s) => `<tr>
        <td>${deep.has(s.puuid) ? `<a href="#" onclick="document.querySelector('[id^=s-${r.toLowerCase()}-${s.puuid.slice(0, 8)}]').scrollIntoView({behavior:'smooth'});return false"><b>${esc(s.name)}</b></a>` : `<b>${esc(s.name)}</b>`}</td>
        <td class="n"><b class="${s.score >= 80 ? "bad" : ""}">${s.score}</b></td>
        <td class="n">${s.g}</td>
        <td class="n">${nearCell(s)}</td>
        <td class="sec">${s.friends.map(([n, k]) => `${esc(n)} ×${k}`).join(", ")}</td>
        <td>${ROLE_NAME[s.mainRole] || s.mainRole} <span class="sec">${pct(s.roleShare)}</span></td>
        <td>${s.commonChamps.length ? `<span class="chips">${s.commonChamps.map((c) => champImg(c, "ic sm")).join("")}</span> <span class="sec">${pct(s.champShare)}</span>` : `<span class="muted">aucun</span>`}${s.champs && s.champs.length ? `<div class="sec">joue : <span class="chips">${s.champs.map(([c]) => champImg(c, "ic sm")).join("")}</span></div>` : ""}</td>
        <td class="n">${s.hoursSim != null ? pct(s.hoursSim) : "–"}</td>
        <td class="n">${s.offDays != null ? pct(s.offDays) : "–"}</td>
        <td class="n">${s.level ?? "–"}</td>
        <td class="n">${s.verified ? `<span class="good">0 / ${s.checked}</span>` : `<span class="muted">0 / ${s.g}</span>`}</td>
      </tr>`).join("");
      const cleared = x.cleared.length ? `<p class="caption">Écartés : ${x.cleared.map((c) => `${esc(c.name)} (${esc(c.reason)})`).join(" · ")}</p>` : "";
      return `<div class="sub"><h3>${esc(x.player)}</h3><span class="muted">${ROLE_FR[r]} · partenaires analysés : ${x.friends.length}</span></div>
        ${rows ? `<div class="tbl-wrap"><table><tr><th>Compte</th><th class="n">Score</th><th class="n">G avec ses partenaires</th><th class="n">Enchaînements</th><th>Partenaires</th><th>Rôle</th><th>Champions communs</th><th class="n">Horaires sim.</th><th class="n">Jours où il ne joue pas</th><th class="n">Niv.</th><th class="n">Chevauchements</th></tr>${rows}</table></div>` : `<p class="empty">Aucun candidat ≥ 50.</p>`}
        ${cleared}`;
    }).join("");
    return `<section class="page" id="smurfs"><h2>Détection de smurfs</h2>
      <p class="legend">Méthode : comptes qui jouent avec les partenaires réguliers du joueur, jamais avec ni contre lui, jamais pendant ses games.
      Indice principal : les <b>enchaînements</b> — une game du joueur se termine et une game du compte commence moins d'une heure après (ou l'inverse), sans jamais se chevaucher. Un écart ≤ 15 min compte plein, ≤ 30 min un peu moins, ≤ 60 min peu — mais beaucoup d'enchaînements lâches finissent par peser. Plusieurs enchaînements = très probablement la même personne.
      Le reste du score : games avec ses partenaires, horaires, jours sans le joueur, niveau du compte, vérification des horaires (+10). Même rôle et mêmes champions ne font que renforcer le soupçon (un smurf sert souvent à s'entraîner sur d'autres champions).
      Chevauchements = games en même temps que le joueur / games comparées. ≥ 80 : analysé en détail.</p>
      ${sm.error ? `<p class="err">${esc(sm.error)}</p>` : ""}
      ${blocks}
    </section>`;
  }

  // =====================================================================
  // Head to head
  // =====================================================================
  const RANK_FR = (p) => (p.ranks || []).find((r) => r.queue === "SoloQ") || (p.ranks || [])[0];

  async function renderH2HPicker(a) {
    const list = await api("/api/reports");
    const opt = (sel) => list.map((r) => `<option value="${esc(r.file)}" ${r.file === sel ? "selected" : ""}>${esc(r.team)} · ${r.generated ? date(r.generated) : ""}</option>`).join("");
    $app.innerHTML = `<div style="max-width:720px"><h1>Face à face</h1>
      <p class="legend">Deux rapports existants, comparés rôle par rôle. Lance d'abord une analyse de chaque équipe (la tienne comprise).</p>
      ${list.length < 2 ? `<p class="empty">Il faut au moins deux rapports.</p>` : `
      <form id="h" class="opts" style="grid-template-columns:1fr 1fr">
        <label class="field"><span>Équipe A</span><select name="a">${opt(a || list[0].file)}</select></label>
        <label class="field"><span>Équipe B</span><select name="b">${opt(list.find((r) => r.file !== (a || list[0].file)).file)}</select></label>
        <div class="go"><button class="btn">Comparer</button></div>
      </form>`}</div>`;
    const f = document.getElementById("h");
    if (f) f.onsubmit = (ev) => { ev.preventDefault(); const fd = new FormData(f); location.hash = `#/h2h/${encodeURIComponent(fd.get("a"))}/${encodeURIComponent(fd.get("b"))}`; };
  }

  async function renderH2H(fa, fb) {
    $app.innerHTML = `<p class="muted">Chargement…</p>`;
    const [A, B] = (await Promise.all([api(`/api/reports/${encodeURIComponent(fa)}`), api(`/api/reports/${encodeURIComponent(fb)}`)])).map(upgrade);
    R = A; // static tables (champions, items) for icons
    R.static.champs = { ...B.static.champs, ...A.static.champs };
    const byRole = (T) => Object.fromEntries(T.players.map((p) => [p.role, p]));
    const PA = byRole(A), PB = byRole(B);
    const cmp = (va, vb, higher = true, fmt = (v) => num(v)) => {
      if (va == null && vb == null) return `<td class="n muted">–</td><td class="n muted">–</td>`;
      const better = va == null ? "b" : vb == null ? "a" : va === vb ? "" : (va > vb) === higher ? "a" : "b";
      return `<td class="n ${better === "a" ? "win" : ""}">${va == null ? "–" : fmt(va)}</td><td class="n ${better === "b" ? "win" : ""}">${vb == null ? "–" : fmt(vb)}</td>`;
    };
    const METRICS = [
      ["Rang SoloQ", (p) => (RANK_FR(p) || {}).score, true, (v, p) => esc((RANK_FR(p) || {}).label || "–")],
      ["Games", (p) => p.games, true, (v) => v],
      ["WR au rôle", (p) => p.focusWr, true, pct],
      ["KDA", (p) => p.kda.ratio, true, (v) => num(v, 2)],
      ["GD@15", (p) => p.early.gd15, true, (v) => signed(v)],
      ["CSD@15", (p) => p.early.csd15, true, (v) => signed(v)],
      ["XPD@15", (p) => p.early.xpd15, true, (v) => signed(v)],
      ["Lanes gagnées", (p) => p.early.lanesWon, true, pct],
      ["Morts < 14 min", (p) => p.early.deaths14, false, (v) => num(v)],
      ["Tué en 1v1 < 14", (p) => p.early.deaths1v1_14, false, (v) => num(v)],
      ["Solo kills", (p) => p.early.soloKills, true, (v) => num(v)],
      ["First blood", (p) => p.early.fb, true, pct],
      ["KP", (p) => p.style.kp, true, pct],
      ["Part dégâts", (p) => p.style.dmgShare, true, pct],
      ["Dégâts / min", (p) => p.style.dpm, true, (v) => num(v, 0)],
      ["CS / min", (p) => p.style.csm, true, (v) => num(v)],
      ["Vision / min", (p) => p.style.vspm, true, (v) => num(v, 2)],
      ["Part. objectifs", (p) => p.objPart, true, pct],
      ["WR en avance @15", (p) => p.early.wrAhead15, true, pct],
      ["WR en retard @15", (p) => p.early.wrBehind15, true, pct],
    ];

    // how a player does against the champions the other side actually plays
    const vsTheirPool = (me, them) => {
      if (!me || !them) return [];
      // only what they play in this role
      const role = them.role;
      const pool = them.champions.map((c) => ({ ...c, rg: (c.roles || {})[role] || 0 })).filter((c) => c.rg > 0).sort((x, y) => y.rg - x.rg);
      return pool.slice(0, 6).map((c) => {
        const r = (me.vsOppAll || []).find((x) => x.key === c.champ);
        return { champ: c.champ, theirG: c.rg, theirWr: c.wr, g: r ? r.g : 0, wr: r ? r.wr : null, gd15: r ? r.gd15 : null };
      });
    };
    const poolTable = (rows, me, them) => `<table><tr><th>${esc(them.name)} joue (${ROLE_FR[them.role]})</th><th class="n">G</th><th class="n">WR*</th><th class="n">${esc(me.name)} contre : G</th><th class="n">WR</th><th class="n">GD@15</th></tr>
      ${rows.map((x) => `<tr><td>${champ(x.champ, "ic sm")}</td><td class="n">${x.theirG}</td><td class="n">${wr(x.theirWr, x.theirG)}</td><td class="n">${x.g || `<span class="muted">0</span>`}</td><td class="n">${x.g ? wr(x.wr, x.g) : "–"}</td><td class="n ${sgnCls(x.gd15, 50)}">${x.g ? signed(x.gd15) : "–"}</td></tr>`).join("")}</table>`;
    const classLine = (me, them) => {
      const main = them.champions.find((c) => (c.roles || {})[them.role]);
      if (!main) return "";
      const cls = (R.static.champs[main.champ] || [, , []])[2][0];
      const r = (me.vsClass || []).find((x) => x.key === cls);
      return r ? `<span class="sec">${esc(me.name)} vs ${esc(cls)} : ${r.g} g · ${pct(r.wr)}</span>` : "";
    };

    // games where they met
    const met = [];
    const idx = {};
    B.players.forEach((p) => (p.log || []).forEach(([m, team, win, ch, start]) => { (idx[m] = idx[m] || []).push({ p, team, win, ch, start }); }));
    const seen = new Set();
    A.players.forEach((p) => (p.log || []).forEach(([m, team, win, ch, start]) => {
      if (!idx[m] || seen.has(m)) return;
      seen.add(m);
      const opp = idx[m].filter((x) => x.team !== team);
      const mates = idx[m].filter((x) => x.team === team);
      const aSide = A.players.filter((q) => (q.log || []).some((l) => l[0] === m && l[1] === team)).map((q) => q.name);
      met.push({ m, start, aWin: !!win, aSide, bSide: opp.map((x) => x.p.name), together: mates.map((x) => x.p.name) });
    }));
    met.sort((x, y) => y.start - x.start);
    const vsGames = met.filter((g) => g.bSide.length);
    const aWins = vsGames.filter((g) => g.aWin).length;

    const stackCmp = (k, f, higher = true, fmt = pct) => cmp(A.stack ? f(A.stack) : null, B.stack ? f(B.stack) : null, higher, fmt);
    const objFirst = (st, label) => { const o = (st.objectives || []).find((x) => x.label === label); return o ? o.first : null; };

    $app.innerHTML = `<div class="h2h">
      <div class="kicker"><a href="#/h2h">← choisir d'autres équipes</a></div>
      <h1>${esc(A.team)} <span class="muted">vs</span> ${esc(B.team)}</h1>
      <p class="meta">A : ${dateLong(A.generated)} · ${A.params.days} j · B : ${dateLong(B.generated)} · ${B.params.days} j</p>

      <div class="sub"><h3>Rôle par rôle</h3><span class="muted">en gras : meilleur des deux</span></div>
      <div class="tbl-wrap"><table class="h2h-grid"><tr><th></th>${ROLES.map((r) => `<th colspan="2" class="c">${ROLE_FR[r]}</th>`).join("")}</tr>
        <tr><th></th>${ROLES.map((r) => `<th class="n">${esc(PA[r] ? PA[r].name : "–")}</th><th class="n">${esc(PB[r] ? PB[r].name : "–")}</th>`).join("")}</tr>
        ${METRICS.map(([label, f, higher, fmt]) => `<tr><td>${label}</td>${ROLES.map((r) => {
          const a = PA[r], b = PB[r];
          return cmp(a ? f(a) : null, b ? f(b) : null, higher, (v) => fmt(v, a && f(a) === v ? a : b));
        }).join("")}</tr>`).join("")}
      </table></div>

      <div class="sub"><h3>Matchups de lane</h3><span class="muted">champions joués par le vis-à-vis à ce rôle · résultat du joueur contre eux · WR* = WR du champion toutes positions</span></div>
      ${ROLES.filter((r) => PA[r] && PB[r]).map((r) => `
        <div class="sub" style="margin-top:22px"><h3 style="font-size:17px">${ROLE_FR[r]} · ${esc(PA[r].name)} vs ${esc(PB[r].name)}</h3></div>
        <div class="two">
          <div>${poolTable(vsTheirPool(PA[r], PB[r]), PA[r], PB[r])}${classLine(PA[r], PB[r])}</div>
          <div>${poolTable(vsTheirPool(PB[r], PA[r]), PB[r], PA[r])}${classLine(PB[r], PA[r])}</div>
        </div>`).join("")}

      <div class="two">
        <div><div class="sub"><h3>Bans contre ${esc(B.team)}</h3></div>
          ${B.teamBans.length ? `<table><tr><th>Champion</th><th>Joueur</th><th class="n">G</th><th class="n">WR</th></tr>${B.teamBans.map((b) => `<tr><td>${champ(b.champ)}</td><td>${esc(b.player)}</td><td class="n">${b.g}</td><td class="n">${wr(b.wr, b.g)}</td></tr>`).join("")}</table>` : `<p class="empty">–</p>`}</div>
        <div><div class="sub"><h3>Bans contre ${esc(A.team)}</h3></div>
          ${A.teamBans.length ? `<table><tr><th>Champion</th><th>Joueur</th><th class="n">G</th><th class="n">WR</th></tr>${A.teamBans.map((b) => `<tr><td>${champ(b.champ)}</td><td>${esc(b.player)}</td><td class="n">${b.g}</td><td class="n">${wr(b.wr, b.g)}</td></tr>`).join("")}</table>` : `<p class="empty">–</p>`}</div>
      </div>

      <div class="sub"><h3>En équipe</h3><span class="muted">games à 3+ joueurs de la liste</span></div>
      <table style="max-width:640px"><tr><th></th><th class="n">${esc(A.team)}</th><th class="n">${esc(B.team)}</th></tr>
        <tr><td>Games en stack</td>${stackCmp("n", (s) => s.n, true, (v) => v)}</tr>
        <tr><td>WR en stack</td>${stackCmp("wr", (s) => s.wr)}</tr>
        ${["First blood", "1re tour", "1er drake", "1ers grubs", "Héraut", "1er nashor"].map((l) => `<tr><td>${l} (en 1er)</td>${stackCmp(l, (s) => objFirst(s, l))}</tr>`).join("")}
        <tr><td>Dégâts physiques</td>${stackCmp("p", (s) => s.dmg[0], null, pct).replace(/ win/g, "")}</tr>
        <tr><td>Dégâts magiques</td>${stackCmp("m", (s) => s.dmg[1], null, pct).replace(/ win/g, "")}</tr>
      </table>

      <div class="sub"><h3>Games entre les deux équipes</h3><span class="muted">${vsGames.length ? `${esc(A.team)} ${aWins} – ${vsGames.length - aWins} ${esc(B.team)}` : "aucune dans les périodes analysées"}</span></div>
      ${met.length ? `<table><tr><th>Date</th><th>Côté ${esc(A.team)}</th><th>Côté ${esc(B.team)}</th><th>Coéquipiers</th><th>Résultat A</th></tr>
        ${met.slice(0, 20).map((g) => `<tr><td>${date(g.start)}</td><td>${esc(g.aSide.join(", "))}</td><td>${esc(g.bSide.join(", ") || "–")}</td><td>${esc(g.together.join(", ") || "–")}</td><td class="wl ${g.aWin ? "good" : "bad"}">${g.aWin ? "V" : "D"}</td></tr>`).join("")}</table>` : ""}
    </div>`;
  }

  // =====================================================================
  // Draft against a scouted team
  // =====================================================================
  const TIER_FR = [["emerald_plus", "Émeraude+"], ["platinum_plus", "Platine+"], ["diamond_plus", "Diamant+"], ["master_plus", "Master+"], ["all", "Tous rangs"]];
  const COUNTERS = {}; // "champ|role|tier" -> promise of /api/counters
  const MIN_SHARE = 0.004; // ignore matchups seen in < 0.4 % of the lane's games (noise)

  const fold = (s) => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]/gi, "").toLowerCase();

  async function renderDraftPicker() {
    const list = await api("/api/reports");
    $app.innerHTML = `<div class="folder" style="max-width:860px"><h1>Draft</h1>
      <p class="legend">Choisis l'équipe adverse (un rapport existant). Pour chaque rôle, indique ton pick : les counters que <b>ce joueur-là</b> peut sortir en réponse s'affichent, avec ses stats dessus.</p>
      ${list.length ? `<ul>${list.map((r) => `<li><a href="#/draft/${encodeURIComponent(r.file)}"><div class="t">${esc(r.team)}</div>
        <div class="s">${r.generated ? dateLong(r.generated) : ""} · ${esc((r.region || "").toUpperCase())} · ${esc((r.players || []).join(", "))}</div></a></li>`).join("")}</ul>`
        : `<p class="empty">Aucun rapport : lance d'abord une analyse de l'équipe adverse.</p>`}</div>`;
  }

  async function renderDraft(file) {
    $app.innerHTML = `<p class="muted">Chargement…</p>`;
    R = upgrade(await api(`/api/reports/${encodeURIComponent(file)}`));
    const key = `draft:${file}`;
    const st = Object.assign({ picks: {}, bans: [null, null, null, null, null], tier: "emerald_plus" }, store.get(key, {}));
    const save = () => store.set(key, st);
    const byRole = Object.fromEntries(R.players.map((p) => [p.role, p]));
    const smurfs = (role) => (R.smurfPlayers || []).filter((x) => x.smurfOf && x.smurfOf.role === role);
    const champs = Object.entries(R.static.champs).map(([id, c]) => ({ id: +id, name: c[1], k: fold(c[1]), k2: fold(c[0]) })).sort((a, b) => a.name.localeCompare(b.name, "fr"));
    const findChamp = (txt) => { const k = fold(txt); if (!k) return null; const c = champs.find((x) => x.k === k || x.k2 === k) || champs.filter((x) => x.k.startsWith(k)).sort((a, b) => a.k.length - b.k.length)[0]; return c ? c.id : null; };
    const cname = (id) => champInfo(id)[1];

    const picker = (attr, value, ph) => `<span class="cpick">${value != null ? champImg(value, "ic") : `<span class="ic"></span>`}<input ${attr} list="champlist" value="${value != null ? esc(cname(value)) : ""}" placeholder="${ph}" spellcheck="false"></span>`;

    $app.innerHTML = `<div class="draft">
      <div class="kicker"><a href="#/r/${encodeURIComponent(file)}">← rapport ${esc(R.team)}</a> · <a href="#/draft">autre équipe</a></div>
      <h1>Draft contre ${esc(R.team)}</h1>
      <p class="legend">Pour chaque rôle, choisis ton pick : on liste les champions qui le contrent en lane (stats u.gg, deux derniers patchs, monde) en commençant par ceux que <b>ton vis-à-vis joue vraiment</b>, avec ses stats dessus.
        WR counter = winrate du champion adverse contre ton pick. Les champions bannis ou déjà pris ne peuvent plus sortir.</p>
      <datalist id="champlist">${champs.map((c) => `<option value="${esc(c.name)}">`).join("")}</datalist>
      <div class="draft-top">
        <div class="field"><span>Bans (5 max)</span>
          <div class="bans">${st.bans.map((b, i) => picker(`data-ban="${i}"`, b, "Ban " + (i + 1))).join("")}</div>
          ${R.teamBans.length ? `<div class="sec small">Bans conseillés : ${R.teamBans.slice(0, 6).map((b) => `<button class="linklike chipbtn" data-addban="${b.champ}" title="${esc(b.player)} · ${b.g} g · ${pct(b.wr)}">${champImg(b.champ, "ic sm")}${esc(cname(b.champ))}</button>`).join(" ")}</div>` : ""}
        </div>
        <label class="field"><span>Elo des stats de counter</span><select id="tier">${TIER_FR.map(([v, l]) => `<option value="${v}" ${v === st.tier ? "selected" : ""}>${l}</option>`).join("")}</select></label>
        <div class="field"><span>&nbsp;</span><button class="btn ghost" id="reset">Tout effacer</button></div>
      </div>
      ${ROLES.map((r) => {
        const p = byRole[r];
        const subs = smurfs(r);
        return `<section class="draft-role" id="d-${r}">
          <div class="draft-head">
            <div class="who"><div class="kicker">${ROLE_FR[r]}</div>
              ${p ? `<b>${esc(p.name)}</b><span class="muted">#${esc(p.tag)}</span>${subs.map((x) => ` <span class="flag" title="compte secondaire probable">+ ${esc(x.name)}</span>`).join("")}` : `<span class="muted">pas de joueur à ce rôle</span>`}</div>
            <label class="mine"><span class="muted small">Ton pick</span>${picker(`data-pick="${r}"`, st.picks[r], "Champion…")}</label>
          </div>
          <div class="draft-body" id="db-${r}"></div>
        </section>`;
      }).join("")}
    </div>`;

    const unavailable = () => {
      const s = new Map();
      st.bans.forEach((b) => b != null && s.set(b, "banni"));
      ROLES.forEach((r) => st.picks[r] != null && s.set(st.picks[r], "pris par toi"));
      return s;
    };

    // his pool in this role (main + smurf accounts), one row per champion
    const pool = (role) => {
      const out = new Map();
      [byRole[role], ...smurfs(role)].filter(Boolean).forEach((p) => {
        p.champions.forEach((c) => {
          const rg = (c.roles || {})[role] || 0;
          if (!rg) return;
          const o = out.get(c.champ) || { champ: c.champ, rg: 0, g: 0, w: 0, g30: 0, kda: c.kda, accounts: [] };
          o.rg += rg; o.g += c.g; o.w += (c.wr || 0) * c.g; o.g30 += c.g30 || 0;
          o.accounts.push(p.smurfOf ? p.name : "main");
          out.set(c.champ, o);
        });
      });
      out.forEach((o) => (o.wr = o.g ? o.w / o.g : null));
      return out;
    };

    async function fill(role) {
      const el = document.getElementById(`db-${role}`);
      const mine = st.picks[role];
      const p = byRole[role];
      if (mine == null) { el.innerHTML = `<p class="empty">Choisis ton champion pour voir ses counters.</p>`; return; }
      el.innerHTML = `<p class="muted small">Counters de ${esc(cname(mine))}…</p>`;
      const ck = `${mine}|${role}|${st.tier}`;
      COUNTERS[ck] = COUNTERS[ck] || api(`/api/counters?champ=${mine}&role=${role}&tier=${st.tier}`).catch((e) => { delete COUNTERS[ck]; throw e; });
      let data;
      try { data = await COUNTERS[ck]; } catch (e) { el.innerHTML = `<p class="err">${esc(e.message)}</p>`; return; }
      if (st.picks[role] !== mine) return; // changed while loading
      const off = unavailable();
      const rows = data.rows.filter((x) => x.share >= MIN_SHARE);
      const byChamp = new Map(data.rows.map((x) => [x.champ, x]));
      const his = pool(role);
      const status = (c) => (off.has(c) ? `<span class="flag">${off.get(c)}</span>` : "");
      const vsMe = p && (p.vsOppAll || []).find((x) => x.key === mine);

      // his champions that beat my pick, most dangerous first
      const theirs = [...his.values()].map((o) => ({ ...o, m: byChamp.get(o.champ) })).filter((o) => o.m && o.m.g >= 30);
      const threats = theirs.filter((o) => o.m.wr > 0.5).sort((a, b) => (off.has(a.champ) - off.has(b.champ)) || (b.m.wr - 0.5) * Math.sqrt(b.rg) - (a.m.wr - 0.5) * Math.sqrt(a.rg));
      const safe = theirs.filter((o) => o.m.wr <= 0.5).sort((a, b) => b.rg - a.rg).slice(0, 8);
      const unknown = [...his.values()].filter((o) => !off.has(o.champ) && o.champ !== mine).filter((o) => !byChamp.get(o.champ) || byChamp.get(o.champ).g < 30).sort((a, b) => b.rg - a.rg);
      const general = rows.filter((x) => !his.has(x.champ) && x.wr > 0.5).slice(0, 8);

      const cwr = (x) => `<b class="${x.wr >= 0.53 ? "bad" : x.wr > 0.5 ? "" : "good"}">${pct(x.wr)}</b>`;
      el.innerHTML = `
        <p class="draft-line">${data.games ? `${esc(cname(mine))} ${ROLE_FR[role]} : <b>${data.games.toLocaleString("fr-FR")}</b> games analysées (${esc(data.patches.join(" + "))}, ${esc(TIER_FR.find((t) => t[0] === data.tier)[1])})` : `<span class="err">Aucune donnée u.gg pour ${esc(cname(mine))} ${ROLE_FR[role]}.</span>`}
          ${p ? ` · ${esc(p.name)} contre ${esc(cname(mine))} : ${vsMe ? `<b>${vsMe.g}</b> g · ${wr(vsMe.wr, vsMe.g)}${vsMe.g ? ` · GD@15 <span class="${sgnCls(vsMe.gd15, 50)}">${signed(vsMe.gd15)}</span>` : ""}` : `<span class="muted">jamais affronté</span>`}` : ""}</p>
        ${p ? `<div class="sub"><h3>Ses réponses possibles</h3><span class="muted">champions de son pool à ce rôle qui gagnent contre ${esc(cname(mine))}</span></div>
          ${threats.length ? `<div class="tbl-wrap"><table><tr><th>Champion</th><th class="n">WR counter</th><th class="n">GD@15</th><th class="n">Échantillon</th><th class="n">Ses G au rôle</th><th class="n">Son WR</th><th class="n">KDA</th><th class="n">30 j</th><th></th></tr>
            ${threats.map((o) => `<tr class="${off.has(o.champ) ? "gone" : ""}"><td>${champ(o.champ)}</td><td class="n">${cwr(o.m)}</td><td class="n ${sgnCls(-o.m.gd15, 100)}">${signed(o.m.gd15)}</td><td class="n sec">${o.m.g.toLocaleString("fr-FR")}</td>
              <td class="n"><b>${o.rg}</b></td><td class="n">${wr(o.wr, o.g)}</td><td class="n">${num(o.kda, 2)}</td><td class="n">${o.g30 || `<span class="muted">0</span>`}</td>
              <td>${status(o.champ)}${o.accounts.some((a) => a !== "main") ? ` <span class="sec">sur ${esc(o.accounts.filter((a) => a !== "main").join(", "))}</span>` : ""}</td></tr>`).join("")}</table></div>`
            : `<p class="empty">Rien dans son pool ne contre ${esc(cname(mine))}.</p>`}
          ${safe.length ? `<p class="caption">Dans son pool mais faibles contre ${esc(cname(mine))} : ${safe.map((o) => `${champImg(o.champ, "ic sm")}${esc(cname(o.champ))} <span class="good">${pct(o.m.wr)}</span> <span class="muted">(${o.rg} g)</span>`).join(" · ")}</p>` : ""}
          ${unknown.length ? `<p class="caption">Trop peu de données de matchup : ${unknown.slice(0, 8).map((o) => `${esc(cname(o.champ))} (${o.rg} g)`).join(", ")}</p>` : ""}` : ""}
        <div class="sub"><h3>Autres counters</h3><span class="muted">hors de son pool · au moins ${num(MIN_SHARE * 100)}${NB}% des games de la lane</span></div>
        ${general.length ? `<div class="chips counters">${general.map((x) => `<span class="${off.has(x.champ) ? "gone" : ""}">${champ(x.champ, "ic sm")} ${cwr(x)} <span class="sec">${signed(x.gd15)} or</span>${status(x.champ)}</span>`).join("")}</div>` : `<p class="empty">–</p>`}`;
    }

    const fillAll = () => ROLES.forEach(fill);
    const setIcon = (input, id) => {
      const holder = input.parentElement;
      holder.firstElementChild.outerHTML = id != null ? champImg(id, "ic") : `<span class="ic"></span>`;
      if (id != null) input.value = cname(id);
      input.classList.toggle("bad-input", id == null && !!input.value.trim());
    };
    $app.querySelectorAll("[data-pick]").forEach((inp) => (inp.onchange = () => {
      const id = findChamp(inp.value);
      st.picks[inp.dataset.pick] = id; save(); setIcon(inp, id); fillAll();
    }));
    $app.querySelectorAll("[data-ban]").forEach((inp) => (inp.onchange = () => {
      const id = findChamp(inp.value);
      st.bans[+inp.dataset.ban] = id; save(); setIcon(inp, id); fillAll();
    }));
    $app.querySelectorAll("[data-addban]").forEach((b) => (b.onclick = () => {
      const id = +b.dataset.addban;
      if (st.bans.includes(id)) return;
      const i = st.bans.findIndex((x) => x == null);
      if (i < 0) { alert("Déjà 5 bans."); return; }
      st.bans[i] = id; save();
      setIcon($app.querySelector(`[data-ban="${i}"]`), id); fillAll();
    }));
    document.getElementById("tier").onchange = (e) => { st.tier = e.target.value; save(); fillAll(); };
    document.getElementById("reset").onclick = () => { if (confirm("Effacer picks et bans ?")) { store.set(key, {}); renderDraft(file); } };
    fillAll();
  }

  route();
})();
