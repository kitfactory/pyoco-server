const els = {
  apiHeader: document.getElementById("apiHeader"),
  apiKey: document.getElementById("apiKey"),
  saveAuth: document.getElementById("saveAuth"),
  runsFilters: document.getElementById("runsFilters"),
  fStatus: document.getElementById("fStatus"),
  fFlow: document.getElementById("fFlow"),
  fTag: document.getElementById("fTag"),
  fRunId: document.getElementById("fRunId"),
  fWorkerId: document.getElementById("fWorkerId"),
  fSortKey: document.getElementById("fSortKey"),
  fSortDir: document.getElementById("fSortDir"),
  fLimit: document.getElementById("fLimit"),
  runStats: document.getElementById("runStats"),
  runsMeta: document.getElementById("runsMeta"),
  runsList: document.getElementById("runsList"),
  detailMeta: document.getElementById("detailMeta"),
  detailCancel: document.getElementById("detailCancel"),
  detailJson: document.getElementById("detailJson"),
  detailFlowJson: document.getElementById("detailFlowJson"),
  watchState: document.getElementById("watchState"),
  workersFilters: document.getElementById("workersFilters"),
  wState: document.getElementById("wState"),
  wIncludeHidden: document.getElementById("wIncludeHidden"),
  workersList: document.getElementById("workersList"),
  kpiRunning: document.getElementById("kpiRunning"),
  kpiCompletedToday: document.getElementById("kpiCompletedToday"),
  kpiFailedToday: document.getElementById("kpiFailedToday"),
  clearMetricsBase: document.getElementById("clearMetricsBase"),
  lastUpdate: document.getElementById("lastUpdate"),
  errorLine: document.getElementById("errorLine"),
};

