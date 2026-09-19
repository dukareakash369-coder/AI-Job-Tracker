# AI Job Tracker V2.2 - Fixed
# Gemini primary + OpenRouter free fallback
# Fixes:
# 1) Robust OpenRouter JSON extraction
# 2) Reliable Google Sheets append verification
# 3) Gemini quota fallback
# 4) Existing filtering / duplicate logic retained

import os
import re
import json
import time
from datetime import datetime

import requests
import gspread
from google.oauth2.service_account import Credentials
from google import genai


SPREADSHEET_ID = "1TeQSVAHVitgB2T6iBte-MOjHQeyHR-RS0HwTltgjIRo"
WORKSHEET_NAME = "Sheet1"

AI_MODEL = "gemini-3.6-flash"
OPENROUTER_MODEL = "openrouter/free"

MAX_AI_JOBS = 15
AI_MIN_SCORE = 60

RESULTS_PER_PAGE = 20
TOTAL_PAGES = 3

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

HEADERS = [
    "Date", "Company", "Job Role", "Location", "Salary", "Experience",
    "Skills", "Match Score", "Apply Link", "Status", "Matched Skills",
    "Missing Skills", "Experience Match", "Match Reason"
]

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

gemini_client = None
gemini_available = False
gemini_rate_limited = False

stats = {
    "total_jobs_seen": 0,
    "jobs_analyzed": 0,
    "new_jobs_added": 0,
    "duplicate_jobs_skipped": 0,
    "jobs_rejected": 0,
    "adzuna_api_errors": 0,
    "openrouter_fallback_uses": 0,
    "openrouter_errors": 0,
}

existing_job_keys = set()


def clean_text(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def normalize_key(value):
    value = clean_text(value).lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def safe_int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def safe_list(value):
    if isinstance(value, list):
        return [clean_text(x) for x in value if clean_text(x)]
    if value is None:
        return []
    value = clean_text(value)
    return [value] if value else []


def load_candidate_profile():
    path = "profile.json"
    if not os.path.exists(path):
        print("WARNING: profile.json not found. Using fallback profile.")
        return {
            "experience_level": "Entry-level / Fresher",
            "target_roles": [
                "Embedded Engineer", "Embedded Software Engineer",
                "Embedded Systems Engineer", "Firmware Engineer",
                "Embedded AI Engineer", "Edge AI Engineer",
                "IoT Engineer", "Robotics Engineer"
            ],
            "skills": [
                "C", "Embedded C", "C++", "Python", "Arduino", "ESP32",
                "Raspberry Pi", "Embedded Linux", "GPIO", "PWM",
                "UART", "SPI", "I2C", "Hardware Debugging"
            ],
            "education": "Electronics and Telecommunication Engineering"
        }

    try:
        with open(path, "r", encoding="utf-8") as f:
            profile = json.load(f)
        print("Candidate profile loaded successfully!")
        return profile
    except Exception as exc:
        print(f"WARNING: Could not load profile.json: {exc}")
        return {}


def initialize_gemini():
    global gemini_client, gemini_available
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        print("Gemini API key not found. OpenRouter will be used.")
        return
    try:
        gemini_client = genai.Client(api_key=key)
        gemini_available = True
        print("Gemini client initialized successfully!")
    except Exception as exc:
        print(f"Gemini initialization failed: {exc}")


def build_ai_prompt(job, profile):
    return f"""
You are evaluating a job for an entry-level Electronics and Telecommunication
Engineering candidate targeting Embedded Systems, Embedded AI, Edge AI, IoT,
Firmware and Robotics roles.

Candidate profile:
{json.dumps(profile, ensure_ascii=False)}

Job:
Company: {clean_text(job.get("company", "Unknown"))}
Title: {clean_text(job.get("title", ""))}
Location: {clean_text(job.get("location", ""))}
Description:
{clean_text(job.get("description", ""))[:12000]}

Return ONLY one valid JSON object. Do not use Markdown fences.
Do not add explanations before or after the JSON.

Required schema:
{{
  "match_score": 0,
  "matched_skills": [],
  "missing_skills": [],
  "experience_match": "",
  "reason": ""
}}

Rules:
- match_score must be an integer from 0 to 100.
- Consider role relevance, candidate skills, location, education/experience
  level and job requirements.
- Do not invent candidate skills.
- Keep reason concise.
"""


def extract_json_object(text):
    """Extract the first complete JSON object from an AI response."""
    if text is None:
        return None

    text = str(text).strip()
    if not text:
        return None

    text = re.sub(r"^\s*```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```\s*$", "", text)

    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escaped = False

    for i in range(start, len(text)):
        ch = text[i]

        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start:i + 1]
                try:
                    obj = json.loads(candidate)
                    return obj if isinstance(obj, dict) else None
                except json.JSONDecodeError:
                    return None

    return None


