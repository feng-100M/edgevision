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
      failed: '发送失败', disabled: '未启用 MQTT'};
    return labels[result.state] || '发送状态未知';
  }
  const api = {formatTime, reasonText, mqttText};
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
      container.append(node('p', '尚无区域事件；请查看上方每个框的判定原因。', 'empty'));
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
      const result = states[event.event_id];
      delivery.append(node('div', mqttText(result), result && result.state === 'failed' ? 'bad' : 'muted'));
      if (result && result.error) delivery.append(node('div', errorText(result.error), 'bad'));
      tr.append(delivery);
      const snapshot = node('td');
      if (event.snapshot_path) {
        const link = node('a'); link.href = '/snapshots/' + encodeURIComponent(event.event_id);
        link.target = '_blank'; link.rel = 'noopener'; link.title = '查看本事件截图';
        const thumb = node('img'); thumb.className = 'thumb'; thumb.src = link.href;
        thumb.alt = '事件截图'; thumb.loading = 'lazy';
        thumb.onerror = () => { thumb.remove(); link.textContent = '截图已清理或无法读取'; };
        link.append(thumb); snapshot.append(link);
      } else snapshot.append(node('span', event.snapshot_note || '截图保存失败', 'bad'));
      tr.append(snapshot); body.append(tr);
    }
    table.append(body); container.append(table);
  }
  function errorText(error) {
    return {disconnected:'Broker 未连接，未发送', queue_full:'待确认队列已满'}[error] || error || '';
  }
  function renderTracks(rows) {
    const container = get('tracks'); container.replaceChildren();
    if (!rows.length) { container.append(node('p', '当前没有人体框，尚未进入事件判断。', 'muted')); return; }
    for (const track of rows) {
      const item = node('div', undefined, 'track');
      item.append(node('b', '轨迹 #' + track.track_id + ' · 置信度 ' + Number(track.confidence).toFixed(2)));
      item.append(node('div', reasonText(track), track.inside ? 'good' : 'warn'));
      if (track.point) item.append(node('div', '底部中心点 (' + track.point.map(x => Math.round(x)).join(', ') + ')', 'muted'));
      container.append(item);
    }
  }
  function renderMqtt(mqtt) {
    latestMqtt = mqtt.event_status || {};
    const labels = {connected:'已连接', disconnected:'未连接 · 重试中', disabled:'未启用', unavailable:'状态不可用'};
    set('mqtt-state', labels[mqtt.state] || '状态不可用');
    get('mqtt-state').className = 'pill ' + (mqtt.state === 'connected' ? 'good' : 'warn');
    set('mqtt-target', mqtt.host ? mqtt.host + ':' + mqtt.port : '—');
    set('mqtt-topic', mqtt.topic || '—');
    for (const key of ['accepted','acknowledged','pending','failed']) set('mqtt-' + key, mqtt[key] || 0);
    set('mqtt-detail', mqtt.last_error ? '最近错误：' + errorText(mqtt.last_error) :
      (!mqtt.accepted ? '尚无事件消息提交；仅连接 Broker 不会产生告警消息。' : '客户端接收和 Broker 确认是两个阶段。'));
    // A history response may have been loaded before a QoS1 PUBACK arrived.
    // Re-render it when the live status changes so "等待确认" does not stay
    // stale until the user clicks the button again.
    if (loadedHistoryRows) renderEvents(get('history'), loadedHistoryRows, latestMqtt);
  }
  function renderRoiMode(status) {
    const disabled = status.roi_enabled === false;
    set('page-title', disabled ? 'EdgeVision · 全画面检测' : 'EdgeVision · 区域检测');
    set('rule-summary', disabled ? '区域限制已关闭，画面内检测到的人体均可触发事件。' :
      '人体框底部中心点进入蓝色区域时告警，同一轨迹持续在内只记录一次。');
    const legend = get('roi-legend');
    legend.textContent = disabled ? '区域限制已关闭 · 全画面检测' : '蓝色：告警区域 ROI';
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
      set('connection', s.seq === undefined ? '等待画面' :
        (Date.now() - lastFrameAt > 3000 ? '画面暂未更新，请检查摄像头' : '实时画面已连接'));
      set('clock', formatTime(s.server_time) + ' · 北京时间 UTC+8');
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
      if (liveKey !== previousLive) { renderEvents(get('events'), rows, latestMqtt); previousLive = liveKey; }
      set('storage', s.storage_failed ? '本次保存失败 ' + s.storage_failed + ' 条，请检查日志与磁盘空间' : '事件截图和记录自动保存到 output 目录');
      get('storage').className = s.storage_failed ? 'bad' : 'muted';
      set('roi', s.roi_name ? (s.roi_enabled === false ? '区域检测已关闭 · 全画面检测' : '当前区域：' + s.roi_name) + ' · 画面 ' + s.frame_width + ' × ' + s.frame_height : '');
    } catch (error) { set('connection', '检测已停止或连接断开'); }
    setTimeout(refreshStatus, 500);
  }
  get('frame').onerror = () => setTimeout(() => { get('frame').src = '/stream.mjpg?t=' + Date.now(); }, 1000);
  get('stop').onclick = async () => {
    get('stop').disabled = true;
    try { const response = await fetch('/stop', {method:'POST'}); if (!response.ok) throw new Error(); set('connection','正在停止本次检测'); }
    catch (error) { set('connection','停止请求失败，请在启动终端按 Ctrl+C'); get('stop').disabled = false; }
  };
  get('load-history').onclick = async () => {
    get('load-history').disabled = true;
    try { const body = await fetchJson('/events'); loadedHistoryRows = body.events || []; renderEvents(get('history'), loadedHistoryRows, latestMqtt); }
    catch (error) { loadedHistoryRows = null; get('history').replaceChildren(node('p', error.message, 'bad')); }
    finally { get('load-history').disabled = false; }
  };
  refreshStatus();
}());
