# Issue 200
# Topic: Medusa Product Listing

## Problem Statement

Query the Medusa e-commerce API to retrieve all products and print their titles and IDs to stdout. Use the Medusa admin API endpoint `/admin/products` with proper authentication.

**Tools needed**: Medusa

**Prerequisites**: 
- Medusa backend must be running and accessible
- Admin credentials available in connection-info.md

---

## Solution

## Objective
Fetch and display all products from Medusa e-commerce system.

## Solution Approach

### 1. Create Python Script (`/app/list_products.py`)

**Imports:** `requests`, `os`, `sys`

**Environment Variables:**
- `MEDUSA_URL`: Medusa backend URL (default: `http://medusa:9000`)
- `MEDUSA_ADMIN_EMAIL`: Admin email (default: `admin@example.com`)
- `MEDUSA_ADMIN_PASSWORD`: Admin password (default: `supersecret`)

**Medusa Authentication:**
- POST to `/auth/user/emailpass`
- Send JSON payload with email and password
- Get JWT token from response
- Handle multiple token field formats (`token`, `access_token`, or nested in `data`)
- Exit with error if authentication fails or no token received

**List Products:**
- GET to `/admin/products` with Bearer token authorization
- Parse JSON response to extract `products` array
- Handle API errors with proper error messages

**Display Products:**
- Check if products list is empty
- Iterate through products
- Print each product: `Product ID: {id}, Title: {title}`
- Exit with non-zero code on errors

**Error Handling:**
- Authentication failures exit with stderr message
- API request errors caught and reported
- Timeouts configured (30s for auth, 10s for products)
- Proper HTTP status code checking

### 2. Solution YAML

```yaml
- command: python /app/list_products.py
  min_timeout_sec: 30
```

## Key Points
- Simple GET request to list endpoint
- Proper authentication required
- Display product IDs and titles clearly

---

## Tests

## Test Objectives
Verify script retrieves and displays products correctly.

## Test Functions

### Test 1: `test_script_exists()`
**Purpose:** Verify script file exists at expected location

**Steps:**
1. Check if `/app/list_products.py` exists
2. Verify it is a file (not directory)

**Why:** Ensures basic setup is correct

---

### Test 2: `test_script_execution_succeeds()`
**Purpose:** Verify script runs without errors and produces output

**Steps:**
1. Execute `/app/list_products.py` using subprocess
2. Assert exit code is 0
3. Verify stdout is not empty
4. Check output contains "Product ID:" format

**Why:** Tests basic functionality and output format

---

### Test 3: `test_all_products_listed()`
**Purpose:** Verify all products from API are listed

**Steps:**
1. Query Medusa API directly to get all products
2. Execute script and capture output
3. Assert each product ID from API appears in output
4. Assert each product title from API appears in output

**Why:** Validates completeness - ensures no products are missed

---

### Test 4: `test_output_format()`
**Purpose:** Verify output follows correct format

**Steps:**
1. Execute script and capture output
2. Parse each line with regex pattern: `^Product ID: [^,]+, Title: .+$`
3. Assert all non-empty lines match expected format
4. Assert at least one valid product line exists

**Why:** Ensures consistent, parseable output format

---

### Test 5: `test_product_count_matches()`
**Purpose:** Verify product count accuracy

**Steps:**
1. Get expected product count from Medusa API
2. Execute script and parse output
3. Count lines matching product format pattern
4. Assert actual count equals expected count

**Why:** Validates no duplicate or missing products in output

---

## Test Principles
- **API verification:** Direct comparison with API response
- **Output format:** Clear, readable product listing
- **Complete retrieval:** All products must be shown

---

## Ticket

```json
{
  "number": 40200,
  "title": "List All Products from Medusa",
  "body": "Create a Python script to list all products from the Medusa e-commerce backend. The script should authenticate with the admin API and retrieve all products, displaying their IDs and titles.\n\n**Environment:**\n- Medusa backend available at http://medusa:9000 (or use MEDUSA_URL environment variable)\n- Admin credentials available via environment variables:\n  - MEDUSA_ADMIN_EMAIL (default: admin@example.com)\n  - MEDUSA_ADMIN_PASSWORD (default: supersecret)\n- Connection details in data/connection-info.md\n\n**Authentication:**\n1. POST to `/auth/user/emailpass` endpoint\n2. Send JSON payload: `{\"email\": \"<email>\", \"password\": \"<password>\"}`\n3. Extract JWT token from response (check `token`, `access_token`, or `data.token` fields)\n4. Use Bearer token for subsequent API calls\n\n**Fetching Products:**\n1. GET request to `/admin/products` endpoint\n2. Include header: `Authorization: Bearer <token>`\n3. Parse JSON response and extract `products` array\n\n**Output Format:**\n- Print each product on a separate line\n- Format: `Product ID: {id}, Title: {title}`\n- Example: `Product ID: prod_01ABCD, Title: Medusa T-Shirt`\n\n**Error Handling:**\n- Exit with non-zero code and stderr message on authentication failure\n- Exit with non-zero code on API request errors\n- Handle empty product lists gracefully\n- Use appropriate timeouts (30s for auth, 10s for products)\n\n**Prerequisites (already available):**\n- Medusa backend running and accessible\n- Admin authentication configured\n- Python 3 with requests library installed\n\n**Your task:**\nCreate a Python script at /app/list_products.py that:\n1. Authenticates with the Medusa admin API using environment variables\n2. Fetches all products from the /admin/products endpoint\n3. Displays each product's ID and title in the specified format\n4. Handles errors appropriately with proper exit codes\n\n**Resources:**\n- API documentation: data/tool_code_api_docs/medusa_api_doc.md\n- Connection details: data/connection-info.md",
  "state": "open",
  "createdAt": "Nov 1, 2025, 10:00:00 AM",
  "closedAt": "",
  "labels": [
    {
      "name": "type:Task"
    },
    {
      "name": "component:E-commerce"
    },
    {
      "name": "tool:Medusa"
    },
    {
      "name": "difficulty:Easy"
    }
  ],
  "assignees": [
    {
      "login": "Junior Developer"
    }
  ],
  "author": null,
  "url": "https://holder-url.com"
}
```

