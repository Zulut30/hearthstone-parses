from __future__ import annotations

import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_docker_systemd_installer_covers_every_timer(tmp_path: Path) -> None:
    staged_systemd = tmp_path / "systemd"
    calls_file = tmp_path / "systemctl-calls"
    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" >> \"$SYSTEMCTL_CALLS_FILE\"\n",
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)
    env = {
        **os.environ,
        "INSTALL_DIR": "/custom/hs-api",
        "SYSTEMD_DIR": str(staged_systemd),
        "SYSTEMCTL_BIN": str(fake_systemctl),
        "SYSTEMCTL_CALLS_FILE": str(calls_file),
    }

    subprocess.run(
        ["bash", str(ROOT / "scripts/install-docker-systemd.sh")],
        check=True,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    expected_timers = sorted(path.name for path in (ROOT / "systemd").glob("hs-data-api-docker-*.timer"))
    installed_timers = sorted(path.name for path in staged_systemd.glob("hs-data-api-docker-*.timer"))
    calls = calls_file.read_text(encoding="utf-8").splitlines()
    enabled_timers = sorted(line.removeprefix("enable --now ") for line in calls if line.startswith("enable --now "))
    assert installed_timers == expected_timers
    assert enabled_timers == expected_timers
    assert calls[0] == "daemon-reload"
    assert (staged_systemd / "hs-data-api-docker.service").is_file()
    assert "/custom/hs-api/docker-compose.yml" in (
        staged_systemd / "hs-data-api-docker-refresh-bg-hero-details.service"
    ).read_text(encoding="utf-8")
