"""
One-time helper to find your Canvas LMS URL and verify your API token.
Run this once during setup: python find_canvas_url.py
"""
import sys
import requests


def try_url(base_url, token):
    try:
        r = requests.get(
            f"{base_url.rstrip('/')}/api/v1/users/self",
            headers={"Authorization": f"Bearer {token}"},
            timeout=8,
        )
        if r.status_code == 200:
            data = r.json()
            print(f"  SUCCESS: {base_url}")
            print(f"  Logged in as: {data.get('name')} ({data.get('login_id')})")
            return True
        else:
            print(f"  {base_url} -> HTTP {r.status_code}")
    except requests.exceptions.ConnectionError:
        print(f"  {base_url} -> Could not connect")
    except Exception as e:
        print(f"  {base_url} -> Error: {e}")
    return False


def main():
    print("Canvas URL Finder")
    print("=" * 40)
    print()
    print("How to get your Canvas API token:")
    print("  1. Log into Canvas in your browser")
    print("  2. Click your name/avatar (top-left) -> Settings")
    print("  3. Scroll down to 'Approved Integrations'")
    print("  4. Click '+ New Access Token'")
    print("  5. Name it 'Notifier', leave expiry blank, click Generate")
    print("  6. COPY the token now — it won't be shown again")
    print()

    school = input("Enter your school name or abbreviation (e.g. 'gatech', 'unc', 'mit'): ").strip()
    token = input("Paste your Canvas API token: ").strip()

    if not school or not token:
        print("School name and token are required.")
        sys.exit(1)

    candidates = [
        f"https://{school}.instructure.com",
        f"https://canvas.{school}.edu",
        f"https://elearning.{school}.edu",
        f"https://lms.{school}.edu",
        f"https://{school}.canvas.com",
        f"https://online.{school}.edu",
    ]

    print(f"\nTrying {len(candidates)} common Canvas URL patterns...")
    for url in candidates:
        if try_url(url, token):
            print()
            print("Add these to your .env file:")
            print(f"  CANVAS_API_URL={url}")
            print(f"  CANVAS_API_TOKEN={token}")
            sys.exit(0)

    print("\nNone of the common patterns worked.")
    print("Try entering the full URL from your browser's address bar when logged into Canvas:")
    custom = input("Full Canvas URL (e.g. https://canvas.myschool.edu): ").strip()
    if custom:
        if try_url(custom, token):
            print()
            print("Add these to your .env file:")
            print(f"  CANVAS_API_URL={custom}")
            print(f"  CANVAS_API_TOKEN={token}")
        else:
            print("\nCould not authenticate. Double-check your token and URL.")
            print("Make sure the URL does NOT include /login or any path — just the base domain.")


if __name__ == "__main__":
    main()
