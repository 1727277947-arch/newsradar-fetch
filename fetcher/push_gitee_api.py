#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""push files to Gitee via REST contents API.
Avoids git clone/commit/push so Gitee HTTP 429 clone-rate-limits never block delivery.
Usage: python3 push_gitee_api.py <gitee_repo> <gitee_user> <gitee_token> <branch> LOCAL_PATH=REMOTE_PATH [...]
Env-independent; fully urllib (no 3rd party deps).
"""
import json, sys, base64, time, urllib.request, urllib.parse

def api(base, repo, path, token, method="GET", body=None):
    url = "https://gitee.com/api/v5/repos/%s/contents/%s" % (repo, path)
    if method == "GET":
        url += "?ref=" + urllib.parse.quote(base)
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", "token " + token)
    req.add_header("User-Agent", "newsradar-bot")
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        req.data = data
        req.add_header("Content-Type", "application/json;charset=utf-8")
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            code = e.code
            if code == 429 and attempt < 3:
                time.sleep(6 * (attempt + 1))
                continue
            try:
                err = e.read().decode("utf-8")
            except Exception:
                err = ""
            return {"__http_error": code, "__detail": err}
        except Exception as ex:
            if attempt < 3:
                time.sleep(3 * (attempt + 1))
                continue
            return {"__http_error": "net", "__detail": str(ex)}
    return {"__http_error": "net", "__detail": "retries exhausted"}

def main():
    if len(sys.argv) < 5:
        sys.exit("usage: push_gitee_api.py <user> <token> <branch> <repo_path> LOCAL=REMOTE ...")
    user, token, branch, repo = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    bindings = []
    for a in sys.argv[5:]:
        if "=" not in a:
            sys.exit("bad binding: " + a)
        lp, rp = a.split("=", 1)
        bindings.append((lp, rp))
    messages = []
    for lp, rp in bindings:
        with open(lp, "rb") as f:
            content_raw = f.read()
        b64 = base64.b64encode(content_raw).decode("ascii")
        cur = api(branch, repo, rp, token)
        cur_sha = cur.get("sha") if isinstance(cur, dict) else None
        body = {
            "branch": branch,
            "message": "auto push " + rp,
            "content": b64,
            "encoding": "base64",
        }
        # strip newlines inside base64; gitee accepts standard trailing newline possibly
        body["content"] = b64
        if cur_sha:
            body["sha"] = cur_sha
        res = api(branch, repo, rp, token, method="PUT", body=body)
        if isinstance(res, dict) and res.get("__http_error"):
            messages.append("FAIL %s %s: %s" % (rp, res["__http_error"], res.get("__detail") or ""))
        else:
            messages.append("OK   %s -> sha %s" % (rp, (res.get("content") or {}).get("sha") or "?"))
        time.sleep(1)
    print("\n".join(messages))
    if any(m.startswith("FAIL") for m in messages):
        sys.exit(2)

if __name__ == "__main__":
    main()
