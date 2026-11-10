from bs4 import BeautifulSoup
import json
import requests
import os
import re
from datetime import datetime

URL = "https://dinkspace.co.uk/dinkspace-schedule"

# Explicit mapping for exact URLs with their # anchors
EVENT_URL_OVERRIDES = {
    "abingdon festival": "https://dinkspace.co.uk/festivals#abingdonnov",
    "somerset county team training": "https://dinkspace.co.uk/dinkspace-schedule#somersetnov",
    "courtside (stourbridge) coaching clinics": "https://dinkspace.co.uk/coachingclinics#courtsidenov",
    "exeter coaching clinic": "https://dinkspace.co.uk/coachingclinics#exeternov",
    "london christmas festival": "https://dinkspace.co.uk/festivals#londondec",
    "southampton christmas festival": "https://dinkspace.co.uk/festivals#southamptondec",
    "taunton christmas festival": "https://dinkspace.co.uk/festivals#tauntondec"
}

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
    try:
        response = requests.get(URL, headers=headers, timeout=10)
        if response.status_code != 200:
            print(f"Failed to fetch schedule page, status code: {response.status_code}")
            return []
    except Exception as e:
        print(f"Error fetching URL: {e}")
        return []

    soup = BeautifulSoup(response.text, 'html.parser')
    events = []
    today = datetime.now().date()

    for element in soup.select('li, p, div, span'):
        text = element.get_text(strip=True)
        
        if '-' in text and any(kw in text.lower() for kw in ['festival', 'coaching', 'tournament', 'break', 'clinic', 'training']):
            if len(text) < 150 and "Skip to Content" not in text:
                parts = text.split('-', 1)
                date_part = parts[0].strip()
                title_part = parts[1].strip() if len(parts) > 1 else text

                iso_date = parse_date_to_iso(date_part)
                if not iso_date:
                    continue

                try:
                    event_date = datetime.strptime(iso_date, "%Y-%m-%d").date()
                    if event_date < today:
                        continue
                except Exception:
                    continue

                # Classify Event Type
                title_lower = title_part.lower()
                ev_type = "Coaching"
                if 'festival' in title_lower:
                    ev_type = "Festival"
                elif any(kw in title_lower for kw in ['tournament', 'slam', 'championships', 'open']):
                    ev_type = "Tournament"
                elif any(kw in title_lower for kw in ['training', 'squad', 'team']):
                    ev_type = "Training"
                elif any(kw in title_lower for kw in ['clinic', 'break', 'coaching']):
                    ev_type = "Coaching"

                # Check if we have an explicit override mapping for this title
                matched_url = "https://dinkspace.co.uk/dinkspace-schedule"
                for key, url_val in EVENT_URL_OVERRIDES.items():
                    if key in title_lower:
                        matched_url = url_val
                        break
                
                # Fallback default subpage routes if not explicitly mapped
                if matched_url == "https://dinkspace.co.uk/dinkspace-schedule":
                    if ev_type == "Festival":
                        matched_url = "https://dinkspace.co.uk/festivals"
                    elif ev_type == "Coaching":
                        matched_url = "https://dinkspace.co.uk/coachingclinics"

                events.append({
                    "title": title_part,
                    "date": iso_date,
                    "type": ev_type,
                    "url": matched_url,
                    "desc": f"Official scheduled event: {title_part}"
                })

    # Deduplicate events by title and date
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
    
    output_path = "events.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)
    print(f"Successfully saved {len(data)} events with explicit anchor URLs to {output_path}")
