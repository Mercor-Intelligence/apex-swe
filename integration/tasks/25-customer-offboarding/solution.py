#!/usr/bin/env python3
import base64
import requests
import sys


def find_and_update_lead():
    """
    Find lead with firstName "John" and lastName "Doe" and update status to "Dead".
    """
    base_url = "http://espocrm"
    username = "admin"
    password = "ChangeMe123"

    # Step 1: Authenticate and get token
    auth_header = base64.b64encode(f"{username}:{password}".encode()).decode()

    try:
        print("Authenticating with EspoCRM...")
        user_response = requests.get(
            f"{base_url}/api/v1/App/user",
            headers={"Espo-Authorization": auth_header},
            timeout=30,
        )

        if user_response.status_code != 200:
            print(f"Failed to authenticate: {user_response.status_code}")
            sys.exit(1)

        user_data = user_response.json()
        if "token" not in user_data:
            print(f"No token in response: {user_data}")
            sys.exit(1)

        token = user_data["token"]
        print("Authentication successful!")

        # Step 2: Create token auth header for subsequent requests
        token_auth_header = base64.b64encode(f"{username}:{token}".encode()).decode()

        # Step 3: Search for lead by firstName "John" and lastName "Doe"
        print("Searching for lead with firstName 'John' and lastName 'Doe'...")
        
        search_params = {
            "where[0][type]": "equals",
            "where[0][attribute]": "firstName",
            "where[0][value]": "John",
            "where[1][type]": "equals",
            "where[1][attribute]": "lastName",
            "where[1][value]": "Doe",
        }
        
        search_response = requests.get(
            f"{base_url}/api/v1/Lead",
            headers={
                "Espo-Authorization": token_auth_header,
                "X-No-Total": "true"
            },
            params=search_params,
            timeout=30,
        )

        if search_response.status_code != 200:
            print(f"Failed to search for lead: {search_response.status_code}")
            sys.exit(1)

        search_data = search_response.json()
        leads_list = search_data.get("list", [])

        if len(leads_list) == 0:
            print("Lead not found")
            sys.exit(1)

        # Use first match if multiple leads found
        lead = leads_list[0]
        lead_id = lead.get("id")
        print(f"Found lead with ID: {lead_id}")

        # Step 4: Update lead status to "Dead"
        print(f"Updating lead status to 'Dead'...")
        
        update_response = requests.put(
            f"{base_url}/api/v1/Lead/{lead_id}",
            headers={
                "Espo-Authorization": token_auth_header,
                "Content-Type": "application/json"
            },
            json={"status": "Dead"},
            timeout=30,
        )

        if update_response.status_code != 200:
            print(f"Failed to update lead: {update_response.status_code}")
            sys.exit(1)

        # Print in required format: "Updated lead {id}: status set to Dead"
        print(f"Updated lead {lead_id}: status set to Dead")
        return True

    except requests.exceptions.RequestException as e:
        print(f"Failed to connect to EspoCRM API: {e}")
        sys.exit(1)


if __name__ == "__main__":
    find_and_update_lead()
