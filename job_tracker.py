import os
import re
import json
import time
from datetime import datetime

import requests
import gspread
from google.oauth2.service_account import Credentials
from google import genai


# ============================================================
# CONFIGURATION
# ============================================================

ADZUNA_APP_ID = os.environ.get("ADZUNA_APP_ID")
ADZUNA_APP_KEY = os.environ.get("ADZUNA_APP_KEY")

GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get(
    "GOOGLE_SERVICE_ACCOUNT_JSON"
)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")


# Google Sheet
SPREADSHEET_ID = "1TeQSVAHVitgB2T6iBte-MOjHQeyHR-RS0HwTltgjIRo"

# First worksheet
WORKSHEET_NAME = "Sheet1"


# Gemini
AI_MODEL = "gemini-3.6-flash"

# Keep this low because Gemini free-tier quota is limited
MAX_AI_JOBS = 15

# Minimum score required to add a job
AI_MIN_SCORE = 60


# Adzuna
API_URL = "https://api.adzuna.com/v1/api/jobs/in/search/{page}"

RESULTS_PER_PAGE = 20
TOTAL_PAGES = 3

MAX_API_RETRIES = 3
RETRY_DELAY_SECONDS = 3


# Delay between Gemini requests
GEMINI_DELAY_SECONDS = 2


# Search priority
SEARCH_QUERIES = [
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
    "Junior Robotics Engineer",
]


LOCATIONS = [
    "Pune",
    "Remote",
]


# ============================================================
# FILTER WORDS
# ============================================================

SENIOR_TITLE_WORDS = [
    "senior",
    "sr.",
    "sr ",
    "lead",
    "manager",
    "principal",
    "architect",
    "director",
    "head of",
    "vice president",
    "vp ",
]


FRESHER_WORDS = [
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
    "1 to 2 years",
    "0–1 years",
    "0–2 years",
    "1–2 years",
]


# ============================================================
# GLOBAL VARIABLES
# ============================================================

gemini_client = None

gemini_rate_limited = False

ai_jobs_processed = 0

new_jobs_added = 0

duplicate_jobs = 0

rejected_jobs = 0

total_jobs_seen = 0

adzuna_api_errors = 0


# ============================================================
# GEMINI INITIALIZATION
# ============================================================

def initialize_gemini():

    global gemini_client

    if not GEMINI_API_KEY:
        print("ERROR: GEMINI_API_KEY not found.")
        return False

    try:

        gemini_client = genai.Client(
            api_key=GEMINI_API_KEY
        )

        print("Gemini client initialized successfully!")

        return True

    except Exception as e:

        print("Gemini initialization error:")
        print(e)

        return False


# ============================================================
# LOAD PROFILE
# ============================================================

def load_profile():

    try:

        with open(
            "profile.json",
            "r",
            encoding="utf-8"
        ) as file:

            profile = json.load(file)

        print("Candidate profile loaded successfully!")

        return profile

    except Exception as e:

        print("Profile loading error:")
        print(e)

        return None


# ============================================================
# GOOGLE SHEETS CONNECTION
# ============================================================

def connect_google_sheet():

    if not GOOGLE_SERVICE_ACCOUNT_JSON:

        print(
            "ERROR: GOOGLE_SERVICE_ACCOUNT_JSON not found."
        )

        return None

    try:

        service_account_info = json.loads(
            GOOGLE_SERVICE_ACCOUNT_JSON
        )

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]

        credentials = Credentials.from_service_account_info(
            service_account_info,
            scopes=scopes,
        )

        client = gspread.authorize(credentials)

        spreadsheet = client.open_by_key(
            SPREADSHEET_ID
        )

        worksheet = spreadsheet.worksheet(
            WORKSHEET_NAME
        )

        print("Google Sheet connected successfully!")

        return worksheet

    except Exception as e:

        print("Google Sheet connection error:")
        print(e)

        return None


# ============================================================
# UPDATE SHEET HEADERS
# ============================================================

def update_sheet_headers(worksheet):

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
        "Match Reason",
    ]

    try:

        worksheet.update(
            "A1:N1",
            [headers]
        )

        print(
            "Google Sheet headers updated for V2.1!"
        )

    except Exception as e:

        print("Header update error:")
        print(e)


# ============================================================
# GET EXISTING JOBS
# ============================================================

