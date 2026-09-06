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

print("\nSearching for suitable jobs...\n")

for role in roles:

    print("=" * 40)
    print(role)
    print("=" * 40)

    url = "https://api.adzuna.com/v1/api/jobs/in/search/1"

    params = {
        "app_id": APP_ID,
        "app_key": APP_KEY,
        "what": role,
        "where": "Pune",
        "results_per_page": 20,
        "content-type": "application/json"
    }

    response = requests.get(url, params=params)

    if response.status_code != 200:
        print("API Error:", response.status_code)
        continue

    data = response.json()

    found = 0

    for job in data.get("results", []):

        title = job.get("title", "")
        company = job.get("company", {}).get("display_name", "Not specified")
        location = job.get("location", {}).get("display_name", "Not specified")
        description = job.get("description", "").lower()

        # Reject senior / experienced jobs
        reject_words = [
            "senior",
            "lead",
            "manager",
            "5+ years",
            "6+ years",
            "7+ years",
            "8+ years",
            "3-5 years",
            "5-8 years"
        ]

        text = (title + " " + description).lower()

        if any(word in text for word in reject_words):
            continue

        # Look for fresher / entry-level indicators
        fresher_words = [
            "fresher",
            "entry level",
            "entry-level",
            "junior",
            "trainee",
            "graduate",
            "0-2 years",
            "0 to 2 years",
            "1-2 years",
            "1 to 2 years"
        ]

        is_fresher = any(word in text for word in fresher_words)

        # Calculate match score
        score = 50

        if is_fresher:
            score += 20

        if "c" in description or "c++" in description:
            score += 10

        if "python" in description:
            score += 5

        if "esp32" in description or "stm32" in description:
            score += 5

        if "embedded" in text:
            score += 10

        if score > 100:
            score = 100

        salary_min = job.get("salary_min")
        salary_max = job.get("salary_max")

        salary = "Not specified"

        if salary_min or salary_max:
            salary = f"{salary_min or 'N/A'} - {salary_max or 'N/A'} per year"

        apply_link = job.get("redirect_url", "Not available")

        print("\nJob:", title)
        print("Company:", company)
        print("Location:", location)
        print("Salary:", salary)
        print("Match Score:", score, "/100")
        print("Apply:", apply_link)

        found += 1

    print(f"\nSuitable jobs found for {role}: {found}")

print("\nJob filtering completed!")
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

print("\nSearching for suitable jobs...\n")

for role in roles:

    print("=" * 40)
    print(role)
    print("=" * 40)

    url = "https://api.adzuna.com/v1/api/jobs/in/search/1"

    params = {
        "app_id": APP_ID,
        "app_key": APP_KEY,
        "what": role,
        "where": "Pune",
        "results_per_page": 20,
        "content-type": "application/json"
    }

    response = requests.get(url, params=params)

    if response.status_code != 200:
        print("API Error:", response.status_code)
        continue

    data = response.json()

    found = 0

    for job in data.get("results", []):

        title = job.get("title", "")
        company = job.get("company", {}).get("display_name", "Not specified")
        location = job.get("location", {}).get("display_name", "Not specified")
        description = job.get("description", "").lower()

        # Reject senior / experienced jobs
        reject_words = [
            "senior",
            "lead",
            "manager",
            "5+ years",
            "6+ years",
            "7+ years",
            "8+ years",
            "3-5 years",
            "5-8 years"
        ]

        text = (title + " " + description).lower()

        if any(word in text for word in reject_words):
            continue

        # Look for fresher / entry-level indicators
        fresher_words = [
            "fresher",
            "entry level",
            "entry-level",
            "junior",
            "trainee",
            "graduate",
            "0-2 years",
            "0 to 2 years",
            "1-2 years",
            "1 to 2 years"
        ]

        is_fresher = any(word in text for word in fresher_words)

        # Calculate match score
        score = 50

        if is_fresher:
            score += 20

        if "c" in description or "c++" in description:
            score += 10

        if "python" in description:
            score += 5

        if "esp32" in description or "stm32" in description:
            score += 5

        if "embedded" in text:
            score += 10

        if score > 100:
            score = 100

        salary_min = job.get("salary_min")
        salary_max = job.get("salary_max")

        salary = "Not specified"

        if salary_min or salary_max:
            salary = f"{salary_min or 'N/A'} - {salary_max or 'N/A'} per year"

        apply_link = job.get("redirect_url", "Not available")

        print("\nJob:", title)
        print("Company:", company)
        print("Location:", location)
        print("Salary:", salary)
        print("Match Score:", score, "/100")
        print("Apply:", apply_link)

        found += 1

    print(f"\nSuitable jobs found for {role}: {found}")

print("\nJob filtering completed!")
