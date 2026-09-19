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
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

SPREADSHEET_ID = "1TeQSVAHVitgB2T6iBte-MOjHQeyHR-RS0HwTltgjIRo"
WORKSHEET_NAME = "Sheet1"

GEMINI_MODEL = "gemini-3.6-flash"
OPENROUTER_MODEL = "openrouter/free"

MAX_AI_JOBS = 15
AI_MIN_SCORE = 60

ADZUNA_API_URL = "https://api.adzuna.com/v1/api/jobs/in/search/{page}"
RESULTS_PER_PAGE = 20
TOTAL_PAGES = 3
MAX_API_RETRIES = 3
RETRY_DELAY_SECONDS = 3
AI_DELAY_SECONDS = 2
OPENROUTER_TIMEOUT_SECONDS = 45

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

LOCATIONS = ["Pune", "Remote"]

SENIOR_TITLE_WORDS = [
    "senior", "sr.", "sr ", "lead", "manager", "principal",
    "architect", "director", "head of", "vice president", "vp ",
]

FRESHER_WORDS = [
    "fresher", "entry level", "entry-level", "junior", "trainee",
    "graduate", "intern", "0-1 years", "0-2 years",
    "0 to 1 years", "0 to 2 years", "1-2 years",
    "1 to 2 years", "0–1 years", "0–2 years", "1–2 years",
]

HEADERS = [
    "Date", "Company", "Job Role", "Location", "Salary", "Experience",
    "Skills", "Match Score", "Apply Link", "Status", "Matched Skills",
    "Missing Skills", "Experience Match", "Match Reason",
]

gemini_client = None
gemini_available = True
gemini_rate_limited = False

ai_jobs_processed = 0
new_jobs_added = 0
duplicate_jobs = 0
rejected_jobs = 0
total_jobs_seen = 0
adzuna_api_errors = 0
openrouter_fallbacks = 0
openrouter_errors = 0


# ============================================================
# BASIC HELPERS
# ============================================================

def initialize_gemini():
    global gemini_client, gemini_available

    if not GEMINI_API_KEY:
        print("WARNING: GEMINI_API_KEY not found.")
        gemini_available = False
        return False

    try:
        gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        print("Gemini client initialized successfully!")
        return True
    except Exception as exc:
        print("Gemini initialization error:", exc)
        gemini_available = False
        return False


def load_profile():
    try:
        with open("profile.json", "r", encoding="utf-8") as file:
            profile = json.load(file)
        print("Candidate profile loaded successfully!")
        return profile
    except Exception as exc:
        print("Profile loading error:", exc)
        return None


def connect_google_sheet():
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        print("ERROR: GOOGLE_SERVICE_ACCOUNT_JSON not found.")
        return None

    try:
        service_account_info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]

        credentials = Credentials.from_service_account_info(
            service_account_info,
            scopes=scopes,
        )

        client = gspread.authorize(credentials)
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        worksheet = spreadsheet.worksheet(WORKSHEET_NAME)

        print("Google Sheet connected successfully!")
        return worksheet

    except Exception as exc:
        print("Google Sheet connection error:", exc)
        return None


def update_sheet_headers(worksheet):
    try:
        # Named arguments avoid the current gspread deprecation warning.
        worksheet.update(
            range_name="A1:N1",
            values=[HEADERS],
        )
        print("Google Sheet headers updated for V2.2!")

    except Exception as exc:
        print("Header update error:", exc)


def get_existing_jobs(worksheet):
    existing_jobs = set()

    try:
        rows = worksheet.get_all_values()

        for row in rows[1:]:
            if len(row) >= 3:
                company = row[1].strip().lower()
                title = row[2].strip().lower()

                if company and title:
                    existing_jobs.add((company, title))

        print(f"Existing jobs in Sheet: {len(existing_jobs)}")

    except Exception as exc:
        print("Error reading existing jobs:", exc)

    return existing_jobs


def is_duplicate(job, existing_jobs):
    company = (
        job.get("company", {})
        .get("display_name", "")
        .strip()
        .lower()
    )

    title = job.get("title", "").strip().lower()

    return (company, title) in existing_jobs


def is_senior_title(title):
    title_lower = title.lower()
    return any(word in title_lower for word in SENIOR_TITLE_WORDS)


