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
git add data/news.json data/prices.json data/tr_cache.json
if [ "${WEEKEND:-0}" = "1" ]; then
  echo "== weekend aggregate (for Monday basis) =="
  python3 fetcher/weekend_prep.py || echo "[weekend] prep failed (skip)"
  if [ -f data/weekend_summary.json ]; then git add data/weekend_summary.json; fi
fi
git commit -m "auto fetch news+prices ${STAMP}" || echo "no github changes"
if [ -n "${GITHUB_TOKEN:-}" ]; then
  # default GITHUB_TOKEN (has contents:write) preferred to push GitHub
  GH_PUSH="https://1727277947-arch:${GITHUB_TOKEN}@github.com/1727277947-arch/newsradar-fetch.git"
elif [ -n "${GH_TOKEN:-}" ]; then
  GH_PUSH="https://1727277947-arch:${GH_TOKEN}@github.com/1727277947-arch/newsradar-fetch.git"
else
  GH_PUSH=""
fi

# 并发推送会互相顶掉：体检工作流也会往 main 提交 data/health.json，
# 单发一次 git push 会被 non-fast-forward 直接拒掉（曾出现 09:43 那次丢档）。
# 所以改成“被拒就 fetch+merge 后重试”，冲突时以本轮刚生成的数据为准（-X ours）。
push_github() {
  local tries=4 i=1
  while [ "$i" -le "$tries" ]; do
    if [ -z "$GH_PUSH" ]; then
      git push origin "HEAD:main" && return 0
    else
      git push "$GH_PUSH" "HEAD:main" && return 0
    fi
    echo "[github] push rejected (attempt $i/$tries), syncing with remote before retry..."
    if { [ -n "$GH_PUSH" ] && git fetch "$GH_PUSH" main; } || git fetch origin main; then
      if ! git merge -s recursive -X ours --no-edit FETCH_HEAD; then
        echo "[github] merge failed, aborting merge"
        git merge --abort 2>/dev/null || true
      fi
    fi
    sleep $((i * 5))
    i=$((i + 1))
  done
  return 1
}

if push_github; then
  echo "[github] pushed"
else
  echo "::warning::GitHub 推送重试全部失败；本轮数据只到 Gitee（App 主源仍可用），下一轮会补齐"
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

