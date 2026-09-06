import os
import requests

print("AI Job Tracker Started!")

# Get Adzuna API credentials from GitHub Secrets
APP_ID = os.environ.get("ADZUNA_APP_ID")
APP_KEY = os.environ.get("ADZUNA_APP_KEY")

if not APP_ID or not APP_KEY:
    print("ERROR: Adzuna API credentials not found.")
    exit(1)


# Target job roles
roles = [
    "Embedded Engineer",
    "Embedded AI Engineer",
    "IoT Engineer",
    "Robotics Engineer"
]

print("\nSearching for suitable jobs...\n")


# Words that indicate experienced/senior jobs
reject_words = [
    "senior",
    "lead",
    "manager",
    "principal",
    "architect",
    "5+ years",
    "6+ years",
    "7+ years",
    "8+ years",
    "3-5 years",
    "5-8 years",
    "10+ years"
]


# Words that indicate fresher/entry-level jobs
fresher_words = [
    "fresher",
    "entry level",
    "entry-level",
    "junior",
    "trainee",
    "graduate",
    "0-1 years",
    "0-2 years",
    "0 to 1 years",
    "0 to 2 years",
    "1-2 years",
    "1 to 2 years"
]


for role in roles:

    print("=" * 50)
    print(f"Searching: {role}")
    print("=" * 50)

    url = "https://api.adzuna.com/v1/api/jobs/in/search/1"

    params = {
        "app_id": APP_ID,
        "app_key": APP_KEY,
        "what": role,
        "where": "Pune",
        "results_per_page": 20,
        "content-type": "application/json"
    }

    try:
        response = requests.get(
            url,
            params=params,
            timeout=30
        )

    except requests.RequestException as error:
        print("Request Error:", error)
        continue


    if response.status_code != 200:
        print("API Error:", response.status_code)
        print(response.text[:500])
        continue


    data = response.json()

    found = 0


    for job in data.get("results", []):

        title = job.get("title", "").strip()

        company = job.get(
            "company", {}
        ).get(
            "display_name",
            "Not specified"
        )

        location = job.get(
            "location", {}
        ).get(
            "display_name",
            "Not specified"
        )

        description = job.get(
            "description",
            ""
        ).lower()


        # Combine title + description
        text = (title + " " + description).lower()


        # Reject senior/experienced jobs
        if any(word in text for word in reject_words):
            continue


        # Check fresher/entry-level indicators
        is_fresher = any(
            word in text
            for word in fresher_words
        )


        # -------------------------
        # MATCH SCORE
        # -------------------------

        score = 40


        if is_fresher:
            score += 25


        # C / C++ skills
        if (
            "c programming" in description
            or "c language" in description
            or "c/c++" in description
            or "c++" in description
        ):
            score += 10


        # Python
        if "python" in description:
            score += 5


        # Embedded
        if "embedded" in text:
            score += 10


        # ESP32 / STM32
        if (
            "esp32" in description
            or "stm32" in description
        ):
            score += 5


        # IoT
        if "iot" in text:
            score += 5


        # Robotics
        if "robotics" in text:
            score += 5


        # Maximum score = 100
        if score > 100:
            score = 100


        # -------------------------
        # SALARY
        # -------------------------

        salary_min = job.get("salary_min")
        salary_max = job.get("salary_max")

        salary = "Not specified"


        if salary_min or salary_max:

            salary = (
                f"{salary_min or 'N/A'} - "
                f"{salary_max or 'N/A'} per year"
            )


        # -------------------------
        # APPLY LINK
        # -------------------------

        apply_link = job.get(
            "redirect_url",
            "Not available"
        )


        # -------------------------
        # PRINT JOB
        # -------------------------

        print("\n" + "-" * 50)

        print("Job:", title)

        print("Company:", company)

        print("Location:", location)

        print("Salary:", salary)

        print(
            "Fresher/Entry Level:",
            "Yes" if is_fresher else "Not specified"
        )

        print(
            "Match Score:",
            score,
            "/100"
        )

        print("Apply:", apply_link)

        found += 1


    print("\nSuitable jobs found for "
          f"{role}: {found}")


print("\n" + "=" * 50)
print("Job filtering completed!")
print("=" * 50)
