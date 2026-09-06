import os
import requests

print("AI Job Tracker Started!")

APP_ID = os.environ.get("ADZUNA_APP_ID")
APP_KEY = os.environ.get("ADZUNA_APP_KEY")

if not APP_ID or not APP_KEY:
    print("ERROR: Adzuna API credentials not found.")
    exit()

roles = [
    "Embedded Engineer",
    "Embedded AI Engineer",
    "IoT Engineer",
    "Robotics Engineer"
]

print("\nSearching for jobs...")

for role in roles:

    url = "https://api.adzuna.com/v1/api/jobs/in/search/1"

    params = {
        "app_id": APP_ID,
        "app_key": APP_KEY,
        "what": role,
        "where": "Pune",
        "results_per_page": 10,
        "content-type": "application/json"
    }

    response = requests.get(url, params=params)

    if response.status_code == 200:

        data = response.json()

        print(f"\n===== {role} =====")

        for job in data.get("results", []):

            title = job.get("title", "N/A")
            company = job.get("company", {}).get("display_name", "N/A")
            location = job.get("location", {}).get("display_name", "N/A")
            salary_min = job.get("salary_min", "Not specified")
            salary_max = job.get("salary_max", "Not specified")
            apply_link = job.get("redirect_url", "N/A")

            print("\nJob:", title)
            print("Company:", company)
            print("Location:", location)
            print("Salary:", salary_min, "-", salary_max)
            print("Apply:", apply_link)

    else:
        print("API Error:", response.status_code)