def normalize_ai_result(data):
    if not isinstance(data, dict):
        return None

    score = max(0, min(100, safe_int(data.get("match_score", 0))))
    return {
        "match_score": score,
        "matched_skills": safe_list(data.get("matched_skills")),
        "missing_skills": safe_list(data.get("missing_skills")),
        "experience_match": clean_text(data.get("experience_match")),
        "reason": clean_text(data.get("reason")),
    }


def analyze_with_gemini(job, profile):
    global gemini_available, gemini_rate_limited

    if not gemini_available or gemini_rate_limited or gemini_client is None:
        return None

    try:
        interaction = gemini_client.interactions.create(
            model=AI_MODEL,
            input=build_ai_prompt(job, profile)
        )
        raw = getattr(interaction, "output_text", None)
        result = normalize_ai_result(extract_json_object(raw))

        if result is None:
            print("Gemini returned invalid JSON.")
            return None

        return result

    except Exception as exc:
        msg = str(exc).lower()
        if any(x in msg for x in [
            "429", "rate limit", "quota", "resource exhausted"
        ]):
            gemini_rate_limited = True
            gemini_available = False
            print("⚠️ GEMINI RATE LIMIT / QUOTA REACHED")
            print("➡️ Switching to OpenRouter FREE fallback.")
        else:
            print(f"Gemini error: {exc}")
            gemini_available = False
        return None


def analyze_with_openrouter(job, profile):
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        print("OpenRouter API key not found.")
        stats["openrouter_errors"] += 1
        return None

    print("🔄 Trying OpenRouter FREE fallback...")

    strict_prompt = build_ai_prompt(job, profile) + """
IMPORTANT:
Return exactly ONE JSON object and nothing else.
Use double quotes for every JSON key and string.
Do not use Markdown, code fences, commentary, or bullet points.
"""
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [{"role": "user", "content": strict_prompt}],
        "temperature": 0.0,
        "max_tokens": 1000,
        "response_format": {"type": "json_object"},
    }

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "X-Title": "AI Job Tracker",
    }

    for attempt in range(2):
        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=60,
            )

            if response.status_code != 200:
                print(
                    f"OpenRouter HTTP {response.status_code}: "
                    f"{response.text[:500]}"
                )
                if attempt == 0:
                    time.sleep(2)
                    continue
                stats["openrouter_errors"] += 1
                return None

            data = response.json()
            choices = data.get("choices") or []
            if not choices:
                print("OpenRouter returned no choices.")
                stats["openrouter_errors"] += 1
                return None

            content = (choices[0].get("message") or {}).get("content", "")

            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("text"):
                        parts.append(str(item["text"]))
                    elif isinstance(item, str):
                        parts.append(item)
                content = "\n".join(parts)

            result = normalize_ai_result(extract_json_object(content))

            if result is not None:
                print("✅ OpenRouter FREE fallback analysis successful!")
                return result

            print(
                "AI returned invalid JSON. "
                f"Raw response: {str(content)[:700]}"
            )
            if attempt == 0:
                time.sleep(2)
                continue

            stats["openrouter_errors"] += 1
            return None

        except requests.RequestException as exc:
            print(f"OpenRouter request error: {exc}")
            if attempt == 0:
                time.sleep(2)
                continue
            stats["openrouter_errors"] += 1
            return None
        except Exception as exc:
            print(f"OpenRouter processing error: {exc}")
            stats["openrouter_errors"] += 1
            return None

    return None


def analyze_job(job, profile):
    if gemini_available and not gemini_rate_limited:
        result = analyze_with_gemini(job, profile)
        if result is not None:
            print("AI Provider: Gemini")
            return result, "Gemini"

    stats["openrouter_fallback_uses"] += 1
    result = analyze_with_openrouter(job, profile)

    if result is not None:
        print("AI Provider: OpenRouter")
        return result, "OpenRouter"

    return None, "None"


