"""Read-only GitHub ingestion with hard caps and an in-process cache.

No git binary, no clone, no writes: only public read endpoints (plus the optional
server-side token for rate limit headroom).
"""
from __future__ import annotations

import re
import threading
import time
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .. import config
from ..analysis import taxonomy
from ..security import clamp_text, clean_one_line

API = "https://api.github.com"
CACHE_TTL_SECONDS = 900
MAX_BODY_CHARS = 4000


class GitHubError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


_cache: Dict[str, Tuple[float, Any]] = {}
_cache_lock = threading.Lock()


def _cache_get(key: str) -> Optional[Any]:
    with _cache_lock:
        entry = _cache.get(key)
        if not entry:
            return None
        if time.time() - entry[0] > CACHE_TTL_SECONDS:
            del _cache[key]
            return None
        return entry[1]


def _cache_set(key: str, value: Any) -> None:
    with _cache_lock:
        if len(_cache) > 200:
            _cache.clear()
        _cache[key] = (time.time(), value)


def parse_repo_url(raw: str) -> Tuple[str, str]:
    """Accept https://github.com/o/r(.git), github.com/o/r, or o/r."""
    value = (raw or "").strip()
    if not value:
        raise GitHubError("Enter a public GitHub repository URL, or load the sample project.")
    value = re.sub(r"^https?://", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^www\.", "", value, flags=re.IGNORECASE)
    if value.lower().startswith("github.com/"):
        value = value[len("github.com/") :]
    value = value.split("?")[0].split("#")[0].strip("/")
    value = re.sub(r"\.git$", "", value, flags=re.IGNORECASE)
    match = re.match(r"^([A-Za-z0-9_.-]{1,39})/([A-Za-z0-9_.-]{1,100})$", value)
    if not match:
        raise GitHubError("That does not look like a repo. Use the form https://github.com/owner/repo.")
    return match.group(1), match.group(2)


def _headers() -> Dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "handover-lens/1.0",
    }
    if config.GITHUB_TOKEN:
        headers["Authorization"] = "Bearer %s" % config.GITHUB_TOKEN
    return headers


