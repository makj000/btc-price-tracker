const state = {
  history: [],
  settings: null,
  nextCheckAt: null,
  alerts: [],
  alertsOffset: 0,
  alertsHasMore: true,
  alertsLoading: false,
  hoverIndex: null,
  editingThreshold: null,
};

const settingsStatusEl = document.getElementById("settings-status");
const chartEl = document.getElementById("history-chart");
const chartEmptyEl = document.getElementById("chart-empty");
const alertsTableBodyEl = document.getElementById("alerts-table-body");
const alertsTableWrapEl = document.getElementById("alerts-table-wrap");
const alertsMetaEl = document.getElementById("alerts-meta");
const alertsLoadingEl = document.getElementById("alerts-loading");
const frequencyInputEl = document.getElementById("frequency-input");
const frequencyOptionEls = Array.from(document.querySelectorAll(".frequency-option"));
const ALERTS_PAGE_SIZE = 40;
const VALID_POLL_FREQUENCIES = new Set([5, 10, 15, 30, 60, 120, 360]);
const POLL_FREQUENCY_ERROR =
  "Frequency must be one of: 5, 10, 15, 30 minutes, or 1, 2, 6 hours.";

async function loadDashboard() {
  const [statusResponse, historyResponse] = await Promise.all([
    fetch("/api/status"),
    fetch("/api/history?limit=288"),
  ]);

  const statusPayload = await statusResponse.json();
  const historyPayload = await historyResponse.json();

  state.settings = statusPayload.settings;
  state.nextCheckAt = statusPayload.next_check_at;
  state.history = historyPayload.history;
  resetAlertsState();

  renderHistory(historyPayload.history);
  renderSettingsForm(statusPayload.settings);
  await loadMoreAlerts();
}


function renderSettingsForm(settings) {
  setFrequencySelection(settings.poll_frequency_minutes ?? 5);
  document.getElementById("cooldown-input").value = settings.alert_cooldown_minutes ?? 60;
}

