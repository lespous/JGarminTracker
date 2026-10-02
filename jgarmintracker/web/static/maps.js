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

function trackMap(id, points, color) {
  if (!points || points.length < 2) return null;
  const map = baseMap(id);
  const line = L.polyline(points, { color, weight: 4, opacity: .9 }).addTo(map);
  endpoint(map, points[0], "#2D7A4C", "Départ");
  endpoint(map, points[points.length - 1], "#A8413A", "Arrivée");
  map.fitBounds(line.getBounds(), { padding: [20, 20] });
  return map;
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
