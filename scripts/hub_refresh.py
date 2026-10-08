"""Refresh the auto-generated sections of this repo's README.

Reads hub.json, then:
  * pulls the newest matching papers from the public arXiv API, and
  * pulls the most-starred, recently active GitHub repositories for each
    code section from the GitHub search API.
Each result list is written between its START/END markers in README.md.
Standard library only. Set GITHUB_TOKEN for a higher API rate limit.
"""
import datetime as dt
import json
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ATOM = {"a": "http://www.w3.org/2005/Atom"}
UA = {"User-Agent": "DatariusAI-hub-refresh"}


def get(url, headers=None):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read()


def clean(text):
    text = " ".join((text or "").split())
    return text.replace("|", "-").replace("[", "(").replace("]", ")")


def arxiv_rows(query, n):
    params = urllib.parse.urlencode({
        "search_query": query, "sortBy": "submittedDate",
        "sortOrder": "descending", "max_results": n,
    })
    root = ET.fromstring(get("https://export.arxiv.org/api/query?" + params))
    rows = []
    for e in root.findall("a:entry", ATOM):
        title = clean(e.find("a:title", ATOM).text)
        link = re.sub(r"v\d+$", "", e.find("a:id", ATOM).text.strip()).replace("http://", "https://")
        date = e.find("a:published", ATOM).text[:10]
        names = [a.find("a:name", ATOM).text for a in e.findall("a:author", ATOM)]
        who = (names[0] + (" et al." if len(names) > 1 else "")) if names else ""
        rows.append(f"| {date} | [{title}]({link}) | {clean(who)} |")
    if not rows:
        return None
    return "| Date | Paper | Authors |\n|---|---|---|\n" + "\n".join(rows)


def github_rows(queries, n, since_days):
    token = os.environ.get("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    since = (dt.date.today() - dt.timedelta(days=since_days)).isoformat()
    seen, items = set(), []
    for q in queries:
        params = urllib.parse.urlencode({
            "q": f"{q} pushed:>{since} archived:false",
            "sort": "stars", "order": "desc", "per_page": n,
        })
        try:
            data = json.loads(get("https://api.github.com/search/repositories?" + params, headers))
        except Exception as exc:  # keep going if one query fails
            print("search failed:", q, exc)
            continue
        for it in data.get("items", []):
            if it["full_name"] not in seen:
                seen.add(it["full_name"])
                items.append(it)
        time.sleep(3)  # stay well inside the search rate limit
    items.sort(key=lambda it: it["stargazers_count"], reverse=True)
    rows = []
    for it in items[:n]:
        desc = clean(it.get("description") or "")[:140]
        lang = it.get("language") or ""
        rows.append(
            f"| [{it['full_name']}]({it['html_url']}) | {desc} | {lang} "
            f"| {it['stargazers_count']:,} | {it['pushed_at'][:10]} |"
        )
    if not rows:
        return None
    return ("| Repository | What it is | Language | Stars | Last update |\n"
            "|---|---|---|---|---|\n" + "\n".join(rows))


def replace_block(text, key, body):
    pattern = rf"(<!-- {key}:START -->).*?(<!-- {key}:END -->)"
    return re.sub(pattern, lambda m: m.group(1) + "\n" + body + "\n" + m.group(2), text, flags=re.S)


def main():
    cfg = json.load(open("hub.json", encoding="utf-8"))
    text = open("README.md", encoding="utf-8").read()
    original = text

    try:
        body = arxiv_rows(cfg["arxiv_query"], cfg.get("arxiv_max", 8))
        if body:
            text = replace_block(text, "ARXIV", body)
    except Exception as exc:
        print("arXiv failed:", exc)

    for sec in cfg.get("code_sections", []):
        body = github_rows(sec["queries"], cfg.get("repos_per_section", 6), cfg.get("since_days", 365))
        if body:
            text = replace_block(text, sec["key"], body)

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    text = replace_block(text, "STAMP", f"_Last refreshed: {stamp}_")

    if text != original:
        open("README.md", "w", encoding="utf-8").write(text)
        print("README updated")
    else:
        print("No change")


if __name__ == "__main__":
    main()
