"""
Minimal connectivity test -- run this on its own, no Streamlit or secrets
file needed. Just checks whether this one specific host is reachable from
wherever you run it.

Usage:
    python test_fpl_connection.py
"""

import requests

url = "https://users.premierleague.com/accounts/login/"

print(f"Trying to reach: {url}")
try:
    response = requests.get(url, timeout=10)
    print(f"SUCCESS -- got HTTP {response.status_code}")
    print("This confirms the domain is reachable from this machine/network.")
except requests.RequestException as e:
    print(f"FAILED -- {e}")
    print("If this fails here too, it's not Streamlit-Cloud-specific.")
