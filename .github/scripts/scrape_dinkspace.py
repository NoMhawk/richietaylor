from bs4 import BeautifulSoup
import json
import requests
import os
import re
from datetime import datetime

URL = "https://dinkspace.co.uk/dinkspace-schedule"

def parse_date_to_iso(date_str):
    months = {
        'january': '01', 'february': '02', 'march': '03', 'april': '04',
        'may': '05', 'june': '06', 'july': '07', 'august': '08',
        'september': '09', 'october': '10', 'november': '11', 'december': '12'
    }
    date_str = date_str.lower()
    for m_name, m_num in months.items():
        if m_name in date_str:
            day_match = re.search(r'\b(\d{1,2})(?:st|nd|rd|th)?\b', date_str)
            if day_match:
                day = day_match.group(1).zfill(2)
                year = '2027' if m_num in ['01', '02', '03', '04'] and '2027' in date_str else '2026'
                return f"{year}-{m_num}-{day}"
    return None

def fetch_dinkspace_schedule():
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    response = requests.get(URL, headers=headers)
    if response.status_code != 200:
        print("Failed to fetch schedule page.")
        return []

    soup = BeautifulSoup(response.text, 'html.parser')
    events = []
    today = datetime.now().date()

# Inside your element loop in fetch_dinkspace_schedule():
for element in soup.select('li a, p a, div a'):
    text = element.get_text(strip=True)
    link = element.get('href', 'https://dinkspace.co.uk/dinkspace-schedule')
    
    if '-' in text and any(kw in text.lower() for kw in ['festival', 'coaching', 'tournament', 'break', 'clinic', 'training']):
        if len(text) < 120 and "Skip to Content" not in text:
            parts = text.split('-', 1)
            date_part = parts[0].strip()
            title_part = parts[1].strip() if len(parts) > 1 else text
            
            iso_date = parse_date_to_iso(date_part)
            if not iso_date:
                continue

            event_date = datetime.strptime(iso_date, "%Y-%m-%d").date()
            if event_date < today:
                continue

            events.append({
                "title": title_part,
                "date": iso_date,
                "type": "Festival" if 'festival' in title_part.lower() else "Coaching",
                "location": "Dinkspace Venue",
                "url": link if link.startswith('http') else f"https://dinkspace.co.uk{link}",
                "desc": f"Official scheduled event: {title_part}"
            })

    # Deduplicate
    unique_events = []
    seen = set()
    for ev in events:
        identifier = (ev['title'], ev['date'])
        if identifier not in seen:
            seen.add(identifier)
            unique_events.append(ev)

    return unique_events

if __name__ == "__main__":
    data = fetch_dinkspace_schedule()
    
    output_dir = "dinkspace"
    os.makedirs(output_dir, exist_ok=True)
    
    output_path = os.path.join(output_dir, "events.json")
    with open(output_path, 'w') as f:
        json.dump(data, f, indent=4)
    print(f"Successfully saved {len(data)} future events to {output_path}")
