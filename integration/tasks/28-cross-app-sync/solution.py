#!/usr/bin/env python3
"""
Solution: Create and run the sync_crm_to_medusa.py script
This solution creates a script that syncs EspoCRM contacts to Medusa customers
"""
import base64
import json
import os
import subprocess
import sys
import requests


def create_sync_script():
    """
    Create the sync_crm_to_medusa.py script that searches for contact by name
    """
    script_content = '''#!/usr/bin/env python3
"""
CRM to Medusa Sync Script
Fetches EspoCRM contact and creates/updates customer in Medusa
"""
import base64
import sys
import requests


def get_espocrm_token():
    """Authenticate with EspoCRM and return the token"""
    base_url = "http://espocrm"
    username = "admin"
    password = "ChangeMe123"
    
    auth_header = base64.b64encode(f"{username}:{password}".encode()).decode()
    
    try:
        response = requests.get(
            f"{base_url}/api/v1/App/user",
            headers={"Espo-Authorization": auth_header},
            timeout=30,
        )
        response.raise_for_status()
        
        user_data = response.json()
        if "token" not in user_data:
            print("Error: Authentication failed - no token in response")
            sys.exit(1)
        
        return user_data["token"]
    except Exception as e:
        print(f"Error: Failed to authenticate with EspoCRM: {e}")
        sys.exit(1)


def search_contact_by_name(token, first_name, last_name):
    """Search for contact by firstName and lastName"""
    base_url = "http://espocrm"
    username = "admin"
    
    token_auth_header = base64.b64encode(f"{username}:{token}".encode()).decode()
    
    search_params = {
        "where[0][type]": "equals",
        "where[0][attribute]": "firstName",
        "where[0][value]": first_name,
        "where[1][type]": "equals",
        "where[1][attribute]": "lastName",
        "where[1][value]": last_name,
    }
    
    try:
        response = requests.get(
            f"{base_url}/api/v1/Contact",
            headers={
                "Espo-Authorization": token_auth_header,
                "X-No-Total": "true"
            },
            params=search_params,
            timeout=30,
        )
        response.raise_for_status()
        
        search_data = response.json()
        contacts = search_data.get("list", [])
        
        if len(contacts) == 0:
            print(f"Error: Contact with firstName='{first_name}' and lastName='{last_name}' not found")
            sys.exit(1)
        
        return contacts[0]
    except Exception as e:
        print(f"Error: Failed to search for contact: {e}")
        sys.exit(1)


def get_medusa_jwt_token():
    """Authenticate with Medusa and get JWT token"""
    medusa_base_url = "http://medusa:9000"
    admin_email = "admin@example.com"
    admin_password = "supersecret"
    
    try:
        response = requests.post(
            f"{medusa_base_url}/auth/user/emailpass",
            json={"email": admin_email, "password": admin_password},
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        response.raise_for_status()
        
        data = response.json()
        token = data.get("token") or data.get("access_token")
        
        if not token:
            print("Error: No token in Medusa auth response")
            sys.exit(1)
        
        return token
    except Exception as e:
        print(f"Error: Failed to authenticate with Medusa: {e}")
        sys.exit(1)


def get_medusa_customer_by_email(email):
    """Check if customer exists in Medusa by email"""
    medusa_base_url = "http://medusa:9000"
    
    try:
        # Get JWT token
        token = get_medusa_jwt_token()
        
        # Search for customer by email
        search_response = requests.get(
            f"{medusa_base_url}/admin/customers",
            params={"q": email},
            headers={"Authorization": f"Bearer {token}"},
            timeout=30
        )
        search_response.raise_for_status()
        
        customers = search_response.json().get("customers", [])
        
        # Find exact email match
        for customer in customers:
            if customer.get("email") == email:
                return customer
        
        return None
    except Exception as e:
        print(f"Error: Failed to search Medusa customers: {e}")
        sys.exit(1)


def create_medusa_customer(first_name, last_name, email):
    """Create a new customer in Medusa"""
    medusa_base_url = "http://medusa:9000"
    
    try:
        # Get JWT token
        token = get_medusa_jwt_token()
        
        # Create customer
        create_response = requests.post(
            f"{medusa_base_url}/admin/customers",
            json={
                "email": email,
                "first_name": first_name,
                "last_name": last_name
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=30
        )
        create_response.raise_for_status()
        
        return create_response.json().get("customer")
    except Exception as e:
        print(f"Error: Failed to create Medusa customer: {e}")
        sys.exit(1)


def update_medusa_customer(customer_id, first_name, last_name, email):
    """Update an existing customer in Medusa"""
    medusa_base_url = "http://medusa:9000"
    
    try:
        # Get JWT token
        token = get_medusa_jwt_token()
        
        # Update customer
        update_response = requests.post(
            f"{medusa_base_url}/admin/customers/{customer_id}",
            json={
                "first_name": first_name,
                "last_name": last_name
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=30
        )
        update_response.raise_for_status()
        
        return update_response.json().get("customer")
    except Exception as e:
        print(f"Error: Failed to update Medusa customer: {e}")
        sys.exit(1)


def main():
    # Get authentication token for EspoCRM
    token = get_espocrm_token()
    
    # Search for contact by name
    contact = search_contact_by_name(token, "Robert", "Williams")
    
    # Extract contact data
    first_name = contact.get("firstName", "")
    last_name = contact.get("lastName", "")
    email = contact.get("emailAddress", "")
    
    if not email:
        print("Error: Contact does not have an email address")
        sys.exit(1)
    
    # Check if customer exists in Medusa
    existing_customer = get_medusa_customer_by_email(email)
    
    if existing_customer:
        # Update existing customer
        update_medusa_customer(existing_customer["id"], first_name, last_name, email)
        action = "updated"
    else:
        # Create new customer
        create_medusa_customer(first_name, last_name, email)
        action = "created"
    
    # Print result
    print(f"Synced customer: {email} - {action} in Medusa")


if __name__ == "__main__":
    main()
'''
    
    # Write the script to /app directory
    script_path = "/app/sync_crm_to_medusa.py"
    
    with open(script_path, 'w') as f:
        f.write(script_content)
    
    # Make it executable
    os.chmod(script_path, 0o755)
    
    print(f"✓ Created sync_crm_to_medusa.py script at {script_path}")
    return script_path


def main():
    """
    Main solution:
    1. Create the sync script that searches by name
    2. Run the script
    """
    print("=== CRM to Medusa Sync Solution ===\\n")
    
    # Step 1: Create the sync script
    print("✓ Creating sync script...")
    script_path = create_sync_script()
    
    # Step 2: Run the sync script
    print(f"=== Running: python {script_path} ===\\n")
    result = subprocess.run(
        ["python", script_path],
        capture_output=True,
        text=True
    )
    
    # Print the script output
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr, file=sys.stderr)
    
    # Check exit code
    if result.returncode != 0:
        print(f"\\n✗ Script exited with code {result.returncode}")
        sys.exit(result.returncode)
    
    print("\\n✓ Solution completed successfully!")


if __name__ == "__main__":
    main()