const MESSAGES = {
  en: {
    "header.subtitle": "One playful control room for runs, workers, and metrics.",
    "header.mood": "CUTE mode spirit: serious ops, joyful feedback.",
    "auth.header": "Header",
    "auth.api_key": "API Key",
    "auth.api_key_placeholder": "optional",
    "auth.apply": "Apply",
    "common.refresh": "Refresh",
    "common.all": "ALL",
    "common.partial_match": "partial match",
    "runs.title": "Runs",
    "runs.filter.status": "Status",
    "runs.filter.flow_name": "flow_name",
    "runs.filter.flow_placeholder": "main",
    "runs.filter.tag": "Tag",
    "runs.filter.tag_placeholder": "default",
    "runs.filter.run_id": "run_id",
    "runs.filter.sort_by": "Sort by",
    "runs.filter.order": "Order",
    "runs.filter.worker_id": "worker_id",
    "runs.filter.limit": "Limit",
    "runs.filter.apply": "Apply Filters",
    "runs.glossary": "flow_name = workflow name / tag = route label",
    "runs.sort.ops_default": "ops_default (RUNNING > FAILED > COMPLETED)",
    "runs.sort.updated_at": "updated_at",
    "runs.sort.start_time": "start_time (started at)",
    "runs.sort.end_time": "end_time (ended at)",
    "runs.sort.flow_name": "flow_name",
    "runs.sort.status": "status",
    "runs.sort.run_id": "run_id",
    "runs.order.desc": "desc",
    "runs.order.asc": "asc",
    "runs.chip.flow": "flow",
    "runs.chip.tag": "tag",
    "runs.item.bottom": "run {run_id} | updated {updated}",
    "runs.meta": "visible={visible}/{total} | latest_ts={latest}",
    "stats.all": "All",
    "stats.running": "Running",
    "stats.completed": "Completed",
    "stats.failed": "Failed",
    "stats.pending": "Pending",
    "stats.cancelled": "Cancelled",
    "stats.all_initial": "◉ All 0",
    "stats.running_initial": "▶ Running 0",
    "stats.completed_initial": "✓ Completed 0",
    "stats.failed_initial": "⚠ Failed 0",
    "detail.title": "Run Detail",
    "detail.cancel": "Cancel",
    "detail.cancelling": "Cancelling...",
    "detail.unselected": "Run is not selected.",
    "detail.unselected_execution": "Pick a run from the left panel to see its execution story.",
    "detail.unselected_flow": "Flow recipe appears here after selecting a run.",
    "detail.execution_story": "Execution Story",
    "detail.flow_recipe": "Flow Recipe",
    "detail.meta": "{run_id} | {status} | updated {updated}",
    "detail.flow_note_with_yaml": "YAML body is not stored in snapshot; only metadata is available.",
    "detail.flow_note_no_yaml": "This run may be flow_name route (without YAML upload metadata).",
    "workers.title": "Workers",
    "workers.filter.state": "State",
    "workers.filter.include_hidden": "include_hidden",
    "workers.empty": "No workers on stage right now.",
    "workers.hidden": "hidden",
    "workers.disconnected": "connection lost; waiting for comeback",
    "workers.seen_tags": "seen={seen} tags=[{tags}]",
    "workers.current_last": "current_run={current} last_result={last}",
    "workers.action.hide": "Hide",
    "workers.action.unhide": "Unhide",
    "workers.action.hide_title": "Hide worker",
    "workers.action.unhide_title": "Unhide worker",
    "workers.state.running": "RUNNING",
    "workers.state.idle": "IDLE",
    "workers.state.stopped_graceful": "STOPPED_GRACEFUL",
    "workers.state.disconnected": "DISCONNECTED",
    "workers.state.unknown": "UNKNOWN",
    "metrics.title": "Metrics",
    "metrics.running": "Engines running",
    "metrics.completed_today": "Today's completed",
    "metrics.failed_today": "Today's failed",
    "metrics.reset": "RESET COUNTER",
    "footer.last_update": "Last update: {time}",
    "footer.last_update_initial": "Last update: -",
    "watch.idle": "idle",
    "watch.connecting": "connecting",
    "watch.streaming": "streaming",
    "watch.reconnecting": "reconnecting",
    "watch.retrying": "retrying",
    "watch.terminal": "terminal",
    "status.pending_code": "PENDING",
    "status.running_code": "RUNNING",
    "status.cancelling_code": "CANCELLING",
    "status.completed_code": "COMPLETED",
    "status.failed_code": "FAILED",
    "status.cancelled_code": "CANCELLED",
    "status.idle_code": "IDLE",
    "status.stopped_graceful_code": "STOPPED_GRACEFUL",
    "status.disconnected_code": "DISCONNECTED",
    "status.pending": "PENDING (queued)",
    "status.running": "RUNNING (in action)",
    "status.cancelling": "CANCELLING (stopping)",
    "status.completed": "COMPLETED (done)",
    "status.failed": "FAILED (retry ready)",
    "status.cancelled": "CANCELLED",
    "status.unknown": "UNKNOWN",
  },
  ja: {
    "header.subtitle": "runs・workers・metrics をまとめて見られる、たのしい運用ルーム。",
    "header.mood": "CUTE mode: 真面目な運用に、楽しいフィードバックを。",
    "auth.header": "ヘッダー名",
    "auth.api_key": "API キー",
    "auth.api_key_placeholder": "任意",
    "auth.apply": "適用",
    "common.refresh": "更新",
    "common.all": "ALL",
    "common.partial_match": "部分一致",
    "runs.title": "Runs",
    "runs.filter.status": "ステータス",
    "runs.filter.flow_name": "flow_name",
    "runs.filter.flow_placeholder": "main",
    "runs.filter.tag": "タグ",
    "runs.filter.tag_placeholder": "default",
    "runs.filter.run_id": "run_id",
    "runs.filter.sort_by": "並び替え",
    "runs.filter.order": "順序",
    "runs.filter.worker_id": "worker_id",
    "runs.filter.limit": "件数",
    "runs.filter.apply": "フィルタ適用",
    "runs.glossary": "flow_name = ワークフロー名 / tag = ルーティングラベル",
    "runs.sort.ops_default": "ops_default (RUNNING > FAILED > COMPLETED)",
    "runs.sort.updated_at": "updated_at（更新時刻）",
    "runs.sort.start_time": "start_time（開始時刻）",
    "runs.sort.end_time": "end_time（終了時刻）",
    "runs.sort.flow_name": "flow_name",
    "runs.sort.status": "status",
    "runs.sort.run_id": "run_id",
    "runs.order.desc": "desc",
    "runs.order.asc": "asc",
    "runs.chip.flow": "flow",
    "runs.chip.tag": "tag",
    "runs.item.bottom": "run {run_id} | 更新 {updated}",
    "runs.meta": "表示={visible}/{total} | 最新ts={latest}",
    "stats.all": "All",
    "stats.running": "実行中",
    "stats.completed": "完了",
    "stats.failed": "失敗",
    "stats.pending": "待機",
    "stats.cancelled": "キャンセル",
    "stats.all_initial": "◉ All 0",
    "stats.running_initial": "▶ 実行中 0",
    "stats.completed_initial": "✓ 完了 0",
    "stats.failed_initial": "⚠ 失敗 0",
    "detail.title": "Run Detail",
    "detail.cancel": "キャンセル",
    "detail.cancelling": "キャンセル中...",
    "detail.unselected": "Run が未選択です。",
    "detail.unselected_execution": "左の一覧から Run を選ぶと、実行内容を表示します。",
    "detail.unselected_flow": "Run を選ぶと、フロー情報を表示します。",
    "detail.execution_story": "Execution Story",
    "detail.flow_recipe": "Flow Recipe",
    "detail.meta": "{run_id} | {status} | 更新 {updated}",
    "detail.flow_note_with_yaml": "YAML 本文は snapshot に保存せず、メタデータのみ保持します。",
    "detail.flow_note_no_yaml": "この run は flow_name ルート実行（YAML メタデータなし）の可能性があります。",
    "workers.title": "Workers",
    "workers.filter.state": "状態",
    "workers.filter.include_hidden": "hidden も表示",
    "workers.empty": "表示中の worker はありません。",
    "workers.hidden": "hidden",
    "workers.disconnected": "接続が途切れました。再接続待ちです",
    "workers.seen_tags": "最終確認={seen} tags=[{tags}]",
    "workers.current_last": "current_run={current} last_result={last}",
    "workers.action.hide": "非表示",
    "workers.action.unhide": "再表示",
    "workers.action.hide_title": "worker を非表示にする",
    "workers.action.unhide_title": "worker を再表示する",
    "workers.state.running": "実行中",
    "workers.state.idle": "待機中",
    "workers.state.stopped_graceful": "正常停止",
    "workers.state.disconnected": "切断",
    "workers.state.unknown": "不明",
    "metrics.title": "Metrics",
    "metrics.running": "実行中",
    "metrics.completed_today": "本日の完了",
    "metrics.failed_today": "本日の失敗",
    "metrics.reset": "カウンタリセット",
    "footer.last_update": "最終更新: {time}",
    "footer.last_update_initial": "最終更新: -",
    "watch.idle": "待機",
    "watch.connecting": "接続中",
    "watch.streaming": "監視中",
    "watch.reconnecting": "再接続中",
    "watch.retrying": "再試行中",
    "watch.terminal": "終了",
    "status.pending_code": "PENDING",
    "status.running_code": "RUNNING",
    "status.cancelling_code": "CANCELLING",
    "status.completed_code": "COMPLETED",
    "status.failed_code": "FAILED",
    "status.cancelled_code": "CANCELLED",
    "status.idle_code": "IDLE",
    "status.stopped_graceful_code": "STOPPED_GRACEFUL",
    "status.disconnected_code": "DISCONNECTED",
    "status.pending": "PENDING（待機中）",
    "status.running": "RUNNING（実行中）",
    "status.cancelling": "CANCELLING（停止処理中）",
    "status.completed": "COMPLETED（完了）",
    "status.failed": "FAILED（再試行候補）",
    "status.cancelled": "CANCELLED（中止）",
    "status.unknown": "UNKNOWN",
  },
};

const STATUS_META = {
  PENDING: { icon: "○", cls: "pending", textKey: "status.pending" },
  RUNNING: { icon: "▶", cls: "running", textKey: "status.running" },
  CANCELLING: { icon: "…", cls: "cancelling", textKey: "status.cancelling" },
  COMPLETED: { icon: "✓", cls: "completed", textKey: "status.completed" },
  FAILED: { icon: "⚠", cls: "failed", textKey: "status.failed" },
  CANCELLED: { icon: "■", cls: "cancelled", textKey: "status.cancelled" },
};

