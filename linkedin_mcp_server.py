#!/usr/bin/env python3
"""
LinkedIn Official REST API MCP Server for Antigravity.
Supports creating, editing/altering (PARTIAL_UPDATE), deleting, and tracking posts,
plus uploading images and interactive OAuth 2.0 / Token setup.
Zero external dependencies (Python stdlib only).
"""
import http.server
import json
import mimetypes
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

CONFIG_DIR = os.path.expanduser("~/.gemini/config")
CREDS_FILE = os.path.join(CONFIG_DIR, "linkedin_credentials.json")
HISTORY_FILE = os.path.join(CONFIG_DIR, "linkedin_posts_history.json")
DEFAULT_API_VERSION = os.environ.get("LINKEDIN_API_VERSION", "202604")
REDIRECT_PORT = 8765
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"


def log(msg: str) -> None:
    sys.stderr.write(f"[LinkedIn-MCP] {msg}\n")
    sys.stderr.flush()


def escape_little_text(text: str) -> str:
    """Escape reserved LinkedIn Little Text Format characters while preserving @[Name](urn:li:...) and {hashtag|#|...}."""
    return re.sub(
        r"(@\[[^\]]+\]\(urn:li:[^)]+\)|\{hashtag\|[#＃]\|[^}]+\})|([\\|{}@\[\]()<>*_~])",
        lambda m: m.group(1) if m.group(1) else "\\" + m.group(2),
        text,
    )


def load_creds() -> dict:
    creds = {}
    if os.path.exists(CREDS_FILE):
        try:
            with open(CREDS_FILE, "r", encoding="utf-8") as f:
                creds = json.load(f)
        except Exception as e:
            log(f"Warning: could not read {CREDS_FILE}: {e}")
    for key, env_name in [
        ("access_token", "LINKEDIN_ACCESS_TOKEN"),
        ("client_id", "LINKEDIN_CLIENT_ID"),
        ("client_secret", "LINKEDIN_CLIENT_SECRET"),
        ("person_urn", "LINKEDIN_PERSON_URN"),
        ("api_version", "LINKEDIN_API_VERSION"),
    ]:
        val = os.environ.get(env_name, "").strip()
        if val:
            creds[key] = val
    return creds