function renderHistory(history) {
  if (!history.length) {
    chartEl.innerHTML = "";
    chartEmptyEl.style.display = "block";
    state.hoverIndex = null;
    return;
  }

  chartEmptyEl.style.display = "none";
  const prices = history.map((point) => point.price_usd);
  const thresholdValues = [
    state.settings?.low_threshold,
    state.settings?.high_threshold,
  ].filter((value) => value !== null && value !== undefined);
  const min = Math.min(...prices, ...thresholdValues);
  const max = Math.max(...prices, ...thresholdValues);
  const range = max - min || 1;
  const chartWidth = 800;
  const topPad = 20;
  const rightPad = 16;
  const bottomPad = 44;
  const leftPad = 52;
  const chartBottom = 280 - bottomPad;
  const chartTop = topPad;
  const projected = projectHistoryPoints(history, {
    chartWidth,
    leftPad,
    rightPad,
    chartTop,
    chartBottom,
    min,
    range,
    nextCheckAt: state.nextCheckAt,
  });
  const latestPoint = projected[projected.length - 1];
  const latestX = latestPoint.x;
  const latestY = latestPoint.y;
  const gapThresholdMs = (state.settings?.poll_frequency_minutes ?? 5) * 60 * 1000 * 1.5;
  const lineSegments = [];
  const gapMarkers = [];
  let currentSegment = [];

  for (let index = 0; index < projected.length; index += 1) {
    const point = projected[index];
    const previous = projected[index - 1];
    if (previous && point.timestampMs - previous.timestampMs > gapThresholdMs) {
      if (currentSegment.length) {
        lineSegments.push(currentSegment.join(" "));
      }
      currentSegment = [];
      gapMarkers.push(
        `<line x1="${point.x}" y1="${chartTop}" x2="${point.x}" y2="${chartBottom}" class="chart-gap-marker"></line>`
      );
    }
    currentSegment.push(`${point.x},${point.y}`);
  }
  if (currentSegment.length) {
    lineSegments.push(currentSegment.join(" "));
  }

  const xTicks = [0, Math.floor((history.length - 1) / 2), history.length - 1]
    .filter((value, index, values) => values.indexOf(value) === index)
    .map((index) => {
      const x = projected[index].x;
      const anchor =
        index === 0 ? "start" : index === history.length - 1 ? "end" : "middle";
      return `
        <text x="${x}" y="268" text-anchor="${anchor}" class="chart-x-label">
          ${escapeHtml(formatChartTick(history[index].fetched_at))}
        </text>
      `;
    })
    .join("");

  let hoverMarkup = "";
  if (state.hoverIndex !== null) {
    const hoverPoint = history[state.hoverIndex];
    const hoverProjected = projected[state.hoverIndex];
    if (hoverPoint) {
      const hoverX = hoverProjected.x;
      const hoverY = hoverProjected.y;
      const tooltipX = Math.min(Math.max(hoverX - 66, leftPad + 6), chartWidth - rightPad - 132);
      const tooltipY = Math.max(hoverY - 38, chartTop + 4);
      hoverMarkup = `
        <line x1="${hoverX}" y1="${chartTop}" x2="${hoverX}" y2="${chartBottom}" class="chart-axis chart-hover-line"></line>
        <circle cx="${hoverX}" cy="${hoverY}" r="6" class="chart-hover-dot"></circle>
        <rect x="${tooltipX}" y="${tooltipY}" width="132" height="34" rx="8" class="chart-hover-box"></rect>
        <text x="${tooltipX + 8}" y="${tooltipY + 14}" class="chart-hover-text">${escapeHtml(formatMoney(hoverPoint.price_usd))}</text>
        <text x="${tooltipX + 8}" y="${tooltipY + 27}" class="chart-hover-subtext">${escapeHtml(formatChartTick(hoverPoint.fetched_at))}</text>
      `;
    }
  }

  let nextCheckMarkup = "";
  if (state.nextCheckAt) {
    const nextCheckTime = new Date(state.nextCheckAt).getTime();
    if (!Number.isNaN(nextCheckTime) && nextCheckTime > latestPoint.timestampMs) {
      const nextCheckPoint = projectSingleTimePoint(
        nextCheckTime,
        projected.minTime,
        projected.maxTime,
        chartWidth,
        leftPad,
        rightPad
      );
      nextCheckMarkup = `
        <line x1="${latestX}" y1="${latestY}" x2="${nextCheckPoint.x}" y2="${latestY}" class="chart-next-gap"></line>
        <line x1="${nextCheckPoint.x}" y1="${chartTop}" x2="${nextCheckPoint.x}" y2="${chartBottom}" class="chart-axis chart-next-line"></line>
        <circle cx="${nextCheckPoint.x}" cy="${latestY}" r="3" class="chart-next-dot"></circle>
      `;
    }
  }

  let thresholdMarkup = "";
  if (state.settings?.low_threshold !== null && state.settings?.low_threshold !== undefined) {
    const lowY =
      chartBottom - ((state.settings.low_threshold - min) / range) * (chartBottom - chartTop);
    thresholdMarkup += renderThresholdControl({
      key: "low_threshold",
      label: "Low threshold",
      value: state.settings.low_threshold,
      y: lowY,
      chartWidth,
      rightPad,
      leftPad,
      chartTop,
      chartBottom,
    });
  }
  if (state.settings?.high_threshold !== null && state.settings?.high_threshold !== undefined) {
    const highY =
      chartBottom - ((state.settings.high_threshold - min) / range) * (chartBottom - chartTop);
    thresholdMarkup += renderThresholdControl({
      key: "high_threshold",
      label: "High threshold",
      value: state.settings.high_threshold,
      y: highY,
      chartWidth,
      rightPad,
      leftPad,
      chartTop,
      chartBottom,
      pinnedLabelY: chartTop + 2,
    });
  }

  chartEl.innerHTML = `
    <line x1="${leftPad}" y1="${chartTop}" x2="${leftPad}" y2="${chartBottom}" class="chart-axis"></line>
    <line x1="${leftPad}" y1="${chartBottom}" x2="${chartWidth - rightPad}" y2="${chartBottom}" class="chart-axis"></line>
    ${gapMarkers.join("")}
    ${lineSegments.map((segment) => `<polyline points="${segment}" class="chart-line"></polyline>`).join("")}
    <circle cx="${latestX}" cy="${latestY}" r="5" class="chart-dot"></circle>
    ${nextCheckMarkup}
    ${state.nextCheckAt ? `<text x="${chartWidth - rightPad}" y="16" text-anchor="end" class="chart-x-label">Next check: ${escapeHtml(formatChartTick(state.nextCheckAt))}</text>` : ""}
    ${hoverMarkup}
    ${xTicks}
    ${thresholdMarkup}
  `;

  const editor = chartEl.querySelector(".chart-threshold-editor-input");
  if (editor) {
    editor.focus();
    editor.select();
    editor.addEventListener("keydown", handleThresholdEditorKeydown);
    editor.addEventListener("blur", cancelThresholdEdit, { once: true });
  }
}

