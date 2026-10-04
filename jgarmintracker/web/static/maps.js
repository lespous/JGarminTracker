// Cartes Leaflet : fond OpenStreetMap (tuiles chargées depuis internet), tracés dessinés localement.
// Si les tuiles sont bloquées (proxy), les tracés restent visibles sur le fond neutre du conteneur.
function baseMap(id) {
  const map = L.map(id, { preferCanvas: true, scrollWheelZoom: true });
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>',
  }).addTo(map);
  return map;
}

function endpoint(map, latlng, color, label) {
  return L.circleMarker(latlng, { radius: 7, color: "#fff", weight: 2, fillColor: color, fillOpacity: 1 })
    .bindTooltip(label).addTo(map);
}

const START_COLOR = "#2D7A4C", END_COLOR = "#A8413A";

function trackMap(id, points, color) {
  if (!points || points.length < 2) return null;
  const map = baseMap(id);
  const line = L.polyline(points, { color, weight: 4, opacity: .9 }).addTo(map);
  directionCues(map, points, color);
  endpoint(map, points[0], START_COLOR, "Départ");
  endpoint(map, points[points.length - 1], END_COLOR, "Arrivée");
  map.fitBounds(line.getBounds(), { padding: [20, 20] });
  return map;
}

// Sens du parcours : 100 premiers mètres à la couleur du départ, 100 derniers à celle de l'arrivée,
// et une petite flèche tous les km dans le sens de la sortie.
function directionCues(map, points, color, ends = 100) {
  const cum = [0];
  for (let k = 1; k < points.length; k++) cum.push(cum[k - 1] + map.distance(points[k - 1], points[k]));
  const total = cum[cum.length - 1];
  if (total < 3 * ends) return;
  const upTo = (m) => points.slice(0, cum.findIndex(c => c >= m) + 1);
  const from = (m) => points.slice(Math.max(0, cum.findIndex(c => c >= m) - 1));
  L.polyline(upTo(ends), { color: START_COLOR, weight: 6, opacity: 1 }).addTo(map);
  L.polyline(from(total - ends), { color: END_COLOR, weight: 6, opacity: 1 }).addTo(map);
  for (let km = 1000; km < total - 300; km += 1000) {
    const i = cum.findIndex(c => c >= km), a = points[Math.max(0, i - 1)], b = points[Math.min(points.length - 1, i + 1)];
    const bearing = Math.atan2((b[1] - a[1]) * Math.cos(a[0] * Math.PI / 180), b[0] - a[0]) * 180 / Math.PI;  // 0 = nord
    L.marker(points[i], { interactive: false, keyboard: false, icon: L.divIcon({
      className: "dir-arrow", iconSize: [16, 16], iconAnchor: [8, 8],
      html: `<svg viewBox="0 0 16 16" width="16" height="16" style="transform: rotate(${bearing.toFixed(0)}deg)" aria-hidden="true"><path d="M8 1 L14 14 L8 10.5 L2 14 Z" fill="${color}" stroke="#fff" stroke-width="1.4" stroke-linejoin="round"/></svg>` }) }).addTo(map);
  }
}

