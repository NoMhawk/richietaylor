from bs4 import BeautifulSoup
import json
import requests
import os

URL = "https://dinkspace.co.uk/dinkspace-schedule"

def fetch_dinkspace_schedule():
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    response = requests.get(URL, headers=headers)
    if response.status_code != 200:
        print("Failed to fetch schedule page.")
        return []

    soup = BeautifulSoup(response.text, 'html.parser')
    events = []

    # Scrape structured event data from the page elements
    # (Adjust selectors as needed based on exact live HTML layout tags)
    for element in soup.select('li, p, div'):
        text = element.get_text(strip=True)
        if '-' in text and any(kw in text.lower() for kw in ['festival', 'coaching', 'tournament', 'break', 'clinic']):
            events.append({
                "title": text,
                "date": "2026-11-01", # Placeholder mapping logic or pattern-matching date extraction
                "type": "Coaching" if "coaching" in text.lower() else "Festival",
                "location": "Dinkspace Venue",
                "desc": text
            })

    return events

if __name__ == "__main__":
    data = fetch_dinkspace_schedule()
    
    # Ensure the output directory exists
    output_dir = "dinkspace"
    os.makedirs(output_dir, exist_ok=True)
    
    output_path = os.path.join(output_dir, "events.json")
    with open(output_path, 'w') as f:
        json.dump(data, f, indent=4)
    print(f"Successfully saved {len(data)} events to {output_path}")
