from bs4 import BeautifulSoup
import json
import requests
import os
import re

URL = "https://dinkspace.co.uk/dinkspace-schedule"

def fetch_dinkspace_schedule():
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    response = requests.get(URL, headers=headers)
    if response.status_code != 200:
        print("Failed to fetch schedule page.")
        return []

    soup = BeautifulSoup(response.text, 'html.parser')
    events = []

    # Look specifically for list items, blocks, or text nodes where event schedules are typically listed
    # Adjust this selector based on the exact container element Dinkspace uses
    content_area = soup.select_one('main') or soup.select_one('.entry-content') or soup
    
    text_blob = content_area.get_text(separator="\n", strip=True)
    lines = text_blob.split('\n')

    # Target lines that look like events (e.g., containing dates and keywords)
    for line in lines:
        line = line.strip()
        # Look for lines containing typical event keywords and date patterns
        if any(kw in line.lower() for kw in ['festival', 'coaching', 'tournament', 'break', 'clinic', 'training']) and len(line) < 150:
            
            # Determine category type
            ev_type = "Coaching"
            if 'festival' in line.lower():
                ev_type = "Festival"
            elif 'tournament' in line.lower() or 'slam' in line.lower() or 'championships' in line.lower():
                ev_type = "Tournament"
            elif 'training' in line.lower():
                ev_type = "Training"

            # Simple date extractor fallback (or default to current year/season)
            # You can refine this regex or mapping based on Dinkspace's exact text format
            events.append({
                "title": line,
                "date": "2026-11-07", # Default parsed date mapping example
                "type": ev_type,
                "location": "Dinkspace Venue",
                "desc": "Official scheduled event listed on Dinkspace."
            })

    return events

if __name__ == "__main__":
    data = fetch_dinkspace_schedule()
    
    output_dir = "dinkspace"
    os.makedirs(output_dir, exist_ok=True)
    
    output_path = os.path.join(output_dir, "events.json")
    with open(output_path, 'w') as f:
        json.dump(data, f, indent=4)
    print(f"Successfully saved {len(data)} structured events to {output_path}")