def get_existing_jobs(worksheet):

    existing_jobs = set()

    try:

        rows = worksheet.get_all_values()

        for row in rows[1:]:

            if len(row) >= 3:

                company = row[1].strip().lower()

                job_role = row[2].strip().lower()

                if company and job_role:

                    existing_jobs.add(
                        (
                            company,
                            job_role
                        )
                    )

        print(
            f"Existing jobs in Sheet: {len(existing_jobs)}"
        )

    except Exception as e:

        print("Error reading existing jobs:")
        print(e)

    return existing_jobs


# ============================================================
# NORMALIZE URL
# ============================================================

def normalize_url(url):

    if not url:
        return ""

    return url.split("?")[0].strip().lower()


# ============================================================
# CHECK DUPLICATE
# ============================================================

def is_duplicate(job, existing_jobs):

    company = (
        job.get("company", {})
        .get("display_name", "")
        .strip()
        .lower()
    )

    title = (
        job.get("title", "")
        .strip()
        .lower()
    )

    key = (
        company,
        title
    )

    return key in existing_jobs


# ============================================================
# CHECK SENIOR TITLE
# ============================================================

def is_senior_title(title):

    title_lower = title.lower()

    for word in SENIOR_TITLE_WORDS:

        if word in title_lower:

            return True

    return False


# ============================================================
# CHECK 3+ YEARS EXPERIENCE
# ============================================================

def requires_three_plus_years(text):

    if not text:

        return False

    text_lower = text.lower()

    patterns = [

        r"\b3\+?\s*years?\b",
        r"\b4\+?\s*years?\b",
        r"\b5\+?\s*years?\b",
        r"\b6\+?\s*years?\b",
        r"\b7\+?\s*years?\b",
        r"\b8\+?\s*years?\b",
        r"\b9\+?\s*years?\b",
        r"\b10\+?\s*years?\b",

        r"\b3\s*to\s*5\s*years?\b",
        r"\b4\s*to\s*6\s*years?\b",
        r"\b5\s*to\s*7\s*years?\b",
        r"\b6\s*to\s*8\s*years?\b",
        r"\b7\s*to\s*10\s*years?\b",

        r"\bminimum\s+3\s*years?\b",
        r"\bminimum\s+4\s*years?\b",
        r"\bminimum\s+5\s*years?\b",

        r"\bat\s+least\s+3\s*years?\b",
        r"\bat\s+least\s+4\s*years?\b",
        r"\bat\s+least\s+5\s*years?\b",
    ]

    for pattern in patterns:

        if re.search(
            pattern,
            text_lower
        ):

            return True

    return False


# ============================================================
# CHECK FRESHER / ENTRY LEVEL
# ============================================================

def detect_fresher(text):

    if not text:

        return False

    text_lower = text.lower()

    for word in FRESHER_WORDS:

        if word in text_lower:

            return True

    return False


# ============================================================
# FORMAT SALARY
# ============================================================

def format_salary(job):

    salary_min = job.get(
        "salary_min"
    )

    salary_max = job.get(
        "salary_max"
    )

    if salary_min and salary_max:

        return (
            f"{salary_min:.0f} - "
            f"{salary_max:.0f} per year"
        )

    if salary_min:

        return f"{salary_min:.0f} per year"

    if salary_max:

        return f"{salary_max:.0f} per year"

    return "Not specified"


# ============================================================
# GEMINI AI ANALYSIS
# ============================================================