def get_adzuna_jobs(query, location, page):
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")

    if not app_id or not app_key:
        print("Adzuna credentials missing.")
        stats["adzuna_api_errors"] += 1
        return []

    url = f"https://api.adzuna.com/v1/api/jobs/in/search/{page}"
    params = {
        "app_id": app_id,
        "app_key": app_key,
        "results_per_page": RESULTS_PER_PAGE,
        "what": query,
        "where": location,
        "content-type": "application/json",
    }

    for attempt in range(3):
        try:
            response = requests.get(url, params=params, timeout=30)

            if response.status_code in {500, 502, 503, 504}:
                print(f"Adzuna server error {response.status_code}")
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue

            response.raise_for_status()
            return response.json().get("results", [])

        except requests.RequestException as exc:
            print(f"Adzuna API error: {exc}")
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            stats["adzuna_api_errors"] += 1
            return []
        except Exception as exc:
            print(f"Adzuna response error: {exc}")
            stats["adzuna_api_errors"] += 1
            return []

    stats["adzuna_api_errors"] += 1
    return []


SENIOR_TITLE_PATTERNS = [
    r"\bsenior\b", r"\bsr\.?\b", r"\blead\b", r"\bprincipal\b",
    r"\bmanager\b", r"\bdirector\b", r"\bhead\b", r"\barchitect\b",
    r"\bvp\b", r"\bvice president\b", r"\btechnical lead\b",
]

THREE_PLUS_YEAR_PATTERNS = [
    r"\b3\+?\s*years?\b", r"\b4\+?\s*years?\b",
    r"\b5\+?\s*years?\b", r"\b6\+?\s*years?\b",
    r"\b7\+?\s*years?\b", r"\b8\+?\s*years?\b",
    r"\b9\+?\s*years?\b", r"\b10\+?\s*years?\b",
]


def is_senior_title(title):
    title = clean_text(title).lower()
    return any(re.search(p, title) for p in SENIOR_TITLE_PATTERNS)


def requires_three_plus_years(job):
    text = clean_text(
        job.get("experience") or job.get("description") or ""
    ).lower()
    return any(re.search(p, text) for p in THREE_PLUS_YEAR_PATTERNS)


def prepare_job(raw, location):
    title = clean_text(raw.get("title"))
    company_data = raw.get("company") or {}
    company = (
        clean_text(company_data.get("display_name"))
        if isinstance(company_data, dict)
        else clean_text(company_data)
    ) or "Unknown"

    loc_data = raw.get("location") or {}
    if isinstance(loc_data, dict):
        job_location = clean_text(loc_data.get("display_name")) or location
    else:
        job_location = clean_text(loc_data) or location

    lo = raw.get("salary_min")
    hi = raw.get("salary_max")
    if lo and hi:
        salary = f"{lo} - {hi}"
    elif lo:
        salary = str(lo)
    elif hi:
        salary = str(hi)
    else:
        salary = "Not specified"

    return {
        "title": title,
        "company": company,
        "location": job_location,
        "salary": salary,
        "experience": clean_text(raw.get("experience") or raw.get("contract_time")),
        "description": clean_text(raw.get("description")),
        "apply_link": clean_text(raw.get("redirect_url") or raw.get("url")),
    }


def make_job_key(company, title, location):
    return (
        normalize_key(company),
        normalize_key(title),
        normalize_key(location),
    )


def connect_google_sheet():
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        print("GOOGLE_SERVICE_ACCOUNT_JSON missing.")
        return None

    try:
        info = json.loads(raw)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SPREADSHEET_ID).worksheet(WORKSHEET_NAME)
        print("Google Sheet connected successfully!")
        return sheet
    except Exception as exc:
        print(f"Google Sheet connection failed: {exc}")
        return None


def update_headers(worksheet):
    try:
        worksheet.update(range_name="A1:N1", values=[HEADERS])
        print("Google Sheet headers updated for V2.2!")
        return True
    except Exception as exc:
        print(f"Google Sheet header update failed: {exc}")
        return False


