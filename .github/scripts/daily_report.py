#!/usr/bin/env python3
"""Create a daily GitHub issue summarising today's commits using GitHub Models."""

import json
import os
import subprocess
import sys
import urllib.request
from datetime import date

REPO = os.environ["GITHUB_REPOSITORY"]
TOKEN = os.environ["GITHUB_TOKEN"]
TODAY = date.today().isoformat()


def fetch_commits() -> str:
    result = subprocess.run(
        ["git", "log", "--pretty=format:%h %s", f"--after={TODAY}T00:00:00Z"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def summarise(commits: str) -> str:
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a concise technical reporter. Given a list of git commit messages, "
                    "write a 2-3 sentence plain-English summary of what changed today and why. "
                    "Be specific about the changes, not generic."
                ),
            },
            {
                "role": "user",
                "content": f"Repository: {REPO}\nDate: {TODAY}\n\nCommits:\n{commits}",
            },
        ],
        "max_tokens": 400,
        "temperature": 0.3,
    }
    req = urllib.request.Request(
        "https://models.inference.ai.azure.com/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    return data["choices"][0]["message"]["content"].strip()


def create_issue(summary: str, commits: str) -> str:
    body = (
        f"## Summary\n\n{summary}\n\n"
        f"<details>\n<summary>Commits</summary>\n\n"
        f"```\n{commits}\n```\n\n</details>\n"
    )
    payload = {"title": f"Daily report: {TODAY}", "body": body}
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/issues",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        issue = json.load(resp)
    return issue["html_url"]


def main() -> None:
    commits = fetch_commits()
    if not commits:
        print(f"No commits on {TODAY} — skipping issue creation")
        sys.exit(0)

    print(f"Found commits:\n{commits}\n")
    summary = summarise(commits)
    print(f"Summary:\n{summary}\n")
    url = create_issue(summary, commits)
    print(f"Issue created: {url}")


if __name__ == "__main__":
    main()
