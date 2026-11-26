#!/usr/bin/env bash
set -euo pipefail

message=$1
shift
repo=${XML_CHECKOUT_PATH:?XML_CHECKOUT_PATH is required}
base=$(git -C "$repo" rev-parse HEAD)
relative_paths=()

for path in "$@"; do
  case "$path" in
    "$repo"/*) relative_paths+=("${path#"$repo"/}") ;;
    *) echo "::error::$path is outside $repo/"; exit 1 ;;
  esac
done

git -C "$repo" add -- "${relative_paths[@]}"
if git -C "$repo" diff --cached --quiet; then
  echo "No XML changes to publish."
  exit 0
fi

git -C "$repo" -c user.name='github-actions[bot]' \
  -c user.email='github-actions[bot]@users.noreply.github.com' commit -m "$message"

for attempt in 1 2 3 4 5; do
  if git -C "$repo" push origin HEAD:refs/heads/main; then
    exit 0
  fi

  git -C "$repo" fetch origin main
  upstream=$(git -C "$repo" rev-parse FETCH_HEAD)
  if ! git -C "$repo" merge-base --is-ancestor "$base" "$upstream"; then
    echo "::error::XML/main history changed. Rerun from the current branch tip."
    exit 1
  fi
  if ! git -C "$repo" diff --quiet "$base" "$upstream" -- "${relative_paths[@]}"; then
    echo "::error::XML/main changed a feed being published. Rerun from the current branch tip."
    exit 1
  fi
  if [[ "$attempt" == 5 ]]; then
    break
  fi
  git -C "$repo" -c user.name='github-actions[bot]' \
    -c user.email='github-actions[bot]@users.noreply.github.com' rebase "$upstream"
  sleep "$attempt"
done

echo "::error::Could not push XML changes after 5 attempts."
exit 1
