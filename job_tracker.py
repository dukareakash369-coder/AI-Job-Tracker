mport os
import json
import re
from datetime import date

import requests
import gspread
from google.oauth2.service_account import Credentials


print("AI Job Tracker Started!")


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


# Google Sheets authorization
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets"
]

try:
    service_account_info = json.loads(GOOGLE_JSON)

    credentials = Credentials.from_service_account_info(
        service_account_info,
        scopes=SCOPES
    )

    gc = gspread.authorize(credentials)
    print("Google service account:", service_account_info.get("client_email"))

# Diagnostic: ask Google Drive directly whether this exact spreadsheet ID is visible.
# This avoids gspread hiding the actual Google API response behind "<Response [404]>".
try:
    from google.auth.transport.requests import AuthorizedSession

    session = AuthorizedSession(credentials)
    drive_url = f"https://www.googleapis.com/drive/v3/files/{SPREADSHEET_ID}"
    drive_response = session.get(
        drive_url,
        params={"fields": "id,name,mimeType,trashed,owners(emailAddress)"},
        timeout=30,
    )

    print("DIRECT DRIVE STATUS:", drive_response.status_code)
    print("DIRECT DRIVE RESPONSE:", drive_response.text[:1000])

except Exception as error:
    print("Direct Drive diagnostic error:", error)


except Exception as error:
    print("Google authentication error:", error)
    exit(1)


# =========================================================
# 3. GOOGLE SHEET
# =========================================================

SPREADSHEET_ID = "1A8XAEfCB6kEUqJBa9GLPPSyeSf6XMT0iAglsAa_xNVM"

WORKSHEET_NAME = "Sheet1"

# Stop after the direct API diagnostic for this test.
exit(0)

try:
    # Open the spreadsheet by its exact name instead of spreadsheet ID.
    # This uses the Google Drive scope and avoids the current 404 from open_by_key().
    spreadsheet = gc.open("AI Job Tracker")
    worksheet = spreadsheet.worksheet(WORKSHEET_NAME)

except Exception as error:
    print("Google Sheet connection error:", error)
    print("Could not open spreadsheet by name: AI Job Tracker")
    exit(1)


print("Google Sheet connected successfully!")


# =========================================================
# 4. TARGET JOB ROLES
# =========================================================

roles = [
    "Embedded Engineer",
    "Embedded AI Engineer",
    "IoT Engineer",
    "Robotics Engineer"
]


# =========================================================
# 5. FILTER WORDS
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
    "5+ years",
    "6+ years",
    "7+ years",
    "8+ years",
    "10+ years"
]


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


# =========================================================
# 6. GET EXISTING APPLY LINKS
# =========================================================

try:

    existing_rows = worksheet.get_all_values()

    existing_links = set()

    # Apply Link is column I = index 8
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
# 7. SEARCH JOBS
# =========================================================

total_added = 0


for role in roles:

    print("\n" + "=" * 60)
    print(f"Searching: {role}")
    print("=" * 60)

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


    # =====================================================
    # 8. PROCESS EACH JOB
    # =====================================================

    for job in data.get("results", []):

        title = job.get(
            "title",
            ""
        ).strip()


        company = job.get(
            "company",
            {}
        ).get(
            "display_name",
            "Not specified"
        )


        location = job.get(
            "location",
            {}
        ).get(
            "display_name",
            "Pune"
        )


        description = job.get(
            "description",
            ""
        )


        text = (
            title + " " + description
        ).lower()


        # =================================================
        # REJECT SENIOR JOBS
        # =================================================

        if any(
            word in text
            for word in reject_words
        ):
            continue


        # =================================================
        # EXPERIENCE FILTER
        # =================================================

        # Detect explicit 3+ years requirement
        high_experience = re.search(
            r"\b([3-9]|1[0-9])\+?\s*(?:years?|yrs?)\b",
            text
        )


        if high_experience:

            required_years = int(
                high_experience.group(1)
            )

            if required_years >= 3:
                continue


        is_fresher = any(
            word in text
            for word in fresher_words
        )


        # =================================================
        # MATCH SCORE
        # =================================================

        score = 40


        if is_fresher:
            score += 25


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
        if "robotics" in text:
            score += 5


        if score > 100:
            score = 100


        # =================================================
        # ONLY GOOD MATCHES
        # =================================================

        if score < 60:
            continue


        # =================================================
        # SALARY
        # =================================================

        salary_min = job.get("salary_min")
        salary_max = job.get("salary_max")

        salary = "Not specified"


        if salary_min or salary_max:

            salary = (
                f"{salary_min or 'N/A'} - "
                f"{salary_max or 'N/A'} per year"
            )


        # =================================================
        # EXPERIENCE TEXT
        # =================================================

        experience = "Not specified"


        if is_fresher:

            experience = "Fresher / 0-2 years"

        elif high_experience:

            experience = (
                f"{high_experience.group(1)}+ years"
            )


        # =================================================
        # SKILLS
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
        # APPLY LINK
        # =================================================

        apply_link = job.get(
            "redirect_url",
            ""
        )


        if not apply_link:
            continue


        # =================================================
        # DUPLICATE CHECK
        # =================================================

        if apply_link in existing_links:

            print(
                "Skipping duplicate:",
                title
            )

            continue


        # =================================================
        # ADD TO GOOGLE SHEET
        # =================================================

        row = [
            str(date.today()),
            company,
            title,
            location,
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

            existing_links.add(apply_link)

            total_added += 1
            found += 1


            print("\n" + "-" * 60)
            print("ADDED TO GOOGLE SHEET")
            print("Job:", title)
            print("Company:", company)
            print("Location:", location)
            print("Salary:", salary)
            print("Experience:", experience)
            print("Skills:", skills_text)
            print("Match Score:", score, "/100")
            print("Apply:", apply_link)


        except Exception as error:

            print(
                "Could not add job to Sheet:",
                error
            )


    print(
        f"\nSuitable new jobs for {role}: {found}"
    )


# =========================================================
# 9. COMPLETION
# =========================================================

print("\n" + "=" * 60)

print(
    f"Job filtering completed! "
    f"New jobs added: {total_added}"
)

print("=" * 60)
