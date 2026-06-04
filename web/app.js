const els = {
  healthPill: document.getElementById('health-pill'),
  csvInput: document.getElementById('csv-input'),
  fileInput: document.getElementById('file-input'),
  scaleInput: document.getElementById('scale-input'),
  gapInput: document.getElementById('gap-input'),
  concurrencyInput: document.getElementById('concurrency-input'),
  previewBtn: document.getElementById('preview-btn'),
  runBtn: document.getElementById('run-btn'),
  cancelBtn: document.getElementById('cancel-btn'),
  runMeta: document.getElementById('run-meta'),
  latencyGrid: document.getElementById('latency-grid'),
  previewGrid: document.getElementById('preview-grid'),
  previewSchedule: document.getElementById('preview-schedule'),
  events: document.getElementById('events'),
  progressFill: document.getElementById('progress-fill'),
  progressText: document.getElementById('progress-text'),
};

let activeRunId = null;
let pollTimer = null;
let latencyChart = null;

function initLatencyChart() {
  const ctx = document.getElementById('latency-chart').getContext('2d');
  latencyChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: [],
      datasets: [{
        label: 'Time-to-complete (s)',
        data: [],
        borderColor: '#6C5CE7',
        backgroundColor: 'rgba(108,92,231,0.08)',
        pointRadius: 2,
        tension: 0.1,
      }]
    },
    options: {
      scales: {
        x: { type: 'category', title: { display: true, text: 'Time' } },
        y: { title: { display: true, text: 'Seconds' } }
      },
      plugins: { legend: { display: true } },
    }
  });
}

function metric(label, value, subvalue = '') {
  return `
    <div class="metric">
      <div class="label">${label}</div>
      <div class="value">${value}</div>
      ${subvalue ? `<div class="subvalue">${subvalue}</div>` : ''}
    </div>
  `;
}

function fmtNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  return Number(value).toFixed(digits);
}

async function checkHealth() {
  try {
    const response = await fetch('/api/health');
    const data = await response.json();
    els.healthPill.textContent = data.ok ? 'backend online' : 'backend unavailable';
    els.healthPill.style.color = data.ok ? 'var(--success)' : 'var(--danger)';
  } catch {
    els.healthPill.textContent = 'backend unavailable';
    els.healthPill.style.color = 'var(--danger)';
  }
}

function renderPreview(data) {
  els.previewGrid.innerHTML = [
    metric('Rows total', data.rows_total),
    metric('Rows active', data.rows_active),
    metric('Rows skipped', data.rows_skipped),
    metric('Compressed duration', `${fmtNumber(data.compressed_duration_s)}s`, `scale ${els.scaleInput.value}`),
  ].join('');

  const schedule = (data.schedule_preview || []).map(row => `
    <div class="schedule-row">
      <div class="time">${row.submission_time}<span class="tag">+${fmtNumber(row.offset_s)}s</span></div>
      <div class="line">attempt ${row.attempt_number || '—'} · score ${row.score || '—'} · active ${row.active || '—'}</div>
    </div>
  `).join('');
  els.previewSchedule.innerHTML = schedule || '<div class="event"><div class="msg">No active rows found.</div></div>';
}

