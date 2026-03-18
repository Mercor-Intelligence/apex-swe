# Issue 22
# Topic: Customer Sentiment Sync

## Problem Statement

Search for Zammad ticket by title "Data loss after system update" and analyze the `title` and first article `body` text. Apply simple sentiment rules: if text contains words "bad", "terrible", "awful", "hate" → sentiment="negative", otherwise sentiment="positive". Write output to `/app/ticket_sentiment.txt` with format: "Ticket #{number} sentiment: [sentiment]" using the actual ticket number.
   
   **Tools needed**: Zammad
   
   **Prerequisites**: Zammad ticket with title "Data loss after system update" must exist with title and article body.

---

## Solution

## Objective
Analyze Zammad ticket text and write sentiment result to file.

## Solution Approach

### 1. Search for Ticket

**Search Ticket by Title:**
- Use search API: GET `/api/v1/tickets/search?query=Data loss after system update`
- Fallback: List all tickets and filter by title if search fails
- Extract ticket `id`, `number`, and `title`
- GET articles: `/api/v1/ticket_articles/by_ticket/{ticket_id}`
- Extract first article `body`

### 2. Analyze Sentiment

**Simple Rule-Based Analysis:**
```python
negative_words = ["bad", "terrible", "awful", "hate"]
text = ticket['title'] + " " + first_article['body']
text_lower = text.lower()

sentiment = "positive"  # default
for word in negative_words:
    if word in text_lower:
        sentiment = "negative"
        break
```

### 3. Write Output to File

**File Location:** `/app/ticket_sentiment.txt`

**Format:**
- `"Ticket #{ticket_number} sentiment: {sentiment}"`
- Uses the actual ticket number retrieved from the API

### 4. Solution YAML Structure

```yaml
- command: |
    cat > /app/analyze_sentiment.py << 'EOF'
    #!/usr/bin/env python3
    import requests
    import os
    
    # Fetch ticket
    # Analyze sentiment
    # Write result to /app/ticket_sentiment.txt
    EOF
    chmod +x /app/analyze_sentiment.py

- command: python /app/analyze_sentiment.py
  min_timeout_sec: 30
```

## Key Points
- Search for ticket by title "Data loss after system update"
- Robust search with fallback mechanism (search API → list all tickets)
- Analyze both title and first article body
- Simple keyword matching (case-insensitive)
- Default to positive if no negative words
- Write output to `/app/ticket_sentiment.txt`
- Output format: `Ticket #{ticket_number} sentiment: {sentiment}` (uses actual ticket number)


---

## Tests

### Test 1: `test_ticket_4_exists()`
**Purpose:** Verify prerequisite ticket exists

**Steps:**
1. Search for Zammad ticket by title "Data loss after system update"
2. Assert ticket exists with 'id' and 'title' fields
3. Assert ticket has articles with 'body' field

**Why:** Validates environment setup

---

### Test 2: `test_sentiment_analysis_logic()`
**Purpose:** Verify sentiment analysis logic and output file correctness

**Steps:**
1. Search for ticket by title "Data loss after system update"
2. Get ticket id, number, and title
3. Get first article body
4. Combine title and body, check if contains negative words
5. Calculate expected sentiment (negative if has keywords, positive otherwise)
6. Verify output file `/app/ticket_sentiment.txt` exists
7. Read and validate output file content
8. Assert output contains the correct sentiment
9. Assert output matches exact expected format: `"Ticket #{ticket_number} sentiment: {sentiment}"`
10. Extract and validate ticket number from output
11. Verify ticket number in output matches API response

**Why:** Tests analysis accuracy, validates the sentiment logic matches specification, and ensures output file is written correctly with proper sentiment and ticket number

---

### Test 3: `test_output_file_format()`
**Purpose:** Verify output file format and structure

**Steps:**
1. Check that `/app/ticket_sentiment.txt` exists
2. Read file contents
3. Verify format matches regex pattern `"Ticket #{number} sentiment: (positive|negative)"`
4. Extract sentiment from output using pattern matching
5. Get ticket data from API and calculate expected sentiment
6. Verify sentiment in output matches the actual analysis

**Why:** Validates output file creation, correct format, and that output can be parsed correctly

---

### Test 4: `test_ticket_number_matches_api()`
**Purpose:** Verify ticket number in output matches API response

**Steps:**
1. Get ticket from Zammad API by searching for "Data loss after system update"
2. Extract ticket number from API response
3. Assert ticket has valid 'number' field
4. Read output file `/app/ticket_sentiment.txt`
5. Extract ticket number from output using regex
6. Compare output ticket number with API ticket number
7. Assert they match exactly

**Why:** Ensures that the exact ticket number from the Zammad API is written to the output file, not a hardcoded or incorrect value. Validates dynamic data handling.

---

## Test Principles

- **Content-based validation:** Verify sentiment matches actual text
- **Case-insensitive:** Sentiment detection should work regardless of case
- **Default behavior:** No negative words → positive sentiment
- **File output:** Results must be written to `/app/ticket_sentiment.txt`
- **Output format:** Must match "Ticket #{number} sentiment: (positive|negative)" with actual ticket number
- **Data consistency:** Ticket number and sentiment must match API response and calculated logic

---

## Ticket

```json
{
  "number": 45018,
  "title": "Simple Sentiment Analysis for Single Zammad Ticket",
  "body": "Search for Zammad ticket by title \"Data loss after system update\" and analyze the `title` and first article `body` text. Apply simple sentiment rules: if text contains words \"bad\", \"terrible\", \"awful\", \"hate\" \u2192 sentiment=\"negative\", otherwise sentiment=\"positive\". Write output to `/app/ticket_sentiment.txt` with format: \"Ticket #{number} sentiment: [sentiment]\" using the actual ticket number.\n\n**Prerequisites (already available):**\n- Zammad available via MCP Tools\n- Zammad ticket with title \"Data loss after system update\" already exists with title and article body",
  "state": "open",
  "createdAt": "Oct 22, 2025, 12:00:00 PM",
  "closedAt": "",
  "labels": [
    {
      "name": "component:Sentiment Analysis"
    },
    {
      "name": "type:Integration"
    },
    {
      "name": "tool:Zammad"
    }
  ],
  "assignees": [
    {
      "login": "Software Engineer"
    }
  ],
  "author": null,
  "url": "https://holder-url.com"
}
```
