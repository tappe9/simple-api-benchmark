export function wireDashboard(root, model, { tests, metrics, stacks }) {
  const dashboard = root.querySelector("[data-dashboard]");
  if (!dashboard) return;

  const endpoints = model.conditions.endpoints;
  let endpoint = endpoints[0];
  let metric = "rps";
  const visibleImplementations = new Set(model.implementations);
  const visibleLanguages = new Set(model.implementations.map((id) => stacks[id].language));

  const included = (id) => visibleImplementations.has(id) && visibleLanguages.has(stacks[id].language);

  const refresh = () => {
    const endpointButtons = [...dashboard.querySelectorAll("[data-endpoint]")];
    endpointButtons.forEach((button) => {
      const selected = button.dataset.endpoint === endpoint;
      button.setAttribute("aria-selected", String(selected));
      button.tabIndex = selected ? 0 : -1;
    });
    dashboard.querySelectorAll("[data-metric]").forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.metric === metric));
    });
    dashboard.querySelectorAll("[data-chart]").forEach((section) => {
      section.hidden = section.dataset.chartEndpoint !== endpoint || section.dataset.chartMetric !== metric;
      section.querySelectorAll("[data-chart-implementation]").forEach((item) => {
        item.hidden = !included(item.dataset.chartImplementation);
      });
    });
    root.querySelectorAll("[data-result-row]").forEach((row) => {
      row.hidden = row.dataset.rowEndpoint !== endpoint || !included(row.dataset.implementation);
    });
    const visibleCount = model.implementations.filter(included).length;
    const status = dashboard.querySelector("[data-dashboard-status]");
    if (status) {
      status.textContent = `Showing ${tests[endpoint]} ${metrics[metric].label} for ${visibleCount} framework${visibleCount === 1 ? "" : "s"}.`;
    }
  };

  dashboard.addEventListener("click", (event) => {
    const endpointButton = event.target.closest("[data-endpoint]");
    if (endpointButton) endpoint = endpointButton.dataset.endpoint;
    const metricButton = event.target.closest("[data-metric]");
    if (metricButton) metric = metricButton.dataset.metric;
    refresh();
  });

  dashboard.addEventListener("keydown", (event) => {
    const current = event.target.closest("[data-endpoint]");
    if (!current || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    const buttons = [...dashboard.querySelectorAll("[data-endpoint]")];
    let index = buttons.indexOf(current);
    if (event.key === "Home") index = 0;
    else if (event.key === "End") index = buttons.length - 1;
    else if (event.key === "ArrowRight") index = (index + 1) % buttons.length;
    else index = (index - 1 + buttons.length) % buttons.length;
    event.preventDefault();
    endpoint = buttons[index].dataset.endpoint;
    refresh();
    buttons[index].focus();
  });

  dashboard.addEventListener("change", (event) => {
    const frameworkFilter = event.target.closest("[data-implementation-filter]");
    if (frameworkFilter) {
      const id = frameworkFilter.dataset.implementationFilter;
      if (frameworkFilter.checked) visibleImplementations.add(id);
      else visibleImplementations.delete(id);
    }
    const languageFilter = event.target.closest("[data-language-filter]");
    if (languageFilter) {
      const language = languageFilter.dataset.languageFilter;
      if (languageFilter.checked) visibleLanguages.add(language);
      else visibleLanguages.delete(language);
    }
    refresh();
  });

  refresh();
}

export function wireTheme(document, storage = globalThis.localStorage) {
  const button = document.getElementById("theme-toggle");
  if (!button) return;
  const root = document.documentElement;
  const stored = storage?.getItem("sab-theme");
  const initial = stored === "dark" ? "dark" : "light";
  const apply = (theme) => {
    root.dataset.theme = theme;
    button.setAttribute("aria-pressed", String(theme === "dark"));
    button.textContent = theme === "dark" ? "Use light theme" : "Use dark theme";
  };
  apply(initial);
  button.addEventListener("click", () => {
    const next = root.dataset.theme === "dark" ? "light" : "dark";
    storage?.setItem("sab-theme", next);
    apply(next);
  });
}
