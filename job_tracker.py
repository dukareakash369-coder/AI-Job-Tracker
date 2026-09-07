import os
import json
import re
from datetime import date

import requests
import gspread
from google.oauth2.service_account import Credentials


print("AI Job Tracker V1.1 Started!")


# =========================================================
# 1. ADZUNA CREDENTIALS
# =========================================================

APP_ID = os.environ.get("ADZUNA_APP_ID")
APP_KEY = os.environ.get("ADZUNA_APP_KEY")

if not APP_ID or not APP_KEY:
    print("ERROR: Adzuna API credentials not found.")
    exit(1)


# =========================================================
# 2. GOOGLE SHEETS CREDENTIALS
# =========================================================

GOOGLE_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")

if not GOOGLE_JSON:
    print("ERROR: Google Service Account credentials not found.")
    exit(1)


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

try:
    service_account_info = json.loads(GOOGLE_JSON)

    credentials = Credentials.from_service_account_info(
        service_account_info,
        scopes=SCOPES
    )

    gc = gspread.authorize(credentials)

except Exception as error:
    print("Google authentication error:", error)
    exit(1)


# =========================================================
# 3. GOOGLE SHEET
# =========================================================

SPREADSHEET_ID = "1TeQSVAHVitgB2T6iBte-MOjHQeyHR-RS0HwTltgjIRo"

WORKSHEET_NAME = "Sheet1"

try:
    spreadsheet = gc.open_by_key(SPREADSHEET_ID)
    worksheet = spreadsheet.worksheet(WORKSHEET_NAME)

except Exception as error:
    print("Google Sheet connection error:", error)
    exit(1)


print("Google Sheet connected successfully!")


# =========================================================
# 4. SEARCH QUERIES
# =========================================================

search_queries = [
    "Embedded Engineer",
    "Embedded Software Engineer",
    "Embedded Systems Engineer",
    "Firmware Engineer",
    "Junior Embedded Engineer",
    "Embedded AI Engineer",
    "Edge AI Engineer",
    "IoT Engineer",
    "Junior IoT Engineer",
    "Robotics Engineer",
    "Junior Robotics Engineer"
]


# =========================================================
# 5. TARGET LOCATIONS
# =========================================================

locations = [
    "Pune",
    "Remote"
]


# =========================================================
# 6. REJECT WORDS
# =========================================================

reject_words = [
    "senior",
    "sr.",
    "sr ",
    "lead",
    "manager",
    "principal",
    "architect",
    "director",
    "head of"
]


# =========================================================
# 7. FRESHER / ENTRY LEVEL WORDS
# =========================================================

fresher_words = [
    "fresher",
    "entry level",
    "entry-level",
    "junior",
    "trainee",
    "graduate",
    "intern",
    "0-1 years",
    "0-2 years",
    "0 to 1 years",
    "0 to 2 years",
    "1-2 years",
    "1 to 2 years"
]


# =========================================================
# 8. GET EXISTING APPLY LINKS
# =========================================================

try:

    existing_rows = worksheet.get_all_values()

    existing_links = set()

    # Apply Link = Column I = index 8
    for row in existing_rows[1:]:

        if len(row) > 8:

            link = row[8].strip()

            if link:
                existing_links.add(link)

    print(
        f"Existing jobs in Sheet: {len(existing_links)}"
    )

except Exception as error:

    print(
        "Could not read existing Sheet data:",
        error
    )

    existing_links = set()


# =========================================================
# 9. API SETTINGS
# =========================================================

API_URL = (
    "https://api.adzuna.com/v1/api/jobs/in/search/{page}"
)

RESULTS_PER_PAGE = 20

TOTAL_PAGES = 3


# =========================================================
# 10. TOTAL COUNTERS
# =========================================================

total_added = 0
total_seen = 0
total_rejected = 0


# =========================================================
# 11. SEARCH JOBS
# =========================================================

