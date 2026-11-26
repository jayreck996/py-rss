#!/usr/bin/env python3
"""Load remote py-rss paths and expose them to GitHub Actions."""

import os
import re
import sys
from pathlib import PurePosixPath, Path

try:
    import yaml
except ImportError:
    import subprocess

    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyyaml", "-q"])
    import yaml


CONFIG_PATH = Path("YML/PY-RSS/YML.yml")
SOURCE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def validate_relative_path(value: str, prefix: str, label: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{label} must be a relative path without '..': {value}")
    if not path.parts or path.parts[0] != prefix:
        raise ValueError(f"{label} must be inside {prefix}/: {value}")
    return value


def load_outputs() -> dict[str, str]:
    with CONFIG_PATH.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle).get("config", {})

    xml = config.get("repositories", {}).get("xml", {})
    repository = xml.get("name", "")
    checkout_path = xml.get("checkout_path", "")
    checkout = PurePosixPath(checkout_path)
    if repository.count("/") != 1:
        raise ValueError("config.repositories.xml.name must be owner/repository")
    if checkout.is_absolute() or len(checkout.parts) != 1 or ".." in checkout.parts:
        raise ValueError("config.repositories.xml.checkout_path must be one relative directory")

    outputs = {
        "xml_repository": repository,
        "xml_checkout_path": checkout_path,
    }
    feed_paths = []
    feeds = config.get("feeds", {})
    if not feeds:
        raise ValueError("config.feeds must contain at least one feed")
    for source, feed in feeds.items():
        if not SOURCE_RE.fullmatch(source):
            raise ValueError(f"Invalid feed key: {source}")
        output = validate_relative_path(feed.get("output", ""), checkout_path, f"{source}.output")
        pages_name = feed.get("pages_name", "")
        if PurePosixPath(pages_name).name != pages_name or not pages_name.endswith(".xml"):
            raise ValueError(f"{source}.pages_name must be one XML filename")
        outputs[f"{source}_feed_path"] = output
        outputs[f"{source}_pages_name"] = pages_name
        feed_paths.append(output)
    outputs["feed_paths"] = " ".join(feed_paths)
    return outputs


def emit(outputs: dict[str, str]) -> None:
    github_output = os.environ.get("GITHUB_OUTPUT")
    github_env = os.environ.get("GITHUB_ENV")
    for destination in (github_output, github_env):
        if destination:
            with open(destination, "a", encoding="utf-8") as handle:
                for key, value in outputs.items():
                    name = key if destination == github_output else key.upper()
                    handle.write(f"{name}={value}\n")
    if not github_output:
        for key, value in outputs.items():
            print(f"{key}={value}")


if __name__ == "__main__":
    emit(load_outputs())
