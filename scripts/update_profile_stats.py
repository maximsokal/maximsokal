#!/usr/bin/env python3
"""Update the public GitHub metrics table in a profile README."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_ROOT = "https://api.github.com"
PER_PAGE = 100
OWNER_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?\Z")


def github_get(url):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "maximsokal-profile-stats",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    with urlopen(Request(url, headers=headers), timeout=30) as response:
        return json.load(response)


def paginate(path, fetch=github_get, **query):
    """Fetch every page; a full 100-item page requires one more request."""
    records = []
    for page in range(1, 1001):
        url = f"{API_ROOT}{path}?{urlencode({**query, 'per_page': PER_PAGE, 'page': page})}"
        batch = fetch(url)
        if not isinstance(batch, list) or len(batch) > PER_PAGE:
            raise ValueError(f"Unexpected GitHub API response for {path} page {page}")
        records.extend(batch)
        if len(batch) < PER_PAGE:
            return records
    raise RuntimeError(f"Exceeded pagination safety limit for {path}")


def calculate_metrics(owner, fetch=github_get):
    if not OWNER_RE.fullmatch(owner):
        raise ValueError("Invalid GitHub username")
    repos = paginate(f"/users/{owner}/repos", fetch, type="owner")
    stars = downloads = count = 0
    for repo in repos:
        if not isinstance(repo, dict) or not isinstance(repo.get("private"), bool):
            raise ValueError("Invalid repository record")
        # A user's profile repository is public and intentionally included.
        if repo["private"]:
            continue
        if repo.get("owner", {}).get("login", "").lower() != owner.lower():
            raise ValueError("Unexpected repository owner")
        name = repo.get("name")
        star_count = repo.get("stargazers_count")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            raise ValueError("Invalid repository name")
        if type(star_count) is not int or star_count < 0:
            raise ValueError("Invalid star count")
        count += 1
        stars += star_count
        for release in paginate(f"/repos/{owner}/{name}/releases", fetch):
            if not isinstance(release, dict) or not isinstance(release.get("assets"), list):
                raise ValueError("Invalid release record")
            for asset in release["assets"]:
                value = asset.get("download_count") if isinstance(asset, dict) else None
                if type(value) is not int or value < 0:
                    raise ValueError("Invalid release download count")
                downloads += value
    return {"stars": stars, "downloads": downloads, "repositories": count}


def render_readme(content, metrics, today):
    """Replace only the metrics table, without rewriting unrelated content."""
    section_pattern = re.compile(r"(?ms)^## Open-source impact\n(?P<section>.*?)(?=^## |\Z)")
    found = list(section_pattern.finditer(content))
    if len(found) != 1:
        raise ValueError("Expected exactly one Open-source impact section")
    section = found[0].group("section")
    rules = {
        "stars": (r"\| Stars across public repositories \| \*\*(\d+)\*\* \|", "Stars across public repositories"),
        "downloads": (r"\| GitHub Release asset downloads \| \*\*(\d+)\*\* \|", "GitHub Release asset downloads"),
        "repositories": (r"\| Public repositories \| \*\*(\d+)\*\* \|", "Public repositories"),
    }
    changed = False
    for key, (pattern, label) in rules.items():
        if type(metrics.get(key)) is not int or metrics[key] < 0:
            raise ValueError(f"Invalid {key} metric")
        matches = list(re.finditer(rf"(?m)^{pattern}$", section))
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one row for {label}")
        if int(matches[0].group(1)) != metrics[key]:
            changed = True
    if not changed:
        return content
    header = r"(?m)^\| Metric \| Verified on \d{4}-\d{2}-\d{2} \|$"
    if len(re.findall(header, section)) != 1:
        raise ValueError("Expected exactly one dated metrics table header")
    section = re.sub(header, f"| Metric | Verified on {today} |", section)
    for key, (_, label) in rules.items():
        # Replacement must not match a different table elsewhere in README.
        section = re.sub(
            rf"(?m)^\| {re.escape(label)} \| \*\*\d+\*\* \|$",
            f"| {label} | **{metrics[key]}** |",
            section,
        )
    return content[:found[0].start("section")] + section + content[found[0].end("section"):]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", default="maximsokal")
    parser.add_argument("--readme", type=Path, default=Path("README.md"))
    args = parser.parse_args()
    # Compute everything before touching README: API errors must never destroy data.
    metrics = calculate_metrics(args.owner)
    original = args.readme.read_text(encoding="utf-8")
    updated = render_readme(original, metrics, datetime.now(timezone.utc).date().isoformat())
    if updated == original:
        print(f"Unchanged: {metrics}")
        return
    temporary = args.readme.with_name(args.readme.name + ".tmp")
    temporary.write_text(updated, encoding="utf-8", newline="\n")
    temporary.replace(args.readme)
    print(f"Updated: {metrics}")


if __name__ == "__main__":
    main()