// ---------------------------------------------------------------- lecture de la sortie
// Lecteur sous la carte : lecture / pause, barre de position, vitesse ×30 à ×1000, infos du point et profil
// d'altitude. Au premier « lecture », les données point par point sont demandées au serveur (téléchargées une
// fois chez Garmin) ; sans elles, le tracé est rejoué à vitesse constante (position et distance seulement).
// cfg.view : ce qui affiche le point (carte 2D Leaflet par défaut, survol 3D dans flyover.js).
function replayPlayer(map, points, cfg) {
  const box = document.getElementById(cfg.box);
  if (!map || !box || points.length < 2) return;
  const nf = (v, d = 0) => v.toLocaleString("fr-BE", { minimumFractionDigits: d, maximumFractionDigits: d });
  const hms = (s) => { s = Math.round(s); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60;
    return h ? `${h}h${String(m).padStart(2, "0")}min${String(x).padStart(2, "0")}s` : `${m}min${String(x).padStart(2, "0")}s`; };
  const speedText = (v) => {
    if (!v || v < 0.3) return "arrêt";
    if (cfg.unit === "kmh") return nf(v * 3.6, 1) + " km/h";
    const per = cfg.unit === "min_100m" ? 100 : 1000, s = per / v;
    return `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")} ${per === 100 ? "/100 m" : "/km"}`;
  };
  const speedLabel = cfg.unit === "kmh" ? "Vitesse" : "Allure";
  const view = cfg.view || leafletView(map, cfg);
  let S = null, detailed = false, pos = 0, playing = false, mult = cfg.mult || 100, last = null, loading = false, follow = true;

  box.innerHTML = `<div class="rp-controls">
      <button type="button" class="rp-play primary" aria-label="Rejouer la sortie"><i class="ph ph-play" aria-hidden="true"></i></button>
      <input type="range" class="rp-scrub" min="0" max="1000" value="0" disabled aria-label="Position dans la sortie">
      <div class="rp-speeds" role="group" aria-label="Vitesse de lecture">${[2, 10, 30, 100, 300, 1000].map(m => `<button type="button" data-m="${m}" aria-pressed="${m === mult}">×${m}</button>`).join("")}</div>
      <span class="rp-clock num">Rejouer la sortie</span>
      <button type="button" class="rp-follow" aria-pressed="true" title="La carte suit le point pendant la lecture"><i class="ph ph-crosshair" aria-hidden="true"></i>Suivre</button>
      ${cfg.extraControls || ""}
      <button type="button" class="rp-full" title="Plein écran (Échap pour sortir)" aria-label="Plein écran"><i class="ph ph-corners-out" aria-hidden="true"></i></button>
    </div>
    <p class="rp-note note" hidden></p>
    <div class="rp-stats" hidden></div>
    <svg class="rp-profile" viewBox="0 0 720 110" hidden role="slider" tabindex="0" aria-label="Profil d'altitude : position de lecture"></svg>`;
  const $ = (sel) => box.querySelector(sel);
  const btn = $(".rp-play"), scrub = $(".rp-scrub"), clock = $(".rp-clock"), stats = $(".rp-stats"), prof = $(".rp-profile"), note = $(".rp-note");

  // Plein écran : la carte et le lecteur passent dans un même conteneur ; en plein écran, le lecteur se pose en
  // surimpression sur la carte. API Fullscreen si le navigateur l'accepte, sinon simple calque fixe (Échap pour sortir).
  const stage = document.createElement("div");
  stage.className = "rp-stage";
  const mapEl = view.container();
  mapEl.parentNode.insertBefore(stage, mapEl);
  stage.append(mapEl, box);
  const fullBtn = $(".rp-full"), followBtn = $(".rp-follow");
  function setFull(on) {
    stage.classList.toggle("is-full", on);
    fullBtn.innerHTML = `<i class="ph ph-${on ? "corners-in" : "corners-out"}" aria-hidden="true"></i>`;
    fullBtn.setAttribute("aria-label", on ? "Quitter le plein écran" : "Plein écran");
    if (on && stage.requestFullscreen && !document.fullscreenElement) stage.requestFullscreen().catch(() => {});
    if (!on && document.fullscreenElement === stage) document.exitFullscreen().catch(() => {});
    setTimeout(() => view.resize(follow), 60);
  }
  fullBtn.addEventListener("click", () => setFull(!stage.classList.contains("is-full")));
  document.addEventListener("fullscreenchange", () => { if (!document.fullscreenElement && stage.classList.contains("is-full")) setFull(false); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && stage.classList.contains("is-full") && !document.fullscreenElement) setFull(false); });
  followBtn.addEventListener("click", () => {
    follow = !follow;
    followBtn.setAttribute("aria-pressed", String(follow));
    if (follow) view.refollow();
  });
  if (cfg.onReady) cfg.onReady(box);

  function fromTrack() {  // sans détails : vitesse constante sur la durée de la sortie
    const out = [[0, points[0][0], points[0][1], 0, null, null]];
    for (let k = 1; k < points.length; k++) out.push([0, points[k][0], points[k][1], out[k - 1][3] + view.distance(points[k - 1], points[k]), null, null]);
    const total = out[out.length - 1][3], dur = cfg.duration || total / 3;
    out.forEach(p => { p[0] = p[3] / total * dur; });
    return out;
  }
  function at(t) {  // point interpolé au temps t
    let i = S.findIndex(p => p[0] >= t);
    if (i <= 0) return { i: 0, p: S[0] };
    const a = S[i - 1], b = S[i], f = (t - a[0]) / ((b[0] - a[0]) || 1);
    const mix = (k) => a[k] == null || b[k] == null ? (a[k] ?? b[k]) : a[k] + (b[k] - a[k]) * f;
    return { i, p: [t, mix(1), mix(2), mix(3), mix(4), mix(5)] };
  }
  function ahead(i, d) {  // point ~60 m plus loin : direction de la sortie (caméra du survol 3D)
    let k = i;
    while (k < S.length - 1 && S[k][3] - d < 60) k++;
    return S[k];
  }
  function speedAt(t) {
    const a = at(Math.max(0, t - 15)).p, b = at(Math.min(S[S.length - 1][0], t + 15)).p;
    return (b[3] - a[3]) / ((b[0] - a[0]) || 1);
  }
  function gradeAt(i) {
    const d0 = S[i][3];
    let j = i, k = i;
    while (j > 0 && d0 - S[j][3] < 50) j--;
    while (k < S.length - 1 && S[k][3] - d0 < 50) k++;
    return S[j][5] == null || S[k][5] == null || S[k][3] === S[j][3] ? null : (S[k][5] - S[j][5]) / (S[k][3] - S[j][3]) * 100;
  }
  function drawProfile() {
    const eles = S.map(p => p[5]).filter(e => e != null);
    if (!detailed || eles.length < 2) return;
    const total = S[S.length - 1][3], w = 720, h = 110, l = 44, r = 8, top = 8, bottom = 20;
    let mn = Math.floor(Math.min(...eles) / 10) * 10, mx = Math.ceil(Math.max(...eles) / 10) * 10;
    if (mx === mn) mx = mn + 10;
    const X = (d) => l + d / total * (w - l - r), Y = (e) => top + (1 - (e - mn) / (mx - mn)) * (h - top - bottom);
    const step = Math.max(1, Math.floor(S.length / 600));
    const pts = S.filter((p, i) => p[5] != null && (i % step === 0 || i === S.length - 1)).map(p => `${X(p[3]).toFixed(1)},${Y(p[5]).toFixed(1)}`);
    let axis = `<text x="${l - 6}" y="${Y(mx) + 4}" text-anchor="end">${nf(mx)} m</text><text x="${l - 6}" y="${Y(mn) + 4}" text-anchor="end">${nf(mn)} m</text>`;
    const kmStep = total > 20000 ? 5 : total > 8000 ? 2 : 1;
    for (let km = 0; km * 1000 <= total; km += kmStep) axis += `<text x="${X(km * 1000)}" y="${h - 5}" text-anchor="middle">${km} km</text>`;
    prof.innerHTML = `<g class="rp-axis">${axis}</g><polygon class="rp-area" points="${l},${h - bottom} ${pts.join(" ")} ${w - r},${h - bottom}"/><polyline class="rp-line" points="${pts.join(" ")}"/><line class="rp-cursor" y1="${top}" y2="${h - bottom}"/><circle class="rp-dot" r="5"/>`;
    prof.hidden = false;
    prof.setAttribute("aria-valuemin", 0); prof.setAttribute("aria-valuemax", Math.round(total));
    prof._x = X; prof._y = Y;
  }
  function render() {
    const T = S[S.length - 1][0], { i, p } = at(pos);
    clock.textContent = `${hms(pos)} / ${hms(T)}`;
    scrub.value = Math.round(pos / T * 1000);
    view.show(p, { playing, follow, ahead: ahead(i, p[3]), progress: p[3] / S[S.length - 1][3] });
    const grade = detailed ? gradeAt(i) : null;
    const cells = [
      ["Position", `${nf(p[1], 5)}, ${nf(p[2], 5)}`],
      ["Altitude", p[5] != null ? `${nf(p[5])} m` : null],
      ["Pente", grade != null ? `${grade > 0 ? "+" : ""}${nf(grade, 1)} %` : null],
      ["Distance", `${nf(p[3] / 1000, 2)} km`],
      ["Temps", hms(pos)],
      [speedLabel, detailed ? speedText(speedAt(pos)) : null],
      ["FC", p[4] != null ? `${Math.round(p[4])} bpm` : null],
    ].filter(c => c[1] != null);
    stats.innerHTML = cells.map(([k, v]) => `<div class="metric"><small>${k}</small><b>${v}</b></div>`).join("");
    stats.hidden = false;
    if (!prof.hidden) {
      const x = prof._x(p[3]);
      prof.querySelector(".rp-cursor").setAttribute("x1", x); prof.querySelector(".rp-cursor").setAttribute("x2", x);
      const dot = prof.querySelector(".rp-dot");
      if (p[5] != null) { dot.setAttribute("cx", x); dot.setAttribute("cy", prof._y(p[5])); }
      prof.setAttribute("aria-valuenow", Math.round(p[3]));
    }
    // Icône réécrite seulement quand l'état change : la remplacer à chaque image (60 fois par seconde) faisait
    // disparaître l'élément sous la souris entre l'appui et le relâchement, et le clic « pause » ne partait pas.
    if (btn.dataset.state !== String(playing)) {
      btn.dataset.state = String(playing);
      btn.innerHTML = `<i class="ph ph-${playing ? "pause" : "play"}" aria-hidden="true"></i>`;
      btn.setAttribute("aria-label", playing ? "Pause" : "Lecture");
    }
  }
  async function load() {
    if (S || loading) return !!S;
    loading = true;
    clock.textContent = "Chargement des détails…";
    try {
      const r = await fetch(cfg.url);
      const data = await r.json();
      if (data.samples && data.samples.length > 1) { S = data.samples; detailed = true; }
      else note.textContent = data.error ? `Détails indisponibles (${data.error}) : lecture à vitesse constante, sans altitude ni FC.`
                                         : "Garmin n'a pas de données détaillées pour cette sortie : lecture à vitesse constante, sans altitude ni FC.";
    } catch (e) {
      note.textContent = "Détails indisponibles : lecture à vitesse constante, sans altitude ni FC.";
    }
    if (!S) { S = fromTrack(); note.hidden = false; }
    loading = false;
    scrub.disabled = false;
    drawProfile();
    return true;
  }
  // Une seule boucle d'animation à la fois (pause puis lecture très vite en lançait une deuxième : vitesse doublée).
  // La vitesse choisie est toujours respectée, y compris si Windows demande de réduire les animations.
  let frame = null;
  function tick(now) {
    frame = null;
    if (!playing) return;
    const T = S[S.length - 1][0];
    if (last !== null) pos = Math.min(T, pos + (now - last) / 1000 * mult);
    last = now;
    if (pos >= T) playing = false;
    render();
    if (playing) frame = requestAnimationFrame(tick);
  }
  btn.addEventListener("click", async () => {
    if (!(await load())) return;
    if (pos >= S[S.length - 1][0]) pos = 0;
    playing = !playing; last = null;
    if (frame !== null) { cancelAnimationFrame(frame); frame = null; }
    if (playing && follow) view.start(at(pos).p);  // zoomer sur le point au lancement
    render();
    if (playing) frame = requestAnimationFrame(tick);
  });
  scrub.addEventListener("input", () => { if (!S) return; playing = false; pos = scrub.value / 1000 * S[S.length - 1][0]; render(); });
  box.querySelectorAll(".rp-speeds button").forEach(b => b.addEventListener("click", () => {
    mult = +b.dataset.m;
    box.querySelectorAll(".rp-speeds button").forEach(x => x.setAttribute("aria-pressed", String(x === b)));
  }));
  const seek = (e) => {  // clic ou glisser sur le profil : aller à cette distance
    const r = prof.getBoundingClientRect(), total = S[S.length - 1][3];
    const d = Math.min(1, Math.max(0, ((e.clientX - r.left) / r.width * 720 - 44) / 668)) * total;
    const k = S.findIndex(p => p[3] >= d);
    playing = false; pos = S[k < 0 ? S.length - 1 : k][0]; render();
  };
  prof.addEventListener("pointerdown", (e) => { prof.setPointerCapture(e.pointerId); seek(e); });
  prof.addEventListener("pointermove", (e) => { if (e.buttons) seek(e); });
  prof.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault(); playing = false;
    pos = Math.min(S[S.length - 1][0], Math.max(0, pos + (e.key === "ArrowRight" ? 30 : -30))); render();
  });
}

