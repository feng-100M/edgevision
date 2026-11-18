from pathlib import Path

def test_run_script_is_local_raspberry_pi_gui_launcher():
    script=(Path(__file__).parents[1]/"scripts/run.sh").read_text(encoding="utf-8")
    assert "chromium" in script
    assert "wayland-0" in script
    assert "127.0.0.1:8765" in script
    assert "ssh.exe" not in script
    assert "18765" not in script
    assert 'CHROMIUM_PROFILE="$PROJECT_DIR/.tmp/chromium"' in script
    assert 'user-data-dir="$CHROMIUM_PROFILE"' in script
    assert 'stop_browser_profile TERM' in script
    assert 'stop_browser_profile KILL' in script


def test_relocated_checkout_reaches_setup_check(tmp_path):
    import shutil
    import subprocess
    import pytest
    shell = shutil.which("sh")
    if not shell:
        pytest.skip("POSIX shell unavailable")
    scripts = tmp_path / "a different checkout" / "scripts"
    scripts.mkdir(parents=True)
    shutil.copyfile(Path(__file__).parents[1] / "scripts/run.sh", scripts / "run.sh")
    completed = subprocess.run([shell, "run.sh"], cwd=scripts, text=True,
                               capture_output=True, timeout=10)
    assert completed.returncode == 2
    assert "setup is incomplete" in completed.stderr
