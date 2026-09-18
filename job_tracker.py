import os
import json
import re
import time
from datetime import date

import requests
import gspread
from google.oauth2.service_account import Credentials
from google import genai


print("AI Job Tracker V2 Started!")


# =========================================================
# 1. ADZUNA CREDENTIALS
# =========================================================

APP_ID = os.environ.get("ADZUNA_APP_ID")
APP_KEY = os.environ.get("ADZUNA_APP_KEY")

if not APP_ID or not APP_KEY:
    print("ERROR: Adzuna API credentials not found.")
    exit(1)


# =========================================================
# 2. GEMINI API
# =========================================================

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    print("ERROR: GEMINI_API_KEY not found.")
    exit(1)

try:
    gemini_client = genai.Client(api_key=GEMINI_API_KEY)
    print("Gemini client initialized successfully!")

except Exception as error:
    print("Gemini initialization error:", error)
    exit(1)


# =========================================================
# 3. LOAD CANDIDATE PROFILE
# =========================================================

PROFILE_FILE = "profile.json"

try:

    with open(PROFILE_FILE, "r", encoding="utf-8") as file:
        profile = json.load(file)

    print("Candidate profile loaded successfully!")

except Exception as error:

    print("Profile loading error:", error)
    exit(1)


# =========================================================
# 4. GOOGLE SHEETS CREDENTIALS
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
# 5. GOOGLE SHEET
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
# 6. GOOGLE SHEET HEADERS
# =========================================================

headers = [
    "Date",
    "Company",
    "Job Role",
    "Location",
    "Salary",
    "Experience",
    "Skills",
    "Match Score",
    "Apply Link",
    "Status",
    "Matched Skills",
    "Missing Skills",
    "Experience Match",
    "Match Reason"
]


try:

    current_headers = worksheet.row_values(1)

    if current_headers != headers:

        worksheet.update(
            "A1:N1",
            [headers]
        )

        print("Google Sheet headers updated for V2!")

except Exception as error:

    print("Could not update Sheet headers:", error)


# =========================================================
# 7. SEARCH QUERIES
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
# 8. TARGET LOCATIONS
# =========================================================

locations = [
    "Pune",
    "Remote"
]


# =========================================================
# 9. BASIC REJECT WORDS
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
# 10. FRESHER / ENTRY LEVEL WORDS
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
# 11. API SETTINGS
# =========================================================

API_URL = "https://api.adzuna.com/v1/api/jobs/in/search/{page}"

RESULTS_PER_PAGE = 20

TOTAL_PAGES = 3


# =========================================================
# 12. AI SETTINGS
# =========================================================

AI_MODEL = "gemini-3.6-flash"

AI_MIN_SCORE = 60

MAX_AI_JOBS = 40

ai_jobs_processed = 0


# =========================================================
# 13. GET EXISTING APPLY LINKS
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
# 14. TOTAL COUNTERS
# =========================================================

total_added = 0
total_seen = 0
total_rejected = 0
total_ai_analyzed = 0


# =========================================================
# 15. GEMINI JOB ANALYSIS FUNCTION
# =========================================================

def analyze_job_with_gemini(
    title,
    company,
    location,
    description
):

    profile_text = json.dumps(
        profile,
        indent=2,
        ensure_ascii=False
    )


    prompt = f"""
You are an intelligent job matching system.

Your task is to compare a candidate profile with a job description.

CANDIDATE PROFILE:
{profile_text}


JOB INFORMATION:

Company:
{company}

Job Role:
{title}

Location:
{location}

Job Description:
{description}


Analyze the job against the candidate profile.

Important rules:

1. Focus on the candidate being a FRESHER / ENTRY LEVEL candidate.
2. Consider required technical skills.
3. Consider programming languages.
4. Consider embedded systems skills.
5. Consider electronics and communication skills.
6. Consider IoT and robotics skills.
7. Consider location.
8. Consider required experience.
9. Do not assume the candidate has skills that are not present in the profile.
10. Missing skills should be identified clearly.
11. Match score must be between 0 and 100.
12. Give a realistic score, not an artificially high score.
13. If the job clearly requires senior-level experience, score it low.
14. Return ONLY valid JSON.
15. Do not use markdown.
16. Do not include ```json or ```.

Return exactly this JSON structure:

{{
    "match_score": 0,
    "matched_skills": [],
    "missing_skills": [],
    "experience_match": "",
    "match_reason": ""
}}

Keep match_reason short and practical.
"""


    try:

        interaction = gemini_client.interactions.create(
            model=AI_MODEL,
            input=prompt
        )

        response_text = interaction.output_text.strip()

        # Remove accidental markdown fences

        response_text = re.sub(
            r"^```json\s*",
            "",
            response_text,
            flags=re.IGNORECASE
        )

        response_text = re.sub(
            r"\s*```$",
            "",
            response_text
        )

        result = json.loads(response_text)

        return result

    except Exception as error:

        print(
            "Gemini analysis error:",
            error
        )

        return None