function normalizeLocale(value) {
  const raw = String(value || "").trim().toLowerCase();
  if (!raw) {
    return null;
  }
  if (raw.startsWith("ja")) {
    return "ja";
  }
  if (raw.startsWith("en")) {
    return "en";
  }
  return null;
}

function resolveLocale() {
  const globalLocale = normalizeLocale(window.__PYOCO_DASHBOARD_LANG__);
  if (globalLocale) {
    return globalLocale;
  }
  return "en";
}

const state = {
  locale: resolveLocale(),
  authHeader: "X-API-Key",
  authKey: "",
  filters: {
    status: "",
    flow: "",
    tag: "",
    runId: "",
    workerId: "",
    sortKey: "ops_default",
    sortDir: "desc",
    limit: 50,
  },
  workerFilters: {
    state: "",
    includeHidden: false,
  },
  runsById: new Map(),
  maxUpdatedAt: 0,
  selectedRunId: null,
  watchAbort: null,
  watchTerminal: false,
  pollingRuns: false,
  pollingWorkers: false,
  pendingWorkersRefresh: false,
  pollingMetrics: false,
  metricsBaseline: null,
  latestMetrics: null,
};

function t(key, vars = {}) {
  const localeTable = MESSAGES[state.locale] || MESSAGES.en;
  const fallback = MESSAGES.en[key];
  const template = localeTable[key] || fallback || key;
  return String(template).replace(/\{([a-zA-Z0-9_]+)\}/g, (_, name) => String(vars[name] ?? ""));
}

function applyI18nToDocument() {
  document.documentElement.lang = state.locale;
  for (const node of document.querySelectorAll("[data-i18n]")) {
    const key = node.getAttribute("data-i18n");
    if (!key) {
      continue;
    }
    node.textContent = t(key);
  }
  for (const node of document.querySelectorAll("[data-i18n-placeholder]")) {
    const key = node.getAttribute("data-i18n-placeholder");
    if (!key) {
      continue;
    }
    node.setAttribute("placeholder", t(key));
  }
}

function getStatusMeta(status) {
  const key = String(status || "").toUpperCase();
  const meta = STATUS_META[key];
  if (!meta) {
    return { icon: "•", cls: "unknown", text: t("status.unknown") };
  }
  return { icon: meta.icon, cls: meta.cls, text: t(meta.textKey) };
}

function setLabelActive(inputEl, active) {
  if (!inputEl) {
    return;
  }
  const label = inputEl.closest("label");
  if (!label) {
    return;
  }
  if (active) {
    label.classList.add("active");
  } else {
    label.classList.remove("active");
  }
}

function setError(message) {
  els.errorLine.textContent = message || "";
}

function localeTag() {
  return state.locale === "ja" ? "ja-JP" : "en-US";
}

function setLastUpdate() {
  els.lastUpdate.textContent = t("footer.last_update", { time: new Date().toLocaleTimeString(localeTag()) });
}

function setWatchState(mode, textKey) {
  els.watchState.className = "badge";
  if (mode) {
    els.watchState.classList.add(mode);
  }
  els.watchState.textContent = t(textKey);
}

function isTerminal(status) {
  return status === "COMPLETED" || status === "FAILED" || status === "CANCELLED";
}

function canCancel(status) {
  const st = String(status || "").toUpperCase();
  return st === "PENDING" || st === "RUNNING" || st === "CANCELLING";
}

function loadSavedAuth() {
  state.authHeader = localStorage.getItem("pyoco.auth_header") || "X-API-Key";
  state.authKey = localStorage.getItem("pyoco.auth_key") || "";
  els.apiHeader.value = state.authHeader;
  els.apiKey.value = state.authKey;
}

function saveAuth() {
  state.authHeader = (els.apiHeader.value || "X-API-Key").trim() || "X-API-Key";
  state.authKey = (els.apiKey.value || "").trim();
  localStorage.setItem("pyoco.auth_header", state.authHeader);
  localStorage.setItem("pyoco.auth_key", state.authKey);
}

function todayKeyLocal(now = new Date()) {
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function saveMetricsBaseline() {
  if (!state.metricsBaseline) {
    return;
  }
  localStorage.setItem("pyoco.metrics_baseline", JSON.stringify(state.metricsBaseline));
}

function loadMetricsBaseline() {
  const today = todayKeyLocal();
  const fallback = {
    dateKey: today,
    completedToday: 0,
    failedToday: 0,
    clearedAt: null,
  };
  const raw = localStorage.getItem("pyoco.metrics_baseline");
  if (!raw) {
    state.metricsBaseline = fallback;
    return;
  }
  try {
    const parsed = JSON.parse(raw);
    const dateKey = String(parsed?.dateKey || today);
    state.metricsBaseline = {
      dateKey,
      completedToday: Number(parsed?.completedToday || 0),
      failedToday: Number(parsed?.failedToday || 0),
      clearedAt: parsed?.clearedAt ? Number(parsed.clearedAt) : null,
    };
  } catch {
    state.metricsBaseline = fallback;
  }
  if (!state.metricsBaseline || state.metricsBaseline.dateKey !== today) {
    state.metricsBaseline = fallback;
    saveMetricsBaseline();
  }
}

function ensureMetricsBaselineDate(dayKey) {
  if (!state.metricsBaseline || state.metricsBaseline.dateKey !== dayKey) {
    state.metricsBaseline = {
      dateKey: dayKey,
      completedToday: 0,
      failedToday: 0,
      clearedAt: null,
    };
    saveMetricsBaseline();
  }
}

function parsePrometheusMetrics(text) {
  const rows = [];
  for (const line of String(text || "").split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) {
      continue;
    }
    const match = trimmed.match(/^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{([^}]*)\})?\s+([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)$/);
    if (!match) {
      continue;
    }
    const name = match[1];
    const labelsRaw = match[3] || "";
    const value = Number(match[4]);
    if (!Number.isFinite(value)) {
      continue;
    }
    const labels = {};
    if (labelsRaw) {
      for (const token of labelsRaw.split(",")) {
        const i = token.indexOf("=");
        if (i <= 0) {
          continue;
        }
        const k = token.slice(0, i).trim();
        const vRaw = token.slice(i + 1).trim();
        const v = vRaw.replace(/^"/, "").replace(/"$/, "");
        labels[k] = v;
      }
    }
    rows.push({ name, labels, value });
  }
  return rows;
}

