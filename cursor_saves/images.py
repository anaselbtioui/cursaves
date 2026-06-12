"""Export/import chat image attachments from Cursor workspace storage."""

from __future__ import annotations

import base64
import os
import platform
import re
import shutil
from pathlib import Path
from typing import Any

_WORKSPACE_IMAGE_FILE_RE = re.compile(
    r'(?:[A-Za-z]:[\\/]|/)[^\s"]*?[/\\]workspaceStorage[/\\][^/\\"\s]+[/\\]images[/\\]([^/\\"\s]+\.(?:png|jpe?g|gif|webp))',
    re.IGNORECASE,
)


def image_path_for_workspace(workspace_dir: Path, filename: str) -> str:
    """Build the platform-native path Cursor expects for a workspace image."""
    path = os.path.normpath(str(workspace_dir / "images" / filename))
    if platform.system() == "Windows":
        return path
    return path.replace("\\", "/")


def extract_image_paths(data: Any) -> set[str]:
    """Collect filesystem paths to workspace image files referenced in chat data."""
    found: set[str] = set()

    if isinstance(data, dict):
        path = data.get("path")
        if isinstance(path, str) and re.search(r"[/\\]images[/\\]", path, re.IGNORECASE):
            found.add(path)
        for value in data.values():
            found |= extract_image_paths(value)
    elif isinstance(data, list):
        for item in data:
            found |= extract_image_paths(item)
    elif isinstance(data, str):
        for match in _WORKSPACE_IMAGE_FILE_RE.finditer(data):
            found.add(match.group(0))

    return found


def extract_image_filenames(data: Any) -> set[str]:
    """Collect image filenames referenced in chat data."""
    filenames: set[str] = set()
    for path in extract_image_paths(data):
        filenames.add(Path(path).name)
    return filenames


def collect_image_assets(snapshot: dict) -> dict[str, str]:
    """Read referenced workspace image files and return {filename: base64}."""
    paths_found = extract_image_paths(snapshot)
    assets: dict[str, str] = {}
    for raw_path in paths_found:
        file_path = Path(os.path.normpath(raw_path))
        if not file_path.exists():
            continue
        assets[file_path.name] = base64.b64encode(file_path.read_bytes()).decode("ascii")
    return assets


def snapshot_images_dir(snapshot_path: Path, composer_id: str) -> Path:
    """Return the sidecar directory for a snapshot's image assets."""
    return snapshot_path.parent / f"{composer_id}.images"


def save_image_assets(
    assets: dict[str, str],
    snapshot_path: Path,
    composer_id: str,
) -> int:
    """Write image assets next to a snapshot file. Returns files written."""
    if not assets:
        return 0

    image_dir = snapshot_images_dir(snapshot_path, composer_id)
    if image_dir.exists():
        shutil.rmtree(image_dir)
    image_dir.mkdir(parents=True, exist_ok=True)

    for filename, encoded in assets.items():
        (image_dir / filename).write_bytes(base64.b64decode(encoded))

    return len(assets)


def install_image_assets(
    snapshot_path: Path,
    composer_id: str,
    workspace_dir: Path,
) -> set[str]:
    """Copy sidecar image assets into the target workspace images directory."""
    image_dir = snapshot_images_dir(snapshot_path, composer_id)
    if not image_dir.exists():
        return set()

    target_dir = workspace_dir / "images"
    target_dir.mkdir(parents=True, exist_ok=True)

    installed: set[str] = set()
    for src in image_dir.iterdir():
        if not src.is_file():
            continue
        shutil.copy2(src, target_dir / src.name)
        installed.add(src.name)

    return installed


def rewrite_image_paths(
    data: Any,
    workspace_dir: Path,
    filenames: set[str],
) -> Any:
    """Rewrite workspace image paths to the target workspace images directory."""
    if not filenames:
        return data

    if isinstance(data, str):
        result = data
        for filename in sorted(filenames, key=len, reverse=True):
            new_path = image_path_for_workspace(workspace_dir, filename)
            pattern = re.compile(
                r'[^"\s]*[/\\]images[/\\]' + re.escape(filename),
                re.IGNORECASE,
            )
            result = pattern.sub(new_path, result)
        return result

    if isinstance(data, dict):
        return {
            key: rewrite_image_paths(value, workspace_dir, filenames)
            for key, value in data.items()
        }

    if isinstance(data, list):
        return [rewrite_image_paths(item, workspace_dir, filenames) for item in data]

    return data


def remove_image_assets(snapshot_path: Path, composer_id: str) -> None:
    """Delete sidecar image assets for a snapshot."""
    image_dir = snapshot_images_dir(snapshot_path, composer_id)
    if image_dir.exists():
        shutil.rmtree(image_dir)