def requires_three_plus_years(text):
    if not text:
        return False

    text_lower = text.lower()

    patterns = [
        r"\b(?:3|4|5|6|7|8|9|10)\+?\s*years?\b",
        r"\b(?:3|4|5|6|7)\s*to\s*(?:5|6|7|8|10)\s*years?\b",
        r"\bminimum\s+(?:3|4|5)\s*years?\b",
        r"\bat\s+least\s+(?:3|4|5)\s*years?\b",
    ]

    return any(re.search(pattern, text_lower) for pattern in patterns)


def detect_fresher(text):
    if not text:
        return False

    text_lower = text.lower()
    return any(word in text_lower for word in FRESHER_WORDS)


def format_salary(job):
    salary_min = job.get("salary_min")
    salary_max = job.get("salary_max")

    if salary_min and salary_max:
        return f"{salary_min:.0f} - {salary_max:.0f} per year"

    if salary_min:
        return f"{salary_min:.0f} per year"

    if salary_max:
        return f"{salary_max:.0f} per year"

    return "Not specified"


# ============================================================
# AI PROMPT / JSON PARSING
# ============================================================

def build_ai_prompt(job, profile):
    title = job.get("title", "Unknown")

    company = (
        job.get("company", {})
        .get("display_name", "Unknown")
    )

    location = (
        job.get("location", {})
        .get("display_name", "Unknown")
    )

    description = job.get("description", "")
    salary = format_salary(job)

    profile_text = json.dumps(
        profile,
        indent=2,
        ensure_ascii=False,
    )

    return f"""
You are an AI job matching system.

Compare this job against the candidate profile.

CANDIDATE PROFILE:
{profile_text}

JOB INFORMATION:
Title: {title}
Company: {company}
Location: {location}
Salary: {salary}

Description:
{description}

Return ONLY valid JSON with exactly this structure:

{{
  "match_score": 0,
  "matched_skills": [],
  "missing_skills": [],
  "experience_match": "",
  "reason": ""
}}

Rules:
1. match_score must be an integer from 0 to 100.
2. The candidate is a fresher / entry-level candidate.
3. Use only skills actually present in the candidate profile.
4. Identify important missing technical skills.
5. Consider education, skills, experience level and location.
6. Do not invent qualifications or experience.
7. Keep the reason concise.
8. Return JSON only. No markdown.
"""


