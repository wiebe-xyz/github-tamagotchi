"""Promote deploys by digest, and the manifest it applies names no usable tag."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / ".github" / "scripts"
MANIFEST = REPO / "k8s" / "production" / "deployment.yaml"
WORKFLOW = REPO / ".github" / "workflows" / "promote-to-production.yml"
PLACEHOLDER = "ghcr.io/wiebe-xyz/github-tamagotchi:set-by-promote"
DIGEST = "sha256:" + "a1" * 32


def resolve(tmp_path: Path, answer: str, exit_code: int = 0) -> subprocess.CompletedProcess[str]:
    docker = tmp_path / "docker"
    docker.write_text(
        f'#!/usr/bin/env bash\necho "$*" > "{tmp_path}/args"\necho "{answer}"\nexit {exit_code}\n'
    )
    docker.chmod(docker.stat().st_mode | stat.S_IXUSR)
    return subprocess.run(
        ["bash", str(SCRIPTS / "resolve_image_digest.sh"), "ghcr.io/o/app:prod-1"],
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"},
    )


def test_resolve_prints_the_repository_at_the_digest(tmp_path: Path) -> None:
    result = resolve(tmp_path, DIGEST)

    assert result.returncode == 0
    assert result.stdout.strip() == f"ghcr.io/o/app@{DIGEST}"
    assert "ghcr.io/o/app:prod-1" in (tmp_path / "args").read_text()


@pytest.mark.parametrize("answer", ["", "sha256:short", "prod-1", f"{DIGEST}x"])
def test_resolve_refuses_anything_but_a_digest(tmp_path: Path, answer: str) -> None:
    result = resolve(tmp_path, answer)

    assert result.returncode != 0
    assert result.stdout == ""


def test_resolve_fails_when_the_registry_read_fails(tmp_path: Path) -> None:
    result = resolve(tmp_path, DIGEST, exit_code=1)

    assert result.returncode != 0
    assert result.stdout == ""


def pin(blue: str, green: str) -> list[str]:
    result = subprocess.run(
        ["bash", str(SCRIPTS / "pin_color_images.sh"), str(MANIFEST), blue, green],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return result.stdout.splitlines()


def images_by_color(lines: list[str]) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {"blue": [], "green": []}
    color = ""
    for line in lines:
        if line == "  name: github-tamagotchi-blue":
            color = "blue"
        elif line == "  name: github-tamagotchi-green":
            color = "green"
        elif line.strip().startswith("image: "):
            found[color].append(line.strip().removeprefix("image: "))
    return found


def test_pin_sets_every_container_of_each_color() -> None:
    images = images_by_color(pin("img:blue", "img:green"))

    assert images["blue"] == ["img:blue", "img:blue"]
    assert images["green"] == ["img:green", "img:green"]


def test_pin_with_empty_image_keeps_the_manifest_value() -> None:
    images = images_by_color(pin("img:blue", ""))

    assert images["blue"] == ["img:blue", "img:blue"]
    assert images["green"] == [PLACEHOLDER, PLACEHOLDER]


def test_pin_changes_only_image_lines() -> None:
    original = MANIFEST.read_text().splitlines()
    pinned = pin("img:blue", "img:green")

    assert len(pinned) == len(original)
    changed = [new for old, new in zip(original, pinned, strict=True) if old != new]
    assert len(changed) == 4
    assert all(line.strip().startswith("image: ") for line in changed)


def test_manifest_names_only_the_placeholder_image() -> None:
    images = images_by_color(MANIFEST.read_text().splitlines())

    assert images["blue"] == [PLACEHOLDER, PLACEHOLDER]
    assert images["green"] == [PLACEHOLDER, PLACEHOLDER]


def test_workflow_applies_the_pinned_manifest_and_sets_the_digest() -> None:
    workflow = WORKFLOW.read_text()

    assert "kubectl apply -f k8s/production/deployment.yaml" not in workflow
    assert 'kubectl apply -f "$PINNED"' in workflow
    assert 'IMAGE="${{ needs.promote-image.outputs.image }}"' in workflow
    assert "github-tamagotchi=$IMAGE migrate=$IMAGE" in workflow
