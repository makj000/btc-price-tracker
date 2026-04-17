const state = {
  history: [],
  settings: null,
};

const latestPriceEl = document.getElementById("latest-price");
const latestUpdatedEl = document.getElementById("latest-updated");
const nextCheckEl = document.getElementById("next-check");
const settingsStatusEl = document.getElementById("settings-status");
const chartEl = document.getElementById("history-chart");
const chartEmptyEl = document.getElementById("chart-empty");
const alertsTableBodyEl = document.getElementById("alerts-table-body");

async function loadDashboard() {
  const [statusResponse, historyResponse, alertsResponse] = await Promise.all([
    fetch("/api/status"),
    fetch("/api/history?limit=288"),
    fetch("/api/alerts?limit=20"),
  ]);

  const statusPayload = await statusResponse.json();
  const historyPayload = await historyResponse.json();
  const alertsPayload = await alertsResponse.json();

  state.settings = statusPayload.settings;
  state.history = historyPayload.history;

  renderStatus(statusPayload.latest_price, statusPayload.next_check_at);
  renderHistory(historyPayload.history);
  renderSettingsForm(statusPayload.settings);
  renderAlerts(alertsPayload.alerts);
}

function renderStatus(latestPrice, nextCheckAt) {
  latestPriceEl.textContent = latestPrice ? formatMoney(latestPrice.price_usd) : "$--";
  latestUpdatedEl.textContent = latestPrice
    ? `Last check: ${formatDateTime(latestPrice.fetched_at)}`
    : "No samples yet";
  nextCheckEl.textContent = nextCheckAt
    ? `Next check: ${formatDateTime(nextCheckAt)}`
    : "Next check: --";
}

function renderSettingsForm(settings) {
  document.getElementById("high-threshold-input").value = settings.high_threshold ?? "";
  document.getElementById("low-threshold-input").value = settings.low_threshold ?? "";
  document.getElementById("alert-phone-input").value = settings.alert_phone ?? "";
  document.getElementById("frequency-input").value = settings.poll_frequency_minutes ?? 5;
  document.getElementById("cooldown-input").value = settings.alert_cooldown_minutes ?? 60;
  document.getElementById("sms-enabled-input").checked = Boolean(settings.sms_enabled);
}

function renderHistory(history) {
  if (!history.length) {
    chartEl.innerHTML = "";
    chartEmptyEl.style.display = "block";
    return;
  }

  chartEmptyEl.style.display = "none";
  const prices = history.map((point) => point.price_usd);
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const range = max - min || 1;
  let latestX = 0;
  let latestY = 240;

  const points = history
    .map((point, index) => {
      const x = (index / Math.max(history.length - 1, 1)) * 800;
      const y = 240 - ((point.price_usd - min) / range) * 200;
      if (index === history.length - 1) {
        latestX = x;
        latestY = y;
      }
      return `${x},${y}`;
    })
    .join(" ");

  chartEl.innerHTML = `
    <line x1="0" y1="240" x2="800" y2="240" class="chart-axis"></line>
    <polyline points="${points}" class="chart-line"></polyline>
    <circle cx="${latestX}" cy="${latestY}" r="5" class="chart-dot"></circle>
    <text x="10" y="24" class="chart-label">High ${formatMoney(max)}</text>
    <text x="10" y="258" class="chart-label">Low ${formatMoney(min)}</text>
  `;
}

function renderAlerts(alerts) {
  if (!alerts.length) {
    alertsTableBodyEl.innerHTML = `
      <tr>
        <td colspan="6" class="muted">No alerts recorded yet.</td>
      </tr>
    `;
    return;
  }

  alertsTableBodyEl.innerHTML = alerts
    .map(
      (alert) => `
        <tr>
          <td>${alert.alert_type}</td>
          <td>${formatMoney(alert.price_usd)}</td>
          <td>${formatThreshold(alert.threshold_value)}</td>
          <td>${escapeHtml(alert.sms_status)}</td>
          <td>${escapeHtml(alert.sms_message)}</td>
          <td>${formatDateTime(alert.triggered_at)}</td>
        </tr>
      `
    )
    .join("");
}

document.getElementById("settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  settingsStatusEl.textContent = "Saving...";

  const payload = {
    high_threshold: readNumberInput("high-threshold-input"),
    low_threshold: readNumberInput("low-threshold-input"),
    alert_phone: document.getElementById("alert-phone-input").value.trim(),
    poll_frequency_minutes: Number(document.getElementById("frequency-input").value || 5),
    alert_cooldown_minutes: Number(document.getElementById("cooldown-input").value || 60),
    sms_enabled: document.getElementById("sms-enabled-input").checked,
  };

  const response = await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const saved = await response.json();
  if (!response.ok) {
    throw new Error(saved.error || "Saving settings failed.");
  }
  state.settings = saved;
  settingsStatusEl.textContent = "Settings saved.";
  renderStatus(state.history[state.history.length - 1] || null, nextCheckFromHistory());
});

document.getElementById("refresh-button").addEventListener("click", () => {
  loadDashboard().catch(showError);
});

document.getElementById("run-poll-button").addEventListener("click", async () => {
  settingsStatusEl.textContent = "Running price check...";

  const response = await fetch("/api/poll", { method: "POST" });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "Polling failed.");
  }

  settingsStatusEl.textContent = `Price updated: ${formatMoney(payload.price_usd)}`;
  await loadDashboard();
});

function readNumberInput(id) {
  const value = document.getElementById(id).value;
  return value === "" ? null : Number(value);
}

function formatMoney(value) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(value);
}

function formatThreshold(value) {
  return value === null ? "--" : formatMoney(value);
}

function formatDateTime(value) {
  return new Date(value).toLocaleString();
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function showError(error) {
  console.error(error);
  settingsStatusEl.textContent = error.message;
}

function nextCheckFromHistory() {
  const latest = state.history[state.history.length - 1];
  if (!latest) {
    return null;
  }
  const frequencyMinutes = state.settings?.poll_frequency_minutes ?? 5;
  return new Date(new Date(latest.fetched_at).getTime() + frequencyMinutes * 60 * 1000).toISOString();
}

loadDashboard().catch(showError);
