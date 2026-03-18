#!/usr/bin/env python3
"""
Oracle solution for listing all products from Medusa e-commerce platform.
This script authenticates with the Medusa admin API and retrieves all products.
"""

import requests
import os
import sys
import shutil


def get_medusa_token():
    """
    Authenticate with Medusa and get JWT token.
    """
    medusa_url = os.environ.get('MEDUSA_URL', 'http://medusa:9000')
    admin_email = os.environ.get('MEDUSA_ADMIN_EMAIL', 'admin@example.com')
    admin_password = os.environ.get('MEDUSA_ADMIN_PASSWORD', 'supersecret')
    
    auth_url = f"{medusa_url}/auth/user/emailpass"
    
    try:
        response = requests.post(
            auth_url,
            json={
                'email': admin_email,
                'password': admin_password
            },
            headers={'Content-Type': 'application/json'},
            timeout=30
        )
        response.raise_for_status()
        
        # Handle different token field formats
        data = response.json()
        token = (
            data.get('token')
            or data.get('access_token')
            or (data.get('data') or {}).get('token')
        )
        
        if not token:
            print("Error: No token in authentication response", file=sys.stderr)
            sys.exit(1)
            
        return token
        
    except requests.exceptions.RequestException as e:
        print(f"Error authenticating with Medusa: {e}", file=sys.stderr)
        sys.exit(1)


def list_products(token):
    """
    Fetch and display all products from Medusa.
    """
    medusa_url = os.environ.get('MEDUSA_URL', 'http://medusa:9000')
    products_url = f"{medusa_url}/admin/products"
    
    headers = {
        'Authorization': f'Bearer {token}'
    }
    
    try:
        response = requests.get(products_url, headers=headers, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        products = data.get('products', [])
        
        if not products:
            print("No products found")
            return
        
        # Display products in the required format
        for product in products:
            product_id = product.get('id')
            product_title = product.get('title')
            print(f"Product ID: {product_id}, Title: {product_title}")
            
    except requests.exceptions.RequestException as e:
        print(f"Error fetching products: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    """
    Main execution function.
    """
    # For oracle mode: copy this script to expected location if not already there
    if __file__ != '/app/list_products.py' and not os.path.exists('/app/list_products.py'):
        os.makedirs('/app', exist_ok=True)
        shutil.copy(__file__, '/app/list_products.py')
    
    # Get authentication token
    token = get_medusa_token()
    
    # List all products
    list_products(token)


if __name__ == "__main__":
    main()
