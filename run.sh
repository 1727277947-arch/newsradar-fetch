#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export TZ=Asia/Shanghai

echo "== fetch news =="
python3 fetcher/clean_fetch.py output/news.json
echo "== fetch prices =="
python3 fetcher/fetch_prices.py output/prices.json

STAMP=$(date '+%Y%m%d-%H%M%S')

echo "== commit + push to github =="
git config user.name "NewsRadarBot"
git config user.email "bot@newsradar.local"
git add -A
git commit -m "auto fetch news+prices ${STAMP}" || echo "no github changes"
if [ -n "${GH_TOKEN:-}" ]; then
  GH_PUSH="https://1727277947-arch:${GH_TOKEN}@github.com/1727277947-arch/newsradar-fetch.git"
  git push "$GH_PUSH" "HEAD:main" || echo "github push failed"
else
  git push || echo "github push (default token) failed"
fi

echo "== push to gitee =="
if [ -z "${GITEE_TOKEN:-}" ]; then
  echo "GITEE_TOKEN not set, skip"
  exit 0
fi
rm -rf _gitee
git clone --depth 1 --branch "$GITEE_BRANCH" "$GITEE_REPO" _gitee
cd _gitee
git config user.name "NewsRadarBot"
git config user.email "bot@newsradar.local"
mkdir -p data
cp ../output/news.json data/news.json
cp ../output/prices.json data/prices.json
git add -A
git commit -m "auto push news+prices ${STAMP}" || echo "no gitee changes"
push_url="https://${GITEE_USER}:${GITEE_TOKEN}@${GITEE_REPO#https://}"
git push "$push_url" "HEAD:$GITEE_BRANCH"
echo "== done =="
