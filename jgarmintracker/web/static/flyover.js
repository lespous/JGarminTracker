// Survol 3D d'une sortie (MapLibre GL, copié dans static/) : relief Terrarium (Mapzen / AWS Open Data, sans clé),
// fond plan OpenStreetMap ou satellite Esri, relief accentué réglable. La caméra suit le point en regardant dans le
// sens de la sortie ; le lecteur (replayPlayer, maps.js) est le même que celui de la carte 2D.
function flyover(id, points, cfg) {
  if (!points || points.length < 2 || !window.maplibregl) return;
  const R = 6371008.8, rad = Math.PI / 180;
  const dist = (a, b) => {  // haversine, en mètres ; points [lat, lon]
    const dLat = (b[0] - a[0]) * rad, dLon = (b[1] - a[1]) * rad;
    const h = Math.sin(dLat / 2) ** 2 + Math.cos(a[0] * rad) * Math.cos(b[0] * rad) * Math.sin(dLon / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(h));
  };
  const bearing = (a, b) => {
    const y = Math.sin((b[1] - a[1]) * rad) * Math.cos(b[0] * rad);
    const x = Math.cos(a[0] * rad) * Math.sin(b[0] * rad) - Math.sin(a[0] * rad) * Math.cos(b[0] * rad) * Math.cos((b[1] - a[1]) * rad);
    return (Math.atan2(y, x) / rad + 360) % 360;
  };
  const lnglat = (p) => [p[1], p[0]];
  const cum = [0];
  for (let k = 1; k < points.length; k++) cum.push(cum[k - 1] + dist(points[k - 1], points[k]));
  const total = cum[cum.length - 1];
  const part = (from, to) => points.filter((_, k) => cum[k] >= from && cum[k] <= to).map(lnglat);
  const line = (coords, props = {}) => ({ type: "Feature", properties: props, geometry: { type: "LineString", coordinates: coords } });
  const pointF = (p) => ({ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: p } });
  const css = (n, fb) => getComputedStyle(document.documentElement).getPropertyValue(n).trim() || fb;
  const accent = css("--accent", "#6b4fc1"), color = cfg.color || "#E4572E";
  let exaggeration = 1.8;

  const map = new maplibregl.Map({
    container: id,
    attributionControl: { compact: true },
    maxPitch: 80,
    style: {
      version: 8,
      sources: {
        osm: { type: "raster", tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"], tileSize: 256, maxzoom: 19,
               attribution: "© contributeurs OpenStreetMap" },
        sat: { type: "raster", tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],
               tileSize: 256, maxzoom: 19, attribution: "Imagerie © Esri, Maxar, Earthstar Geographics" },
        dem: { type: "raster-dem", tiles: ["https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"],
               tileSize: 256, maxzoom: 15, encoding: "terrarium", attribution: "Relief : Mapzen, AWS Terrain Tiles" },
        hill: { type: "raster-dem", tiles: ["https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"],
                tileSize: 256, maxzoom: 15, encoding: "terrarium" },
        route: { type: "geojson", data: line(points.map(lnglat)) },
        done: { type: "geojson", data: line([lnglat(points[0]), lnglat(points[0])]) },
        ends: { type: "geojson", data: { type: "FeatureCollection", features: total > 300 ? [
          line(part(0, 100), { c: START_COLOR }), line(part(total - 100, total), { c: END_COLOR })] : [] } },
        pins: { type: "geojson", data: { type: "FeatureCollection", features: [
          { ...pointF(lnglat(points[0])), properties: { c: START_COLOR } },
          { ...pointF(lnglat(points[points.length - 1])), properties: { c: END_COLOR } }] } },
        runner: { type: "geojson", data: pointF(lnglat(points[0])) },
      },
      layers: [
        { id: "osm", type: "raster", source: "osm" },
        { id: "sat", type: "raster", source: "sat", layout: { visibility: "none" } },
        { id: "hillshade", type: "hillshade", source: "hill", paint: { "hillshade-exaggeration": .35, "hillshade-shadow-color": "#3b3426" } },
        { id: "route-casing", type: "line", source: "route", layout: { "line-join": "round", "line-cap": "round" },
          paint: { "line-color": "#ffffff", "line-width": 8, "line-opacity": .8 } },
        { id: "route", type: "line", source: "route", layout: { "line-join": "round", "line-cap": "round" },
          paint: { "line-width": 5, "line-color": color } },
        { id: "done", type: "line", source: "done", layout: { "line-join": "round", "line-cap": "round" },
          paint: { "line-width": 6, "line-color": accent } },
        { id: "ends", type: "line", source: "ends", layout: { "line-cap": "round" }, paint: { "line-color": ["get", "c"], "line-width": 7 } },
        { id: "pins", type: "circle", source: "pins", paint: { "circle-radius": 7, "circle-color": ["get", "c"], "circle-stroke-color": "#fff", "circle-stroke-width": 2.5 } },
        { id: "runner", type: "circle", source: "runner", paint: { "circle-radius": 8, "circle-color": accent, "circle-stroke-color": "#fff", "circle-stroke-width": 3 } },
      ],
      terrain: { source: "dem", exaggeration },
    },
  });
  map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-left");
  const lons = points.map(p => p[1]), lats = points.map(p => p[0]);
  map.fitBounds([[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]], { padding: 50, pitch: 55, duration: 0 });

  let camBearing = null, lastShow = null, near = 0;
  // Tracé déjà parcouru (couleur d'accent) : points du tracé jusqu'au plus proche du point courant, cherché près du
  // précédent (la distance des données détaillées ne correspond pas exactement au tracé simplifié).
  const kx = Math.cos(points[0][0] * rad);
  function nearestIndex(lat, lon) {
    const d2 = (k) => ((points[k][0] - lat) ** 2 + ((points[k][1] - lon) * kx) ** 2);
    let best = near, bestD = d2(near);
    const lo = Math.max(0, near - 80), hi = Math.min(points.length - 1, near + 200);
    for (let k = lo; k <= hi; k++) { const v = d2(k); if (v < bestD) { bestD = v; best = k; } }
    if (bestD > 1e-6) for (let k = 0; k < points.length; k++) { const v = d2(k); if (v < bestD) { bestD = v; best = k; } }  // saut (barre, profil)
    near = best;
    return best;
  }
  // Le relief arrive après la caméra : une fois chargé, recentrer sur le point (sinon la caméra vise l'altitude 0).
  // Une seule fois par position affichée : sinon recentrer -> redessiner -> « idle » -> recentrer… sans fin.
  map.on("idle", () => {
    if (lastShow && lastShow.follow && !lastShow.playing && !lastShow.recentred) { lastShow.recentred = true; map.jumpTo({ center: lastShow.here }); }
  });
  const view = {
    container: () => map.getContainer(),
    distance: dist,
    show(p, { playing, follow, ahead }) {
      const here = [p[2], p[1]];
      lastShow = { here, follow, playing };
      map.getSource("runner")?.setData(pointF(here));
      const k = nearestIndex(p[1], p[2]);
      map.getSource("done")?.setData(line([...points.slice(0, k + 1).map(lnglat), here]));
      if (!follow) return;
      const target = ahead && (ahead[1] !== p[1] || ahead[2] !== p[2]) ? bearing([p[1], p[2]], [ahead[1], ahead[2]]) : (camBearing ?? 0);
      if (camBearing === null) camBearing = target;
      let delta = ((target - camBearing + 540) % 360) - 180;  // virage le plus court, lissé
      camBearing = (camBearing + delta * (playing ? .08 : 1) + 360) % 360;
      map.jumpTo({ center: here, bearing: camBearing, pitch: Math.max(map.getPitch(), 55) });
    },
    start(p) {
      camBearing = null;
      map.jumpTo({ center: [p[2], p[1]], zoom: Math.max(map.getZoom(), 15), pitch: 62 });
    },
    refollow() {},
    resize() { map.resize(); },
  };

  replayPlayer(map, points, {
    ...cfg, view, mult: 30,
    extraControls: `<div class="fly-base" role="group" aria-label="Fond de carte">
        <button type="button" data-base="osm" aria-pressed="true">Plan</button><button type="button" data-base="sat" aria-pressed="false">Satellite</button></div>
      <label class="fly-exag" title="Relief accentué">Relief <input type="range" min="1" max="3" step="0.5" value="${exaggeration}" aria-label="Relief accentué"><span class="num">×${exaggeration}</span></label>`,
    onReady(box) {
      box.querySelectorAll(".fly-base button").forEach(b => b.addEventListener("click", () => {
        const sat = b.dataset.base === "sat";
        map.setLayoutProperty("sat", "visibility", sat ? "visible" : "none");
        map.setLayoutProperty("osm", "visibility", sat ? "none" : "visible");
        map.setPaintProperty("hillshade", "hillshade-exaggeration", sat ? .15 : .35);
        box.querySelectorAll(".fly-base button").forEach(x => x.setAttribute("aria-pressed", String(x === b)));
      }));
      const r = box.querySelector(".fly-exag input"), out = box.querySelector(".fly-exag span");
      r.addEventListener("input", () => {
        exaggeration = +r.value;
        out.textContent = "×" + exaggeration.toLocaleString("fr-BE");
        map.setTerrain({ source: "dem", exaggeration });
      });
    },
  });
  return map;
}
