#!/usr/bin/env python3
"""
Create an API token with ALL permissions in EspoCRM.

It will:
  - Log in as admin using Espo-Authorization (username:password -> token).
  - Build a Role that grants the most permissive allowed level for every ACL-enabled scope/action.
  - Create (or reuse) an active API user, attach the Role, and add the 'Global' team if it exists.
  - Generate (or reuse) an API key.
  - Verify the key by hitting /api/v1/Contact?select=id&maxSize=1
  - Print the API key.

ENV (override as needed):
  ESPOCRM_SITE_URL           e.g. https://crm.example.com
  ESPOCRM_ADMIN_USERNAME     e.g. admin
  ESPOCRM_ADMIN_PASSWORD     e.g. ChangeMe123
  ESPOCRM_ROLE_NAME          (optional) default: api-all-permissions
  ESPOCRM_API_USERNAME       (optional) default: integration-bot
"""

import os, time, base64, requests, sys

# ---------- config ----------
SITE = os.environ.get("ESPOCRM_SITE_URL", "http://espocrm:80").rstrip("/")
ADMIN_USER = os.environ.get("ESPOCRM_ADMIN_USERNAME", "admin")
ADMIN_PASS = os.environ.get("ESPOCRM_ADMIN_PASSWORD", "ChangeMe123")
ROLE_NAME  = os.environ.get("ESPOCRM_ROLE_NAME", "api-all-permissions")
API_USERNAME = os.environ.get("ESPOCRM_API_USERNAME", "integration-bot")

# ---------- tiny utils ----------
def b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()

def h_user_pass(u: str, p: str):
    return {"Espo-Authorization": b64(f"{u}:{p}"), "Accept": "application/json"}

def h_user_token(u: str, t: str):
    return {"Espo-Authorization": b64(f"{u}:{t}"), "Accept": "application/json"}

def get_json(r: requests.Response):
    try:
        return r.json()
    except Exception:
        raise RuntimeError(f"Non-JSON response ({r.status_code}): {r.text[:400]}")

def req_get(url, headers, **kw):
    r = requests.get(url, headers=headers, timeout=30, **kw)
    if r.status_code >= 400:
        raise RuntimeError(f"GET {url} -> {r.status_code}: {r.text[:400]}")
    return get_json(r)

def req_post(url, headers, json):
    r = requests.post(url, headers=headers, json=json, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"POST {url} -> {r.status_code}: {r.text[:400]}")
    return get_json(r)

# ---------- auth ----------
def get_admin_token() -> str:
    url = f"{SITE}/api/v1/App/user"
    r = requests.get(url, headers=h_user_pass(ADMIN_USER, ADMIN_PASS), timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"Admin auth failed: {r.status_code} {r.text[:400]}")
    token = get_json(r).get("token")
    if not token:
        raise RuntimeError("No token returned by App/user")
    return token

# ---------- role helpers ----------
def find_role_id(h, name: str):
    url = f"{SITE}/api/v1/Role"
    params = {
        "select": "id",
        "where[0][type]": "equals",
        "where[0][attribute]": "name",
        "where[0][value]": name,
        "maxSize": 1,
    }
    r = requests.get(url, headers=h, params=params, timeout=30)
    if r.status_code == 200:
        items = get_json(r).get("list", [])
        if items:
            return items[0]["id"]
    return None

def build_all_perms_role_payload(h):
    # Pull ACL metadata to know what actions/levels are legal per scope
    acl_defs   = req_get(f"{SITE}/api/v1/Metadata?key=aclDefs", h)
    scopes     = req_get(f"{SITE}/api/v1/Metadata?key=scopes", h)
    role_fields= req_get(f"{SITE}/api/v1/Metadata?key=entityDefs.Role.fields", h)

    role_data = {}
    for scope, acl_def in acl_defs.items():
        sm = scopes.get(scope, {})
        if sm.get("acl") in [False, "boolean"]:
            continue

        actions = sm.get("aclActionList", acl_def.get("aclActionList", []))
        level_map = sm.get("aclActionLevelListMap", {})
        default_levels = sm.get("aclLevelList", ["yes","all","team","own","no"])

        scope_perms = {}
        for action in actions:
            levels = level_map.get(action, default_levels)
            # choose the most permissive that actually exists for this action
            # read/edit/delete prefer 'all', create prefers 'yes' if present (Espo semantics)
            prefs = ("all","yes","team","own") if action != "create" else ("yes","all","team","own")
            chosen = next((p for p in prefs if p in levels), None)
            scope_perms[action] = chosen or "no"

        if scope_perms:
            role_data[scope] = scope_perms

    # Special permissions: pick most permissive existing option
    desired = {
        "assignmentPermission": ["all","team","no"],
        "userPermission": ["all","team","no"],
        "messagePermission": ["all","team","no"],
        "portalPermission": ["yes","no"],
        "groupEmailAccountPermission": ["all","team","no"],
        "exportPermission": ["yes","no"],
        "massUpdatePermission": ["yes","no"],
        "dataPrivacyPermission": ["yes","no"],
        "followerManagementPermission": ["all","team","no"],
        "auditPermission": ["yes","no"],
        "mentionPermission": ["all","team","no"],
        "userCalendarPermission": ["all","team","no"],
    }
    special = {}
    for field, prefs in desired.items():
        if field in role_fields:
            opts = role_fields[field].get("options", [])
            for p in prefs:
                if p in opts:
                    special[field] = p
                    break

    payload = {
        "name": ROLE_NAME,
        "isActive": True,
        "data": role_data,
        **special,
    }
    return payload

