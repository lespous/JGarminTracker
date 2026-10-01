// Aides communes aux graphiques Chart.js : couleurs du thème (variables CSS) et formats belges.
const css = getComputedStyle(document.documentElement);
const cssVar = (name) => css.getPropertyValue(name).trim();

const fmt = {
  num: (v, d = 0) => v == null ? "—" : v.toLocaleString("fr-BE", { minimumFractionDigits: d, maximumFractionDigits: d }),
  // Secondes -> « m:ss » (allures).
  mmss: (s) => {
    if (s == null) return "—";
    const t = Math.round(s);
    return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`;
  },
  // Heures décimales -> « 3 h 56 », ou « 50 min » sous l'heure (le « : » est réservé aux allures).
  hmm: (h) => {
    if (h == null) return "—";
    const m = Math.round(h * 60);
    return m >= 60 ? `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")}` : `${m} min`;
  },
};

function baseOptions(extra = {}) {
  const muted = cssVar("--muted"), grid = cssVar("--soft"), ink = cssVar("--ink");
  return {
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    scales: {
      x: { ticks: { color: muted, maxRotation: 0, autoSkip: true, autoSkipPadding: 12 }, grid: { display: false } },
      y: { ticks: { color: muted }, grid: { color: grid } },
    },
    plugins: { legend: { labels: { color: ink, boxWidth: 12 } } },
    ...extra,
  };
}

// Fusion simple d'options imbriquées (scales, plugins).
function merge(target, src) {
  for (const [k, v] of Object.entries(src)) {
    if (v && typeof v === "object" && !Array.isArray(v) && target[k] && typeof target[k] === "object") merge(target[k], v);
    else target[k] = v;
  }
  return target;
}

function chart(id, config, extraOptions = {}) {
  const el = document.getElementById(id);
  if (!el) return null;
  config.options = merge(baseOptions(), merge(config.options || {}, extraOptions));
  return new Chart(el, config);
}
