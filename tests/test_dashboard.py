from pathlib import Path
import shutil
import subprocess

import pytest


def test_dashboard_formats_beijing_time_and_explains_alarm_and_delivery():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js unavailable for browser helper execution')
    script_path = Path(__file__).parents[1] / 'src/edgevision/dashboard.js'
    script = r'''
const assert = require('node:assert/strict');
const ui = require(process.argv[1]);
assert.equal(ui.formatTime('2026-10-29T08:50:54.000Z'), '2026-10-29 16:50:54');
assert.equal(ui.formatTime('2026-10-29T23:50:54Z'), '2026-10-30 07:50:54');
assert.equal(ui.formatTime('invalid'), '时间不可用');
assert.match(ui.reasonText({reason:'outside_roi',bottom_clipped:true}), /底部.*裁切/);
assert.match(ui.reasonText({reason:'already_inside'}), /不重复/);
assert.match(ui.reasonText({reason:'cooldown',cooldown_remaining:1.25}), /1.3/);
assert.match(ui.mqttText({state:'acknowledged'}), /Broker 已确认/);
assert.match(ui.mqttText({state:'pending'}), /等待 Broker/);
assert.match(ui.mqttText(undefined), /未知/);
console.log('DASHBOARD_BEHAVIOR_OK');
'''
    result = subprocess.run([node, '-e', script, str(script_path)],
                            capture_output=True, text=True, encoding='utf-8', timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'DASHBOARD_BEHAVIOR_OK' in result.stdout