def load_existing_job_keys(worksheet):
    """
    Load existing jobs from the normal A:N layout.

    Also recognize the older malformed J:W layout so previously saved jobs
    are not re-added after the sheet layout is repaired.
    """
    keys = set()

    try:
        rows = worksheet.get_all_values()

        for row in rows[1:]:
            # Normal layout: A=Date, B=Company, C=Title, D=Location
            if len(row) >= 4 and (row[1] or row[2]):
                company = clean_text(row[1])
                title = clean_text(row[2])
                location = clean_text(row[3])

                if company or title:
                    keys.add(make_job_key(company, title, location))

            # Legacy malformed layout seen in previous runs:
            # J=Date, K=Company, L=Title, M=Location
            if len(row) >= 13:
                legacy_company = clean_text(row[10])
                legacy_title = clean_text(row[11])
                legacy_location = clean_text(row[12])

                if legacy_company or legacy_title:
                    keys.add(
                        make_job_key(
                            legacy_company,
                            legacy_title,
                            legacy_location,
                        )
                    )

    except Exception as exc:
        print(f"Could not load existing sheet rows: {exc}")

    return keys


def build_sheet_row(job, result):
    matched = result.get("matched_skills", [])
    row = [
        datetime.now().strftime("%Y-%m-%d"),
        job["company"],
        job["title"],
        job["location"],
        job["salary"],
        job["experience"],
        ", ".join(matched),
        result["match_score"],
        job["apply_link"],
        "Not Applied",
        ", ".join(matched),
        ", ".join(result.get("missing_skills", [])),
        result.get("experience_match", ""),
        result.get("reason", ""),
    ]

    if len(row) != len(HEADERS):
        raise ValueError(
            f"Sheet row has {len(row)} columns; expected {len(HEADERS)}."
        )

    return row


def get_next_sheet_row(worksheet):
    """
    Find the next row from column A.
    This avoids gspread append_row/table detection placing new data
    into a shifted column block.
    """
    try:
        col_a = worksheet.col_values(1)
        last_nonempty = 0

        for index, value in enumerate(col_a, start=1):
            if clean_text(value):
                last_nonempty = index

        return max(2, last_nonempty + 1)

    except Exception as exc:
        print(f"Could not determine next sheet row: {exc}")
        raise


def append_and_verify_job(worksheet, row, job):
    """
    Write explicitly to A:N on the next available row.
    Then read the exact same range back and verify it.
    """
    try:
        if len(row) != len(HEADERS):
            print(
                f"❌ GOOGLE SHEET ROW ERROR: expected {len(HEADERS)} "
                f"columns, got {len(row)}."
            )
            return False

        next_row = get_next_sheet_row(worksheet)
        target_range = f"A{next_row}:N{next_row}"

        print(f"📌 Writing exactly to {target_range}")

        worksheet.update(
            range_name=target_range,
            values=[row],
            value_input_option="USER_ENTERED",
        )

        time.sleep(1)

        written = worksheet.get(target_range)

        if not written or not written[0]:
            print("❌ GOOGLE SHEET VERIFICATION FAILED: row is empty.")
            return False

        saved = written[0]

        if len(saved) < len(HEADERS):
            print(
                f"❌ GOOGLE SHEET VERIFICATION FAILED: expected "
                f"{len(HEADERS)} columns, got {len(saved)}."
            )
            return False

        expected_key = make_job_key(
            job["company"],
            job["title"],
            job["location"],
        )

        saved_key = make_job_key(
            saved[1],
            saved[2],
            saved[3],
        )

        if saved_key != expected_key:
            print("❌ GOOGLE SHEET VERIFICATION FAILED: row data mismatch.")
            print(f"Expected: {expected_key}")
            print(f"Saved:    {saved_key}")
            return False

        print(f"✅ Google Sheet append verified at {target_range}!")
        return True

    except Exception as exc:
        print(f"❌ Google Sheet append failed: {exc}")
        return False