function getMetricValue(rows, name, labels = {}) {
  let total = 0;
  for (const row of rows || []) {
    if (row.name !== name) {
      continue;
    }
    let ok = true;
    for (const [k, v] of Object.entries(labels)) {
      if (String(row.labels?.[k] || "") !== String(v)) {
        ok = false;
        break;
      }
    }
    if (ok) {
      total += Number(row.value || 0);
    }
  }
  return total;
}

function renderMetricsKpis(snapshot) {
  if (!snapshot) {
    return;
  }
  ensureMetricsBaselineDate(snapshot.dayKey);

  if (els.kpiRunning) {
    els.kpiRunning.textContent = String(Math.max(0, Math.trunc(snapshot.runningNow)));
  }
  if (els.kpiCompletedToday) {
    els.kpiCompletedToday.textContent = String(Math.max(0, Math.trunc(snapshot.completedToday)));
  }
  if (els.kpiFailedToday) {
    els.kpiFailedToday.textContent = String(Math.max(0, Math.trunc(snapshot.failedToday)));
  }
}

function buildHeaders() {
  const headers = {};
  if (state.authKey) {
    headers[state.authHeader] = state.authKey;
  }
  return headers;
}

function buildRunsQuery({ updatedAfter, cursor } = {}) {
  const params = new URLSearchParams();
  if (state.filters.status) {
    params.set("status", state.filters.status);
  }
  if (state.filters.flow) {
    params.set("flow", state.filters.flow);
  }
  if (state.filters.tag) {
    params.set("tag", state.filters.tag);
  }
  params.set("limit", String(state.filters.limit));
  if (updatedAfter !== undefined && updatedAfter !== null) {
    params.set("updated_after", String(updatedAfter));
  }
  if (cursor) {
    params.set("cursor", cursor);
  }
  return params;
}

async function fetchJson(path) {
  const resp = await fetch(path, { headers: buildHeaders() });
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`${resp.status} ${body}`.trim());
  }
  return resp.json();
}

async function fetchJsonWith(path, options = {}) {
  const headers = { ...buildHeaders(), ...(options.headers || {}) };
  const resp = await fetch(path, { ...options, headers });
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`${resp.status} ${body}`.trim());
  }
  return resp.json();
}

async function fetchText(path) {
  const resp = await fetch(path, { headers: buildHeaders() });
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`${resp.status} ${body}`.trim());
  }
  return resp.text();
}

function normalizeRunItems(body) {
  if (Array.isArray(body)) {
    return body;
  }
  if (body && Array.isArray(body.items)) {
    return body.items;
  }
  return [];
}

function mergeRuns(items) {
  for (const item of items || []) {
    if (!item || !item.run_id) {
      continue;
    }
    const runId = String(item.run_id);
    const incomingUpdated = Number(item.updated_at || 0);
    const existing = state.runsById.get(runId);
    const existingUpdated = Number(existing?.updated_at || 0);
    if (!existing || incomingUpdated >= existingUpdated) {
      state.runsById.set(runId, item);
    }
    if (incomingUpdated > state.maxUpdatedAt) {
      state.maxUpdatedAt = incomingUpdated;
    }
  }
}

function sortedRuns() {
  const sortKey = state.filters.sortKey || "ops_default";
  const sortDir = state.filters.sortDir === "asc" ? "asc" : "desc";
  const factor = sortDir === "asc" ? 1 : -1;
  const numericKeys = new Set(["updated_at", "start_time", "end_time"]);

  if (sortKey === "ops_default") {
    const priority = {
      RUNNING: 0,
      CANCELLING: 0,
      PENDING: 0,
      FAILED: 1,
      CANCELLED: 1,
      COMPLETED: 2,
    };

    function toNum(v) {
      const n = Number(v || 0);
      return Number.isFinite(n) ? n : 0;
    }

    function rank(row) {
      const st = String(row?.status || "").toUpperCase();
      return st in priority ? priority[st] : 3;
    }

    function recency(row) {
      const st = String(row?.status || "").toUpperCase();
      if (st === "RUNNING" || st === "PENDING" || st === "CANCELLING") {
        return toNum(row?.updated_at) || toNum(row?.start_time);
      }
      if (st === "FAILED" || st === "COMPLETED" || st === "CANCELLED") {
        return toNum(row?.end_time) || toNum(row?.updated_at);
      }
      return toNum(row?.updated_at) || toNum(row?.start_time) || toNum(row?.end_time);
    }

    function cmpDefault(a, b) {
      const pa = rank(a);
      const pb = rank(b);
      if (pa !== pb) {
        return pa - pb;
      }
      const ra = recency(a);
      const rb = recency(b);
      if (ra !== rb) {
        return rb - ra;
      }
      return String(b?.run_id || "").localeCompare(String(a?.run_id || ""));
    }

    return Array.from(state.runsById.values()).sort(cmpDefault);
  }

  function getSortValue(row) {
    if (sortKey === "flow_name") {
      return String(row?.flow_name || "");
    }
    if (sortKey === "status") {
      return String(row?.status || "");
    }
    if (sortKey === "run_id") {
      return String(row?.run_id || "");
    }
    return Number(row?.[sortKey] || 0);
  }

  function cmp(a, b) {
    if (numericKeys.has(sortKey)) {
      const av = Number(getSortValue(a));
      const bv = Number(getSortValue(b));
      const aValid = Number.isFinite(av) && av > 0;
      const bValid = Number.isFinite(bv) && bv > 0;
      if (aValid !== bValid) {
        return aValid ? -1 : 1;
      }
      if (aValid && bValid && av !== bv) {
        return (av - bv) * factor;
      }
    } else {
      const av = String(getSortValue(a)).toLowerCase();
      const bv = String(getSortValue(b)).toLowerCase();
      if (av !== bv) {
        return av.localeCompare(bv) * factor;
      }
    }

    const ua = Number(a?.updated_at || 0);
    const ub = Number(b?.updated_at || 0);
    if (ua !== ub) {
      return (ua - ub) * -1;
    }
    return String(b?.run_id || "").localeCompare(String(a?.run_id || ""));
  }

  return Array.from(state.runsById.values()).sort(cmp);
}

