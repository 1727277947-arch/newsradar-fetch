#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export TZ=Asia/Shanghai

echo "== fetch news =="
python3 fetcher/clean_fetch.py output/news.json
echo "== fetch prices =="
python3 fetcher/fetch_prices.py output/prices.json

STAMP=$(date '+%Y%m%d-%H%M%S')

echo "== stage data for github (data/*.json, used by jsDelivr) =="
mkdir -p data
cp output/news.json data/news.json
cp output/prices.json data/prices.json
git config user.name "NewsRadarBot"
git config user.email "bot@newsradar.local"
git add data/news.json data/prices.json
git commit -m "auto fetch news+prices ${STAMP}" || echo "no github changes"
if [ -n "${GITHUB_TOKEN:-}" ]; then
  # default GITHUB_TOKEN (has contents:write) preferred to push GitHub
  git push "https://1727277947-arch:${GITHUB_TOKEN}@github.com/1727277947-arch/newsradar-fetch.git" "HEAD:main" \
    || echo "github push failed (default token)"
elif [ -n "${GH_TOKEN:-}" ]; then
  GH_PUSH="https://1727277947-arch:${GH_TOKEN}@github.com/1727277947-arch/newsradar-fetch.git"
  git push "$GH_PUSH" "HEAD:main" || echo "github push failed (gh_token)"
else
  git push || echo "github push failed (no token)"
fi

echo "== push to gitee =="
if [ -z "${GITEE_TOKEN:-}" ]; then
  echo "GITEE_TOKEN not set, skip"
  exit 0
fi
# Derive user/repo (strip scheme+trailing .git) so we build the kind of token the REST API likes.
GITEE_REPO_PATH="${GITEE_REPO_PATH:-}"
if [ -z "$GITEE_REPO_PATH" ]; then
  # robustly collapse https://gitee.com/user/repo.git -> user/repo
  base="${GITEE_REPO##*/}"
  base="${base%.git}"
  GITEE_REPO_PATH="${GITEE_USER}/${base}"
fi
echo "syncing to gitee repo: $GITEE_REPO_PATH (branch $GITEE_BRANCH)"
# Rate-limit retries happen inside the script; a single API failure must not red X the whole
# workflow after GitHub data already pushed. Non-fatal on retries exhausted.
python3 fetcher/push_gitee_api.py \
  "$GITEE_USER" "$GITEE_TOKEN" "$GITEE_BRANCH" "$GITEE_REPO_PATH" \
  "output/prices.json=data/prices.json" \
  "output/news.json=data/news.json" \
  || echo "[gitee] sync failed (non-fatal), will retry next run"
echo "== done =="

