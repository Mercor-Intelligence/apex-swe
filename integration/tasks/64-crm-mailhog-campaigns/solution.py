#!/usr/bin/env python3
import base64
import csv
import os
import requests


def fetch_contacts_and_create_csv():
    """Fetch contacts from EspoCRM and create CSV with first 10 contacts that have email addresses."""
    base_url = "http://espocrm"
    username = os.environ.get("ESPOCRM_USERNAME", "admin")
    password = os.environ.get("ESPOCRM_PASSWORD", "ChangeMe123")
    output_csv = "/app/contacts.csv"

    # Step 1: Get authentication token
    auth_header = base64.b64encode(f"{username}:{password}".encode()).decode()

    try:
        # Get user info and token
        print("Authenticating with EspoCRM...")
        user_response = requests.get(
            f"{base_url}/api/v1/App/user",
            headers={"Espo-Authorization": auth_header},
            timeout=30,
        )

        if user_response.status_code != 200:
            print(f"Failed to authenticate: {user_response.status_code} - {user_response.text}")
            return

        user_data = user_response.json()
        if "token" not in user_data:
            print(f"No token in response: {user_data}")
            return

        token = user_data["token"]
        print("Authentication successful!")

        # Step 2: Use token to get all contacts
        token_auth_header = base64.b64encode(f"{username}:{token}".encode()).decode()

        # Call the Contact API with pagination to get all contacts
        page = 0
        size = 200
        all_contacts = []

        print("Fetching contacts...")
        while True:
            contacts_response = requests.get(
                f"{base_url}/api/v1/Contact",
                headers={"Espo-Authorization": token_auth_header, "X-No-Total": "true"},
                params={
                    "select": "id,firstName,lastName,emailAddress,createdAt",
                    "orderBy": "createdAt",
                    "order": "desc",
                    "offset": page * size,
                    "maxSize": size,
                },
                timeout=30,
            )

            if contacts_response.status_code != 200:
                print(f"Failed to get contacts: {contacts_response.status_code} - {contacts_response.text}")
                return

            contacts_data = contacts_response.json()
            contacts_list = contacts_data.get("list", [])

            if len(contacts_list) == 0:
                break

            all_contacts.extend(contacts_list)
            page += 1

        print(f"Fetched {len(all_contacts)} total contacts")

        # Step 3: Filter for contacts with email addresses
        contacts_with_email = [
            contact for contact in all_contacts 
            if contact.get("emailAddress") and contact.get("emailAddress").strip()
        ]

        print(f"Found {len(contacts_with_email)} contacts with email addresses")

        # Step 4: Take first 10 contacts
        first_10_contacts = contacts_with_email[:10]

        if len(first_10_contacts) < 10:
            print(f"Warning: Only found {len(first_10_contacts)} contacts with email addresses (need 10)")

        # Step 5: Create CSV file
        print(f"Creating CSV file at {output_csv}...")
        with open(output_csv, "w", newline="") as csvfile:
            writer = csv.writer(csvfile)
            # Write header
            writer.writerow(["name", "email"])
            
            # Write contact rows
            for contact in first_10_contacts:
                first_name = contact.get("firstName", "")
                last_name = contact.get("lastName", "")
                # Combine first and last name
                full_name = f"{first_name} {last_name}".strip()
                email = contact.get("emailAddress", "")
                
                writer.writerow([full_name, email])

        print(f"Successfully created CSV with {len(first_10_contacts)} contacts at {output_csv}")

    except requests.exceptions.RequestException as e:
        print(f"Failed to connect to EspoCRM API: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    fetch_contacts_and_create_csv()