def _get(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    url = API + path
    cache_key = url + "|" + repr(sorted((params or {}).items()))
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    try:
        with httpx.Client(timeout=config.GITHUB_TIMEOUT_SECONDS, headers=_headers()) as client:
            response = client.get(url, params=params)
    except httpx.TimeoutException:
        raise GitHubError("GitHub did not respond in %ds. Try again, or use the sample project." % config.GITHUB_TIMEOUT_SECONDS, 504)
    except httpx.HTTPError as exc:
        raise GitHubError("Could not reach GitHub (%s)." % exc.__class__.__name__, 502)

    if response.status_code == 404:
        raise GitHubError("Repository not found, or it is private. Only public repos can be read.", 404)
    if response.status_code in (401, 403):
        reset = response.headers.get("x-ratelimit-reset")
        wait_hint = ""
        if reset and reset.isdigit():
            wait_minutes = max(0, int((int(reset) - time.time()) / 60))
            wait_hint = " Resets in about %d min." % wait_minutes
        if not config.GITHUB_TOKEN:
            raise GitHubError(
                "GitHub's anonymous limit (60 requests/hour) is used up.%s "
                "The server owner can set GITHUB_TOKEN for 5,000/hour, or you can use the sample project." % wait_hint,
                429,
            )
        raise GitHubError("GitHub rejected the request (HTTP %d).%s" % (response.status_code, wait_hint), 502)
    if response.status_code >= 500:
        raise GitHubError("GitHub is having trouble (HTTP %d). Try again shortly." % response.status_code, 502)
    if response.status_code >= 400:
        raise GitHubError("GitHub request failed (HTTP %d)." % response.status_code, 502)

    try:
        payload = response.json()
    except ValueError:
        raise GitHubError("GitHub returned an unreadable response.", 502)
    _cache_set(cache_key, payload)
    return payload


def _slug(name: str) -> str:
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _matches_leaver(login: Optional[str], name: Optional[str], leaver_name: str, leaver_email: str) -> bool:
    target_name = (leaver_name or "").strip().lower()
    target_slug = _slug(target_name)
    login_lower = (login or "").lower()
    name_lower = (name or "").lower()
    if not target_name:
        return False
    if target_slug and (target_slug == login_lower or target_slug in _slug(name_lower)):
        return True
    if target_name and target_name in name_lower:
        return True
    if leaver_email and leaver_email.lower() in (name or "").lower():
        return True
    return False


def fetch_repo_evidence(
    repo_input: str,
    leaver_name: str,
    leaver_email: str,
    window_start: Optional[str],
    window_end: Optional[str],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], List[str]]:
    owner, repo = parse_repo_url(repo_input)
    full_name = "%s/%s" % (owner, repo)
    warnings: List[str] = []
    items: List[Dict[str, Any]] = []

    meta_repo = _get("/repos/%s/%s" % (owner, repo))
    default_branch = str(meta_repo.get("default_branch") or "main")

    params: Dict[str, Any] = {"per_page": 100}
    if window_start:
        params["since"] = window_start
    if window_end:
        params["until"] = window_end

    commits: List[Dict[str, Any]] = []
    page = 1
    while len(commits) < config.GITHUB_MAX_COMMITS and page <= 4:
        batch = _get("/repos/%s/%s/commits" % (owner, repo), dict(params, page=page))
        if not isinstance(batch, list) or not batch:
            break
        commits.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    commits = commits[: config.GITHUB_MAX_COMMITS]

    detail_budget = config.GITHUB_MAX_COMMIT_DETAIL if config.GITHUB_TOKEN else 0
    if not config.GITHUB_TOKEN:
        warnings.append(
            "No GitHub token on the server: commit file detail and review history were skipped "
            "to stay inside the anonymous rate limit."
        )

    for index, commit in enumerate(commits):
        sha = str(commit.get("sha") or "")
        if not sha:
            continue
        author_info = (commit.get("commit") or {}).get("author") or {}
        author_name = author_info.get("name")
        login = (commit.get("author") or {}).get("login") if isinstance(commit.get("author"), dict) else None
        files: List[str] = []
        if index < detail_budget:
            try:
                detail = _get("/repos/%s/%s/commits/%s" % (owner, repo, sha))
                files = [str(f.get("filename") or "") for f in (detail.get("files") or [])][:25]
            except GitHubError:
                files = []
        message = str((commit.get("commit") or {}).get("message") or sha)
        items.append(
            {
                "source_type": "git_commit",
                "source_label": full_name,
                "external_id": sha[:12],
                "title": clean_one_line(message.splitlines()[0] if message else sha, 160),
                "body": clamp_text(message, MAX_BODY_CHARS),
                "author": author_name or login or "unknown",
                "occurred_at": ((commit.get("commit") or {}).get("author") or {}).get("date"),
                "url": commit.get("html_url"),
                "areas": taxonomy.infer_areas(message, files),
                "metadata": {"sha": sha, "login": login, "files": files},
            }
        )

    pulls: List[Dict[str, Any]] = []
    try:
        pulls = _get(
            "/repos/%s/%s/pulls" % (owner, repo),
            {"state": "all", "sort": "updated", "direction": "desc", "per_page": 100},
        )
    except GitHubError as exc:
        warnings.append("Pull requests were not read: %s" % exc.message)
    if not isinstance(pulls, list):
        pulls = []
    pulls = pulls[: config.GITHUB_MAX_PULLS]

    for pull in pulls:
        number = pull.get("number")
        title = str(pull.get("title") or "")
        body = clamp_text(pull.get("body") or "", MAX_BODY_CHARS)
        labels = [str((label or {}).get("name") or "") for label in (pull.get("labels") or [])]
        state = str(pull.get("state") or "open")
        if pull.get("merged_at"):
            state = "merged"
        items.append(
            {
                "source_type": "pull_request",
                "source_label": full_name,
                "external_id": "PR #%s" % number,
                "title": clean_one_line(title, 160),
                "body": body,
                "author": ((pull.get("user") or {}).get("login") or "unknown"),
                "occurred_at": pull.get("created_at"),
                "url": pull.get("html_url"),
                "areas": taxonomy.infer_areas("%s %s" % (title, " ".join(labels))),
                "metadata": {
                    "number": number,
                    "state": state,
                    "labels": labels,
                    "branch": (pull.get("head") or {}).get("ref"),
                    "base": (pull.get("base") or {}).get("ref"),
                },
            }
        )

    reviews_read = 0
    if config.GITHUB_TOKEN:
        for pull in pulls[:20]:
            number = pull.get("number")
            if not number:
                continue
            try:
                reviews = _get("/repos/%s/%s/pulls/%s/reviews" % (owner, repo, number))
            except GitHubError:
                continue
            if not isinstance(reviews, list):
                continue
            for review in reviews:
                reviewer = ((review.get("user") or {}).get("login")) or ""
                body = clamp_text(review.get("body") or "", 1200)
                if not reviewer or not body:
                    continue
                reviews_read += 1
                items.append(
                    {
                        "source_type": "review",
                        "source_label": full_name,
                        "external_id": "review:%s:%s" % (number, review.get("id")),
                        "title": clean_one_line("Review on PR #%s: %s" % (number, review.get("state") or ""), 160),
                        "body": body,
                        "author": reviewer,
                        "occurred_at": review.get("submitted_at"),
                        "url": "%s/pull/%s" % (str(pull.get("html_url") or "").rstrip("/"), number),
                        "areas": taxonomy.infer_areas("%s %s" % (str(pull.get("title") or ""), body)),
                        "metadata": {"pr": number, "state": review.get("state")},
                    }
                )
        if reviews_read:
            warnings.append("Read %d review comments from the 20 most recent pull requests." % reviews_read)

    issues: List[Dict[str, Any]] = []
    try:
        issues = _get(
            "/repos/%s/%s/issues" % (owner, repo),
            {"state": "all", "sort": "updated", "direction": "desc", "per_page": 60},
        )
    except GitHubError as exc:
        warnings.append("Issues were not read: %s" % exc.message)
    if not isinstance(issues, list):
        issues = []

    for issue in issues[:60]:
        if isinstance(issue, dict) and issue.get("pull_request"):
            continue
        assignees = [str((a or {}).get("login") or "") for a in (issue.get("assignees") or [])]
        items.append(
            {
                "source_type": "issue",
                "source_label": full_name,
                "external_id": "Issue #%s" % issue.get("number"),
                "title": clean_one_line(str(issue.get("title") or ""), 160),
                "body": clamp_text(issue.get("body") or "", MAX_BODY_CHARS),
                "author": ((issue.get("user") or {}).get("login") or "unknown"),
                "occurred_at": issue.get("created_at"),
                "url": issue.get("html_url"),
                "areas": taxonomy.infer_areas("%s %s" % (str(issue.get("title") or ""), " ".join(assignees))),
                "metadata": {
                    "number": issue.get("number"),
                    "state": issue.get("state"),
                    "assignees": assignees,
                    "labels": [str((l or {}).get("name") or "") for l in (issue.get("labels") or [])],
                },
            }
        )

    try:
        tree = _get("/repos/%s/%s/git/trees/%s" % (owner, repo, default_branch), {"recursive": "1"})
        entries = tree.get("tree") if isinstance(tree, dict) else None
        if isinstance(entries, list):
            paths = [str(e.get("path") or "") for e in entries if e.get("type") == "blob"][:3000]
            doc_paths = [p for p in paths if taxonomy.areas_from_paths([p]) == ["docs"]][:40]
            top_dirs = sorted({p.split("/")[0] for p in paths if "/" in p})[:30]
            items.append(
                {
                    "source_type": "document",
                    "source_label": full_name,
                    "external_id": "tree:%s" % default_branch,
                    "title": "Repository structure snapshot (%s)" % default_branch,
                    "body": "Top-level directories: %s\nDocumentation files: %s"
                    % (", ".join(top_dirs) or "none", ", ".join(doc_paths) or "none found"),
                    "author": None,
                    "occurred_at": None,
                    "url": "%s/tree/%s" % (str(meta_repo.get("html_url") or "").rstrip("/"), default_branch),
                    "areas": taxonomy.areas_from_paths(paths),
                    "metadata": {"parser": "tree", "file_count": len(paths), "doc_files": doc_paths},
                }
            )
        if not (tree.get("tree") if isinstance(tree, dict) else None):
            warnings.append("Repository file tree was empty; documentation coverage may be under-reported.")
    except GitHubError as exc:
        warnings.append("Repository tree was not read: %s" % exc.message)

    meta = {
        "repo_full_name": full_name,
        "default_branch": default_branch,
        "description": clean_one_line(meta_repo.get("description") or "", 240),
        "stars": meta_repo.get("stargazers_count"),
        "language": meta_repo.get("language"),
        "commits_read": len(commits),
        "pulls_read": len(pulls),
        "reviews_read": reviews_read,
        "has_token": bool(config.GITHUB_TOKEN),
    }

    if not items:
        raise GitHubError(
            "No commits, pull requests or issues came back for %s in that window. Widen the dates or use the sample project."
            % full_name,
            422,
        )

    matched = [
        item
        for item in items
        if _matches_leaver(
            (item.get("metadata") or {}).get("login") or item.get("author"),
            item.get("author"),
            leaver_name,
            leaver_email,
        )
    ]
    if leaver_name and not matched:
        warnings.append(
            "No activity matched \"%s\" as an author. Ownership and open work will be thin — check the spelling "
            "of the leaver or the date window." % leaver_name
        )
        meta["leaver_matched"] = False
    else:
        meta["leaver_matched"] = True
    meta["leaver_activity"] = len(matched)

    return items, meta, warnings