def main():
    global existing_job_keys

    print("=" * 70)
    print("AI Job Tracker V2.2 Started!")
    print("Gemini PRIMARY + OpenRouter FREE FALLBACK")
    print("=" * 70)

    profile = load_candidate_profile()
    initialize_gemini()

    worksheet = connect_google_sheet()
    if worksheet is None:
        print("Cannot continue without Google Sheet.")
        return

    update_headers(worksheet)
    existing_job_keys = load_existing_job_keys(worksheet)

    print(f"Existing jobs in Sheet: {len(existing_job_keys)}")

    ai_counter = 0

    for query in SEARCH_QUERIES:
        if ai_counter >= MAX_AI_JOBS:
            break

        print("\n" + "=" * 70)
        print(f"Searching: {query}")
        print("=" * 70)

        for location in LOCATIONS:
            if ai_counter >= MAX_AI_JOBS:
                break

            print(f"\nLocation: {location}")

            for page in range(1, TOTAL_PAGES + 1):
                if ai_counter >= MAX_AI_JOBS:
                    break

                jobs = get_adzuna_jobs(query, location, page)
                print(f"Page {page}: {len(jobs)} jobs received.")

                if not jobs:
                    continue

                for raw in jobs:
                    stats["total_jobs_seen"] += 1
                    job = prepare_job(raw, location)

                    if not job["title"]:
                        stats["jobs_rejected"] += 1
                        continue

                    if is_senior_title(job["title"]):
                        print(f"Rejected senior/lead title: {job['title']}")
                        stats["jobs_rejected"] += 1
                        continue

                    if requires_three_plus_years(job):
                        print(f"Rejected 3+ years: {job['title']}")
                        stats["jobs_rejected"] += 1
                        continue

                    key = make_job_key(
                        job["company"], job["title"], job["location"]
                    )

                    if key in existing_job_keys:
                        print(f"Skipping duplicate: {job['title']}")
                        stats["duplicate_jobs_skipped"] += 1
                        continue

                    ai_counter += 1
                    stats["jobs_analyzed"] += 1

                    print("\n" + "-" * 70)
                    print(f"AI Analysis: {ai_counter}/{MAX_AI_JOBS}")
                    print(f"Job: {job['title']}")
                    print(f"Company: {job['company']}")

                    result, provider = analyze_job(job, profile)

                    if result is None:
                        print("❌ No valid AI analysis available.")
                        stats["jobs_rejected"] += 1
                        continue

                    score = result["match_score"]
                    print(f"AI Provider: {provider}")
                    print(f"AI Match Score: {score}/100")

                    if score < AI_MIN_SCORE:
                        print(f"Rejected by AI: {job['title']}")
                        stats["jobs_rejected"] += 1
                        continue

                    print("\n" + "=" * 70)
                    print("🎯 NEW AI-MATCHED JOB FOUND")
                    print(f"Job: {job['title']}")
                    print(f"Company: {job['company']}")
                    print(f"Location: {job['location']}")
                    print(f"Salary: {job['salary']}")
                    print(f"Matched Skills: {result['matched_skills']}")
                    print(f"Missing Skills: {result['missing_skills']}")
                    print(f"Experience Match: {result['experience_match']}")
                    print(f"Reason: {result['reason']}")

                    print("\n📊 Writing job to Google Sheet...")
                    row = build_sheet_row(job, result)

                    if append_and_verify_job(worksheet, row, job):
                        existing_job_keys.add(key)
                        stats["new_jobs_added"] += 1
                    else:
                        print("❌ Job append could not be verified.")

                    time.sleep(2)

                    if ai_counter >= MAX_AI_JOBS:
                        break

    print("\n" + "=" * 70)
    print("JOB SEARCH COMPLETED")
    print("=" * 70)
    print(f"Total jobs seen: {stats['total_jobs_seen']}")
    print(f"Jobs analyzed: {stats['jobs_analyzed']}")
    print(f"New AI-matched jobs added: {stats['new_jobs_added']}")
    print(f"Duplicate jobs skipped: {stats['duplicate_jobs_skipped']}")
    print(f"Jobs rejected: {stats['jobs_rejected']}")
    print(f"Adzuna API errors: {stats['adzuna_api_errors']}")
    print(f"OpenRouter fallback uses: {stats['openrouter_fallback_uses']}")
    print(f"OpenRouter errors: {stats['openrouter_errors']}")

    if gemini_rate_limited:
        print("Gemini status: RATE LIMIT / QUOTA REACHED → OPENROUTER FALLBACK")
    elif gemini_available:
        print("Gemini status: AVAILABLE")
    else:
        print("Gemini status: UNAVAILABLE")

    print("=" * 70)
    print("AI Job Tracker V2.2 Finished!")
    print("=" * 70)


if __name__ == "__main__":
    main()