def clean_ai_json(text):
    if not text:
        return ""

    text = text.strip()

    text = re.sub(
        r"```json\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"```\s*",
        "",
        text,
    )

    match = re.search(
        r"\{.*\}",
        text,
        flags=re.DOTALL,
    )

    return match.group(0) if match else text


def parse_ai_result(text):
    try:
        result = json.loads(clean_ai_json(text))

        score = int(result.get("match_score", 0))
        result["match_score"] = max(0, min(100, score))

        for field in ["matched_skills", "missing_skills"]:
            value = result.get(field, [])

            if not isinstance(value, list):
                result[field] = [str(value)] if value else []

        result["experience_match"] = str(
            result.get("experience_match", "")
        )

        result["reason"] = str(
            result.get("reason", "")
        )

        return result

    except (
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ) as exc:

        print("AI returned invalid JSON:", exc)
        return None


# ============================================================
# GEMINI PRIMARY
# ============================================================

def analyze_job_with_gemini(job, profile):
    global gemini_available
    global gemini_rate_limited

    if not gemini_client or not gemini_available:
        return None

    try:
        interaction = gemini_client.interactions.create(
            model=GEMINI_MODEL,
            input=build_ai_prompt(job, profile),
        )

        return parse_ai_result(
            interaction.output_text
        )

    except Exception as exc:
        error_text = str(exc)

        if (
            "429" in error_text
            or "rate limit" in error_text.lower()
            or "too_many_requests" in error_text.lower()
            or "quota" in error_text.lower()
        ):
            gemini_rate_limited = True

            print(
                "⚠️ GEMINI RATE LIMIT / QUOTA REACHED"
            )

            print(
                "➡️ Switching to OpenRouter FREE fallback."
            )

        else:
            print(
                "⚠️ Gemini unavailable."
            )

            print(
                "➡️ Switching to OpenRouter FREE fallback."
            )

            print(
                "Gemini error:",
                error_text,
            )

        gemini_available = False

        return None


# ============================================================
# OPENROUTER FREE FALLBACK
# ============================================================

def analyze_job_with_openrouter(job, profile):
    global openrouter_fallbacks
    global openrouter_errors

    if not OPENROUTER_API_KEY:
        print(
            "ERROR: OPENROUTER_API_KEY not found."
        )

        openrouter_errors += 1
        return None

    url = (
        "https://openrouter.ai/api/v1/"
        "chat/completions"
    )

    headers = {
        "Authorization":
            f"Bearer {OPENROUTER_API_KEY}",

        "Content-Type":
            "application/json",

        "X-Title":
            "AI Job Tracker",
    }

    payload = {
        "model": OPENROUTER_MODEL,

        "messages": [
            {
                "role": "user",
                "content": build_ai_prompt(
                    job,
                    profile,
                ),
            }
        ],

        "temperature": 0.1,

        "max_tokens": 500,
    }

    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=OPENROUTER_TIMEOUT_SECONDS,
        )

        if response.status_code != 200:
            openrouter_errors += 1

            print(
                "OpenRouter API error:",
                response.status_code,
            )

            print(
                response.text[:500]
            )

            return None

        data = response.json()

        choices = data.get(
            "choices",
            [],
        )

        if not choices:
            openrouter_errors += 1

            print(
                "OpenRouter returned no choices."
            )

            return None

        content = (
            choices[0]
            .get("message", {})
            .get("content", "")
        )

        result = parse_ai_result(
            content
        )

        if result is not None:
            openrouter_fallbacks += 1

            print(
                "✅ OpenRouter FREE fallback "
                "analysis successful!"
            )

        return result

    except requests.RequestException as exc:
        openrouter_errors += 1

        print(
            "OpenRouter request error:",
            exc,
        )

        return None

    except (
        ValueError,
        TypeError,
    ) as exc:
        openrouter_errors += 1

        print(
            "OpenRouter response error:",
            exc,
        )

        return None


def analyze_job_with_ai(job, profile):
    """
    Gemini is primary.
    OpenRouter/free is fallback when Gemini is unavailable,
    rate-limited or returns an unusable result.
    """

    if gemini_available:
        result = analyze_job_with_gemini(
            job,
            profile,
        )

        if result is not None:
            return result, "Gemini"

    print(
        "🔄 Trying OpenRouter FREE fallback..."
    )

    result = analyze_job_with_openrouter(
        job,
        profile,
    )

    if result is not None:
        return result, "OpenRouter"

    return None, "None"


# ============================================================
# ADZUNA
# ============================================================

def fetch_adzuna_page(
    page,
    query,
    location,
):
    global adzuna_api_errors

    params = {
        "app_id":
            ADZUNA_APP_ID,

        "app_key":
            ADZUNA_APP_KEY,

        "results_per_page":
            RESULTS_PER_PAGE,

        "what":
            query,

        "where":
            location,

        "content-type":
            "application/json",
    }

    for attempt in range(
        1,
        MAX_API_RETRIES + 1,
    ):

        try:
            url = ADZUNA_API_URL.format(
                page=page,
            )

            response = requests.get(
                url,
                params=params,
                timeout=30,
            )

            if response.status_code == 200:
                data = response.json()

                return data.get(
                    "results",
                    [],
                )

            if response.status_code in {
                500,
                502,
                503,
                504,
            }:

                print(
                    f"Adzuna server error "
                    f"{response.status_code}. "
                    f"Retry {attempt}/"
                    f"{MAX_API_RETRIES}"
                )

                if attempt < MAX_API_RETRIES:
                    time.sleep(
                        RETRY_DELAY_SECONDS
                        * attempt
                    )

                    continue

            print(
                "Adzuna API error:",
                response.status_code,
            )

            adzuna_api_errors += 1

            return []

        except requests.RequestException as exc:

            print(
                "Adzuna request error:",
                exc,
            )

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
# GOOGLE SHEETS VERIFY + WRITE
# ============================================================

def verify_sheet_append(
    worksheet,
    company,
    job_title,
):
    try:
        rows = worksheet.get_all_values()

        target_company = (
            company.strip().lower()
        )

        target_title = (
            job_title.strip().lower()
        )

        for row_number in range(
            len(rows) - 1,
            0,
            -1,
        ):

            row = rows[row_number]

            if len(row) < 3:
                continue

            if (
                row[1].strip().lower()
                == target_company
                and
                row[2].strip().lower()
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
                    f"Sheet Row: {actual_row}"
                )

                return True

        print(
            "❌ GOOGLE SHEET "
            "VERIFICATION FAILED"
        )

        return False

    except Exception as exc:

        print(
            "Sheet verification error:",
            exc,
        )

        return False


def append_job_to_sheet(
    worksheet,
    job,
    ai_result,
):
    global new_jobs_added

    company = (
        job.get("company", {})
        .get(
            "display_name",
            "Unknown",
        )
    )

    job_title = job.get(
        "title",
        "Unknown",
    )

    location = (
        job.get("location", {})
        .get(
            "display_name",
            "Not specified",
        )
    )

    description = job.get(
        "description",
        "",
    )

    salary = format_salary(
        job
    )

    experience = (
        "Fresher / Entry Level"
        if detect_fresher(
            description
        )
        else "Not specified"
    )

    skills = description[:300]

    match_score = ai_result.get(
        "match_score",
        0,
    )

    matched_skills = ai_result.get(
        "matched_skills",
        [],
    )

    missing_skills = ai_result.get(
        "missing_skills",
        [],
    )

    if not isinstance(
        matched_skills,
        list,
    ):
        matched_skills = [
            str(matched_skills)
        ]

    if not isinstance(
        missing_skills,
        list,
    ):
        missing_skills = [
            str(missing_skills)
        ]

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

        job.get(
            "redirect_url",
            "",
        ),

        "Not Applied",

        ", ".join(
            str(x)
            for x in matched_skills
        ),

        ", ".join(
            str(x)
            for x in missing_skills
        ),

        ai_result.get(
            "experience_match",
            "",
        ),

        ai_result.get(
            "reason",
            "",
        ),
    ]

    try:
        print(
            "📊 Writing job to Google Sheet..."
        )

        worksheet.append_row(
            row,
            value_input_option="USER_ENTERED",
        )

        verified = verify_sheet_append(
            worksheet,
            company,
            job_title,
        )

        if not verified:
            print(
                "❌ Job append could not "
                "be verified."
            )

            return False

        new_jobs_added += 1

        print(
            "✅ Job saved and verified "
            "in Google Sheet."
        )

        return True

    except Exception as exc:

        print(
            "❌ Google Sheet append error:",
            exc,
        )

        return False


# ============================================================
# MAIN
# ============================================================

def main():
    global ai_jobs_processed
    global duplicate_jobs
    global rejected_jobs
    global total_jobs_seen

    print(
        "\n" + "=" * 70
    )

    print(
        "AI Job Tracker V2.2 Started!"
    )

    print(
        "Gemini PRIMARY + OpenRouter FREE FALLBACK"
    )

    print(
        "=" * 70 + "\n"
    )

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

    initialize_gemini()

    if not OPENROUTER_API_KEY:
        print(
            "WARNING: OPENROUTER_API_KEY "
            "not found. Fallback unavailable."
        )

    profile = load_profile()

    if not profile:
        return

    worksheet = connect_google_sheet()

    if worksheet is None:
        return

    update_sheet_headers(
        worksheet
    )

    existing_jobs = get_existing_jobs(
        worksheet
    )

    stop_search = False

    for query in SEARCH_QUERIES:

        if stop_search:
            break

        print(
            "\n" + "=" * 70
        )

        print(
            f"Searching: {query}"
        )

        print(
            "=" * 70
        )

        for location in LOCATIONS:

            if stop_search:
                break

            print(
                f"\nLocation: {location}"
            )

            for page in range(
                1,
                TOTAL_PAGES + 1,
            ):

                if ai_jobs_processed >= MAX_AI_JOBS:

                    print(
                        "Maximum AI analysis "
                        "limit reached."
                    )

                    stop_search = True

                    break

                jobs = fetch_adzuna_page(
                    page,
                    query,
                    location,
                )

                print(
                    f"Page {page}: "
                    f"{len(jobs)} jobs received."
                )

                for job in jobs:

                    if ai_jobs_processed >= MAX_AI_JOBS:

                        stop_search = True

                        break

                    total_jobs_seen += 1

                    title = job.get(
                        "title",
                        "",
                    )

                    company = (
                        job.get("company", {})
                        .get(
                            "display_name",
                            "Unknown",
                        )
                    )

                    description = job.get(
                        "description",
                        "",
                    )

                    if is_duplicate(
                        job,
                        existing_jobs,
                    ):

                        duplicate_jobs += 1

                        print(
                            f"Skipping duplicate: "
                            f"{title}"
                        )

                        continue

                    if is_senior_title(
                        title
                    ):

                        rejected_jobs += 1

                        print(
                            f"Rejected senior/lead "
                            f"title: {title}"
                        )

                        continue

                    if requires_three_plus_years(
                        description
                    ):

                        rejected_jobs += 1

                        print(
                            f"Rejected 3+ years: "
                            f"{title}"
                        )

                        continue

                    ai_jobs_processed += 1

                    print(
                        "\n" + "-" * 70
                    )

                    print(
                        f"AI Analysis: "
                        f"{ai_jobs_processed}/"
                        f"{MAX_AI_JOBS}"
                    )

                    print(
                        f"Job: {title}"
                    )

                    print(
                        f"Company: {company}"
                    )

                    ai_result, provider = (
                        analyze_job_with_ai(
                            job,
                            profile,
                        )
                    )

                    if ai_result is None:

                        rejected_jobs += 1

                        print(
                            "❌ No valid AI "
                            "analysis available."
                        )

                        continue

                    try:

                        ai_score = int(
                            ai_result.get(
                                "match_score",
                                0,
                            )
                        )

                    except (
                        ValueError,
                        TypeError,
                    ):

                        ai_score = 0

                    print(
                        f"AI Provider: "
                        f"{provider}"
                    )

                    print(
                        f"AI Match Score: "
                        f"{ai_score}/100"
                    )

                    if ai_score < AI_MIN_SCORE:

                        rejected_jobs += 1

                        print(
                            f"Rejected by AI: "
                            f"{title}"
                        )

                        continue

                    print(
                        "\n" + "=" * 70
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
                            {},
                        ).get(
                            "display_name",
                            "Not specified",
                        ),
                    )

                    print(
                        "Salary:",
                        format_salary(job),
                    )

                    print(
                        "Matched Skills:",
                        ai_result.get(
                            "matched_skills",
                            [],
                        ),
                    )

                    print(
                        "Missing Skills:",
                        ai_result.get(
                            "missing_skills",
                            [],
                        ),
                    )

                    print(
                        "Experience Match:",
                        ai_result.get(
                            "experience_match",
                            "",
                        ),
                    )

                    print(
                        "Reason:",
                        ai_result.get(
                            "reason",
                            "",
                        ),
                    )

                    save_success = (
                        append_job_to_sheet(
                            worksheet,
                            job,
                            ai_result,
                        )
                    )

                    if save_success:

                        existing_jobs.add(
                            (
                                company
                                .strip()
                                .lower(),

                                title
                                .strip()
                                .lower(),
                            )
                        )

                    time.sleep(
                        AI_DELAY_SECONDS
                    )

                if stop_search:
                    break

            if stop_search:
                break

        if stop_search:
            break

    print(
        "\n" + "=" * 70
    )

    print(
        "JOB SEARCH COMPLETED"
    )

    print(
        "=" * 70
    )

    print(
        f"Total jobs seen: "
        f"{total_jobs_seen}"
    )

    print(
        f"Jobs analyzed: "
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

    print(
        f"OpenRouter fallback uses: "
        f"{openrouter_fallbacks}"
    )

    print(
        f"OpenRouter errors: "
        f"{openrouter_errors}"
    )

    if gemini_rate_limited:

        print(
            "Gemini status: RATE LIMIT / QUOTA "
            "REACHED → OPENROUTER FALLBACK"
        )

    elif gemini_available:

        print(
            "Gemini status: AVAILABLE"
        )

    else:

        print(
            "Gemini status: UNAVAILABLE → "
            "OPENROUTER FALLBACK"
        )

    print(
        "=" * 70
    )

    print(
        "AI Job Tracker V2.2 Finished!"
    )


if __name__ == "__main__":
    main()