function filterRuns(rows) {
  const status = state.filters.status;
  const runNeedle = String(state.filters.runId || "").toLowerCase();
  const workerNeedle = String(state.filters.workerId || "").toLowerCase();
  return rows.filter((row) => {
    const rowStatus = String(row?.status || "").toUpperCase();
    if (status && rowStatus !== status) {
      return false;
    }
    if (runNeedle && !String(row?.run_id || "").toLowerCase().includes(runNeedle)) {
      return false;
    }
    if (workerNeedle && !String(row?.worker_id || "").toLowerCase().includes(workerNeedle)) {
      return false;
    }
    return true;
  });
}

function formatEpochTime(value) {
  const ts = Number(value || 0);
  if (ts <= 0 || !Number.isFinite(ts)) {
    return "-";
  }
  return new Date(ts * 1000).toLocaleTimeString(localeTag());
}

function workerStateText(stateText) {
  const key = String(stateText || "UNKNOWN").toUpperCase();
  if (key === "RUNNING") return t("workers.state.running");
  if (key === "IDLE") return t("workers.state.idle");
  if (key === "STOPPED_GRACEFUL") return t("workers.state.stopped_graceful");
  if (key === "DISCONNECTED") return t("workers.state.disconnected");
  return t("workers.state.unknown");
}

function workerStateBadge(stateText) {
  const stateNorm = String(stateText || "UNKNOWN").toUpperCase();
  let css = "unknown";
  if (stateNorm === "RUNNING") css = "running";
  else if (stateNorm === "IDLE") css = "idle";
  else if (stateNorm === "STOPPED_GRACEFUL") css = "stopped";
  else if (stateNorm === "DISCONNECTED") css = "disconnected";
  return `<span class="worker-state ${css}" title="${stateNorm}">${workerStateText(stateNorm)}</span>`;
}

function buildWorkersQuery() {
  const params = new URLSearchParams();
  params.set("scope", "all");
  if (state.workerFilters.state) {
    params.set("state", state.workerFilters.state);
  }
  if (state.workerFilters.includeHidden) {
    params.set("include_hidden", "true");
  }
  params.set("limit", "200");
  return params;
}

function renderRunStats(rows) {
  if (!els.runStats) {
    return;
  }
  const selectedStatus = String(state.filters.status || "").toUpperCase();

  if (selectedStatus) {
    const labels = {
      PENDING: `○ ${t("stats.pending")}`,
      RUNNING: `▶ ${t("stats.running")}`,
      CANCELLING: `… ${t("status.cancelling_code")}`,
      COMPLETED: `✓ ${t("stats.completed")}`,
      FAILED: `⚠ ${t("stats.failed")}`,
      CANCELLED: `■ ${t("stats.cancelled")}`,
    };
    const cssClass = {
      PENDING: "running",
      RUNNING: "running",
      CANCELLING: "running",
      COMPLETED: "completed",
      FAILED: "failed",
      CANCELLED: "failed",
    };
    const label = labels[selectedStatus] || selectedStatus;
    const klass = cssClass[selectedStatus] || "all";
    els.runStats.innerHTML = `<span class="stat-chip ${klass}">${label} ${rows.length}</span>`;
    return;
  }

  const counts = {
    all: rows.length,
    running: 0,
    completed: 0,
    failed: 0,
  };
  for (const row of rows) {
    const status = String(row?.status || "").toUpperCase();
    if (status === "RUNNING" || status === "PENDING" || status === "CANCELLING") {
      counts.running += 1;
    } else if (status === "COMPLETED") {
      counts.completed += 1;
    } else if (status === "FAILED" || status === "CANCELLED") {
      counts.failed += 1;
    }
  }
  els.runStats.innerHTML = `
    <span class="stat-chip all">◉ ${t("stats.all")} ${counts.all}</span>
    <span class="stat-chip running">▶ ${t("stats.running")} ${counts.running}</span>
    <span class="stat-chip completed">✓ ${t("stats.completed")} ${counts.completed}</span>
    <span class="stat-chip failed">⚠ ${t("stats.failed")} ${counts.failed}</span>
  `;
}

function updateFilterFieldStyles() {
  setLabelActive(els.fStatus, Boolean(state.filters.status));
  setLabelActive(els.fFlow, Boolean(state.filters.flow));
  setLabelActive(els.fTag, Boolean(state.filters.tag));
  setLabelActive(els.fRunId, Boolean(state.filters.runId));
  setLabelActive(els.fWorkerId, Boolean(state.filters.workerId));
  setLabelActive(
    els.fSortKey,
    state.filters.sortKey !== "ops_default"
  );
  setLabelActive(
    els.fSortDir,
    state.filters.sortKey !== "ops_default"
  );
}

function createRunListItem(row) {
  const li = document.createElement("li");
  li.classList.add("run-item");
  const meta = getStatusMeta(row.status);
  li.classList.add(`status-${meta.cls}`);

  const top = document.createElement("div");
  top.classList.add("run-top");

  const icon = document.createElement("span");
  icon.classList.add("run-status-icon", meta.cls);
  icon.textContent = meta.icon;
  top.appendChild(icon);

  const title = document.createElement("div");
  title.classList.add("run-title");
  const flowName = document.createElement("strong");
  flowName.classList.add("run-flow-name");
  flowName.textContent = String(row.flow_name || "-");
  flowName.title = String(row.flow_name || "-");
  const status = document.createElement("small");
  status.textContent = meta.text;
  title.appendChild(flowName);
  title.appendChild(status);
  top.appendChild(title);

  const chips = document.createElement("div");
  chips.classList.add("run-chips");

  const flow = document.createElement("span");
  flow.classList.add("chip");
  flow.textContent = `${t("runs.chip.flow")} ${row.flow_name || "-"}`;
  chips.appendChild(flow);

  const tag = document.createElement("span");
  tag.classList.add("chip");
  tag.textContent = `${t("runs.chip.tag")} ${row.tag || "-"}`;
  chips.appendChild(tag);

  const bottom = document.createElement("div");
  bottom.classList.add("run-bottom");
  bottom.textContent = t("runs.item.bottom", {
    run_id: row.run_id || "-",
    updated: formatEpochTime(row.updated_at),
  });

  li.appendChild(top);
  li.appendChild(chips);
  li.appendChild(bottom);
  return li;
}