function renderAlerts(alerts) {
  if (!alerts.length) {
    alertsMetaEl.textContent = "No alerts recorded yet.";
    alertsTableBodyEl.innerHTML = `
      <tr>
        <td colspan="7" class="muted">No alerts recorded yet.</td>
      </tr>
    `;
    return;
  }

  alertsTableBodyEl.innerHTML = alerts
    .map(
      (alert) => `
        <tr>
          <td title="${escapeHtml(alert.alert_type)}">${escapeHtml(alert.alert_type)}</td>
          <td title="${escapeHtml(formatMoney(alert.price_usd))}">${formatMoney(alert.price_usd)}</td>
          <td title="${escapeHtml(formatThreshold(alert.threshold_value))}">${formatThreshold(alert.threshold_value)}</td>
          <td title="${escapeHtml(alert.sms_status)}">${escapeHtml(alert.sms_status)}</td>
          <td title="${escapeHtml(alert.telegram_status ?? 'skipped')}">${escapeHtml(alert.telegram_status ?? 'skipped')}</td>
          <td title="${escapeHtml(alert.sms_message)}">${escapeHtml(alert.sms_message)}</td>
          <td title="${escapeHtml(formatDateTime(alert.triggered_at))}">${formatDateTime(alert.triggered_at)}</td>
        </tr>
      `
    )
    .join("");

  alertsMetaEl.textContent = state.alertsHasMore
    ? `Showing ${alerts.length} alerts. Scroll for older entries.`
    : `Showing all ${alerts.length} alerts.`;
}

function resetAlertsState() {
  state.alerts = [];
  state.alertsOffset = 0;
  state.alertsHasMore = true;
  state.alertsLoading = false;
  alertsTableWrapEl.scrollTop = 0;
  alertsMetaEl.textContent = "Loading alert history...";
  alertsLoadingEl.hidden = true;
}

async function loadMoreAlerts() {
  if (state.alertsLoading || !state.alertsHasMore) {
    return;
  }

  state.alertsLoading = true;
  alertsLoadingEl.hidden = false;

  try {
    const response = await fetch(`/api/alerts?limit=${ALERTS_PAGE_SIZE}&offset=${state.alertsOffset}`);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Loading alerts failed.");
    }

    state.alerts = state.alerts.concat(payload.alerts);
    state.alertsOffset += payload.alerts.length;
    state.alertsHasMore = payload.alerts.length === ALERTS_PAGE_SIZE;
    renderAlerts(state.alerts);
  } finally {
    state.alertsLoading = false;
    alertsLoadingEl.hidden = true;
  }
}

for (const optionEl of frequencyOptionEls) {
  optionEl.addEventListener("click", async () => {
    const frequency = Number(optionEl.dataset.frequency);
    if (frequency === state.settings?.poll_frequency_minutes) {
      setFrequencySelection(frequency);
      return;
    }

    const previousFrequency = Number(frequencyInputEl.value || state.settings?.poll_frequency_minutes || 5);
    setFrequencySelection(frequency);
    try {
      await savePartialSettings({ poll_frequency_minutes: frequency });
      state.nextCheckAt = nextCheckFromHistory();
      renderHistory(state.history);
    } catch (error) {
      setFrequencySelection(previousFrequency);
      showError(error);
    }
  });
}

document.getElementById("cooldown-input").addEventListener("keydown", async (event) => {
  if (event.key !== "Enter") {
    return;
  }

  event.preventDefault();
  const cooldown = Number(event.currentTarget.value || 60);
  const previousCooldown = state.settings?.alert_cooldown_minutes ?? 60;
  if (cooldown === previousCooldown) {
    return;
  }

  try {
    await savePartialSettings({ alert_cooldown_minutes: cooldown });
  } catch (error) {
    event.currentTarget.value = previousCooldown;
    showError(error);
  }
});

