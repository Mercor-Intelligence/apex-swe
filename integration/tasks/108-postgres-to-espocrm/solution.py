#!/usr/bin/env python3
import os
import base64
import json
import psycopg2
import requests
from typing import List, Tuple, Optional

def get_env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value not in (None, "") else default

DATABASE_URL = get_env('DATABASE_URL', 'postgresql://testuser:testpass@127.0.0.1:5432/testdb')
ESPO_URL = get_env('ESPOCRM_SITE_URL', 'http://espocrm:80')
ESPO_USER = get_env('ESPOCRM_ADMIN_USERNAME', 'admin')
ESPO_PASS = get_env('ESPOCRM_ADMIN_PASSWORD', 'ChangeMe123')

def get_espo_token(base_url: str, username: str, password: str) -> Optional[str]:
    auth_header = base64.b64encode(f"{username}:{password}".encode()).decode()
    resp = requests.get(
        f"{base_url}/api/v1/App/user",
        headers={"Espo-Authorization": auth_header},
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"Failed to get token: HTTP {resp.status_code} - {resp.text}")
        return None
    data = resp.json()
    return data.get('token')

def create_contact(base_url: str, username: str, token: str, first: str, last: str, email: str) -> Optional[dict]:
    token_header = base64.b64encode(f"{username}:{token}".encode()).decode()
    payload = {
        "firstName": first or "",
        "lastName": last or "",
        "emailAddress": email or "",
    }
    resp = requests.post(
        f"{base_url}/api/v1/Contact",
        headers={
            "Espo-Authorization": token_header,
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )
    if resp.status_code == 409:
        print(f"Duplicate detected for email {email}; skipping.")
        return None
    if resp.status_code != 200:
        print(f"Failed to create contact for {email}: HTTP {resp.status_code} - {resp.text}")
        return None
    return resp.json()

def fetch_recent_contacts(base_url: str, username: str, token: str, size: int = 10) -> List[dict]:
    token_header = base64.b64encode(f"{username}:{token}".encode()).decode()
    resp = requests.get(
        f"{base_url}/api/v1/Contact",
        headers={
            "Espo-Authorization": token_header,
            "X-No-Total": "true",
        },
        params={
            "select": "id,firstName,lastName,emailAddress,createdAt",
            "orderBy": "createdAt",
            "order": "desc",
            "offset": 0,
            "maxSize": size,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"Failed to fetch recent contacts: HTTP {resp.status_code} - {resp.text}")
        return []
    data = resp.json()
    return data.get('list', [])

def fetch_recent_users(conn) -> List[Tuple]:
    # Returns rows: (id, first_name, last_name, email, created_at)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, first_name, last_name, email, created_at
            FROM users
            WHERE created_at >= NOW() - INTERVAL '1 hour'
            ORDER BY created_at DESC;
            """
        )
        return cur.fetchall()

def main() -> None:
    try:
        conn = psycopg2.connect(DATABASE_URL)
    except Exception as e:
        print(f"Error connecting to DB: {e}")
        return

    try:
        users = fetch_recent_users(conn)
        print(f"Found {len(users)} new users created in the last hour.")

        token = get_espo_token(ESPO_URL, ESPO_USER, ESPO_PASS)
        if not token:
            return

        created = 0
        for user in users:
            user_id, first_name, last_name, email, created_at = user
            res = create_contact(ESPO_URL, ESPO_USER, token, first_name, last_name, email)
            if res:
                created += 1
                print(
                    f"Created CRM Contact id={res.get('id')} for user_id={user_id} email={email}"
                )

        print(f"Created {created} contact(s).")

        recent = fetch_recent_contacts(ESPO_URL, ESPO_USER, token, size=10)
        print("Recent CRM contacts (up to 10):")
        for c in recent:
            print(
                f"{c.get('id')} | {c.get('firstName')} {c.get('lastName')} | {c.get('emailAddress')} | {c.get('createdAt')}"
            )
    except Exception as e:
        print(f"Error: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass

if __name__ == "__main__":
    main()