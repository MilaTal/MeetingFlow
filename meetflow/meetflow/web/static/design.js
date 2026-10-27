// Оформление: выбор палитры и темы. Возвращено по слову владелицы 27.10.2026 после переноса фронта ERP.
// Настройки хранятся в localStorage браузера (как было в MeetFlow): палитра и тема применяются сразу.
(function () {
  const PALETTES = {
    indigo: ["#6863bf", "Индиго"],
    forest: ["#2f4f41", "Тёмный лес"],
    emerald: ["#1b7a52", "Изумруд"],
    polaris: ["#008060", "Полярная зелень"],
    sage: ["#4b6358", "Шалфей"],
    meadow: ["#257e52", "Луг"],
    petrol: ["#1d5e69", "Нефть"],
    ocean: ["#245a8c", "Океан"],
    slate: ["#46586f", "Сланец"],
    graphite: ["#3f4249", "Графит"],
    ochre: ["#8a5a12", "Охра"],
    clay: ["#a14e36", "Глина"],
    copper: ["#8c5232", "Медь"],
    claret: ["#7d3045", "Бордо"],
  };
  const THEMES = { auto: "Как в системе", light: "Светлая", dark: "Тёмная" };
  const store = {
    get(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* приватное окно */ } },
  };

  function apply() {
    const palette = store.get("palette", "indigo");
    const theme = store.get("theme", "auto");
    if (PALETTES[palette]) document.documentElement.dataset.palette = palette;
    if (theme === "auto") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = theme;
  }

  function renderDesign() {
    const curP = store.get("palette", "indigo");
    const curT = store.get("theme", "auto");
    const main = document.getElementById("main");
    if (!main) return;
    main.innerHTML = `<h1>Оформление</h1>
      <div class="card stack"><h2 style="margin:0">Палитра</h2>
        <div class="sub">Цвет кнопок, ссылок и выделения. Выбор запоминается в этом браузере.</div>
        <div class="row" style="gap:10px">${Object.entries(PALETTES).map(([key, [color, title]]) =>
          `<button class="btn" data-p="${key}" title="${title}" aria-pressed="${key === curP}"
            style="background:${color};color:#fff;border-color:${color};min-width:120px">${title}${key === curP ? " ✓" : ""}</button>`).join("")}</div>
        <h2 style="margin:16px 0 0">Тема</h2>
        <div class="row" style="gap:10px">${Object.entries(THEMES).map(([key, title]) =>
          `<button class="btn ${key === curT ? "btn-primary" : ""}" data-t="${key}">${title}</button>`).join("")}</div>
        <p class="sub">Тёмная тема — по выбору; «Как в системе» следует настройке Windows.</p>
      </div>`;
    main.querySelectorAll("[data-p]").forEach((b) => b.onclick = () => {
      store.set("palette", b.dataset.p); apply(); renderDesign();
    });
    main.querySelectorAll("[data-t]").forEach((b) => b.onclick = () => {
      store.set("theme", b.dataset.t); apply(); renderDesign();
    });
  }

  if (typeof routes !== "undefined") routes.design = renderDesign;
  apply();
})();
