#!/usr/bin/env bash

set -euo pipefail

repo_root="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "Not inside a Git repository." >&2
  exit 1
}

cd "$repo_root"

branch="$(git symbolic-ref --quiet --short HEAD)" || {
  echo "Cannot create a release from a detached HEAD." >&2
  exit 1
}

if [[ "$branch" != "main" ]]; then
  echo "Releases must be created from main, not ${branch}." >&2
  exit 1
fi

if ! git diff --quiet || ! git diff --cached --quiet ||
   [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
  echo "Commit or remove working-tree changes before creating a release." >&2
  exit 1
fi

git remote get-url origin >/dev/null 2>&1 || {
  echo "Git remote 'origin' does not exist." >&2
  exit 1
}

# Année et semaine ISO depuis les outils locaux.
# %G = année correspondant à la semaine ISO
# %V = numéro de semaine ISO, de 01 à 53
year="$(date +%G)"
week_raw="$(date +%V)"

if [[ ! "$year" =~ ^[0-9]{4}$ ]] ||
   [[ ! "$week_raw" =~ ^(0[1-9]|[1-4][0-9]|5[0-3])$ ]]; then
  echo "Unable to determine the current ISO year and week." >&2
  exit 1
fi

# Supprime le zéro initial : 08 devient 8.
week="$((10#$week_raw))"

local_tags="$(git tag --list)"

remote_tags="$(
  git ls-remote --tags --refs origin |
    awk '{
      sub(/^refs\/tags\//, "", $2)
      print $2
    }'
)"

max_id=0

while IFS= read -r existing_tag; do
  [[ -z "$existing_tag" ]] && continue

  if [[ "$existing_tag" =~ ^${year}\.${week}\.([1-9][0-9]*)$ ]]; then
    current_id="$((10#${BASH_REMATCH[1]}))"

    if (( current_id > max_id )); then
      max_id="$current_id"
    fi
  fi
done < <(
  printf '%s\n%s\n%s\n' "$local_tags" "$remote_tags" "$(cat VERSION 2>/dev/null || true)" |
    sort -u
)

next_id=$((max_id + 1))
tag="${year}.${week}.${next_id}"

if git rev-parse --quiet --verify "refs/tags/${tag}" >/dev/null; then
  echo "Tag ${tag} already exists locally." >&2
  exit 1
fi

echo "Creating release ${tag} from branch ${branch}."

printf '%s\n' "$tag" > VERSION

git add -A
git commit -m "Release ${tag}"
git tag -a "$tag" -m "Release ${tag}"

git push --atomic \
  origin \
  "HEAD:refs/heads/${branch}" \
  "refs/tags/${tag}"

echo "Release ${tag} pushed to origin from branch ${branch}."