def save_creds(updates: dict) -> dict:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    creds = load_creds()
    creds.update({k: v for k, v in updates.items() if v is not None})
    creds["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(CREDS_FILE, "w", encoding="utf-8") as f:
        json.dump(creds, f, indent=2)
    try:
        os.chmod(CREDS_FILE, 0o600)
    except OSError:
        pass
    return creds


def load_history() -> list:
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception:
            return []
    return []


def save_history(entries: list) -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(entries[:100], f, indent=2)


def record_post_event(post_urn: str, commentary: str, visibility: str, status: str) -> dict:
    entries = load_history()
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    url = f"https://www.linkedin.com/feed/update/{post_urn}/"
    for item in entries:
        if item.get("post_urn") == post_urn:
            if commentary:
                item["commentary"] = commentary
            if visibility:
                item["visibility"] = visibility
            item["status"] = status
            item["updated_at"] = now
            save_history(entries)
            return item
    entry = {
        "post_urn": post_urn,
        "url": url,
        "commentary": commentary,
        "visibility": visibility,
        "status": status,
        "created_at": now,
        "updated_at": now,
    }
    entries.insert(0, entry)
    save_history(entries)
    return entry


def resolve_post_urn(identifier: str) -> str:
    ident = (identifier or "").strip()
    if not ident or ident.lower() in ("latest", "last"):
        for item in load_history():
            if item.get("status") != "DELETED" and item.get("post_urn"):
                return item["post_urn"]
        raise ValueError("No recent post found in local history. Please pass the post URN (e.g. urn:li:share:...) or post URL.")
    unquoted = urllib.parse.unquote(ident)
    match = re.search(r"(urn:li:(?:share|ugcPost|activity):\d+)", unquoted)
    if match:
        return match.group(1)
    if ident.isdigit():
        return f"urn:li:share:{ident}"
    return ident


def api_request(method: str, url: str, token: str, payload: dict = None, extra_headers: dict = None) -> tuple[int, dict, str]:
    creds = load_creds()
    version = creds.get("api_version") or DEFAULT_API_VERSION
    headers = {
        "Authorization": f"Bearer {token}",
        "Linkedin-Version": version,
        "X-Restli-Protocol-Version": "2.0.0",
    }
    if extra_headers:
        headers.update(extra_headers)
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            resp_headers = {k.lower(): v for k, v in resp.headers.items()}
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, resp_headers, body
    except urllib.error.HTTPError as e:
        resp_headers = {k.lower(): v for k, v in e.headers.items()} if e.headers else {}
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LinkedIn API HTTP {e.code}: {body}") from e


def fetch_userinfo(token: str) -> dict:
    req = urllib.request.Request(
        "https://api.linkedin.com/v2/userinfo",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Failed to verify token via /v2/userinfo (HTTP {e.code}): {body}") from e


def ensure_auth() -> tuple[str, str]:
    creds = load_creds()
    token = creds.get("access_token", "").strip()
    if not token:
        raise RuntimeError(
            "LinkedIn access token not configured yet. Run `linkedin_configure_credentials` with your access_token "
            "(or client_id + client_secret with start_oauth=true)."
        )
    person_urn = creds.get("person_urn", "").strip()
    if not person_urn:
        info = fetch_userinfo(token)
        sub = info.get("sub")
        if not sub:
            raise RuntimeError(f"Could not determine member 'sub' from /v2/userinfo response: {info}")
        person_urn = f"urn:li:person:{sub}"
        save_creds({
            "person_urn": person_urn,
            "name": info.get("name"),
            "email": info.get("email"),
        })
    return token, person_urn


def upload_image(token: str, owner_urn: str, image_path: str) -> str:
    abs_path = os.path.expanduser(image_path)
    if not os.path.isfile(abs_path):
        raise FileNotFoundError(f"Image file not found: {abs_path}")
    _, _, body = api_request(
        "POST",
        "https://api.linkedin.com/rest/images?action=initializeUpload",
        token,
        payload={"initializeUploadRequest": {"owner": owner_urn}},
    )
    val = json.loads(body).get("value", {})
    upload_url = val.get("uploadUrl")
    image_urn = val.get("image")
    if not upload_url or not image_urn:
        raise RuntimeError(f"Unexpected initializeUpload response: {body}")
    mime_type, _ = mimetypes.guess_type(abs_path)
    with open(abs_path, "rb") as f:
        raw_bytes = f.read()
    put_req = urllib.request.Request(
        upload_url,
        data=raw_bytes,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": mime_type or "application/octet-stream",
        },
        method="PUT",
    )
    with urllib.request.urlopen(put_req, timeout=60) as resp:
        if resp.status not in (200, 201):
            raise RuntimeError(f"Image binary upload failed with HTTP {resp.status}")
    return image_urn


def run_interactive_oauth(client_id: str, client_secret: str, open_browser: bool = True) -> dict:
    state = str(int(time.time()))
    params = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "state": state,
        "scope": "openid profile email w_member_social",
    })
    auth_url = f"https://www.linkedin.com/oauth/v2/authorization?{params}"
    captured = {}

    class CallbackHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/start":
                self.send_response(302)
                self.send_header("Location", auth_url)
                self.end_headers()
                return
            qs = urllib.parse.parse_qs(parsed.query)
            if "code" in qs:
                captured["code"] = qs["code"][0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    b"<html><body style='font-family:sans-serif;padding:2rem;'>"
                    b"<h2>&#9989; LinkedIn Connected to Antigravity!</h2>"
                    b"<p>You can close this tab and return to Antigravity.</p></body></html>"
                )
            else:
                err = qs.get("error_description", qs.get("error", ["Waiting for authorization..."]))[0]
                self.send_response(400)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    f"<html><body style='font-family:sans-serif;padding:2rem;'>"
                    f"<h2>OAuth Notice</h2><p>{err}</p>"
                    f"<p><a href='/start'>Click here to try again</a> after enabling both Products and adding the Redirect URL.</p>"
                    f"</body></html>".encode("utf-8")
                )

        def log_message(self, format, *args):
            return

    http.server.HTTPServer.allow_reuse_address = True
    server = http.server.HTTPServer(("127.0.0.1", REDIRECT_PORT), CallbackHandler)
    server.timeout = 3600
    if open_browser:
        log(f"Opening browser for LinkedIn OAuth: {auth_url}")
        webbrowser.open(auth_url)
    deadline = time.time() + 3600
    while "code" not in captured and time.time() < deadline:
        server.handle_request()
    server.server_close()

    if "code" not in captured:
        raise RuntimeError(f"Timed out waiting for OAuth callback on {REDIRECT_URI}. Authorize at: {auth_url}")

    token_data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": captured["code"],
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": REDIRECT_URI,
    }).encode("utf-8")
    token_req = urllib.request.Request(
        "https://www.linkedin.com/oauth/v2/accessToken",
        data=token_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(token_req, timeout=15) as resp:
        tok_json = json.loads(resp.read().decode("utf-8"))

    access_token = tok_json["access_token"]
    info = fetch_userinfo(access_token)
    person_urn = f"urn:li:person:{info['sub']}"
    return save_creds({
        "client_id": client_id,
        "client_secret": client_secret,
        "access_token": access_token,
        "refresh_token": tok_json.get("refresh_token"),
        "expires_in": tok_json.get("expires_in"),
        "person_urn": person_urn,
        "name": info.get("name"),
        "email": info.get("email"),
    })


def handle_tools_list() -> dict:
    return {
        "tools": [
            {
                "name": "linkedin_configure_credentials",
                "description": (
                    "Save LinkedIn API credentials (access_token, or client_id + client_secret for browser OAuth) "
                    "to ~/.gemini/config/linkedin_credentials.json and verify connection."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "access_token": {
                            "type": "string",
                            "description": "LinkedIn OAuth 2.0 Access Token (with openid, profile, w_member_social scopes).",
                        },
                        "person_urn": {
                            "type": "string",
                            "description": "Optional author URN (e.g. urn:li:person:ABC123). Auto-detected via /v2/userinfo if omitted.",
                        },
                        "client_id": {
                            "type": "string",
                            "description": "Optional LinkedIn App Client ID (used if start_oauth=true).",
                        },
                        "client_secret": {
                            "type": "string",
                            "description": "Optional LinkedIn App Client Secret (used if start_oauth=true).",
                        },
                        "start_oauth": {
                            "type": "boolean",
                            "description": "If true, opens browser OAuth flow listening on http://localhost:8765/callback.",
                            "default": False,
                        },
                    },
                },
            },
            {
                "name": "linkedin_get_profile",
                "description": "Verify LinkedIn connection status and get authenticated member profile details and person_urn.",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "linkedin_create_post",
                "description": "Publish a new post on LinkedIn (text, link/article preview, or local image upload).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "commentary": {
                            "type": "string",
                            "description": "The text body of the LinkedIn post. Hashtags (#tag) and newlines are supported.",
                        },
                        "visibility": {
                            "type": "string",
                            "enum": ["PUBLIC", "CONNECTIONS"],
                            "default": "PUBLIC",
                            "description": "Who can see the post: PUBLIC or CONNECTIONS.",
                        },
                        "article_url": {
                            "type": "string",
                            "description": "Optional external URL to attach as an article/link preview card.",
                        },
                        "article_title": {
                            "type": "string",
                            "description": "Optional title for the attached article/link preview card.",
                        },
                        "article_description": {
                            "type": "string",
                            "description": "Optional description for the attached article/link preview card.",
                        },
                        "image_path": {
                            "type": "string",
                            "description": "Optional local file path to an image (PNG/JPG) to upload and attach to the post.",
                        },
                        "image_alt_text": {
                            "type": "string",
                            "description": "Optional accessibility alt-text for the uploaded image.",
                        },
                        "is_draft": {
                            "type": "boolean",
                            "default": False,
                            "description": "If true, creates the post in DRAFT lifecycleState instead of PUBLISHED.",
                        },
                        "author_urn": {
                            "type": "string",
                            "description": "Optional author URN override, e.g. 'urn:li:organization:123456' for a Company Page (requires w_organization_social scope) or defaults to your personal urn:li:person:...",
                        },
                    },
                    "required": ["commentary"],
                },
            },
            {
                "name": "linkedin_edit_post",
                "description": "Alter/edit the text commentary of an existing LinkedIn post via PARTIAL_UPDATE.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "post_urn": {
                            "type": "string",
                            "description": "The post URN (e.g. urn:li:share:123...), full LinkedIn post URL, or 'latest' for the last post you published.",
                        },
                        "commentary": {
                            "type": "string",
                            "description": "The updated full text commentary for the post.",
                        },
                    },
                    "required": ["post_urn", "commentary"],
                },
            },
            {
                "name": "linkedin_delete_post",
                "description": "Delete an existing LinkedIn post by its URN, post URL, or 'latest'.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "post_urn": {
                            "type": "string",
                            "description": "The post URN (e.g. urn:li:share:123...), full LinkedIn post URL, or 'latest'.",
                        },
                    },
                    "required": ["post_urn"],
                },
            },
            {
                "name": "linkedin_list_posts",
                "description": "List your LinkedIn posts tracked in local history (including URNs and direct URLs) or fetch a specific post by URN.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "post_urn": {
                            "type": "string",
                            "description": "Optional specific post URN to query from LinkedIn API.",
                        },
                        "limit": {
                            "type": "integer",
                            "default": 20,
                            "description": "Maximum number of tracked posts to return.",
                        },
                    },
                },
            },
            {
                "name": "linkedin_publish_ship_log",
                "description": (
                    "Zero-Touch Commit/MR Ship Log: fetches your latest merged upstream GitLab MRs & diff stats, "
                    "renders a 1200x630 dark-mode engineering telemetry card PNG, uploads it via /rest/images, "
                    "and publishes a LinkedIn Ship Log post tagging @[HRL International Private Limited]."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "mr_count": {
                            "type": "integer",
                            "default": 5,
                            "description": "Number of recent merged GitLab MRs to include in the Ship Log card.",
                        },
                        "custom_headline": {
                            "type": "string",
                            "description": "Optional headline for the Ship Log card and post.",
                        },
                        "output_image_path": {
                            "type": "string",
                            "description": "Optional local path to save the rendered PNG card.",
                        },
                        "theme": {
                            "type": "string",
                            "enum": ["gitlab-orange", "hrl-rose"],
                            "default": "gitlab-orange",
                            "description": "Color theme for the HRL Light-Theme card (defaults to 'gitlab-orange' for GitLab posts).",
                        },
                    },
                },
            },
        ]
    }


