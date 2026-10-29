#!/usr/bin/env python3
"""
3X-UI Panel Login Probe:
Read-only verification that the reported panel credentials work. Runs on the
target against the loopback listener; credentials arrive via stdin. It never
resets accounts, passwords or 2FA.
"""

# Static remote script (payload: port, base_path, user, password, host)
REMOTE_PROBE_SCRIPT = r'''
import http.cookiejar, json, ssl, sys, urllib.error, urllib.parse, urllib.request

cfg = json.load(sys.stdin)
ctx = ssl.create_default_context()
ctx.check_hostname = False          # loopback connection to our own panel
ctx.verify_mode = ssl.CERT_NONE


def attempt(scheme):
    base = "%s://127.0.0.1:%d%s" % (scheme, cfg["port"], cfg["base_path"])
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
                                         urllib.request.HTTPSHandler(context=ctx))
    headers = {"User-Agent": "vps-skill-probe", "X-Requested-With": "XMLHttpRequest"}
    if cfg.get("host"):
        headers["Host"] = cfg["host"]

    def call(path, data=None, extra=None):
        req = urllib.request.Request(base + path, data=data, headers=dict(headers, **(extra or {})))
        with opener.open(req, timeout=10) as resp:
            return resp.read().decode("utf-8", "replace")

    call("")  # establishes the session cookie
    token = ""
    try:
        token = json.loads(call("csrf-token")).get("obj") or ""
    except (urllib.error.HTTPError, ValueError):
        pass  # older panels have no CSRF endpoint
    form = {"username": cfg["user"], "password": cfg["password"]}
    if token:
        form["_csrf"] = token
    login = json.loads(call("login", urllib.parse.urlencode(form).encode(),
                            {"Content-Type": "application/x-www-form-urlencoded", "X-CSRF-Token": token}))
    if not login.get("success"):
        return {"ok": False, "scheme": scheme, "stage": "login", "msg": login.get("msg", "")}
    api_ok = False
    try:
        api_ok = bool(json.loads(call("panel/api/inbounds/list")).get("success"))
    except (urllib.error.HTTPError, ValueError):
        pass
    return {"ok": True, "scheme": scheme, "api_verified": api_ok}


errors = []
schemes = ("http", "https") if cfg.get("prefer_http", True) else ("https", "http")
for scheme in schemes:
    try:
        res = attempt(scheme)
    except Exception as exc:
        errors.append("%s: %s" % (scheme, exc))
        continue
    print(json.dumps(res))
    sys.exit(0 if res["ok"] else 1)
print(json.dumps({"ok": False, "stage": "connect", "msg": "; ".join(errors)}))
sys.exit(1)
'''
