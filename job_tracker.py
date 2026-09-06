import os
import re
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

# Jobs we do NOT want
senior_keywords = [
    "senior",
    "lead",
    "principal",
    "manager",
    "architect",
    "head",
    "director"
]

# Skills important for our target
target_skills = [
    "c",
    "c++",
    "python",
    "embedded",
    "microcontroller",
    "esp32",
    "stm32",
    "rtos",
    "uart",
    "spi",
    "i2c",
    "can",
    "linux",
    "iot",
    "robotics",
    "edge ai"
]

print("\nSearching Pune jobs...")

for role in roles:

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

    print(f"\n===== {role} =====")

    found = 0

    for job in data.get("results", []):

        title = job.get("title", "N/A")
        description = job.get("description", "")
        company = job.get("company", {}).get(
            "display_name", "N/A"
        )
        location = job.get("location", {}).get(
            "display_name", "N/A"
        )

        salary_min = job.get("salary_min")
        salary_max = job.get("salary_max")

        apply_link = job.get("redirect_url", "N/A")

        text = (title + " " + description).lower()

        # --------------------------------
        # FILTER 1: Remove senior positions
        # --------------------------------

        if any(word in title.lower() for word in senior_keywords):
            continue

        # --------------------------------
        # FILTER 2: Remove jobs requiring 3+ years
        # --------------------------------

        experience_patterns = [
            r"minimum of (\d+)\s*-\s*(\d+)\s*years",
            r"minimum (\d+)\s*years",
            r"(\d+)\s*-\s*(\d+)\s*years of experience",
            r"(\d+)\+\s*years"
        ]

        too_experienced = False

        for pattern in experience_patterns:

            matches = re.findall(pattern, text)

            for match in matches:

                if isinstance(match, tuple):
                    first_number = int(match[0])
                else:
                    first_number = int(match)

                if first_number >= 3:
                    too_experienced = True

        if too_experienced:
            continue

        # --------------------------------
        # FILTER 3: Calculate Match Score
        # --------------------------------

        score = 0

        # Role match
        if any(word in text for word in [
            "embedded",
            "iot",
            "robotics",
            "edge ai"
        ]):
            score += 30

        # Location
        if "pune" in location.lower():
            score += 20

        # Skills
        skill_matches = 0

        for skill in target_skills:
            if skill in text:
                skill_matches += 1

        score += min(skill_matches * 5, 30)

        # Fresher / junior keywords
        if any(word in text for word in [
            "fresher",
            "entry level",
            "junior",
            "trainee",
            "graduate",
            "0-2 years",
            "0 to 2 years"
        ]):
            score += 20

        found += 1

        print("\n----------------------------")
        print("Job:", title)
        print("Company:", company)
        print("Location:", location)
        print("Salary:", salary_min, "-", salary_max)
        print("Match Score:", score, "/ 100")
        print("Apply:", apply_link)

    print(
        f"\nSuitable jobs found for {role}: {found}"
    )

print("\nJob filtering completed!")
