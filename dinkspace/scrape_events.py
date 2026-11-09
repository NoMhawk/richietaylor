from bs4 import BeautifulSoup
import json
import requests

URL = "https://dinkspace.co.uk/dinkspace-schedule"


def fetch_dinkspace_schedule():
  headers = {
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
      )
  }
  response = requests.get(URL, headers=headers)
  if response.status_code != 200:
    return []

  soup = BeautifulSoup(response.text, "html.parser")
  events = []

  # Parse text blocks or event nodes from the Dinkspace schedule page structure
  for element in soup.select("li, p, div"):
    text = element.get_text(strip=True)
    # Filter and extract dates & titles dynamically based on layout patterns
    if "-" in text and any(
        kw in text.lower()
        for kw in ["festival", "coaching", "tournament", "break", "clinic"]
    ):
      events.append({"title": text, "raw": text})

  return events


if __name__ == "__main__":
  data = fetch_dinkspace_schedule()
  # Save to the web directory serving richietaylor.net/dinkspace
  with open("events.json", "w") as f:
    json.dump(data, f, indent=4)
  print(f"Successfully updated {len(events)} events for richietaylor.net/dinkspace")
