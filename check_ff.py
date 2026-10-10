import requests, json

headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# Try different FF URL patterns
urls = [
    "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
    "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
    "https://www.forexfactory.com/calendar.php?week=this",
]

for url in urls:
    try:
        r = requests.get(url, headers=headers, timeout=10)
        print(f"{url}")
        print(f"  Status: {r.status_code}")
        if r.status_code == 200:
            try:
                data = r.json()
                print(f"  Events: {len(data)}")
                # Show date range
                dates = sorted(set(d.get("date","") for d in data if d.get("date")))
                print(f"  Date range: {dates[0]} → {dates[-1]}")
                # Show events with actuals
                with_actual = [d for d in data if d.get("actual") not in (None, "", "")]
                print(f"  With actuals: {len(with_actual)}")
                for e in with_actual[:5]:
                    print(f"    {e.get('date','')} {e.get('title','')} = {e.get('actual','')}")
            except:
                print(f"  (not JSON)")
    except Exception as e:
        print(f"  ERROR: {e}")
    print()
