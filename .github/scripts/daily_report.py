#!/usr/bin/env python3
"""Create a daily GitHub issue summarising today's commits using local Ollama (llama3.2:1b)."""

import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import date

REPO = os.environ["GITHUB_REPOSITORY"]
TOKEN = os.environ["GITHUB_TOKEN"]
TODAY = date.today().isoformat()
MODEL = os.environ.get("MODEL", "llama3.2:1b")

OLLAMA_ENDPOINT = "http://localhost:11434/api/chat"


def start_ollama() -> None:
    subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(30):
        try:
            urllib.request.urlopen("http://localhost:11434", timeout=2)
            break
        except Exception:
            time.sleep(2)
    else:
        raise RuntimeError("Ollama did not start within 60 seconds")
    subprocess.run(["ollama", "pull", MODEL], check=True)


def fetch_commits() -> str:
    result = subprocess.run(
        ["git", "log", "--pretty=format:%h %s", f"--after={TODAY}T00:00:00Z"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def summarise(commits: str) -> str:
    payload = {
        "model": MODEL,
        "stream": False,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a business analyst writing a daily development report for stakeholders. "
                    "For each git commit, write one paragraph in a professional business tone that explains "
                    "the business value or operational impact of the change — avoid jargon, focus on what "
                    "was improved, fixed, or enabled and why it matters. "
                    "Use the commit hash as a heading (e.g. '### abc1234')."
                ),
            },
            {
                "role": "user",
                "content": f"Repository: {REPO}\nDate: {TODAY}\n\nCommits:\n{commits}",
            },
        ],
    }
    req = urllib.request.Request(
        OLLAMA_ENDPOINT,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.load(resp)
    return data["message"]["content"].strip()


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
    start_ollama()
    summary = summarise(commits)
    print(f"Summary:\n{summary}\n")
    url = create_issue(summary, commits)
    print(f"Issue created: {url}")


if __name__ == "__main__":
    main()