async function runPollAndRefresh() {
  settingsStatusEl.textContent = "Running price check...";

  const response = await fetch("/api/poll", { method: "POST" });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "Polling failed.");
  }

  settingsStatusEl.textContent = `BTC: ${formatMoney(payload.price_usd)}`;
  await loadDashboard();
}

document.getElementById("run-poll-button").addEventListener("click", () => {
  runPollAndRefresh().catch(showError);
});

alertsTableWrapEl.addEventListener("scroll", () => {
  const nearBottom =
    alertsTableWrapEl.scrollTop + alertsTableWrapEl.clientHeight >= alertsTableWrapEl.scrollHeight - 80;
  if (nearBottom) {
    loadMoreAlerts().catch(showError);
  }
});

chartEl.addEventListener("mousemove", (event) => {
  if (!state.history.length || state.editingThreshold) {
    return;
  }
  const rect = chartEl.getBoundingClientRect();
  const normalizedX = ((event.clientX - rect.left) / rect.width) * 800;
  const projected = projectHistoryPoints(state.history, {
    chartWidth: 800,
    leftPad: 52,
    rightPad: 16,
    chartTop: 20,
    chartBottom: 236,
    min: Math.min(...state.history.map((point) => point.price_usd)),
    range: Math.max(...state.history.map((point) => point.price_usd)) - Math.min(...state.history.map((point) => point.price_usd)) || 1,
    nextCheckAt: state.nextCheckAt,
  });
  let nearestIndex = 0;
  let nearestDistance = Infinity;
  for (let index = 0; index < projected.length; index += 1) {
    const distance = Math.abs(projected[index].x - normalizedX);
    if (distance < nearestDistance) {
      nearestDistance = distance;
      nearestIndex = index;
    }
  }
  state.hoverIndex = nearestIndex;
  renderHistory(state.history);
});

chartEl.addEventListener("mouseleave", () => {
  if (state.editingThreshold) {
    return;
  }
  state.hoverIndex = null;
  renderHistory(state.history);
});

chartEl.addEventListener("click", (event) => {
  const target = event.target.closest("[data-threshold-key]");
  if (!target) {
    return;
  }
  state.editingThreshold = {
    key: target.dataset.thresholdKey,
    value: state.settings?.[target.dataset.thresholdKey] ?? "",
  };
  renderHistory(state.history);
});

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

