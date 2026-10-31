"""Promote scripts run against stubbed kubectl and curl."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / ".github" / "scripts"
WORKFLOW = REPO / ".github" / "workflows" / "promote-to-production.yml"
BASE_URL = "https://tama.invalid"

# Keeps cluster state in $STUB_DIR. The endpoints follow the selector unless the
# file stuck_endpoints exists.
KUBECTL_STUB = r"""#!/usr/bin/env bash
echo "kubectl $*" >> "$STUB_DIR/calls"
case "$1 $2" in
  "get pod")
    case "$*" in
      *version=blue*) echo -n "10.0.0.1" ;;
      *version=green*) echo -n "10.0.0.2 10.0.0.3" ;;
    esac
    ;;
  "get endpoints")
    if [ -e "$STUB_DIR/stuck_endpoints" ]; then
      echo -n "10.0.0.9"
    elif [ "$(cat "$STUB_DIR/selector")" = blue ]; then
      echo -n "10.0.0.1"
    else
      echo -n "10.0.0.3 10.0.0.2"
    fi
    ;;
  "get deployment") cat "$STUB_DIR/old_ready" ;;
  "patch service")
    [ -e "$STUB_DIR/patch_fails" ] && exit 1
    case "$*" in
      *'"value":"blue"'*) echo blue > "$STUB_DIR/selector" ;;
      *'"value":"green"'*) echo green > "$STUB_DIR/selector" ;;
    esac
    ;;
esac
exit 0
"""

# Each readiness request takes the next line of $STUB_DIR/ready_plan; once the
# plan runs out it answers healthy. The home page follows $STUB_DIR/home_fails.
CURL_STUB = r"""#!/usr/bin/env bash
echo "curl $*" >> "$STUB_DIR/calls"
case "$*" in
  */api/v1/health/ready*)
    step=$(head -n 1 "$STUB_DIR/ready_plan")
    tail -n +2 "$STUB_DIR/ready_plan" > "$STUB_DIR/ready_plan.next"
    mv "$STUB_DIR/ready_plan.next" "$STUB_DIR/ready_plan"
    case "$step" in
      fail) exit 22 ;;
      degraded) echo '{"status":"degraded"}' ;;
      *) echo '{"status":"healthy","checks":{"database":{"status":"ok"}}}' ;;
    esac
    ;;
  *) [ -e "$STUB_DIR/home_fails" ] && exit 22 ;;
esac
exit 0
"""


@pytest.fixture
def stub_dir(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("kubectl", KUBECTL_STUB), ("curl", CURL_STUB)):
        path = bin_dir / name
        path.write_text(body)
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    (tmp_path / "selector").write_text("green\n")
    (tmp_path / "old_ready").write_text("1")
    (tmp_path / "ready_plan").write_text("")
    (tmp_path / "calls").write_text("")
    return tmp_path


def verify(stub_dir: Path, ready_plan: list[str] | None = None) -> subprocess.CompletedProcess[str]:
    (stub_dir / "ready_plan").write_text("".join(f"{step}\n" for step in ready_plan or []))
    env = {
        **os.environ,
        "PATH": f"{stub_dir / 'bin'}{os.pathsep}{os.environ['PATH']}",
        "STUB_DIR": str(stub_dir),
        "ENDPOINT_WAIT_ROUNDS": "2",
        "ENDPOINT_WAIT_INTERVAL": "0",
        "DRAIN_SECONDS": "0",
        "SMOKE_ROUNDS": "3",
        "SMOKE_INTERVAL": "0",
    }
    return subprocess.run(
        ["bash", str(SCRIPTS / "post_switch_verify.sh"), "tama-prod", "blue", "green", BASE_URL],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def selector(stub_dir: Path) -> str:
    return (stub_dir / "selector").read_text().strip()


def calls(stub_dir: Path) -> str:
    return (stub_dir / "calls").read_text()


def test_healthy_switch_keeps_traffic_and_leaves_scaling_to_the_caller(stub_dir: Path) -> None:
    result = verify(stub_dir)

    assert result.returncode == 0, result.stdout
    assert selector(stub_dir) == "green"
    assert "patch service" not in calls(stub_dir)
    assert "scale" not in calls(stub_dir)


def test_one_failed_round_is_tolerated(stub_dir: Path) -> None:
    result = verify(stub_dir, ["fail", "ok", "ok"])

    assert result.returncode == 0, result.stdout
    assert selector(stub_dir) == "green"


def test_two_failed_rounds_return_traffic_to_the_old_color(stub_dir: Path) -> None:
    result = verify(stub_dir, ["fail", "fail"])

    assert result.returncode == 1
    assert selector(stub_dir) == "blue"
    assert "scale deployment/github-tamagotchi-green --replicas=0" in calls(stub_dir)
    assert "ROLLED BACK: blue passes the smoke" in result.stdout


def test_degraded_readiness_counts_as_a_failure(stub_dir: Path) -> None:
    result = verify(stub_dir, ["degraded", "degraded"])

    assert result.returncode == 1
    assert selector(stub_dir) == "blue"


def test_failure_on_the_last_round_rolls_back(stub_dir: Path) -> None:
    result = verify(stub_dir, ["ok", "ok", "fail"])

    assert result.returncode == 1
    assert selector(stub_dir) == "blue"


def test_failing_home_page_rolls_back(stub_dir: Path) -> None:
    (stub_dir / "home_fails").write_text("")

    result = verify(stub_dir)

    assert result.returncode == 1
    assert selector(stub_dir) == "blue"
    assert "FAILS THE SMOKE" in result.stdout


def test_old_color_failing_after_rollback_is_reported(stub_dir: Path) -> None:
    result = verify(stub_dir, ["fail", "fail", "fail"])

    assert result.returncode == 1
    assert selector(stub_dir) == "blue"
    assert "ROLLED BACK, blue FAILS THE SMOKE" in result.stdout


def test_endpoints_that_never_move_keep_the_new_color_running(stub_dir: Path) -> None:
    (stub_dir / "stuck_endpoints").write_text("")

    result = verify(stub_dir)

    assert result.returncode == 1
    assert selector(stub_dir) == "blue"
    assert "ROLLBACK INCOMPLETE" in result.stdout
    assert "scale" not in calls(stub_dir)


def test_no_ready_old_pods_leaves_traffic_on_the_new_color(stub_dir: Path) -> None:
    (stub_dir / "old_ready").write_text("")

    result = verify(stub_dir, ["fail", "fail"])

    assert result.returncode == 1
    assert selector(stub_dir) == "green"
    assert "no rollback target" in result.stdout
    assert "patch service" not in calls(stub_dir)


def test_failed_patch_is_reported_and_keeps_the_new_color_running(stub_dir: Path) -> None:
    (stub_dir / "patch_fails").write_text("")

    result = verify(stub_dir, ["fail", "fail"])

    assert result.returncode == 1
    assert selector(stub_dir) == "green"
    assert "ROLLBACK FAILED" in result.stdout
    assert "scale" not in calls(stub_dir)


def test_workflow_verifies_before_it_scales_down_or_records_the_release() -> None:
    workflow = WORKFLOW.read_text()

    verified = workflow.index("post_switch_verify.sh")
    assert workflow.index("patch service github-tamagotchi -n $NS") < verified
    assert verified < workflow.index("deployment/github-tamagotchi-$ACTIVE --replicas=0")
    assert verified < workflow.index("create configmap deploy-state")
    assert verified < workflow.index("/api/v1/releases")