def render_ship_log_card(mrs_data: list, headline: str, out_path: str, theme_name: str = "gitlab-orange") -> str:
    sys.path.insert(0, "/Users/pavankumars/.gemini/antigravity/scratch/HRL-X-Linkedin-Post-Image")
    from hrl_post_image_generator import render_hrl_post_image
    return render_hrl_post_image(mrs_data=mrs_data, headline=headline, out_path=out_path, theme_name=theme_name)


def handle_tool_call(name: str, args: dict) -> dict:
    try:
        if name == "linkedin_configure_credentials":
            if args.get("start_oauth"):
                cid = (args.get("client_id") or load_creds().get("client_id") or "").strip()
                csec = (args.get("client_secret") or load_creds().get("client_secret") or "").strip()
                if not cid or not csec:
                    raise ValueError("Both client_id and client_secret are required when start_oauth=true.")
                saved = run_interactive_oauth(cid, csec)
                return {
                    "content": [{
                        "type": "text",
                        "text": json.dumps({
                            "status": "connected_via_oauth",
                            "name": saved.get("name"),
                            "email": saved.get("email"),
                            "person_urn": saved.get("person_urn"),
                            "credentials_file": CREDS_FILE,
                        }, indent=2),
                    }]
                }

            updates = {}
            for k in ("access_token", "person_urn", "client_id", "client_secret"):
                if args.get(k):
                    updates[k] = args[k].strip()
            saved = save_creds(updates)
            if saved.get("access_token"):
                info = fetch_userinfo(saved["access_token"])
                person_urn = saved.get("person_urn") or f"urn:li:person:{info.get('sub')}"
                saved = save_creds({
                    "person_urn": person_urn,
                    "name": info.get("name"),
                    "email": info.get("email"),
                })
                return {
                    "content": [{
                        "type": "text",
                        "text": json.dumps({
                            "status": "connected",
                            "name": saved.get("name"),
                            "email": saved.get("email"),
                            "person_urn": saved.get("person_urn"),
                            "credentials_file": CREDS_FILE,
                        }, indent=2),
                    }]
                }
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps({"status": "saved_partial_credentials", "credentials_file": CREDS_FILE}, indent=2),
                }]
            }

        if name == "linkedin_get_profile":
            token, person_urn = ensure_auth()
            info = fetch_userinfo(token)
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps({
                        "status": "authenticated",
                        "person_urn": person_urn,
                        "name": info.get("name"),
                        "email": info.get("email"),
                        "picture": info.get("picture"),
                        "locale": info.get("locale"),
                    }, indent=2),
                }]
            }

        if name == "linkedin_create_post":
            token, person_urn = ensure_auth()
            author_override = (args.get("author_urn") or "").strip()
            if author_override.isdigit():
                author_override = f"urn:li:organization:{author_override}"
            author_urn = author_override or person_urn
            raw_commentary = args.get("commentary", "")
            visibility = args.get("visibility", "PUBLIC")
            lifecycle = "DRAFT" if args.get("is_draft") else "PUBLISHED"

            payload = {
                "author": author_urn,
                "commentary": escape_little_text(raw_commentary),
                "visibility": visibility,
                "distribution": {
                    "feedDistribution": "MAIN_FEED",
                    "targetEntities": [],
                    "thirdPartyDistributionChannels": [],
                },
                "lifecycleState": lifecycle,
                "isReshareDisabledByAuthor": False,
            }

            if args.get("image_path"):
                image_urn = upload_image(token, author_urn, args["image_path"])
                media_obj = {"id": image_urn}
                if args.get("image_alt_text"):
                    media_obj["altText"] = args["image_alt_text"]
                payload["content"] = {"media": media_obj}
            elif args.get("article_url"):
                article = {
                    "source": args["article_url"],
                    "title": args.get("article_title") or args["article_url"],
                }
                if args.get("article_description"):
                    article["description"] = args["article_description"]
                payload["content"] = {"article": article}

            status_code, headers, body = api_request(
                "POST",
                "https://api.linkedin.com/rest/posts",
                token,
                payload=payload,
            )
            post_urn = headers.get("x-restli-id") or headers.get("x-linkedin-id") or ""
            entry = record_post_event(post_urn, raw_commentary, visibility, lifecycle)
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps({
                        "status": "created",
                        "http_status": status_code,
                        "post_urn": post_urn,
                        "url": entry.get("url"),
                        "visibility": visibility,
                        "lifecycleState": lifecycle,
                        "commentary": raw_commentary,
                    }, indent=2),
                }]
            }

        if name == "linkedin_edit_post":
            token, _ = ensure_auth()
            post_urn = resolve_post_urn(args.get("post_urn", "latest"))
            raw_commentary = args.get("commentary", "")
            encoded_urn = urllib.parse.quote(post_urn, safe="")
            patch_payload = {
                "patch": {
                    "$set": {
                        "commentary": escape_little_text(raw_commentary),
                    }
                }
            }
            status_code, _, _ = api_request(
                "POST",
                f"https://api.linkedin.com/rest/posts/{encoded_urn}",
                token,
                payload=patch_payload,
                extra_headers={"X-RestLi-Method": "PARTIAL_UPDATE"},
            )
            entry = record_post_event(post_urn, raw_commentary, "", "UPDATED")
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps({
                        "status": "updated",
                        "http_status": status_code,
                        "post_urn": post_urn,
                        "url": entry.get("url"),
                        "updated_commentary": raw_commentary,
                    }, indent=2),
                }]
            }

        if name == "linkedin_delete_post":
            token, _ = ensure_auth()
            post_urn = resolve_post_urn(args.get("post_urn", "latest"))
            encoded_urn = urllib.parse.quote(post_urn, safe="")
            status_code, _, _ = api_request(
                "DELETE",
                f"https://api.linkedin.com/rest/posts/{encoded_urn}",
                token,
            )
            record_post_event(post_urn, "", "", "DELETED")
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps({
                        "status": "deleted",
                        "http_status": status_code,
                        "post_urn": post_urn,
                    }, indent=2),
                }]
            }

        if name == "linkedin_list_posts":
            limit = int(args.get("limit", 20))
            entries = load_history()[:limit]
            remote_post = None
            if args.get("post_urn"):
                token, _ = ensure_auth()
                urn = resolve_post_urn(args["post_urn"])
                encoded_urn = urllib.parse.quote(urn, safe="")
                try:
                    _, _, body = api_request("GET", f"https://api.linkedin.com/rest/posts/{encoded_urn}", token)
                    remote_post = json.loads(body) if body else None
                except Exception as e:
                    remote_post = {"note": str(e)}
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps({
                        "tracked_posts_count": len(entries),
                        "tracked_posts": entries,
                        "remote_post": remote_post,
                    }, indent=2),
                }]
            }

        if name == "linkedin_publish_ship_log":
            token, person_urn = ensure_auth()
            creds = load_creds()
            org_urn = creds.get("organization_urn", "urn:li:organization:143684970")
            org_name = creds.get("organization_name", "HRL International Private Limited")
            mr_count = min(max(int(args.get("mr_count", 5)), 1), 5)

            gl_token = os.environ.get("GITLAB_PERSONAL_ACCESS_TOKEN", "").strip()
            if not gl_token:
                mcp_cfg_path = os.path.join(CONFIG_DIR, "mcp_config.json")
                if os.path.exists(mcp_cfg_path):
                    with open(mcp_cfg_path, "r", encoding="utf-8") as f:
                        gl_token = (
                            json.load(f)
                            .get("mcpServers", {})
                            .get("gitlab", {})
                            .get("env", {})
                            .get("GITLAB_PERSONAL_ACCESS_TOKEN", "")
                        )
            if not gl_token:
                raise RuntimeError("GITLAB_PERSONAL_ACCESS_TOKEN not found in env or mcp_config.json")

            gl_req = urllib.request.Request(
                f"https://gitlab.com/api/v4/merge_requests?scope=created_by_me&state=merged&per_page={mr_count}&order_by=updated_at",
                headers={"PRIVATE-TOKEN": gl_token},
            )
            mrs = json.loads(urllib.request.urlopen(gl_req, timeout=15).read().decode("utf-8"))
            mrs_data = []
            for mr in mrs[:mr_count]:
                pid = mr["project_id"]
                iid = mr["iid"]
                ch_req = urllib.request.Request(
                    f"https://gitlab.com/api/v4/projects/{pid}/merge_requests/{iid}/changes",
                    headers={"PRIVATE-TOKEN": gl_token},
                )
                ch = json.loads(urllib.request.urlopen(ch_req, timeout=15).read().decode("utf-8"))
                changes = ch.get("changes", [])
                files = [c.get("new_path", "") for c in changes]
                add = sum(c.get("diff", "").count("\n+") for c in changes)
                rem = sum(c.get("diff", "").count("\n-") for c in changes)
                full_ref = mr["references"]["full"]
                repo_short = full_ref.split("!")[0]
                mrs_data.append({
                    "ref": full_ref,
                    "repo": repo_short,
                    "iid_str": f"!{iid}",
                    "title": mr["title"],
                    "url": mr["web_url"],
                    "sha": (mr.get("merge_commit_sha") or mr.get("sha") or "")[:8],
                    "add": add,
                    "rem": rem,
                    "files_count": len(files),
                    "primary_file": files[0] if files else "",
                })

            headline = args.get("custom_headline") or "Upstream GitLab Merge Train — Ship Log"
            out_img = os.path.expanduser(args.get("output_image_path") or os.path.join(CONFIG_DIR, "hrl_upstream_ship_log.png"))
            render_ship_log_card(mrs_data, headline, out_img, theme_name=args.get("theme", "gitlab-orange"))

            bullets = "\n".join(
                f"- {m['ref']} ({m['sha']}): {m['title']} [+{m['add']}/-{m['rem']} LOC]"
                for m in mrs_data
            )
            links = "\n".join(f"• {m['iid_str']}: {m['url']}" for m in mrs_data)
            total_add = sum(m["add"] for m in mrs_data)
            total_rem = sum(m["rem"] for m in mrs_data)
            total_files = sum(m["files_count"] for m in mrs_data)

            raw_commentary = (
                f"Upstream Engineering Ship Log at @[{org_name}]({org_urn})!\n\n"
                f"Auto-generated directly from our live GitLab API + Antigravity LinkedIn MCP pipeline — "
                f"{len(mrs_data)} upstream Merge Requests shipped across gitlab-org (+{total_add} / -{total_rem} LOC across {total_files} files):\n\n"
                f"{bullets}\n\n"
                f"Upstream Merge Requests:\n{links}\n\n"
                f"Follow @[{org_name}]({org_urn}) for more autonomous open-source & systems engineering!\n\n"
                f"#HRLInternational #GitLab #OpenSource #MCP #Antigravity #RubyOnRails #Python #TypeScript #AIAgents"
            )

            image_urn = upload_image(token, person_urn, out_img)
            payload = {
                "author": person_urn,
                "commentary": escape_little_text(raw_commentary),
                "visibility": "PUBLIC",
                "distribution": {
                    "feedDistribution": "MAIN_FEED",
                    "targetEntities": [],
                    "thirdPartyDistributionChannels": [],
                },
                "content": {
                    "media": {
                        "id": image_urn,
                        "altText": f"{headline} — {len(mrs_data)} merged upstream GitLab MRs",
                    }
                },
                "lifecycleState": "PUBLISHED",
                "isReshareDisabledByAuthor": False,
            }
            status_code, headers, _ = api_request("POST", "https://api.linkedin.com/rest/posts", token, payload=payload)
            post_urn = headers.get("x-restli-id") or headers.get("x-linkedin-id") or ""
            entry = record_post_event(post_urn, raw_commentary, "PUBLIC", "PUBLISHED")
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps({
                        "status": "ship_log_published",
                        "http_status": status_code,
                        "post_urn": post_urn,
                        "image_urn": image_urn,
                        "image_path": out_img,
                        "url": entry.get("url"),
                        "mrs_included": mrs_data,
                    }, indent=2),
                }]
            }

        return {"isError": True, "content": [{"type": "text", "text": f"Unknown tool: {name}"}]}
    except Exception as e:
        return {"isError": True, "content": [{"type": "text", "text": f"Error: {e}"}]}


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        # Non-trivial logic self-check (Little Text escaping + URN resolution)
        sample = "Hello (world)! Check [this] & @[Jane](urn:li:person:123) #ai *bold*"
        escaped = escape_little_text(sample)
        assert escaped == r"Hello \(world\)! Check \[this\] & @[Jane](urn:li:person:123) #ai \*bold\*", f"Got: {escaped}"
        assert resolve_post_urn("https://www.linkedin.com/feed/update/urn%3Ali%3Ashare%3A7123456789/") == "urn:li:share:7123456789"
        assert len(handle_tools_list()["tools"]) == 7
        print("SELF_TEST_OK")
        return

    if len(sys.argv) > 1 and sys.argv[1] in ("--auth", "--auth-listen"):
        creds = load_creds()
        cid = creds.get("client_id") or input("LinkedIn Client ID: ").strip()
        csec = creds.get("client_secret") or input("LinkedIn Client Secret: ").strip()
        saved = run_interactive_oauth(cid, csec, open_browser=(sys.argv[1] == "--auth"))
        print(json.dumps({"status": "authenticated", "name": saved.get("name"), "person_urn": saved.get("person_urn")}, indent=2))
        return

    log("LinkedIn MCP Server initialized over stdio JSON-RPC.")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            req_id = msg.get("id")
            method = msg.get("method")

            if method == "initialize":
                res = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "linkedin-mcp", "version": "1.0.0"},
                    },
                }
            elif method == "tools/list":
                res = {"jsonrpc": "2.0", "id": req_id, "result": handle_tools_list()}
            elif method == "tools/call":
                params = msg.get("params", {})
                res = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": handle_tool_call(params.get("name", ""), params.get("arguments", {})),
                }
            elif method == "notifications/initialized":
                continue
            else:
                res = {"jsonrpc": "2.0", "id": req_id, "result": {}}

            sys.stdout.write(json.dumps(res) + "\n")
            sys.stdout.flush()
        except Exception as e:
            log(f"Error handling message: {e}")


if __name__ == "__main__":
    main()