# =========================================================
# 16. SEARCH JOBS
# =========================================================

for location in locations:

    for query in search_queries:

        print("\n" + "=" * 70)
        print(f"Searching: {query}")
        print(f"Location: {location}")
        print("=" * 70)


        for page in range(1, TOTAL_PAGES + 1):

            print(
                f"Fetching page {page}..."
            )


            url = API_URL.format(
                page=page
            )


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

                print(
                    "Request Error:",
                    error
                )

                continue


            if response.status_code != 200:

                print(
                    "API Error:",
                    response.status_code
                )

                print(
                    response.text[:500]
                )

                continue


            try:

                data = response.json()

            except ValueError:

                print(
                    "Invalid JSON response."
                )

                continue


            jobs = data.get(
                "results",
                []
            )


            print(
                f"Jobs received: {len(jobs)}"
            )


            # =================================================
            # 17. PROCESS EACH JOB
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
                # 18. BASIC SENIOR FILTER
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
                # 19. EXPERIENCE FILTER
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
                # 22. AI JOB LIMIT
                # =================================================

                if ai_jobs_processed >= MAX_AI_JOBS:

                    print(
                        "AI analysis limit reached:",
                        MAX_AI_JOBS
                    )

                    continue


                # =================================================
                # 23. GEMINI AI ANALYSIS
                # =================================================

                print("\n" + "-" * 70)

                print(
                    "Sending job to Gemini AI..."
                )

                print(
                    "Job:",
                    title
                )

                print(
                    "Company:",
                    company
                )


                ai_result = analyze_job_with_gemini(
                    title,
                    company,
                    job_location,
                    description
                )


                ai_jobs_processed += 1
                total_ai_analyzed += 1


                if ai_result is None:

                    print(
                        "AI analysis failed. Skipping job."
                    )

                    continue


                # =================================================
                # 24. READ AI RESULT
                # =================================================

                try:

                    ai_score = int(
                        ai_result.get(
                            "match_score",
                            0
                        )
                    )

                except (ValueError, TypeError):

                    ai_score = 0


                if ai_score < 0:
                    ai_score = 0


                if ai_score > 100:
                    ai_score = 100


                matched_skills = ai_result.get(
                    "matched_skills",
                    []
                )


                missing_skills = ai_result.get(
                    "missing_skills",
                    []
                )


                experience_match = ai_result.get(
                    "experience_match",
                    "Not specified"
                )


                match_reason = ai_result.get(
                    "match_reason",
                    "Not specified"
                )


                # =================================================
                # 25. CONVERT AI ARRAYS TO TEXT
                # =================================================

                if isinstance(
                    matched_skills,
                    list
                ):

                    matched_skills_text = ", ".join(
                        str(skill)
                        for skill in matched_skills
                    )

                else:

                    matched_skills_text = str(
                        matched_skills
                    )


                if isinstance(
                    missing_skills,
                    list
                ):

                    missing_skills_text = ", ".join(
                        str(skill)
                        for skill in missing_skills
                    )

                else:

                    missing_skills_text = str(
                        missing_skills
                    )


                if not matched_skills_text:
                    matched_skills_text = "None"


                if not missing_skills_text:
                    missing_skills_text = "None"


                # =================================================
                # 26. AI SCORE FILTER
                # =================================================

                if ai_score < AI_MIN_SCORE:

                    total_rejected += 1

                    print(
                        "Rejected by AI:",
                        title
                    )

                    print(
                        "AI Match Score:",
                        ai_score,
                        "/100"
                    )

                    continue


                # =================================================
                # 27. SALARY
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
                # 28. EXPERIENCE TEXT
                # =================================================

                experience = "Not specified"


                if any(
                    word in text
                    for word in fresher_words
                ):

                    experience = (
                        "Fresher / 0-2 years"
                    )

                elif high_experience:

                    experience = (
                        f"{high_experience.group(1)}+ years"
                    )


                # =================================================
                # 29. SKILLS FROM JOB DESCRIPTION
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
                    ],

                    "Electronics": [
                        "electronics"
                    ],

                    "Telecommunication": [
                        "telecommunication",
                        "telecom"
                    ],

                    "Microcontroller": [
                        "microcontroller"
                    ],

                    "Microprocessor": [
                        "microprocessor"
                    ],

                    "PCB": [
                        "pcb"
                    ],

                    "Circuit Design": [
                        "circuit design"
                    ],

                    "Hardware": [
                        "hardware"
                    ],

                    "UART": [
                        "uart"
                    ],

                    "SPI": [
                        "spi"
                    ],

                    "I2C": [
                        "i2c"
                    ],

                    "CAN Bus": [
                        "can bus"
                    ],

                    "RF": [
                        "rf"
                    ],

                    "Analog Electronics": [
                        "analog electronics"
                    ],

                    "Digital Electronics": [
                        "digital electronics"
                    ]
                }


                for skill, keywords in skill_keywords.items():

                    if any(
                        keyword in text
                        for keyword in keywords
                    ):

                        skills.append(skill)


                skills_text = ", ".join(
                    skills
                )


                if not skills_text:

                    skills_text = "Not specified"


                # =================================================
                # 30. ADD TO GOOGLE SHEET
                # =================================================

                row = [

                    str(date.today()),

                    company,

                    title,

                    job_location,

                    salary,

                    experience,

                    skills_text,

                    ai_score,

                    apply_link,

                    "Not Applied",

                    matched_skills_text,

                    missing_skills_text,

                    experience_match,

                    match_reason
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


                    print("\n" + "=" * 70)

                    print(
                        "🎯 NEW AI-MATCHED JOB ADDED"
                    )

                    print(
                        "Job:",
                        title
                    )

                    print(
                        "Company:",
                        company
                    )

                    print(
                        "Location:",
                        job_location
                    )

                    print(
                        "Salary:",
                        salary
                    )

                    print(
                        "Experience:",
                        experience
                    )

                    print(
                        "Skills:",
                        skills_text
                    )

                    print(
                        "Matched Skills:",
                        matched_skills_text
                    )

                    print(
                        "Missing Skills:",
                        missing_skills_text
                    )

                    print(
                        "Experience Match:",
                        experience_match
                    )

                    print(
                        "AI Match Score:",
                        ai_score,
                        "/100"
                    )

                    print(
                        "Reason:",
                        match_reason
                    )

                    print(
                        "Apply:",
                        apply_link
                    )

                    print("=" * 70)


                except Exception as error:

                    print(
                        "Could not add job to Sheet:",
                        error
                    )


                # Small delay between Gemini requests

                time.sleep(1)


# =========================================================
# 31. FINAL SUMMARY
# =========================================================

print("\n" + "=" * 70)

print(
    "JOB SEARCH COMPLETED"
)

print(
    f"Total jobs seen: {total_seen}"
)

print(
    f"Jobs analyzed by Gemini: {total_ai_analyzed}"
)

print(
    f"New AI-matched jobs added: {total_added}"
)

print(
    f"Jobs rejected: {total_rejected}"
)

print("=" * 70)

print(
    "AI Job Tracker V2 Finished Successfully!"
)
