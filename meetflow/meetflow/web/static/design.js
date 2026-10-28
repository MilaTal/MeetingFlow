// Оформление — как было в MeetFlow до переноса фронта ERP (архив 928f4f7).
// Палитры — круглыми образцами 28 px, двумя группами: «Проекты-примеры и пресеты» и «Для новых проектов»;
// тема — тремя кнопками; метки исполнителей — подписями. Выбор хранится в localStorage и применяется сразу.
(function () {
  const PALETTES = { emerald: "#1f845a", indigo: "#6863bf", forest: "#2f4f41", polaris: "#008060", sage: "#4b6358", meadow: "#257e52" };
  const PALETTES_NEW = { petrol: "#1d5e69", ocean: "#245a8c", slate: "#46586f", graphite: "#3f4249", ochre: "#8a5a12", clay: "#a14e36", copper: "#8c5232", claret: "#7d3045" };
  const THEMES = { auto: "Как в системе", light: "Светлая", dark: "Тёмная" };
  const ACTOR = [["actor-model", "со встречи"], ["actor-operator", "вручную"], ["actor-operator", "комментарий"],
    ["actor-store", "система"], ["actor-local", "локальное распознавание"], ["actor-admin", "супер-админ"]];
  const store = {
    get(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* приватное окно */ } },
  };

  // «Как в системе» — по настройке системы, как в MeetFlow до переноса фронта ERP (решение владелицы 28.10.2026): при тёмной
  // системе ставится та же тёмная тема, что по кнопке «Тёмная», и меняется вместе с системой без перезагрузки.
  const systemDark = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

  function apply() {
    const palette = store.get("palette", "indigo");
    const theme = store.get("theme", "auto");
    if (PALETTES[palette] || PALETTES_NEW[palette]) document.documentElement.dataset.palette = palette;
    const resolved = theme === "auto" ? (systemDark && systemDark.matches ? "dark" : "") : theme;
    if (resolved) document.documentElement.dataset.theme = resolved;
    else delete document.documentElement.dataset.theme;
  }

  function renderDesign() {
    const curP = store.get("palette", "indigo");
    const curT = store.get("theme", "auto");
    const main = document.getElementById("main");
    if (!main) return;
    const set = (items) => `<div class="swatches">${Object.entries(items).map(([key, color]) =>
      `<button class="swatch" style="background:${color}" title="${key}" aria-label="Палитра ${key}"
        aria-pressed="${key === curP}" data-p="${key}"></button>`).join("")}</div>`;
    main.innerHTML = `<h1>Оформление</h1><div class="card stack">
      <h2 style="margin:0">Палитра</h2>
      <div class="sub">Проекты-примеры и пресеты</div>${set(PALETTES)}
      <div class="sub">Для новых проектов</div>${set(PALETTES_NEW)}
      <h2 style="margin:8px 0 0">Тема</h2>
      <div class="design-buttons">${Object.entries(THEMES).map(([key, title]) =>
        `<button class="btn ${key === curT ? "btn-primary" : ""}" data-t="${key}">${title}</button>`).join("")}</div>
      <h2 style="margin:8px 0 0">Метки исполнителей</h2>
      <div class="design-buttons">${ACTOR.map(([cls, title]) => `<span class="actor ${cls}">${title}</span>`).join("")}</div>
    </div>`;
    main.querySelectorAll("[data-p]").forEach((b) => b.onclick = () => {
      store.set("palette", b.dataset.p); apply(); renderDesign();
    });
    main.querySelectorAll("[data-t]").forEach((b) => b.onclick = () => {
      store.set("theme", b.dataset.t); apply(); renderDesign();
    });
  }

  if (typeof routes !== "undefined") routes.design = renderDesign;
  if (systemDark && systemDark.addEventListener) systemDark.addEventListener("change", apply);
  apply();
})();
