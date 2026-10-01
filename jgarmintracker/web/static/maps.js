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

function routesMap(id, routes) {
  const map = baseMap(id);
  if (!routes.length) { map.setView([50.5, 4.5], 7); return map; }
  const all = [];
  for (const r of routes) {
    const line = L.polyline(r.points, { color: r.color, weight: 3, opacity: .55 }).addTo(map);
    const tip = `<b>${escapeHtml(r.name)}</b><br>${r.date} · ${escapeHtml(r.sport)}${r.km ? " · " + r.km : ""}`;
    line.bindTooltip(tip, { sticky: true });
    line.on("mouseover", () => line.setStyle({ weight: 6, opacity: 1 }).bringToFront());
    line.on("mouseout", () => line.setStyle({ weight: 3, opacity: .55 }));
    line.on("click", () => { location.href = r.url; });
    all.push(...r.points);
  }
  map.fitBounds(L.latLngBounds(all), { padding: [20, 20] });
  return map;
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
