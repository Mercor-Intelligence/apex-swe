# Issue 7
# Topic: Localstack Order Intake

## Problem Statement

Using Python boto3, insert a hardcoded order into DynamoDB table `orders` (partition key: `orderId`). The order JSON must contain: `{"orderId": "ORD-001", "customerId": "CUST-123", "items": [{"productId": "PROD-A", "quantity": 2, "price": 29.99}], "total": 59.98, "currency": "USD", "status": "pending", "createdAt": "2025-01-15T10:30:00Z"}`. LocalStack endpoint: `http://localhost:4566`. Verify the item exists in DynamoDB.
   
   **Tools needed**: LocalStack (DynamoDB)
   
   **Prerequisites**: DynamoDB table `orders` must exist with schema (partition key: `orderId`).

---

## Solution

# Solution: Task 3 - LocalStack Order Intake

## Objective
Insert a hardcoded order JSON into DynamoDB and verify it exists.

## Solution Approach

### 1. Create Python Script

**Imports:**
- `boto3` for DynamoDB operations
- `json` for pretty printing (optional)

**DynamoDB Client Setup:**
- Configure boto3 DynamoDB client:
  - `endpoint_url='http://localhost:4566'`
  - `region_name='us-east-1'`
  - Dummy credentials

### 2. Define Order Data

**Hardcoded Order:**
```python
order = {
    "orderId": "ORD-001",
    "customerId": "CUST-123",
    "items": [
        {
            "productId": "PROD-A",
            "quantity": 2,
            "price": 29.99
        }
    ],
    "total": 59.98,
    "currency": "USD",
    "status": "pending",
    "createdAt": "2025-01-15T10:30:00Z"
}
```

### 3. Insert into DynamoDB

**Put Item:**
- Use `dynamodb_client.put_item()`:
  - `TableName='orders'`
  - `Item=order` (boto3 will auto-convert to DynamoDB format)
- Print confirmation message

**Note on Data Types:**
- Strings: `{'S': 'value'}`
- Numbers: `{'N': '123'}` (as string)
- Lists: `{'L': [...]}`
- Maps: `{'M': {...}}`
- Or use boto3's high-level resource which auto-converts

### 4. Verify Item Exists

**Get Item:**
- Use `dynamodb_client.get_item()`:
  - `TableName='orders'`
  - `Key={'orderId': {'S': 'ORD-001'}}`
- Assert response contains `Item`
- Print retrieved order details

**Alternative - Scan Table:**
- Use `dynamodb_client.scan(TableName='orders')`
- Check if `ORD-001` is in results

### 5. Solution YAML Structure

```yaml
- command: |
    # Create Python script
    mkdir -p /app
    cat > /app/insert_order.py << 'EOF'
    #!/usr/bin/env python3
    import boto3
    import json
    
    # DynamoDB client setup
    # Order data definition
    # Put item logic
    # Verification logic
    EOF
    chmod +x /app/insert_order.py

- command: python /app/insert_order.py
  min_timeout_sec: 30
```

## Key Points
- Table `orders` must already exist with partition key `orderId`
- Order JSON must match exact specification
- Items list must contain exactly one item with all fields
- Total must equal quantity × price (2 × 29.99 = 59.98)
- Use ISO 8601 format for `createdAt`
- Consider using boto3 resource API (`dynamodb.Table()`) for simpler syntax vs client API
- Print clear confirmation message after insertion


---

## Tests

# Tests: Task 3 - LocalStack Order Intake

## Test Objectives
Verify order was inserted into DynamoDB with correct structure and values.

## Test Functions

### Test 1: `test_dynamodb_table_exists()`
**Purpose:** Verify prerequisite table exists

**Steps:**
1. Create DynamoDB client with LocalStack endpoint
2. Call `dynamodb_client.describe_table(TableName='orders')`
3. Assert no exception raised
4. Verify `KeySchema` contains partition key `orderId`

**Why:** Validates environment setup

---

### Test 2: `test_order_exists_in_dynamodb()`
**Purpose:** Verify order was inserted

**Steps:**
1. Get item: `dynamodb_client.get_item(TableName='orders', Key={'orderId': {'S': 'ORD-001'}})`
2. Assert `'Item'` in response
3. Assert item is not empty

**Why:** Confirms insertion succeeded

---

### Test 3: `test_order_has_correct_fields()`
**Purpose:** Verify all required fields are present

**Steps:**
1. Retrieve order with `orderId='ORD-001'`
2. Extract item from response
3. Assert all required top-level fields exist:
   - `orderId`
   - `customerId`
   - `items`
   - `total`
   - `currency`
   - `status`
   - `createdAt`

**Why:** Ensures complete data structure

---

### Test 4: `test_order_field_values_correct()`
**Purpose:** Verify field values match specification

**Steps:**
1. Retrieve order
2. Parse DynamoDB format to Python types
3. Assert exact values:
   - `orderId` == `"ORD-001"`
   - `customerId` == `"CUST-123"`
   - `total` == `59.98` (or string "59.98")
   - `currency` == `"USD"`
   - `status` == `"pending"`
   - `createdAt` == `"2025-01-15T10:30:00Z"`

**Why:** Validates data accuracy

---

### Test 5: `test_order_items_structure()`
**Purpose:** Verify items array has correct structure

**Steps:**
1. Retrieve order
2. Extract `items` field (DynamoDB List type)
3. Assert items is a list/array
4. Assert length is 1
5. Extract first item
6. Assert item has fields:
   - `productId` == `"PROD-A"`
   - `quantity` == `2`
   - `price` == `29.99`

**Why:** Validates nested structure

---

### Test 6: `test_total_matches_calculation()`
**Purpose:** Verify total is mathematically correct

**Steps:**
1. Retrieve order
2. Extract `items` and `total`
3. Calculate expected total: sum of (quantity × price) for each item
4. Assert calculated total == stored total
5. For single item: `2 × 29.99 = 59.98`

**Why:** Ensures data consistency

---

## Test Principles
- **DynamoDB format handling:** Parse DynamoDB's type-annotated format (`{'S': '...'}`, `{'N': '...'}`)
- **Use resource API in tests:** Simpler than client API for reading data
- **Type checking:** Numbers might be stored as strings or Decimals, handle both
- **Decimal precision:** DynamoDB uses Decimal type, compare with tolerance if needed
- **Complete validation:** Check both presence and values of all fields

---

## Ticket Header

**Project:** E-commerce Platform  
**Issue Type:** Task  
**Priority:** Low  
**Component:** Order Management  
**Labels:** localstack, dynamodb, order-intake, easy  
**Sprint:** Current Sprint  
**Story Points:** 2  

**Summary:** Basic Order Insertion to DynamoDB for Order Management System

## Ticket Content

### Description

Implement a simple Python script to insert order records into our DynamoDB-based order management system. This foundational task establishes the basic data structure for orders and validates our LocalStack DynamoDB setup. The script should insert a predefined order with all necessary fields (order ID, customer info, line items, totals) and verify successful insertion.

### Technical Requirements

**Environment:**
- LocalStack DynamoDB service on `http://localhost:4566`
- Python 3.x with `boto3` library
- DynamoDB table `orders` with partition key `orderId`

### Dependencies

- DynamoDB table `orders` must be pre-created with proper schema
- Order data must follow exact JSON structure with ISO 8601 timestamps
- Total calculation must match item quantities × prices