function renderRun(snapshot, runId) {
  const metrics = snapshot.metrics || {};
  const schedule = snapshot.schedule || {};
  const progressTotal = schedule.total || 0;
  const progressNow = schedule.replayed_index || 0;
  const percent = progressTotal ? (progressNow / progressTotal) * 100 : 0;

  els.progressFill.style.width = `${Math.min(100, percent)}%`;
  els.progressText.textContent = `${progressNow} / ${progressTotal}`;

  els.runMeta.innerHTML = [
    metric('Run', runId || activeRunId || '—'),
    metric('Status', snapshot.status || '—'),
    metric('Mode', snapshot.mode || '—'),
    metric('Submitted', metrics.submitted ?? 0),
    metric('Completed', metrics.completed ?? 0),
    metric('Errors', metrics.errors ?? 0),
    metric('Active jobs', metrics.active_jobs ?? 0),
    metric('Avg TPS', fmtNumber(metrics.avg_tps ?? 0)),
  ].join('');

  const latencies = snapshot.latency_stats || {};
  const latencyCards = Object.keys(latencies).length
    ? Object.entries(latencies).map(([app, stats]) => metric(
        app,
        `${fmtNumber(stats.avg)}s`,
        `p95 ${fmtNumber(stats.p95)}s · n=${stats.count}`,
      )).join('')
    : metric('Latency', 'waiting', 'no completed jobs yet');
  els.latencyGrid.innerHTML = latencyCards;

  const events = (snapshot.recent_events || []).slice().reverse().map(event => `
    <div class="event">
      <div class="ts">${new Date(event.ts * 1000).toLocaleTimeString()}</div>
      <div class="msg"><strong>${event.kind}</strong> ${event.message}</div>
      ${event.error ? `<div class="ts">${event.error}</div>` : ''}
    </div>
  `).join('');
  els.events.innerHTML = events || '<div class="event"><div class="msg">No events yet.</div></div>';

  els.cancelBtn.disabled = snapshot.status !== 'running';
  if (snapshot.status === 'completed' || snapshot.status === 'failed' || snapshot.status === 'cancelled') {
    stopPolling();
  }

  // Update latency chart with recent completions
  try {
    if (!latencyChart) initLatencyChart();
    const completions = snapshot.completions || [];
    const labels = completions.map(c => new Date(c.ts * 1000).toLocaleTimeString());
    const points = completions.map(c => c.latency);
    latencyChart.data.labels = labels;
    latencyChart.data.datasets[0].data = points;
    latencyChart.update('none');
  } catch (err) {
    // ignore chart failures
  }
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function loadPreview() {
  const csvText = els.csvInput.value.trim();
  if (!csvText) return;
  const response = await fetch('/api/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      csv_text: csvText,
      scale: Number(els.scaleInput.value || 1),
      gap_compression_seconds: Number(els.gapInput.value || 300),
    }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'preview failed');
  renderPreview(data);
}

async function startRun() {
  const csvText = els.csvInput.value.trim();
  if (!csvText) return;
  const response = await fetch('/api/runs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      csv_text: csvText,
      scale: Number(els.scaleInput.value || 1),
      gap_compression_seconds: Number(els.gapInput.value || 300),
      concurrency_target: Number(els.concurrencyInput.value || 80),
      test_duration: 300,
      submission_workers: 20,
    }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'run start failed');
  activeRunId = data.run_id;
  renderRun(data.snapshot, data.run_id);
  pollTimer = setInterval(() => pollRun(activeRunId), 1000);
}

async function pollRun(runId) {
  if (!runId) return;
  const response = await fetch(`/api/runs/${runId}`);
  const data = await response.json();
  if (!response.ok) return;
  renderRun(data.snapshot, runId);
}

async function cancelRun() {
  if (!activeRunId) return;
  const response = await fetch(`/api/runs/${activeRunId}/cancel`, { method: 'POST' });
  const data = await response.json();
  if (response.ok) renderRun(data.snapshot, activeRunId);
}

els.fileInput.addEventListener('change', async (event) => {
  const file = event.target.files && event.target.files[0];
  if (!file) return;
  els.csvInput.value = await file.text();
});

els.previewBtn.addEventListener('click', async () => {
  try {
    await loadPreview();
  } catch (error) {
    alert(error.message);
  }
});

els.runBtn.addEventListener('click', async () => {
  try {
    await loadPreview();
    await startRun();
  } catch (error) {
    alert(error.message);
  }
});

els.cancelBtn.addEventListener('click', async () => {
  try {
    await cancelRun();
  } catch (error) {
    alert(error.message);
  }
});

checkHealth();
els.csvInput.addEventListener('input', () => {
  stopPolling();
  activeRunId = null;
});