def analyze_job_with_gemini(
    job,
    profile
):

    global gemini_rate_limited

    if gemini_rate_limited:

        return None

    title = job.get(
        "title",
        "Unknown"
    )

    company = (
        job.get("company", {})
        .get(
            "display_name",
            "Unknown"
        )
    )

    location = (
        job.get("location", {})
        .get(
            "display_name",
            "Unknown"
        )
    )

    description = job.get(
        "description",
        ""
    )

    salary = format_salary(job)

    profile_text = json.dumps(
        profile,
        indent=2
    )

    prompt = f"""
You are an AI job matching system.

Analyze the following job against the candidate profile.

CANDIDATE PROFILE:
{profile_text}

JOB INFORMATION:

Title:
{title}

Company:
{company}

Location:
{location}

Salary:
{salary}

Description:
{description}

Return ONLY valid JSON.

Use exactly this structure:

{{
    "match_score": 0,
    "matched_skills": [],
    "missing_skills": [],
    "experience_match": "",
    "reason": ""
}}

Rules:

1. match_score must be between 0 and 100.
2. Consider the candidate's education, skills, experience level and location.
3. The candidate is a fresher / entry-level candidate.
4. Do not assume skills that are not present in the profile.
5. Clearly identify missing technical skills.
6. Give a concise reason for the score.
7. Do not use markdown.
8. Return JSON only.
"""

    try:

        interaction = gemini_client.interactions.create(
            model=AI_MODEL,
            input=prompt
        )

        response_text = interaction.output_text.strip()

        # Remove markdown fences if Gemini adds them
        response_text = re.sub(
            r"```json",
            "",
            response_text,
            flags=re.IGNORECASE
        )

        response_text = re.sub(
            r"```",
            "",
            response_text
        )

        response_text = response_text.strip()

        # Extract JSON
        json_match = re.search(
            r"\{.*\}",
            response_text,
            re.DOTALL
        )

        if not json_match:

            print(
                "Gemini returned invalid JSON."
            )

            return None

        result = json.loads(
            json_match.group(0)
        )

        return result

    except Exception as e:

        error_text = str(e)

        # Detect Gemini rate limit
        if (
            "429" in error_text
            or "rate limit" in error_text.lower()
            or "too_many_requests" in error_text.lower()
        ):

            gemini_rate_limited = True

            print(
                "\n"
                + "!" * 70
            )

            print(
                "⚠️ GEMINI RATE LIMIT REACHED"
            )

            print(
                "Gemini AI analysis will STOP "
                "for this workflow."
            )

            print(
                "No more Gemini requests will be sent."
            )

            print(
                "!" * 70
                + "\n"
            )

            return None

        print(
            "Gemini AI Error:"
        )

        print(error_text)

        return None


# ============================================================
# FETCH ADZUNA PAGE
# ============================================================

def fetch_adzuna_page(
    page,
    query,
    location
):

    global adzuna_api_errors

    params = {

        "app_id": ADZUNA_APP_ID,

        "app_key": ADZUNA_APP_KEY,

        "results_per_page":
            RESULTS_PER_PAGE,

        "what": query,

        "where": location,

        "content-type":
            "application/json",
    }

    for attempt in range(
        1,
        MAX_API_RETRIES + 1
    ):

        try:

            url = API_URL.format(
                page=page
            )

            response = requests.get(
                url,
                params=params,
                timeout=30
            )

            if response.status_code == 200:

                data = response.json()

                return data.get(
                    "results",
                    []
                )

            # Retry temporary server errors
            if response.status_code in [
                500,
                502,
                503,
                504
            ]:

                print(
                    f"Adzuna server error "
                    f"{response.status_code}. "
                    f"Retry {attempt}/"
                    f"{MAX_API_RETRIES}"
                )

                time.sleep(
                    RETRY_DELAY_SECONDS
                    * attempt
                )

                continue

            print(
                "Adzuna API error:",
                response.status_code
            )

            adzuna_api_errors += 1

            return []

        except requests.RequestException as e:

            print(
                "Adzuna request error:"
            )

            print(e)

            if attempt < MAX_API_RETRIES:

                time.sleep(
                    RETRY_DELAY_SECONDS
                    * attempt
                )

            else:

                adzuna_api_errors += 1

                return []

    adzuna_api_errors += 1

    return []


# ============================================================
# VERIFY SHEET APPEND
# ============================================================

def verify_sheet_append(
    worksheet,
    company,
    job_title
):

    try:

        rows = worksheet.get_all_values()

        target_company = (
            company.strip().lower()
        )

        target_title = (
            job_title.strip().lower()
        )

        # Search from bottom to top
        for row_number in range(
            len(rows) - 1,
            0,
            -1
        ):

            row = rows[row_number]

            if len(row) < 3:

                continue

            sheet_company = (
                row[1]
                .strip()
                .lower()
            )

            sheet_title = (
                row[2]
                .strip()
                .lower()
            )

            if (
                sheet_company
                == target_company
                and
                sheet_title
                == target_title
            ):

                actual_row = (
                    row_number + 1
                )

                print(
                    "✅ GOOGLE SHEET "
                    "VERIFICATION SUCCESS"
                )

                print(
                    f"Company: {company}"
                )

                print(
                    f"Job: {job_title}"
                )

                print(
                    f"Sheet Row: {actual_row}"
                )

                return True

        print(
            "❌ GOOGLE SHEET "
            "VERIFICATION FAILED"
        )

        print(
            f"Could not find: "
            f"{company} - {job_title}"
        )

        return False

    except Exception as e:

        print(
            "Sheet verification error:"
        )

        print(e)

        return False