for location in locations:

    for query in search_queries:

        print("\n" + "=" * 70)
        print(f"Searching: {query}")
        print(f"Location: {location}")
        print("=" * 70)

        for page in range(1, TOTAL_PAGES + 1):

            print(f"Fetching page {page}...")

            url = API_URL.format(page=page)

            params = {
                "app_id": APP_ID,
                "app_key": APP_KEY,
                "what": query,
                "where": location,
                "results_per_page": RESULTS_PER_PAGE,
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

                print(
                    "API Error:",
                    response.status_code
                )

                print(response.text[:500])

                continue


            try:

                data = response.json()

            except ValueError:

                print("Invalid JSON response.")

                continue


            jobs = data.get("results", [])

            print(
                f"Jobs received: {len(jobs)}"
            )


            # =================================================
            # 12. PROCESS EACH JOB
            # =================================================

            for job in jobs:

                total_seen += 1

                title = job.get(
                    "title",
                    ""
                ).strip()


                if not title:
                    continue


                # -------------------------------------------------
                # COMPANY
                # -------------------------------------------------

                company_data = job.get(
                    "company",
                    {}
                )

                company = company_data.get(
                    "display_name",
                    "Not specified"
                )

                if not company:
                    company = "Not specified"


                # -------------------------------------------------
                # LOCATION
                # -------------------------------------------------

                location_data = job.get(
                    "location",
                    {}
                )

                job_location = location_data.get(
                    "display_name",
                    location
                )

                if not job_location:
                    job_location = location


                # -------------------------------------------------
                # DESCRIPTION
                # -------------------------------------------------

                description = job.get(
                    "description",
                    ""
                )


                text = (
                    title
                    + " "
                    + description
                ).lower()


                # =================================================
                # 13. REJECT SENIOR ROLES
                # =================================================

                if any(
                    word in text
                    for word in reject_words
                ):

                    total_rejected += 1

                    print(
                        "Rejected senior-level:",
                        title
                    )

                    continue


                # =================================================
                # 14. EXPERIENCE FILTER
                # =================================================

                high_experience = re.search(
                    r"\b([3-9]|1[0-9])\+?\s*(?:years?|yrs?)\b",
                    text
                )


                if high_experience:

                    required_years = int(
                        high_experience.group(1)
                    )

                    if required_years >= 3:

                        total_rejected += 1

                        print(
                            "Rejected experience:",
                            title
                        )

                        continue


                is_fresher = any(
                    word in text
                    for word in fresher_words
                )


                # =================================================
                # 15. MATCH SCORE
                # =================================================

                score = 35


                # Fresher / entry-level
                if is_fresher:
                    score += 20


                # C / C++
                if (
                    "c programming" in text
                    or "c language" in text
                    or "c/c++" in text
                    or "c++" in text
                ):
                    score += 10


                # Python
                if "python" in text:
                    score += 5


                # Embedded
                if "embedded" in text:
                    score += 10


                # ESP32 / STM32
                if (
                    "esp32" in text
                    or "stm32" in text
                ):
                    score += 5


                # IoT
                if "iot" in text:
                    score += 5


                # Robotics
                if (
                    "robotics" in text
                    or "ros" in text
                ):
                    score += 5


                # Linux
                if "linux" in text:
                    score += 3


                # RTOS
                if "rtos" in text:
                    score += 3


                # Pune priority
                if "pune" in job_location.lower():
                    score += 5


                # Remote priority
                if "remote" in job_location.lower():
                    score += 5


                # Maximum 100
                if score > 100:
                    score = 100


                # =================================================
                # 16. MINIMUM SCORE
                # =================================================

                if score < 55:

                    total_rejected += 1

                    print(
                        "Rejected low score:",
                        title,
                        score
                    )

                    continue


                # =================================================
                # 17. SALARY
                # =================================================

                salary_min = job.get(
                    "salary_min"
                )

                salary_max = job.get(
                    "salary_max"
                )

                salary = "Not specified"


                if salary_min or salary_max:

                    salary = (
                        f"{salary_min or 'N/A'} - "
                        f"{salary_max or 'N/A'} per year"
                    )


                # =================================================
                # 18. EXPERIENCE TEXT
                # =================================================

                experience = "Not specified"


                if is_fresher:

                    experience = (
                        "Fresher / 0-2 years"
                    )

                elif high_experience:

                    experience = (
                        f"{high_experience.group(1)}+ years"
                    )


                # =================================================
                # 19. SKILLS
                # =================================================

                skills = []


                skill_keywords = {

                    "C": [
                        "c programming",
                        "c language",
                        "c/c++"
                    ],

                    "C++": [
                        "c++"
                    ],

                    "Python": [
                        "python"
                    ],

                    "Embedded": [
                        "embedded"
                    ],

                    "ESP32": [
                        "esp32"
                    ],

                    "STM32": [
                        "stm32"
                    ],

                    "IoT": [
                        "iot"
                    ],

                    "Robotics": [
                        "robotics"
                    ],

                    "ROS": [
                        "ros"
                    ],

                    "Linux": [
                        "linux"
                    ],

                    "RTOS": [
                        "rtos"
                    ]
                }


                for skill, keywords in skill_keywords.items():

                    if any(
                        keyword in text
                        for keyword in keywords
                    ):

                        skills.append(skill)


                skills_text = ", ".join(skills)


                if not skills_text:
                    skills_text = "Not specified"


                # =================================================
                # 20. APPLY LINK
                # =================================================

                apply_link = job.get(
                    "redirect_url",
                    ""
                )


                if not apply_link:
                    continue


                # =================================================
                # 21. DUPLICATE CHECK
                # =================================================

                if apply_link in existing_links:

                    print(
                        "Skipping duplicate:",
                        title
                    )

                    continue


                # =================================================
                # 22. ADD TO GOOGLE SHEET
                # =================================================

                row = [

                    str(date.today()),

                    company,

                    title,

                    job_location,

                    salary,

                    experience,

                    skills_text,

                    score,

                    apply_link,

                    "Not Applied"
                ]


                try:

                    worksheet.append_row(
                        row,
                        value_input_option="USER_ENTERED"
                    )

                    existing_links.add(
                        apply_link
                    )

                    total_added += 1


                    print("\n" + "-" * 70)
                    print("NEW JOB ADDED")
                    print("Job:", title)
                    print("Company:", company)
                    print("Location:", job_location)
                    print("Salary:", salary)
                    print("Experience:", experience)
                    print("Skills:", skills_text)
                    print("Match Score:", score, "/100")
                    print("Apply:", apply_link)
                    print("-" * 70)


                except Exception as error:

                    print(
                        "Could not add job to Sheet:",
                        error
                    )


# =========================================================
# 23. FINAL SUMMARY
# =========================================================

print("\n" + "=" * 70)

print(
    "JOB SEARCH COMPLETED"
)

print(
    f"Total jobs seen: {total_seen}"
)

print(
    f"New jobs added: {total_added}"
)

print(
    f"Jobs rejected: {total_rejected}"
)

print("=" * 70)

print(
    "AI Job Tracker V1.1 Finished Successfully!"
)