function renderRuns() {
  const allRows = sortedRuns();
  const rows = filterRuns(allRows);
  els.runsList.textContent = "";
  updateFilterFieldStyles();
  renderRunStats(rows);
  const frag = document.createDocumentFragment();
  for (const row of rows) {
    const li = createRunListItem(row);
    if (row.run_id === state.selectedRunId) {
      li.classList.add("active");
    }
    li.addEventListener("click", () => {
      selectRun(row.run_id);
    });
    frag.appendChild(li);
  }
  els.runsList.appendChild(frag);
  els.runsMeta.textContent = t("runs.meta", {
    visible: rows.length,
    total: allRows.length,
    latest: state.maxUpdatedAt.toFixed(3),
  });
}

function renderRunDetail(snap) {
  if (!snap || !snap.run_id) {
    if (els.detailCancel) {
      els.detailCancel.disabled = true;
      els.detailCancel.textContent = t("detail.cancel");
    }
    els.detailMeta.textContent = t("detail.unselected");
    els.detailJson.textContent = t("detail.unselected_execution");
    if (els.detailFlowJson) {
      els.detailFlowJson.textContent = t("detail.unselected_flow");
    }
    return;
  }
  const updatedAt = Number(snap.updated_at || 0);
  const dt = updatedAt > 0 ? new Date(updatedAt * 1000).toLocaleString(localeTag()) : "-";
  els.detailMeta.textContent = t("detail.meta", {
    run_id: snap.run_id,
    status: getStatusMeta(snap.status).text,
    updated: dt,
  });

  const executionPayload = {
    run_id: snap.run_id,
    status: snap.status || "-",
    cancel_requested_at: snap.cancel_requested_at ?? null,
    cancel_requested_by: snap.cancel_requested_by ?? null,
    worker_id: snap.worker_id || null,
    start_time: snap.start_time ?? null,
    end_time: snap.end_time ?? null,
    heartbeat_at: snap.heartbeat_at ?? null,
    updated_at: snap.updated_at ?? null,
    tasks: snap.tasks || {},
    task_records_truncated: Boolean(snap.task_records_truncated),
    error: snap.error ?? null,
  };
  els.detailJson.textContent = JSON.stringify(executionPayload, null, 2);

  if (els.detailFlowJson) {
    const hasYamlMeta = Boolean(snap.workflow_yaml_sha256 || snap.workflow_yaml_bytes);
    const contextPayload = {
      flow_name: snap.flow_name || "-",
      tag: snap.tag || "-",
      tags: Array.isArray(snap.tags) ? snap.tags : [],
      params: snap.params || {},
      workflow_yaml: {
        available_in_snapshot: false,
        sha256: snap.workflow_yaml_sha256 || null,
        bytes: snap.workflow_yaml_bytes || null,
        note: hasYamlMeta
          ? t("detail.flow_note_with_yaml")
          : t("detail.flow_note_no_yaml"),
      },
    };
    els.detailFlowJson.textContent = JSON.stringify(contextPayload, null, 2);
  }

  if (els.detailCancel) {
    const statusNorm = String(snap.status || "").toUpperCase();
    const cancellable = canCancel(statusNorm) && statusNorm !== "CANCELLING";
    els.detailCancel.disabled = !cancellable;
    els.detailCancel.textContent = statusNorm === "CANCELLING" ? t("detail.cancelling") : t("detail.cancel");
  }
}

function renderWorkers(workers) {
  els.workersList.textContent = "";
  if (!Array.isArray(workers) || workers.length === 0) {
    const li = document.createElement("li");
    li.textContent = t("workers.empty");
    els.workersList.appendChild(li);
    return;
  }
  const frag = document.createDocumentFragment();
  for (const worker of workers) {
    const li = document.createElement("li");
    li.classList.add("worker-item");
    const stateNorm = String(worker.state || "UNKNOWN").toUpperCase();
    li.classList.add(`state-${stateNorm.toLowerCase()}`);
    const stateBadge = workerStateBadge(stateNorm);
    const hidden = Boolean(worker.hidden);
    const hiddenChip = hidden ? `<span class="worker-hidden">${t("workers.hidden")}</span>` : "";
    const disconnectedNote =
      stateNorm === "DISCONNECTED"
        ? `<small class="worker-alert">${t("workers.disconnected")}</small>`
        : "";
    const lastSeen = formatEpochTime(worker.last_seen_at || worker.heartbeat_at);
    const lastResult = worker.last_run_status ? String(worker.last_run_status) : "-";
    const currentRun = worker.current_run_id ? String(worker.current_run_id) : "-";
    const tags = Array.isArray(worker.tags) ? worker.tags.join(",") : "";
    const workerId = String(worker.worker_id || "-");
    const actionKindClass = hidden ? "is-unhide" : "is-hide";
    const actionIcon = hidden ? "↺" : "🗑";
    const actionLabel = hidden ? t("workers.action.unhide") : t("workers.action.hide");
    const actionTitle = hidden ? t("workers.action.unhide_title") : t("workers.action.hide_title");
    li.innerHTML = `
      <div class="worker-top">
        <strong>${workerId}</strong>
        <div class="worker-top-right">
          ${stateBadge}
          ${hiddenChip}
        </div>
      </div>
      <small>${t("workers.seen_tags", { seen: lastSeen, tags })}</small>
      ${disconnectedNote}
      <small>${t("workers.current_last", { current: currentRun, last: lastResult })}</small>
      <button class="worker-toggle-hidden ${actionKindClass}" data-worker-id="${workerId}" data-hidden="${hidden ? "1" : "0"}" title="${actionTitle}">
        <span class="worker-action-icon" aria-hidden="true">${actionIcon}</span>
        <span class="worker-action-label">${actionLabel}</span>
      </button>
    `;
    frag.appendChild(li);
  }
  els.workersList.appendChild(frag);
}