# ============================================================
# APPEND JOB TO GOOGLE SHEET
# ============================================================

def append_job_to_sheet(
    worksheet,
    job,
    ai_result
):

    global new_jobs_added

    company = (
        job.get("company", {})
        .get(
            "display_name",
            "Unknown"
        )
    )

    job_title = job.get(
        "title",
        "Unknown"
    )

    location = (
        job.get("location", {})
        .get(
            "display_name",
            "Not specified"
        )
    )

    salary = format_salary(job)

    experience = "Not specified"

    if detect_fresher(
        job.get(
            "description",
            ""
        )
    ):

        experience = "Fresher / Entry Level"

    skills = job.get(
        "description",
        ""
    )

    # Keep skills field simple
    if len(skills) > 300:

        skills = skills[:300]

    apply_link = job.get(
        "redirect_url",
        ""
    )

    match_score = ai_result.get(
        "match_score",
        0
    )

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
        ""
    )

    reason = ai_result.get(
        "reason",
        ""
    )

    if isinstance(
        matched_skills,
        list
    ):

        matched_skills_text = ", ".join(
            str(x)
            for x in matched_skills
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
            str(x)
            for x in missing_skills
        )

    else:

        missing_skills_text = str(
            missing_skills
        )

    row = [

        datetime.now().strftime(
            "%Y-%m-%d"
        ),

        company,

        job_title,

        location,

        salary,

        experience,

        skills,

        match_score,

        apply_link,

        "Not Applied",

        matched_skills_text,

        missing_skills_text,

        experience_match,

        reason,
    ]

    try:

        print(
            "\n"
            + "=" * 70
        )

        print(
            "📊 WRITING JOB TO GOOGLE SHEET..."
        )

        print(
            f"Company: {company}"
        )

        print(
            f"Job: {job_title}"
        )

        print(
            f"Score: {match_score}"
        )

        # Actual Google Sheets write
        worksheet.append_row(
            row,
            value_input_option="USER_ENTERED"
        )

        print(
            "✅ GOOGLE SHEET APPEND SUCCESS"
        )

        # Verify actual data exists
        verified = verify_sheet_append(
            worksheet,
            company,
            job_title
        )

        if not verified:

            print(
                "❌ Sheet append verification failed."
            )

            return False

        # Only count after actual successful write
        new_jobs_added += 1

        print(
            "✅ Job successfully saved "
            "and verified in Google Sheet."
        )

        print(
            "=" * 70
            + "\n"
        )

        return True

    except Exception as e:

        print(
            "\n"
            "❌ GOOGLE SHEET APPEND ERROR"
        )

        print(e)

        return False


# ============================================================
# MAIN PROGRAM
# ============================================================

