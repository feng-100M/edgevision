(function () {
  'use strict';
  const timeFormatter = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23'
  });
  function formatTime(value) {
    const date = new Date(value);
    if (!value || !Number.isFinite(date.getTime())) return '时间不可用';
    const p = Object.fromEntries(timeFormatter.formatToParts(date).map(x => [x.type, x.value]));
    return p.year + '-' + p.month + '-' + p.day + ' ' + p.hour + ':' + p.minute + ':' + p.second;
  }
  function reasonText(track) {
    const descriptions = {
      outside_roi: '底部判定点在区域外，未触发事件',
      entered: '刚进入区域，已触发进入事件',
      left: '刚离开区域，已触发离开事件',
      already_inside: '持续在区域内，本次进入已告警，不重复触发',
      inside_suppressed: '本次进入曾被冷却抑制，持续停留不补发；离开后重新进入可再次判断'
    };
    if (track.reason === 'outside_roi' && track.bottom_clipped) {
      return '人体框底部被画面裁切，判定点在区域外；请核对机位和 ROI 下边界';
    }
    if (track.reason === 'cooldown') return '重新进入处于冷却中，剩余 ' + Number(track.cooldown_remaining || 0).toFixed(1) + ' 秒';
    return descriptions[track.reason] || '等待区域判定';
  }
  function mqttText(result) {
    if (!result) return '发送状态未知';
    const labels = {acknowledged: 'Broker 已确认', pending: '客户端已接收，等待 Broker 确认',
      queued: '已落盘，等待 Broker 确认', failed: '发送失败', disabled: '未启用 MQTT'};
    return labels[result.state] || '发送状态未知';
  }
  function countTransitions(rows) {
    let entered = 0;
    let left = 0;
    for (const row of rows) {
      if (row.event_type === 'person_entered') entered++;
      if (row.event_type === 'person_left') left++;
    }
    return {entered, left};
  }
  const api = {formatTime, reasonText, mqttText, countTransitions};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof document === 'undefined') return;
  const get = id => document.getElementById(id);
  const set = (id, value) => { get(id).textContent = value; };
  let latestMqtt = {};
  let loadedHistoryRows = null;
  let previousLive = '';
  let previousSeq;
  let lastFrameAt = 0;
  function node(tag, text, className) {
    const result = document.createElement(tag);
    if (text !== undefined) result.textContent = text;
    if (className) result.className = className;
    return result;
  }
  function renderEvents(container, rows, states) {
    container.replaceChildren();
    if (!rows.length) {
      container.append(node('p', '暂无事件', 'empty'));
      return;
    }
    const table = node('table');
    const heading = node('tr');
    for (const label of ['北京时间', '事件 / 轨迹', '置信度', '区域 / MQTT', '事件截图']) heading.append(node('th', label));
    const head = node('thead'); head.append(heading); table.append(head);
    const body = node('tbody');
    for (const event of rows) {
      const tr = node('tr');
      tr.append(node('td', formatTime(event.occurred_at)));
      tr.append(node('td', (event.event_type === 'person_entered' ? '进入区域' : '离开区域') + ' · #' + event.track_id));
      tr.append(node('td', Number(event.confidence).toFixed(2)));
      const delivery = node('td');
      delivery.append(node('div', event.roi_name));
      const durable = {acked: {state:'acknowledged'}, pending: {state:'queued'}};
      const result = states[event.event_id] || durable[event.delivery_state];
      if (result) delivery.append(node('div', mqttText(result), result.state === 'failed' ? 'bad' : 'muted'));
      if (result && result.error) delivery.append(node('div', errorText(result.error), 'bad'));
      tr.append(delivery);
      const snapshot = node('td');
      if (event.snapshot_path) snapshot.append(snapshotLink(event));
      else {
        const note = event.snapshot_note || '';
        const label = note.startsWith('blurred frame') ? '画面模糊' : '无截图';
        const text = node('span', label, 'muted');
        text.title = note;
        snapshot.append(text);
      }
      tr.append(snapshot); body.append(tr);
    }
    table.append(body); container.append(table);
  }
  function snapshotLink(event) {
    const link = node('a');
    link.href = '/snapshots/' + encodeURIComponent(event.event_id);
    link.target = '_blank';
    link.rel = 'noopener';
    const image = node('img', undefined, 'thumb');
    image.src = link.href;
    image.alt = '查看事件截图';
    image.loading = 'lazy';
    image.onerror = () => { link.replaceChildren('截图不可用'); };
    link.append(image);
    return link;
  }
  function renderLatest(event) {
    const latest = get('latest');
    latest.replaceChildren();
    if (!event) { latest.textContent = '暂无事件'; return; }
    const row = node('div', undefined, 'row');
    if (event.snapshot_path) row.append(snapshotLink(event));
    const text = node('div');
    text.append(node('strong', (event.event_type === 'person_entered' ? '进入' : '离开') +
      ' · 轨迹 #' + event.track_id));
    text.append(node('time', formatTime(event.occurred_at) + ' 北京时间'));
    row.append(text);
    latest.append(row);
  }
  function errorText(error) {
    return {disconnected:'Broker 未连接，未发送', queue_full:'待确认队列已满'}[error] || error || '';
  }
  function renderTracks(rows) {
    const container = get('tracks'); container.replaceChildren();
    if (!rows.length) { container.append(node('p', '暂无轨迹', 'muted')); return; }
    for (const track of rows) {
      const item = node('div', undefined, 'track');
      item.append(node('b', '轨迹 #' + track.track_id + ' · 置信度 ' + Number(track.confidence).toFixed(2)));
      item.append(node('div', reasonText(track), track.inside ? 'good' : 'warn'));
      if (track.point) item.append(node('div', '底部中心点 (' + track.point.map(x => Math.round(x)).join(', ') + ')', 'muted'));
      container.append(item);
    }
  }
  function renderMqtt(mqtt) {
    const states = mqtt.event_status || {};
    const changed = JSON.stringify(states) !== JSON.stringify(latestMqtt);
    latestMqtt = states;
    const labels = {connected:'MQTT 在线', disconnected:'MQTT 重连中', disabled:'MQTT 已关闭'};
    set('mqtt-state', labels[mqtt.state] || 'MQTT 未知');
    get('mqtt-state').className = 'status ' + ({connected:'good', disconnected:'warn'}[mqtt.state] || 'muted');
    set('mqtt-target', mqtt.host ? mqtt.host + ':' + mqtt.port : '—');
    set('mqtt-topic', mqtt.topic || '—');
    for (const key of ['accepted','acknowledged','pending','failed']) set('mqtt-' + key, mqtt.state === 'disabled' ? '—' : mqtt[key] || 0);
    set('mqtt-detail', mqtt.last_error ? errorText(mqtt.last_error) : '');
    if (changed && loadedHistoryRows && !get('history').hidden) renderEvents(get('history'), loadedHistoryRows, latestMqtt);
  }
  function renderRoiMode(status) {
    const disabled = status.roi_enabled === false;
    set('page-title', disabled ? 'EdgeVision · 全画面检测' : 'EdgeVision · 区域检测');
    get('roi-legend').hidden = disabled;
    get('outside-legend').hidden = disabled;
    get('inside-stat').hidden = disabled;
    set('inside-legend', disabled ? '检测目标' : '区域内');
  }
  async function fetchJson(path) {
    const response = await fetch(path, {cache:'no-store'});
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || '请求失败');
    return body;
  }
  async function refreshStatus() {
    try {
      const s = await fetchJson('/status');
      if (s.seq !== undefined && s.seq !== previousSeq) { previousSeq = s.seq; lastFrameAt = Date.now(); }
      const health = s.frame_health || {};
      const stalled = s.seq !== undefined && Date.now() - lastFrameAt > 3000;
      const labels = {starting:'等待首帧', healthy:'画面正常', unavailable:'画面失联', recovered:'画面已恢复'};
      const state = health.state || (s.seq === undefined ? 'starting' : 'healthy');
      const stale = stalled && (state === 'healthy' || state === 'recovered');
      set('connection', stale ? '画面停滞' : labels[state] || '画面未知');
      get('connection').className = 'status ' + (stale || state === 'unavailable' ? 'bad' : state === 'starting' ? 'muted' : 'good');
      set('last-success', health.last_success_at ? formatTime(health.last_success_at) : '—');
      set('last-recovery', health.last_recovery_at ? formatTime(health.last_recovery_at) : '—');
      set('failures', health.consecutive_failures ?? '—');
      renderRoiMode(s);
      set('people', s.detections || 0); set('inside', s.inside_count || 0);
      set('count', s.events || 0); set('frames', s.processed_frames || 0);
      set('fps', Number(s.fps || 0).toFixed(1)); set('preview-fps', Number(s.preview_fps || 0).toFixed(1));
      set('drops', (Number(s.queue_drop_rate || 0) * 100).toFixed(1) + '%');
      set('latency', s.frame_age_p95_ms == null ? '—' : Number(s.frame_age_p95_ms).toFixed(0) + ' ms');
      set('focus-rejected', s.focus_rejected || 0);
      renderTracks(s.track_diagnostics || []); renderMqtt(s.mqtt || {});
      const rows = (s.recent_events || []).slice().reverse();
      const liveKey = JSON.stringify([rows, latestMqtt]);
      if (liveKey !== previousLive) {
        renderEvents(get('events'), rows, latestMqtt);
        renderLatest(rows[0]);
        previousLive = liveKey;
      }
      set('storage', s.storage_failed ? '事件保存失败 ' + s.storage_failed + ' 条' : '');
      const roi = s.roi_enabled === false ? '' : (s.roi_name || '');
      set('roi', [roi, s.frame_width && s.frame_height ? s.frame_width + ' × ' + s.frame_height : ''].filter(Boolean).join(' · '));
    } catch (error) {
      set('connection', '检测连接断开');
      get('connection').className = 'status bad';
    }
    setTimeout(refreshStatus, 500);
  }
  get('frame').onerror = () => setTimeout(() => { get('frame').src = '/stream.mjpg?t=' + Date.now(); }, 1000);
  get('stop').onclick = async () => {
    get('stop').disabled = true;
    try { const response = await fetch('/stop', {method:'POST'}); if (!response.ok) throw new Error(); set('connection','正在停止本次检测'); }
    catch (error) { set('connection','停止请求失败，请在启动终端按 Ctrl+C'); get('stop').disabled = false; }
  };
  let historyRequest = 0;
  function selectHistory(active) {
    get('events').hidden = active;
    get('history').hidden = !active;
    get('refresh-history').hidden = !active;
    get('history-scope').hidden = true;
    get('history-chart').hidden = true;
    get('load-history').setAttribute('aria-pressed', String(active));
    get('show-live').setAttribute('aria-pressed', String(!active));
    set('records-title', active ? '历史事件' : '本次事件');
  }
  async function showHistory() {
    selectHistory(true);
    const request = ++historyRequest;
    loadedHistoryRows = null;
    set('history', '读取中…');
    try {
      const body = await fetchJson('/events');
      if (request !== historyRequest) return;
      const rows = body.events || [];
      loadedHistoryRows = rows;
      const counts = countTransitions(rows);
      for (const key of ['entered','left']) {
        get(key + '-meter').max = Math.max(1, counts.entered, counts.left);
        get(key + '-meter').value = counts[key];
        set(key + '-count', counts[key]);
      }
      set('history-scope', '最近保存的 ' + rows.length + ' 条（最多 50 条）');
      get('history-scope').hidden = false;
      get('history-chart').hidden = rows.length === 0;
      renderEvents(get('history'), rows, latestMqtt);
    } catch (error) {
      if (request === historyRequest) get('history').replaceChildren(node('p', error.message, 'bad'));
    }
  }
  get('show-live').onclick = () => { historyRequest++; selectHistory(false); };
  get('load-history').onclick = showHistory;
  get('refresh-history').onclick = showHistory;
  refreshStatus();
}());
