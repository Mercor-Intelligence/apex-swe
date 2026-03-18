#!/usr/bin/env python3
"""
Sentiment Analysis for Zammad Ticket
Analyzes ticket for sentiment and writes result to /app/ticket_sentiment.txt.
"""

import os
import requests
from typing import Dict, Any, List

# Zammad connection details from environment
ZAMMAD_BASE_URL = os.environ.get('ZAMMAD_BASE_URL', 'http://zammad:8080')
ZAMMAD_USERNAME = os.environ.get('ZAMMAD_USERNAME', 'admin@example.com')
ZAMMAD_PASSWORD = os.environ.get('ZAMMAD_PASSWORD', 'StrongPassw0rd@()')

# Sentiment keywords (as specified in task)
NEGATIVE_WORDS = ["bad", "terrible", "awful", "hate"]

class ZammadClient:
    """Client for interacting with Zammad API."""
    
    def __init__(self):
        self.base_url = ZAMMAD_BASE_URL
        self.auth = (ZAMMAD_USERNAME, ZAMMAD_PASSWORD)
        self.session = requests.Session()
        self.session.auth = self.auth
    
    def search_ticket_by_title(self, title_query: str) -> Dict[str, Any]:
        """Search for a ticket by title."""
        # Try search API first
        url = f"{self.base_url}/api/v1/tickets/search"
        params = {'query': title_query, 'limit': 10}
        
        try:
            response = self.session.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            # Handle different response formats
            tickets = []
            if isinstance(data, dict):
                tickets = data.get('tickets', [])
                if not tickets and 'assets' in data and 'Ticket' in data['assets']:
                    tickets = list(data['assets']['Ticket'].values())
            elif isinstance(data, list):
                tickets = data
            
            if tickets:
                return tickets[0]
        except Exception:
            pass
        
        # Fallback: list all tickets and search by title
        try:
            url = f"{self.base_url}/api/v1/tickets"
            response = self.session.get(url)
            response.raise_for_status()
            all_tickets = response.json()
            
            # Search for ticket with matching title (case-insensitive)
            for ticket in all_tickets:
                if isinstance(ticket, dict):
                    ticket_title = ticket.get('title', '').lower()
                    if title_query.lower() in ticket_title:
                        return ticket
        except Exception:
            pass
        
        return {}
    
    def get_ticket(self, ticket_id: int) -> Dict[str, Any]:
        """Get detailed ticket information."""
        url = f"{self.base_url}/api/v1/tickets/{ticket_id}"
        
        try:
            response = self.session.get(url)
            response.raise_for_status()
            return response.json()
        except Exception:
            return {}
    
    def get_ticket_articles(self, ticket_id: int) -> List[Dict[str, Any]]:
        """Get articles for a ticket."""
        url = f"{self.base_url}/api/v1/ticket_articles/by_ticket/{ticket_id}"
        
        try:
            response = self.session.get(url)
            response.raise_for_status()
            return response.json()
        except Exception:
            return []


def analyze_sentiment(title: str, body: str) -> str:
    """
    Analyze sentiment based on keyword matching.
    Returns "negative" if any negative word found, otherwise "positive".
    """
    # Combine title and body
    text = f"{title} {body}".lower()
    
    # Check for negative words
    for word in NEGATIVE_WORDS:
        if word in text:
            return "negative"
    
    # Default to positive
    return "positive"


def main():
    """Main execution function."""
    client = ZammadClient()
    
    # Search for the target ticket by title
    ticket = client.search_ticket_by_title("Data loss after system update")
    
    if not ticket:
        print("Error: Could not find ticket")
        return
    
    # Get ticket details
    title = ticket.get('title', '')
    ticket_number = ticket.get('number', 0)
    ticket_id = ticket.get('id')
    
    # Get first article body
    articles = client.get_ticket_articles(ticket_id)
    body = ""
    if articles and len(articles) > 0:
        body = articles[0].get('body', '')
    
    # Analyze sentiment and write result to file
    sentiment = analyze_sentiment(title, body)
    output = f"Ticket #{ticket_number} sentiment: {sentiment}"
    
    with open('/app/ticket_sentiment.txt', 'w') as f:
        f.write(output)


if __name__ == '__main__':
    main()