def ensure_all_role(h) -> str:
    rid = find_role_id(h, ROLE_NAME)
    if rid:
        print(f"[role] Reusing role '{ROLE_NAME}' -> {rid}")
        return rid

    print(f"[role] Creating '{ROLE_NAME}' with all-permissions across ACL-enabled scopes …")
    payload = build_all_perms_role_payload(h)
    role = req_post(f"{SITE}/api/v1/Role", h, payload)
    rid = role.get("id")
    if not rid:
        raise RuntimeError("Role creation returned no id")
    print(f"[role] Created -> {rid}")
    return rid

# ---------- team helpers ----------
def find_global_team_id(h):
    r = requests.get(
        f"{SITE}/api/v1/Team",
        headers=h,
        params={"select": "id", "where[0][type]":"equals","where[0][attribute]":"name","where[0][value]":"Global","maxSize":1},
        timeout=30
    )
    if r.status_code == 200:
        items = get_json(r).get("list", [])
        if items:
            return items[0]["id"]
    return None

def add_user_to_team(h, user_id: str, team_id: str):
    # Link team: POST /User/{id}/teams with {"id": team_id}
    r = requests.post(f"{SITE}/api/v1/User/{user_id}/teams", headers=h, json={"id": team_id}, timeout=30)
    if r.status_code not in (200, 204):
        raise RuntimeError(f"Adding user to team failed: {r.status_code} {r.text[:200]}")

# ---------- user helpers ----------
def find_user(h, username: str):
    r = requests.get(
        f"{SITE}/api/v1/User",
        headers=h,
        params={
            "select": "id,userName,isActive,type,authMethod,apiKey,rolesIds,teamsIds",
            "where[0][type]":"equals","where[0][attribute]":"userName","where[0][value]":username,
            "maxSize": 1
        },
        timeout=30
    )
    if r.status_code == 200:
        items = get_json(r).get("list", [])
        if items:
            return items[0]
    return None

def ensure_api_user(h, role_id: str) -> dict:
    user = find_user(h, API_USERNAME)
    if user:
        print(f"[user] Reusing API user '{API_USERNAME}' -> {user['id']}")
        # ensure active and has role; (lightweight update omitted—assume OK if present)
        return user

    payload = {
        "userName": API_USERNAME,
        "type": "api",
        "authMethod": "ApiKey",
        "isActive": True,
        "rolesIds": [role_id],
    }
    print(f"[user] Creating API user '{API_USERNAME}' …")
    created = req_post(f"{SITE}/api/v1/User", h, payload)
    if "id" not in created:
        raise RuntimeError("API user creation returned no id")
    print(f"[user] Created -> {created['id']}")
    return created

def ensure_api_key(h, user_id: str) -> str:
    # try existing
    u = req_get(f"{SITE}/api/v1/User/{user_id}?select=apiKey", h)
    key = u.get("apiKey")
    if key:
        return key
    # generate
    print("[user] Generating API key …")
    g = req_post(f"{SITE}/api/v1/User/{user_id}/action/generateApiKey", h, {})
    key = g.get("apiKey")
    if not key:
        u2 = req_get(f"{SITE}/api/v1/User/{user_id}?select=apiKey", h)
        key = u2.get("apiKey")
    if not key:
        raise RuntimeError("Failed to generate API key")
    return key

# ---------- verification ----------
def verify_key(api_key: str):
    # Minimal call; if this 403s, it’s either role/team/active/HTTPS issue.
    r = requests.get(
        f"{SITE}/api/v1/Contact",
        headers={"X-Api-Key": api_key, "Accept": "application/json", "X-No-Total": "true"},
        params={"select": "id", "maxSize": 1},
        timeout=30
    )
    print(f"[verify] GET /Contact -> {r.status_code}")
    if r.status_code >= 400:
        raise RuntimeError(f"Verification failed: {r.status_code} {r.text[:300]}")

# ---------- main ----------
def main():
    print(f"[init] base={SITE}")
    token = get_admin_token()
    h = h_user_token(ADMIN_USER, token)

    role_id = ensure_all_role(h)
    user = ensure_api_user(h, role_id)

    # Add to Global team if it exists (improves visibility if team security is used)
    gtid = find_global_team_id(h)
    if gtid:
        teams = (user.get("teamsIds") or [])
        if gtid not in teams:
            print("[team] Adding API user to 'Global' team …")
            add_user_to_team(h, user["id"], gtid)

    api_key = ensure_api_key(h, user["id"])
    print("[ok] API key is ready.")
    verify_key(api_key)

    print("\n=== SUCCESS ===")
    print("API Username:", API_USERNAME)
    print("API Key:     ", api_key)
    print("Use it like:  curl -H \"X-Api-Key: <API_KEY>\" \"%s/api/v1/Contact?select=id,firstName,lastName&maxSize=1\"" % SITE)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n[ERROR] {e}")
        print("Hints:")
        print(" - Ensure ESPOCRM_SITE_URL is your public HTTPS URL (behind a TLS proxy, HTTP can 403).")
        print(" - Make sure the API user is active and has the role created above.")
        print(" - If your data uses team security, adding the API user to 'Global' (done above) helps.")
        sys.exit(1)