function formatChartTick(value) {
  return new Date(value).toLocaleString([], {
    month: "numeric",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
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

function setFrequencySelection(frequency) {
  frequencyInputEl.value = String(frequency);
  for (const optionEl of frequencyOptionEls) {
    const isActive = Number(optionEl.dataset.frequency) === frequency;
    optionEl.classList.toggle("is-active", isActive);
    optionEl.setAttribute("aria-pressed", String(isActive));
  }
}

function projectHistoryPoints(history, layout) {
  const timestamps = history.map((point) => new Date(point.fetched_at).getTime());
  const minTime = Math.min(...timestamps);
  let maxTime = Math.max(...timestamps);
  if (layout.nextCheckAt) {
    const nextCheckTime = new Date(layout.nextCheckAt).getTime();
    if (!Number.isNaN(nextCheckTime)) {
      maxTime = Math.max(maxTime, nextCheckTime);
    }
  }
  const timeRange = maxTime - minTime || 1;
  const points = history.map((point, index) => ({
    x: projectSingleTimePoint(
      timestamps[index],
      minTime,
      maxTime,
      layout.chartWidth,
      layout.leftPad,
      layout.rightPad
    ).x,
    y:
      layout.chartBottom -
      ((point.price_usd - layout.min) / layout.range) * (layout.chartBottom - layout.chartTop),
    timestampMs: timestamps[index],
  }));
  points.minTime = minTime;
  points.maxTime = maxTime;
  return points;
}

function projectSingleTimePoint(timestampMs, minTime, maxTime, chartWidth, leftPad, rightPad) {
  const timeRange = maxTime - minTime || 1;
  return {
    x: leftPad + ((timestampMs - minTime) / timeRange) * (chartWidth - leftPad - rightPad),
  };
}

async function savePartialSettings(payload) {
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
  return saved;
}

function renderThresholdControl({ key, label, value, y, chartWidth, rightPad, leftPad, chartTop, pinnedLabelY }) {
  const isEditing = state.editingThreshold?.key === key;
  const midX = (leftPad + chartWidth - rightPad) / 2;
  const labelW = 130;
  const labelH = 34;
  const gap = 5;
  const labelY = pinnedLabelY !== undefined ? pinnedLabelY : Math.max(y - labelH - gap, chartTop + 2);
  const connectorY1 = labelY + labelH;
  const showConnector = connectorY1 < y;

  if (isEditing) {
    return `
      <line x1="${leftPad}" y1="${y}" x2="${chartWidth - rightPad}" y2="${y}" class="chart-threshold-line"></line>
      <foreignObject x="${midX - 66}" y="${labelY}" width="132" height="30">
        <input
          xmlns="http://www.w3.org/1999/xhtml"
          class="chart-threshold-editor-input"
          data-threshold-key="${key}"
          type="number"
          step="0.01"
          value="${escapeHtml(String(value))}"
        />
      </foreignObject>
    `;
  }

  return `
    <g class="chart-threshold-hit" data-threshold-key="${key}">
      <line x1="${leftPad}" y1="${y}" x2="${chartWidth - rightPad}" y2="${y}" class="chart-threshold-line"></line>
      ${showConnector ? `<line x1="${midX}" y1="${connectorY1}" x2="${midX}" y2="${y}" class="chart-threshold-connector"></line>` : ""}
      <rect x="${midX - labelW / 2}" y="${labelY}" width="${labelW}" height="${labelH}" rx="6" class="chart-threshold-bg"></rect>
      <text x="${midX}" y="${labelY + 13}" text-anchor="middle" class="chart-threshold-type-label">
        ${escapeHtml(label)}
      </text>
      <text x="${midX}" y="${labelY + 27}" text-anchor="middle" class="chart-threshold-value-label">
        ${escapeHtml(formatMoney(value))}
      </text>
    </g>
  `;
}

async function handleThresholdEditorKeydown(event) {
  if (event.key === "Escape") {
    cancelThresholdEdit();
    return;
  }
  if (event.key !== "Enter") {
    return;
  }

  event.preventDefault();
  const key = event.currentTarget.dataset.thresholdKey;
  const rawValue = event.currentTarget.value.trim();
  const value = rawValue === "" ? null : Number(rawValue);
  if (rawValue !== "" && Number.isNaN(value)) {
    showError(new Error("Threshold must be a number."));
    return;
  }

  try {
    await savePartialSettings({ [key]: value });
    renderSettingsForm(state.settings);
    state.editingThreshold = null;
    renderHistory(state.history);
  } catch (error) {
    showError(error);
  }
}

function cancelThresholdEdit() {
  if (!state.editingThreshold) {
    return;
  }
  state.editingThreshold = null;
  renderHistory(state.history);
}

function nextCheckFromHistory() {
  const latest = state.history[state.history.length - 1];
  const frequencyMinutes = state.settings?.poll_frequency_minutes ?? 5;
  const latestValue = latest ? latest.fetched_at : null;
  return nextScheduledCheckAt(latestValue, frequencyMinutes);
}

function nextScheduledCheckAt(value, frequencyMinutes) {
  const reference = new Date();
  if (value) {
    const latest = new Date(value);
    if (!Number.isNaN(latest.getTime()) && latest.getTime() > reference.getTime()) {
      reference.setTime(latest.getTime());
    }
  }

  const next = new Date(reference);
  next.setUTCSeconds(0, 0);

  if (frequencyMinutes < 60) {
    const nextMinute = (Math.floor(reference.getUTCMinutes() / frequencyMinutes) + 1) * frequencyMinutes;
    next.setUTCMinutes(0);

    if (nextMinute >= 60) {
      next.setUTCHours(next.getUTCHours() + 1, 0, 0, 0);
    } else {
      next.setUTCMinutes(nextMinute, 0, 0);
    }
  } else {
    const frequencyHours = frequencyMinutes / 60;
    const nextHour = (Math.floor(reference.getUTCHours() / frequencyHours) + 1) * frequencyHours;
    next.setUTCHours(0, 0, 0, 0);

    if (nextHour >= 24) {
      next.setUTCDate(next.getUTCDate() + 1);
    } else {
      next.setUTCHours(nextHour, 0, 0, 0);
    }
  }

  return next.toISOString();
}

loadDashboard().then(() => runPollAndRefresh()).catch(showError);