def main():

    global ai_jobs_processed
    global duplicate_jobs
    global rejected_jobs
    global total_jobs_seen

    print(
        "\n"
        + "=" * 70
    )

    print(
        "AI Job Tracker V2.1 Started!"
    )

    print(
        "=" * 70
        + "\n"
    )

    # --------------------------------------------------------
    # Validate environment variables
    # --------------------------------------------------------

    if not ADZUNA_APP_ID:

        print(
            "ERROR: ADZUNA_APP_ID not found."
        )

        return

    if not ADZUNA_APP_KEY:

        print(
            "ERROR: ADZUNA_APP_KEY not found."
        )

        return

    # --------------------------------------------------------
    # Initialize Gemini
    # --------------------------------------------------------

    if not initialize_gemini():

        return

    # --------------------------------------------------------
    # Load candidate profile
    # --------------------------------------------------------

    profile = load_profile()

    if not profile:

        return

    # --------------------------------------------------------
    # Connect Google Sheet
    # --------------------------------------------------------

    worksheet = connect_google_sheet()

    if worksheet is None:

        return

    # --------------------------------------------------------
    # Update headers
    # --------------------------------------------------------

    update_sheet_headers(
        worksheet
    )

    # --------------------------------------------------------
    # Existing jobs
    # --------------------------------------------------------

    existing_jobs = get_existing_jobs(
        worksheet
    )

    # ========================================================
    # SEARCH LOOP
    # ========================================================

    stop_all_search = False

    for query in SEARCH_QUERIES:

        if gemini_rate_limited:

            break

        print(
            "\n"
            + "=" * 70
        )

        print(
            f"Searching: {query}"
        )

        # ----------------------------------------------------
        # Location loop
        # ----------------------------------------------------

        for location in LOCATIONS:

            if gemini_rate_limited:

                break

            print(
                f"\nLocation: {location}"
            )

            print(
                "=" * 70
            )

            # ------------------------------------------------
            # Page loop
            # ------------------------------------------------

            for page in range(
                1,
                TOTAL_PAGES + 1
            ):

                if gemini_rate_limited:

                    print(
                        "Gemini rate limit reached."
                    )

                    print(
                        "Stopping further "
                        "Gemini analysis."
                    )

                    stop_all_search = True

                    break

                if ai_jobs_processed >= MAX_AI_JOBS:

                    print(
                        "Maximum Gemini analysis "
                        "limit reached."
                    )

                    stop_all_search = True

                    break

                print(
                    f"Fetching page {page}..."
                )

                jobs = fetch_adzuna_page(
                    page,
                    query,
                    location
                )

                print(
                    f"Jobs received: "
                    f"{len(jobs)}"
                )

                # --------------------------------------------
                # Job loop
                # --------------------------------------------

                for job in jobs:

                    if gemini_rate_limited:

                        print(
                            "Gemini rate limit reached."
                        )

                        print(
                            "Stopping further "
                            "Gemini analysis."
                        )

                        stop_all_search = True

                        break

                    if ai_jobs_processed >= MAX_AI_JOBS:

                        print(
                            "Maximum Gemini analysis "
                            "limit reached."
                        )

                        stop_all_search = True

                        break

                    total_jobs_seen += 1

                    title = job.get(
                        "title",
                        ""
                    )

                    company = (
                        job.get(
                            "company",
                            {}
                        )
                        .get(
                            "display_name",
                            "Unknown"
                        )
                    )

                    description = job.get(
                        "description",
                        ""
                    )

                    # ----------------------------------------
                    # Duplicate check
                    # ----------------------------------------

                    if is_duplicate(
                        job,
                        existing_jobs
                    ):

                        duplicate_jobs += 1

                        print(
                            f"Skipping duplicate: "
                            f"{title}"
                        )

                        continue

                    # ----------------------------------------
                    # Senior title filter
                    # ----------------------------------------

                    if is_senior_title(
                        title
                    ):

                        rejected_jobs += 1

                        print(
                            f"Rejected senior/lead title: "
                            f"{title}"
                        )

                        continue

                    # ----------------------------------------
                    # 3+ years filter
                    # ----------------------------------------

                    if requires_three_plus_years(
                        description
                    ):

                        rejected_jobs += 1

                        print(
                            f"Rejected 3+ years: "
                            f"{title}"
                        )

                        continue

                    # ----------------------------------------
                    # Gemini analysis
                    # ----------------------------------------

                    print(
                        "\n"
                        + "-" * 70
                    )

                    print(
                        "Sending job to Gemini AI..."
                    )

                    print(
                        f"Job: {title}"
                    )

                    print(
                        f"Company: {company}"
                    )

                    print(
                        f"AI Analysis: "
                        f"{ai_jobs_processed + 1} / "
                        f"{MAX_AI_JOBS}"
                    )

                    ai_result = (
                        analyze_job_with_gemini(
                            job,
                            profile
                        )
                    )

                    # Count this Gemini attempt
                    ai_jobs_processed += 1

                    # ----------------------------------------
                    # Rate limit happened
                    # ----------------------------------------

                    if gemini_rate_limited:

                        print(
                            "Gemini quota/rate "
                            "limit reached."
                        )

                        print(
                            "Stopping further "
                            "Gemini analysis."
                        )

                        stop_all_search = True

                        break

                    # ----------------------------------------
                    # Invalid AI response
                    # ----------------------------------------

                    if ai_result is None:

                        rejected_jobs += 1

                        print(
                            "Gemini returned no "
                            "valid analysis."
                        )

                        continue

                    # ----------------------------------------
                    # Score
                    # ----------------------------------------

                    try:

                        ai_score = int(
                            ai_result.get(
                                "match_score",
                                0
                            )
                        )

                    except (
                        ValueError,
                        TypeError
                    ):

                        ai_score = 0

                    # ----------------------------------------
                    # Reject low score
                    # ----------------------------------------

                    if ai_score < AI_MIN_SCORE:

                        rejected_jobs += 1

                        print(
                            f"Rejected by AI: "
                            f"{title}"
                        )

                        print(
                            f"AI Match Score: "
                            f"{ai_score} /100"
                        )

                        continue

                    # ----------------------------------------
                    # NEW MATCH
                    # ----------------------------------------

                    print(
                        "\n"
                        + "=" * 70
                    )

                    print(
                        "🎯 NEW AI-MATCHED JOB FOUND"
                    )

                    print(
                        f"Job: {title}"
                    )

                    print(
                        f"Company: {company}"
                    )

                    print(
                        "Location:",
                        job.get(
                            "location",
                            {}
                        ).get(
                            "display_name",
                            "Not specified"
                        )
                    )

                    print(
                        "Salary:",
                        format_salary(job)
                    )

                    print(
                        "Experience:",
                        "Fresher / Entry Level"
                        if detect_fresher(
                            description
                        )
                        else "Not specified"
                    )

                    print(
                        "Skills:",
                        "Embedded"
                    )

                    print(
                        "Matched Skills:",
                        ai_result.get(
                            "matched_skills",
                            []
                        )
                    )

                    print(
                        "Missing Skills:",
                        ai_result.get(
                            "missing_skills",
                            []
                        )
                    )

                    print(
                        "Experience Match:",
                        ai_result.get(
                            "experience_match",
                            ""
                        )
                    )

                    print(
                        f"AI Match Score: "
                        f"{ai_score} /100"
                    )

                    print(
                        "Reason:",
                        ai_result.get(
                            "reason",
                            ""
                        )
                    )

                    print(
                        "Apply:",
                        job.get(
                            "redirect_url",
                            ""
                        )
                    )

                    # ----------------------------------------
                    # WRITE + VERIFY SHEET
                    # ----------------------------------------

                    save_success = (
                        append_job_to_sheet(
                            worksheet,
                            job,
                            ai_result
                        )
                    )

                    if save_success:

                        # Add to duplicate set
                        existing_jobs.add(
                            (
                                company
                                .strip()
                                .lower(),

                                title
                                .strip()
                                .lower()
                            )
                        )

                    else:

                        print(
                            "⚠️ Job was NOT confirmed "
                            "inside Google Sheet."
                        )

                    # ----------------------------------------
                    # Delay
                    # ----------------------------------------

                    if not gemini_rate_limited:

                        time.sleep(
                            GEMINI_DELAY_SECONDS
                        )

                # End job loop

                if stop_all_search:

                    break

            # End page loop

            if stop_all_search:

                break

        # End location loop

        if stop_all_search:

            break

    # ========================================================
    # FINAL SUMMARY
    # ========================================================

    print(
        "\n"
        + "=" * 70
    )

    print(
        "JOB SEARCH COMPLETED"
    )

    print(
        f"Total jobs seen: "
        f"{total_jobs_seen}"
    )

    print(
        f"Jobs analyzed by Gemini: "
        f"{ai_jobs_processed}"
    )

    print(
        f"New AI-matched jobs added: "
        f"{new_jobs_added}"
    )

    print(
        f"Duplicate jobs skipped: "
        f"{duplicate_jobs}"
    )

    print(
        f"Jobs rejected: "
        f"{rejected_jobs}"
    )

    print(
        f"Adzuna API errors: "
        f"{adzuna_api_errors}"
    )

    if gemini_rate_limited:

        print(
            "Gemini status: "
            "RATE LIMIT REACHED"
        )

        print(
            "Remaining jobs were not "
            "sent to Gemini."
        )

    elif ai_jobs_processed >= MAX_AI_JOBS:

        print(
            "Gemini status: "
            "MAX ANALYSIS LIMIT REACHED"
        )

    else:

        print(
            "Gemini status: "
            "AVAILABLE"
        )

    print(
        "=" * 70
    )

    print(
        "\nAI Job Tracker V2.1 "
        "Finished Successfully!"
    )


# ============================================================
# PROGRAM ENTRY POINT
# ============================================================

if __name__ == "__main__":

    main()