async function setWorkerHidden(workerId, hidden) {
  await fetchJsonWith(`/workers/${encodeURIComponent(workerId)}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ hidden: Boolean(hidden) }),
  });
}

function selectRun(runId) {
  state.selectedRunId = runId;
  const snap = state.runsById.get(runId) || null;
  renderRuns();
  renderRunDetail(snap);
  void refreshSelectedRunDetail(runId);
  if (snap && snap.updated_at) {
    startWatch(runId, Number(snap.updated_at));
  } else {
    startWatch(runId, state.maxUpdatedAt);
  }
}

async function refreshSelectedRunDetail(runId) {
  try {
    const snap = await fetchJson(`/runs/${encodeURIComponent(runId)}`);
    mergeRuns([snap]);
    if (state.selectedRunId === runId) {
      renderRuns();
      renderRunDetail(snap);
    }
  } catch (err) {
    setError(String(err?.message || err));
  }
}

async function cancelSelectedRun() {
  const runId = String(state.selectedRunId || "").trim();
  if (!runId) {
    return;
  }
  const snap = await fetchJsonWith(`/runs/${encodeURIComponent(runId)}/cancel`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  mergeRuns([snap]);
  renderRuns();
  if (state.selectedRunId === runId) {
    renderRunDetail(snap);
    const since = Number(snap.updated_at || state.maxUpdatedAt || 0);
    startWatch(runId, since);
  }
}

function stopWatch() {
  if (state.watchAbort) {
    state.watchAbort.abort();
    state.watchAbort = null;
  }
  state.watchTerminal = false;
}

function sleep(ms, signal) {
  return new Promise((resolve, reject) => {
    const id = setTimeout(resolve, ms);
    if (!signal) {
      return;
    }
    signal.addEventListener(
      "abort",
      () => {
        clearTimeout(id);
        reject(new DOMException("Aborted", "AbortError"));
      },
      { once: true }
    );
  });
}

async function consumeSse(response, signal, onEvent) {
  if (!response.body) {
    return;
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let eventName = "message";
  let dataLines = [];

  while (true) {
    if (signal.aborted) {
      return;
    }
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });

    while (true) {
      const idx = buffer.indexOf("\n");
      if (idx < 0) {
        break;
      }
      let line = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 1);
      if (line.endsWith("\r")) {
        line = line.slice(0, -1);
      }
      if (line === "") {
        if (dataLines.length > 0) {
          const raw = dataLines.join("\n");
          let payload;
          try {
            payload = JSON.parse(raw);
          } catch {
            payload = { raw };
          }
          onEvent({ event: eventName, data: payload });
        }
        eventName = "message";
        dataLines = [];
        continue;
      }
      if (line.startsWith("event:")) {
        eventName = line.slice(6).trim();
        continue;
      }
      if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trimStart());
      }
    }
  }
}

function applyWatchEvent(evt, runId) {
  if (evt.event !== "snapshot") {
    return;
  }
  const snapshot = evt.data?.snapshot;
  if (!snapshot || snapshot.run_id !== runId) {
    return;
  }
  mergeRuns([snapshot]);
  renderRuns();
  if (state.selectedRunId === runId) {
    renderRunDetail(snapshot);
  }
  const updatedAt = Number(snapshot.updated_at || 0);
  if (updatedAt > state.maxUpdatedAt) {
    state.maxUpdatedAt = updatedAt;
  }
  if (isTerminal(snapshot.status)) {
    state.watchTerminal = true;
    setWatchState("wait", "watch.terminal");
    if (state.watchAbort) {
      state.watchAbort.abort();
    }
  }
}

async function startWatch(runId, since) {
  stopWatch();
  const controller = new AbortController();
  state.watchAbort = controller;
  state.watchTerminal = false;
  setWatchState("wait", "watch.connecting");
  let watchSince = Math.max(0, Number(since || 0));

  while (!controller.signal.aborted && state.selectedRunId === runId && !state.watchTerminal) {
    try {
      const params = new URLSearchParams();
      params.set("timeout_sec", "60");
      if (watchSince > 0) {
        params.set("since", String(watchSince));
      }
      const resp = await fetch(`/runs/${encodeURIComponent(runId)}/watch?${params.toString()}`, {
        headers: buildHeaders(),
        signal: controller.signal,
      });
      if (!resp.ok) {
        const body = await resp.text();
        throw new Error(`${resp.status} ${body}`.trim());
      }
      setWatchState("live", "watch.streaming");
      await consumeSse(resp, controller.signal, (evt) => {
        applyWatchEvent(evt, runId);
        const updatedAt = Number(evt.data?.snapshot?.updated_at || 0);
        if (updatedAt > watchSince) {
          watchSince = updatedAt;
        }
      });
      if (!state.watchTerminal) {
        setWatchState("wait", "watch.reconnecting");
        await sleep(900, controller.signal);
      }
    } catch (err) {
      if (controller.signal.aborted || state.watchTerminal) {
        break;
      }
      setWatchState("err", "watch.retrying");
      setError(String(err?.message || err));
      await sleep(1200, controller.signal).catch(() => {});
    }
  }
}

async function refreshRunsInitial() {
  state.runsById.clear();
  state.maxUpdatedAt = 0;
  let cursor = null;
  let pages = 0;
  do {
    const query = buildRunsQuery({ updatedAfter: 0, cursor });
    const body = await fetchJson(`/runs?${query.toString()}`);
    const items = normalizeRunItems(body);
    mergeRuns(items);
    cursor = body?.next_cursor || null;
    pages += 1;
  } while (cursor && pages < 8);
  renderRuns();
  if (state.selectedRunId) {
    renderRunDetail(state.runsById.get(state.selectedRunId));
  }
  setLastUpdate();
}

async function refreshRunsDelta() {
  if (state.pollingRuns) {
    return;
  }
  state.pollingRuns = true;
  try {
    const query = buildRunsQuery({ updatedAfter: state.maxUpdatedAt || 0 });
    const body = await fetchJson(`/runs?${query.toString()}`);
    const items = normalizeRunItems(body);
    if (items.length > 0) {
      mergeRuns(items);
      renderRuns();
      if (state.selectedRunId && state.runsById.has(state.selectedRunId)) {
        renderRunDetail(state.runsById.get(state.selectedRunId));
      }
    }
    setLastUpdate();
    setError("");
  } catch (err) {
    setError(String(err?.message || err));
  } finally {
    state.pollingRuns = false;
  }
}

async function refreshWorkers() {
  if (state.pollingWorkers) {
    state.pendingWorkersRefresh = true;
    return;
  }
  state.pollingWorkers = true;
  try {
    const query = buildWorkersQuery();
    const workers = await fetchJson(`/workers?${query.toString()}`);
    renderWorkers(workers);
    setLastUpdate();
    setError("");
  } catch (err) {
    setError(String(err?.message || err));
  } finally {
    state.pollingWorkers = false;
    if (state.pendingWorkersRefresh) {
      state.pendingWorkersRefresh = false;
      void refreshWorkers();
    }
  }
}

async function refreshWorkersAndWait(timeoutMs = 3000) {
  await refreshWorkers();
  const deadline = Date.now() + Math.max(100, Number(timeoutMs) || 3000);
  while ((state.pollingWorkers || state.pendingWorkersRefresh) && Date.now() < deadline) {
    await sleep(40);
  }
}

async function refreshMetrics() {
  if (state.pollingMetrics) {
    return;
  }
  state.pollingMetrics = true;
  try {
    const metrics = await fetchText("/metrics");
    const parsed = parsePrometheusMetrics(metrics);
    const dayKey = todayKeyLocal();
    const snapshot = {
      dayKey,
      runningNow: getMetricValue(parsed, "pyoco_runs_total", { status: "RUNNING" }),
      completedToday: getMetricValue(parsed, "pyoco_runs_today_total", { status: "COMPLETED" }),
      failedToday: getMetricValue(parsed, "pyoco_runs_today_total", { status: "FAILED" }),
    };
    state.latestMetrics = snapshot;
    renderMetricsKpis(snapshot);
    setLastUpdate();
    setError("");
  } catch (err) {
    setError(String(err?.message || err));
  } finally {
    state.pollingMetrics = false;
  }
}

function applyFilterInputs() {
  state.filters.status = (els.fStatus.value || "").trim().toUpperCase();
  state.filters.flow = (els.fFlow.value || "").trim();
  state.filters.tag = (els.fTag.value || "").trim();
  state.filters.runId = (els.fRunId.value || "").trim();
  state.filters.workerId = (els.fWorkerId.value || "").trim();
  state.filters.sortKey = (els.fSortKey.value || "ops_default").trim();
  const requestedDir = (els.fSortDir.value || "desc").trim() === "asc" ? "asc" : "desc";
  state.filters.sortDir = state.filters.sortKey === "ops_default" ? "desc" : requestedDir;
  if (els.fSortDir) {
    els.fSortDir.disabled = state.filters.sortKey === "ops_default";
    if (state.filters.sortKey === "ops_default") {
      els.fSortDir.value = "desc";
    }
  }
  const limit = Number(els.fLimit.value || 50);
  state.filters.limit = Math.max(1, Math.min(200, Number.isFinite(limit) ? limit : 50));
}

function applyWorkerFilterInputs() {
  state.workerFilters.state = (els.wState?.value || "").trim().toUpperCase();
  state.workerFilters.includeHidden = Boolean(els.wIncludeHidden?.checked);
}

function bindEvents() {
  els.saveAuth.addEventListener("click", async () => {
    saveAuth();
    await refreshRunsInitial().catch((err) => setError(String(err?.message || err)));
    await refreshWorkers();
    await refreshMetrics();
    if (state.selectedRunId) {
      startWatch(state.selectedRunId, state.maxUpdatedAt);
    }
  });

  els.runsFilters.addEventListener("submit", async (event) => {
    event.preventDefault();
    applyFilterInputs();
    await refreshRunsInitial().catch((err) => setError(String(err?.message || err)));
  });

  if (els.detailCancel) {
    els.detailCancel.addEventListener("click", async () => {
      try {
        await cancelSelectedRun();
        setError("");
      } catch (err) {
        setError(String(err?.message || err));
      }
    });
  }

  if (els.workersFilters) {
    els.workersFilters.addEventListener("submit", (event) => {
      event.preventDefault();
    });
    const handleWorkerFilterChange = async () => {
      applyWorkerFilterInputs();
      await refreshWorkers();
    };
    els.wState?.addEventListener("change", handleWorkerFilterChange);
    els.wIncludeHidden?.addEventListener("change", handleWorkerFilterChange);
  }

  if (els.workersList) {
    els.workersList.addEventListener("click", async (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) {
        return;
      }
      const btn = target.closest(".worker-toggle-hidden");
      if (!(btn instanceof HTMLButtonElement)) {
        return;
      }
      const workerId = String(btn.dataset.workerId || "").trim();
      if (!workerId) {
        return;
      }
      const currentlyHidden = btn.dataset.hidden === "1";
      try {
        await setWorkerHidden(workerId, !currentlyHidden);
        await refreshWorkersAndWait();
        setError("");
      } catch (err) {
        setError(String(err?.message || err));
      }
    });
  }

  els.clearMetricsBase?.addEventListener("click", () => {
    const m = state.latestMetrics;
    if (!m) {
      return;
    }
    state.metricsBaseline = {
      dateKey: String(m.dayKey),
      completedToday: Number(m.completedToday || 0),
      failedToday: Number(m.failedToday || 0),
      clearedAt: Date.now(),
    };
    saveMetricsBaseline();
    renderMetricsKpis(m);
  });
}

async function boot() {
  applyI18nToDocument();
  loadSavedAuth();
  loadMetricsBaseline();
  bindEvents();
  applyFilterInputs();
  applyWorkerFilterInputs();
  setWatchState("", "watch.idle");

  try {
    await refreshRunsInitial();
    await refreshWorkers();
    await refreshMetrics();
  } catch (err) {
    setError(String(err?.message || err));
  }

  setInterval(refreshRunsDelta, 2000);
  setInterval(refreshWorkers, 10000);
  setInterval(refreshMetrics, 15000);
}

boot();