// Affichage du point sur une carte Leaflet : point violet ; « suivre » recadre dès qu'il approche du bord
// (un quart de la carte), sans animation pendant la lecture ; au lancement, zoom 15 au minimum.
function leafletView(map, cfg) {
  let runner = null;
  return {
    container: () => map.getContainer(),
    distance: (a, b) => map.distance(a, b),
    show(p, { playing, follow }) {
      const ll = [p[1], p[2]];
      if (!runner) runner = L.circleMarker(ll, { radius: 8, color: "#fff", weight: 3, fillColor: cfg.accent || "#6b4fc1", fillOpacity: 1 }).addTo(map);
      runner.setLatLng(ll);
      if (follow && !map.getBounds().pad(-0.25).contains(ll)) map.panTo(ll, { animate: !playing });
    },
    start(p) { if (map.getZoom() < 15) map.setView([p[1], p[2]], 15, { animate: false }); },
    refollow() { if (runner) map.panTo(runner.getLatLng()); },
    resize(follow) { map.invalidateSize(); if (runner && follow) map.panTo(runner.getLatLng(), { animate: false }); },
  };
}

function homeMarker(map, home) {
  return L.circleMarker(home, { radius: 8, color: "#fff", weight: 3, fillColor: "#1F2A36", fillOpacity: 1 })
    .bindTooltip("Domicile").addTo(map);
}

// Carte de tous les parcours. Vue de départ : autour du domicile (s'il est connu), sinon tous les parcours.
// Le menu « Lieu » (select#place) recentre sur un lieu Garmin, sur le domicile ou sur l'ensemble.
// heat = true : carte de chaleur, chaque tracé en trait fin semi-transparent d'une même couleur sur un fond
// assombri ; les routes souvent faites s'additionnent et deviennent vives.
const HEAT = { color: "#FF6A1F", weight: 2, opacity: .1 };

function routesMap(id, routes, home, heat = false) {
  const map = baseMap(id);
  if (heat) document.getElementById(id).classList.add("heat");
  if (home) homeMarker(map, home);
  if (!routes.length) { map.setView(home || [50.5, 4.5], home ? 12 : 7); return map; }
  const all = [], byPlace = {};
  for (const r of routes) {
    (byPlace[r.place] ||= []).push(...r.points);
    const rest = heat ? HEAT : { color: r.color, weight: 3, opacity: .55 };
    const line = L.polyline(r.points, rest).addTo(map);
    const tip = `<b>${escapeHtml(r.name)}</b><br>${r.date} · ${escapeHtml(r.sport)}${r.km ? " · " + r.km : ""}`;
    line.bindTooltip(tip, { sticky: true });
    line.on("mouseover", () => line.setStyle({ color: heat ? "#FFD23F" : r.color, weight: 6, opacity: 1 }).bringToFront());
    line.on("mouseout", () => line.setStyle(rest));
    line.on("click", () => { location.href = r.url; });
    all.push(...r.points);
  }
  const show = (value) => {
    if (value === "__home" && home) map.setView(home, 12);
    else if (value && byPlace[value]) map.fitBounds(L.latLngBounds(byPlace[value]), { padding: [20, 20] });
    else map.fitBounds(L.latLngBounds(all), { padding: [20, 20] });
  };
  const select = document.getElementById("place");
  if (select) select.addEventListener("change", () => show(select.value));
  show(select ? select.value : (home ? "__home" : ""));
  return map;
}

// Petite carte des Paramètres : cliquer pose le domicile dans les champs du formulaire.
function homePicker(id, home, fallback) {
  const map = baseMap(id);
  map.setView(home || fallback || [50.5, 4.5], home || fallback ? 13 : 7);
  let marker = home ? homeMarker(map, home) : null;
  map.on("click", (e) => {
    const lat = e.latlng.lat.toFixed(5), lon = e.latlng.lng.toFixed(5);
    document.getElementById("home-lat").value = lat;
    document.getElementById("home-lon").value = lon;
    if (marker) marker.remove();
    marker = homeMarker(map, [lat, lon]);
    document.getElementById("home-save").disabled = false;
  });
  return map;
}

// Création d'un segment sur la carte d'une sortie : clic sur le départ, puis sur l'arrivée (plus loin dans le sens
// de la sortie). Actif seulement quand le panneau <details id="pickerId"> est ouvert ; remplit son formulaire.
function segmentPicker(map, points, pickerId) {
  const box = document.getElementById(pickerId);
  if (!map || !box || points.length < 2) return;
  const form = box.querySelector("form"), status = box.querySelector(".seg-status"), btn = form.querySelector("button[type=submit]");
  const cum = [0];
  for (let k = 1; k < points.length; k++) cum.push(cum[k - 1] + map.distance(points[k - 1], points[k]));
  const fmtKm = (m) => (m / 1000).toLocaleString("fr-BE", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " km";
  let start = null, end = null, layers = [];

  const nearest = (latlng, from) => {
    let best = -1, bestD = Infinity;
    for (let k = from; k < points.length; k++) {
      const d = map.distance(latlng, points[k]);
      if (d < bestD) { bestD = d; best = k; }
    }
    return [best, bestD];
  };
  const clear = () => { layers.forEach(l => l.remove()); layers = []; };
  const draw = () => {
    clear();
    if (start !== null) layers.push(L.circleMarker(points[start], { radius: 8, color: "#fff", weight: 3, fillColor: "#2D7A4C", fillOpacity: 1 }).addTo(map));
    if (end !== null) {
      layers.push(L.polyline(points.slice(start, end + 1), { color: "#FFB000", weight: 7, opacity: .95 }).addTo(map));
      layers.push(L.circleMarker(points[end], { radius: 8, color: "#fff", weight: 3, fillColor: "#A8413A", fillOpacity: 1 }).addTo(map));
    }
    form.start_idx.value = start ?? "";
    form.end_idx.value = end ?? "";
    btn.disabled = end === null;
    status.textContent = start === null ? "Clique sur le tracé à l'endroit où commence le segment."
      : end === null ? `Départ au km ${fmtKm(cum[start]).replace(" km", "")}. Clique maintenant sur l'arrivée, plus loin dans le sens de la sortie.`
      : `Segment de ${fmtKm(cum[end] - cum[start])}, du km ${fmtKm(cum[start]).replace(" km", "")} au km ${fmtKm(cum[end]).replace(" km", "")}. Donne-lui un nom et enregistre.`;
  };
  map.on("click", (e) => {
    if (!box.open) return;
    const picking = start === null || end !== null ? "start" : "end";
    const [idx, d] = nearest(e.latlng, picking === "start" ? 0 : start + 1);
    if (idx < 0 || d > 150) { status.textContent = "Clique plus près du tracé (à moins de 150 m)."; return; }
    if (picking === "start") { start = idx; end = null; } else { end = idx; }
    draw();
  });
  box.querySelector(".seg-reset").addEventListener("click", () => { start = end = null; draw(); });
  box.addEventListener("toggle", () => {
    map.getContainer().classList.toggle("picking", box.open);
    if (!box.open) { start = end = null; clear(); } else draw();
  });
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
