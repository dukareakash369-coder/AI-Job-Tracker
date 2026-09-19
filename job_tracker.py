# AI Job Tracker V2.4 - Gemini + Groq Stable
# Gemini primary + Groq fallback
#
# V2.2.1 fixes:
# 1) Hard MAX_AI_JOBS limit - never analyzes more than the configured limit
# 2) Groq HTTP 429 hard-stop - no retry after rate limit is exhausted
# 3) No duplicate Groq retry for invalid JSON
# 4) Reliable Google Sheets A:N write + verification
# 5) Existing legacy J:W records are recognized for duplicate protection
# 6) Cleaner final statistics and provider status
# 7) Existing filtering / duplicate logic retained
# 8) OpenRouter removed; Groq is the only fallback provider
# 9) Company-name normalization improves duplicate detection (e.g. Cummins vs Cummins Inc.)
# 10) Sheet header/version log updated to V2.4
# 11) 3+ years filter checks title + experience + description
# 12) AI experience mismatch filter rejects unsuitable AI assessments
# 13) Matched skills are restricted to skills explicitly supported by the job
# 14) V2.4 deterministic skill grounding removes AI-overclaimed matched skills
# 15) Missing skills are kept only when explicitly supported by the job text

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

SPREADSHEET_ID = "1TeQSVAHVitgB2T6iBte-MOjHQeyHR-RS0HwTltgjIRo"
WORKSHEET_NAME = "Sheet1"

AI_MODEL = "gemini-3.6-flash"
GROQ_MODEL = "openai/gpt-oss-20b"

# HARD LIMIT:
# The script will never make more than this many AI analysis attempts.
MAX_AI_JOBS = 15

# Minimum score required to save a job.
AI_MIN_SCORE = 60

RESULTS_PER_PAGE = 20
TOTAL_PAGES = 3

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

HEADERS = [
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
# GLOBAL STATE
# ============================================================

gemini_client = None
gemini_available = False
gemini_rate_limited = False

groq_rate_limited = False

# Set this to True when AI processing must stop immediately.
stop_ai_processing = False

stats = {
    "total_jobs_seen": 0,
    "jobs_analyzed": 0,
    "new_jobs_added": 0,
    "duplicate_jobs_skipped": 0,
    "jobs_rejected": 0,
    "adzuna_api_errors": 0,
    "groq_fallback_uses": 0,
    "groq_errors": 0,
    "groq_invalid_json": 0,
    "groq_rate_limit": 0,
    "gemini_invalid_json": 0,
}

existing_job_keys = set()


# ============================================================
# TEXT / DATA HELPERS
# ============================================================

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


# ============================================================
# CANDIDATE PROFILE
# ============================================================

def load_candidate_profile():
    path = "profile.json"

    if not os.path.exists(path):
        print("WARNING: profile.json not found. Using fallback profile.")

        return {
            "experience_level": "Entry-level / Fresher",
            "target_roles": [
                "Embedded Engineer",
                "Embedded Software Engineer",
                "Embedded Systems Engineer",
                "Firmware Engineer",
                "Embedded AI Engineer",
                "Edge AI Engineer",
                "IoT Engineer",
                "Robotics Engineer",
            ],
            "skills": [
                "C",
                "Embedded C",
                "C++",
                "Python",
                "Arduino",
                "ESP32",
                "Raspberry Pi",
                "Embedded Linux",
                "GPIO",
                "PWM",
                "UART",
                "SPI",
                "I2C",
                "Hardware Debugging",
            ],
            "education": "Electronics and Telecommunication Engineering",
        }

    try:
        with open(path, "r", encoding="utf-8") as f:
            profile = json.load(f)

        print("Candidate profile loaded successfully!")
        return profile

    except Exception as exc:
        print(f"WARNING: Could not load profile.json: {exc}")
        return {}


# ============================================================
# GEMINI
# ============================================================

def initialize_gemini():
    global gemini_client, gemini_available

    key = os.environ.get("GEMINI_API_KEY")

    if not key:
        print("Gemini API key not found. Groq fallback will be used.")
        return

    try:
        gemini_client = genai.Client(api_key=key)
        gemini_available = True
        print("Gemini client initialized successfully!")

    except Exception as exc:
        print(f"Gemini initialization failed: {exc}")
        gemini_available = False


# ============================================================
# AI PROMPT
# ============================================================
def build_ai_prompt(job, profile):
    return f"""
You are an intelligent job-matching system evaluating a job for an
entry-level Electronics and Telecommunication Engineering candidate.

The candidate is specifically targeting:
- Embedded Systems
- Embedded Software
- Firmware
- Embedded AI
- Edge AI
- IoT
- Robotics

Candidate Profile:
{json.dumps(profile, ensure_ascii=False)}

Job Information:
Company: {clean_text(job.get("company", "Unknown"))}
Title: {clean_text(job.get("title", ""))}
Location: {clean_text(job.get("location", ""))}
Experience: {clean_text(job.get("experience", ""))}
Description:
{clean_text(job.get("description", ""))[:12000]}

Your task is to calculate a fair and consistent match score from 0 to 100.

============================================================
SCORING RUBRIC
============================================================

1. ROLE RELEVANCE: 0-30 points
- Strongly relevant Embedded/Firmware/Embedded Software role:
  25-30 points
- Relevant Embedded/IoT/Robotics/Edge AI role:
  20-27 points
- Partially relevant Electronics/Software role:
  10-19 points
- Mostly unrelated role:
  0-9 points

2. SKILLS MATCH: 0-40 points
- Compare the job requirements with the candidate's actual skills.
- IMPORTANT: A candidate skill counts as matched ONLY when the same skill,
  technology, protocol, tool, language, framework, platform, or a clearly
  equivalent term is explicitly mentioned or clearly required/used in the
  job title or job description.
- Never treat a candidate skill as matched merely because it is generally
  relevant to embedded engineering.
- Do NOT infer ESP32, Arduino, Raspberry Pi, GPIO, PWM, UART, SPI, I2C, ROS,
  Motor Control, Embedded C, C++, etc. unless the job explicitly mentions
  them or an unambiguous equivalent.
- Distinguish candidate skills from job requirements. The candidate profile
  is NOT evidence that the job uses that technology.
- Missing required or must-have skills should reduce the skills-match score
  more than optional/good-to-have gaps.
- Do NOT require every optional job skill to be present.

3. EXPERIENCE COMPATIBILITY: 0-15 points
- Fresher / Entry-level / Junior / 0-2 years:
  13-15 points
- Experience requirement is not clearly specified:
  10-12 points
- Requires more than 2 years but is otherwise relevant:
  3-9 points
- Clearly requires 3+ years and is unsuitable for a fresher:
  0-2 points

Important:
If the job does NOT specify experience requirements, do NOT penalize
the candidate heavily.

4. EDUCATION RELEVANCE: 0-10 points
- Electronics / Electronics and Telecommunication / Electrical /
  Instrumentation / Computer or closely related engineering:
  8-10 points
- Somewhat related technical education:
  4-7 points
- Unrelated education:
  0-3 points

5. LOCATION: 0-5 points
- Pune or Remote:
  5 points
- Location is not clearly specified:
  3 points
- Other location:
  0-2 points

============================================================
IMPORTANT MATCHING RULES
============================================================

- Evaluate the candidate as a FRESHER / ENTRY-LEVEL candidate.
- A junior or associate-level position can be a strong match.
- Do NOT reject a job simply because the candidate does not have
  every listed technology.
- Do NOT invent candidate experience, skills, certifications or projects.
- Do NOT assume that missing information means the candidate lacks it.
- If the job description is incomplete, use the available information
  and remain neutral about unknown requirements.
- Senior, Lead, Principal, Manager, Director and similar roles should
  normally receive a very low experience compatibility score.
- Focus on actual job requirements, not only the job title.
- Give a higher score when the role is directly related to Embedded
  Systems, Embedded Software, Firmware, IoT, Robotics or Edge AI.
- C / Embedded C / C++ / Python and hardware interfacing experience
  should be considered relevant for embedded software roles.
- Hardware, firmware, IoT and software skills can overlap. Evaluate
  transferable technical skills reasonably.

============================================================
SCORE INTERPRETATION
============================================================

90-100 = Excellent match
80-89  = Very strong match
70-79  = Strong match
60-69  = Relevant match
50-59  = Partial match
Below 50 = Weak match

The score must reflect the complete profile and job requirements,
not just the number of exact keyword matches.

============================================================
OUTPUT
============================================================

Return ONLY one valid JSON object.
Do not use Markdown fences.
Do not add explanations before or after the JSON.

Required JSON schema:

{{
  "match_score": 0,
  "matched_skills": [],
  "missing_skills": [],
  "experience_match": "",
  "reason": ""
}}

Output rules:
- match_score must be an integer from 0 to 100.
- matched_skills must contain ONLY candidate skills that are explicitly
  grounded in the job text. Every item must satisfy BOTH conditions:
  (1) it exists in the candidate profile, and
  (2) the same skill or an unambiguous equivalent is present in the job
      title or description.
- Do NOT list a candidate skill merely because it is generally relevant to
  embedded jobs.
- Do NOT infer a technology from a broad category. For example, Linux does
  not imply Embedded Linux, and embedded systems does not imply ESP32/Arduino.
- missing_skills should contain important job skills that are explicitly
  required or clearly expected by the job and are not present in the
  candidate profile. Prioritize must-have requirements over good-to-have
  requirements.
- experience_match should briefly describe whether the job experience
  requirement is suitable for the candidate.
- reason should briefly explain why the score was assigned.
- Keep reason concise and factual.
"""
# ============================================================
# JSON EXTRACTION
# ============================================================

def extract_json_object(text):
    """Extract the first complete JSON object from an AI response."""

    if text is None:
        return None

    text = str(text).strip()

    if not text:
        return None

    # Remove common Markdown code fences.
    text = re.sub(
        r"^\s*```(?:json)?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\s*```\s*$", "", text)

    # First try the entire response.
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass

    # Then locate the first complete JSON object.
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


def _flatten_candidate_skills(profile):
    """Return a clean list of skills from either dict- or list-based profiles."""

    skills = profile.get("skills", []) if isinstance(profile, dict) else []

    if isinstance(skills, dict):
        values = []
        for group in skills.values():
            if isinstance(group, list):
                values.extend(group)
            elif group:
                values.append(group)
        return [clean_text(x) for x in values if clean_text(x)]

    return safe_list(skills)


def _skill_key(skill):
    """Normalize a skill without collapsing distinct skills such as C and C++."""

    value = clean_text(skill).lower()
    value = value.replace("c++", "cpp")
    value = value.replace("c#", "csharp")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _skill_is_in_job_text(skill, job_text):
    """Check whether a skill is explicitly grounded in the job text."""

    skill = clean_text(skill)
    job_text = clean_text(job_text)

    if not skill or not job_text:
        return False

    # First use a word-boundary regex. This safely handles C, C++, C#,
    # RS232/485 and other punctuation-heavy skill names.
    escaped = re.escape(skill.lower())
    if re.search(
        r"(?<![a-z0-9])" + escaped + r"(?![a-z0-9])",
        job_text.lower(),
    ):
        return True

    # Also support normalized multi-word phrases.
    normalized_skill = _skill_key(skill)
    normalized_job = _skill_key(job_text)

    return bool(
        normalized_skill
        and normalized_skill in normalized_job
    )


def ground_ai_skill_lists(result, job, profile):
    """
    Deterministically ground AI skill lists after the model responds.

    matched_skills: must exist in candidate profile AND job text.
    missing_skills: must be supported by job text AND not exist in profile.
    """

    candidate_skills = _flatten_candidate_skills(profile)
    candidate_by_normalized = {
        _skill_key(skill): skill
        for skill in candidate_skills
        if _skill_key(skill)
    }

    job_text = " ".join(
        part
        for part in [
            clean_text(job.get("title")),
            clean_text(job.get("description")),
            clean_text(job.get("experience")),
        ]
        if clean_text(part)
    )

    grounded_matched = []
    removed_matched = []

    for ai_skill in safe_list(result.get("matched_skills")):
        normalized_ai = _skill_key(ai_skill)

        # Accept only a skill that maps back to a real candidate skill.
        candidate_skill = candidate_by_normalized.get(normalized_ai)

        if candidate_skill and _skill_is_in_job_text(candidate_skill, job_text):
            if candidate_skill not in grounded_matched:
                grounded_matched.append(candidate_skill)
        else:
            removed_matched.append(ai_skill)

    grounded_missing = []

    for ai_skill in safe_list(result.get("missing_skills")):
        if not _skill_is_in_job_text(ai_skill, job_text):
            continue

        normalized_ai = _skill_key(ai_skill)
        if normalized_ai in candidate_by_normalized:
            continue

        if ai_skill not in grounded_missing:
            grounded_missing.append(ai_skill)

    if removed_matched:
        print(
            "⚠️ V2.4 removed ungrounded AI matched skills: "
            + ", ".join(removed_matched)
        )

    result["matched_skills"] = grounded_matched
    result["missing_skills"] = grounded_missing

    return result


def normalize_ai_result(data):
    if not isinstance(data, dict):
        return None

    score = max(
        0,
        min(
            100,
            safe_int(data.get("match_score", 0)),
        ),
    )

    return {
        "match_score": score,
        "matched_skills": safe_list(data.get("matched_skills")),
        "missing_skills": safe_list(data.get("missing_skills")),
        "experience_match": clean_text(
            data.get("experience_match")
        ),
        "reason": clean_text(data.get("reason")),
    }


# ============================================================
# GEMINI ANALYSIS
# ============================================================

def analyze_with_gemini(job, profile):
    global gemini_available
    global gemini_rate_limited
    global stop_ai_processing

    if (
        not gemini_available
        or gemini_rate_limited
        or gemini_client is None
        or stop_ai_processing
    ):
        return None

    try:
        interaction = gemini_client.interactions.create(
            model=AI_MODEL,
            input=build_ai_prompt(job, profile),
        )

        raw = getattr(interaction, "output_text", None)

        result = normalize_ai_result(
            extract_json_object(raw)
        )

        if result is None:
            stats["gemini_invalid_json"] += 1
            print("Gemini returned invalid JSON.")
            return None

        return result

    except Exception as exc:
        msg = str(exc).lower()

        if any(
            x in msg
            for x in [
                "429",
                "rate limit",
                "quota",
                "resource exhausted",
            ]
        ):
            gemini_rate_limited = True
            gemini_available = False

            print("⚠️ GEMINI RATE LIMIT / QUOTA REACHED")
            print("➡️ Switching to Groq fallback.")

        else:
            print(f"Gemini error: {exc}")
            gemini_available = False

        return None


# ============================================================
# GROQ ANALYSIS
# ============================================================

def analyze_with_groq(job, profile):
    global groq_rate_limited
    global stop_ai_processing

    if stop_ai_processing:
        return None

    if groq_rate_limited:
        return None

    key = os.environ.get("GROQ_API_KEY")

    if not key:
        print("Groq API key not found.")
        stats["groq_errors"] += 1
        return None

    print("🔄 Trying Groq fallback...")

    strict_prompt = build_ai_prompt(job, profile) + """
IMPORTANT:
Return exactly ONE JSON object and nothing else.
Use double quotes for every JSON key and string.
Do not use Markdown, code fences, commentary, reasoning, or bullet points.
"""

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {
                "role": "user",
                "content": strict_prompt,
            }
        ],
        "temperature": 0.0,
        "max_completion_tokens": 1000,
        "reasoning_effort": "low",
        "reasoning_format": "hidden",
        "response_format": {
            "type": "json_object",
        },
    }

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "X-Title": "AI Job Tracker",
        "Accept": "application/json",
    }

    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=60,
        )

        # ----------------------------------------------------
        # HARD STOP ON 429
        # ----------------------------------------------------
        if response.status_code == 429:
            groq_rate_limited = True
            stop_ai_processing = True
            stats["groq_rate_limit"] += 1

            print(
                "🛑 Groq HTTP 429: rate limit reached."
            )
            print(
                "🛑 Stopping further AI analysis for this run."
            )

            return None

        # ----------------------------------------------------
        # OTHER HTTP ERRORS
        # ----------------------------------------------------
        if response.status_code != 200:
            print(
                f"Groq HTTP {response.status_code}: "
                f"{response.text[:500]}"
            )

            stats["groq_errors"] += 1
            return None

        data = response.json()

        choices = data.get("choices") or []

        if not choices:
            print("Groq returned no choices.")
            stats["groq_errors"] += 1
            return None

        message = choices[0].get("message") or {}
        content = message.get("content", "")

        # Some providers may return content as a list.
        if isinstance(content, list):
            parts = []

            for item in content:
                if isinstance(item, dict) and item.get("text"):
                    parts.append(str(item["text"]))
                elif isinstance(item, str):
                    parts.append(item)

            content = "\n".join(parts)

        result = normalize_ai_result(
            extract_json_object(content)
        )

        if result is not None:
            print(
                "✅ Groq fallback analysis successful!"
            )
            return result

        # ----------------------------------------------------
        # INVALID JSON: NO SECOND REQUEST
        # ----------------------------------------------------
        stats["groq_invalid_json"] += 1

        print(
            "⚠️ Groq returned invalid JSON."
        )
        print(
            f"Raw response: {str(content)[:700]}"
        )
        print(
            "➡️ Skipping this job without another Groq retry."
        )

        return None

    except requests.RequestException as exc:
        print(f"Groq request error: {exc}")
        stats["groq_errors"] += 1
        return None

    except Exception as exc:
        print(f"Groq processing error: {exc}")
        stats["groq_errors"] += 1
        return None


# ============================================================
# AI ROUTER
# ============================================================

def analyze_job(job, profile):
    global stop_ai_processing

    if stop_ai_processing:
        return None, "None"

    # Primary: Gemini
    if gemini_available and not gemini_rate_limited:
        result = analyze_with_gemini(job, profile)

        if result is not None:
            print("AI Provider: Gemini")
            return result, "Gemini"

    # Fallback: Groq
    if stop_ai_processing:
        return None, "None"

    stats["groq_fallback_uses"] += 1

    result = analyze_with_groq(
        job,
        profile,
    )

    if result is not None:
        print("AI Provider: Groq")
        return result, "Groq"

    return None, "None"


# ============================================================
# ADZUNA
# ============================================================

def get_adzuna_jobs(query, location, page):
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")

    if not app_id or not app_key:
        print("Adzuna credentials missing.")
        stats["adzuna_api_errors"] += 1
        return []

    url = (
        "https://api.adzuna.com/v1/api/jobs/in/search/"
        f"{page}"
    )

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
            response = requests.get(
                url,
                params=params,
                timeout=30,
            )

            if response.status_code in {
                500,
                502,
                503,
                504,
            }:
                print(
                    f"Adzuna server error "
                    f"{response.status_code}"
                )

                if attempt < 2:
                    time.sleep(
                        2 * (attempt + 1)
                    )
                    continue

            response.raise_for_status()

            return response.json().get(
                "results",
                [],
            )

        except requests.RequestException as exc:
            print(f"Adzuna API error: {exc}")

            if attempt < 2:
                time.sleep(
                    2 * (attempt + 1)
                )
                continue

            stats["adzuna_api_errors"] += 1
            return []

        except Exception as exc:
            print(
                f"Adzuna response error: {exc}"
            )
            stats["adzuna_api_errors"] += 1
            return []

    stats["adzuna_api_errors"] += 1
    return []


# ============================================================
# FILTERING
# ============================================================

SENIOR_TITLE_PATTERNS = [
    r"\bsenior\b",
    r"\bsr\.?\b",
    r"\blead\b",
    r"\bprincipal\b",
    r"\bmanager\b",
    r"\bdirector\b",
    r"\bhead\b",
    r"\barchitect\b",
    r"\bvp\b",
    r"\bvice president\b",
    r"\btechnical lead\b",
]

THREE_PLUS_YEAR_PATTERNS = [
    # Explicit 3+ years
    r"\b3\+?\s*years?\b",
    r"\b4\+?\s*years?\b",
    r"\b5\+?\s*years?\b",
    r"\b6\+?\s*years?\b",
    r"\b7\+?\s*years?\b",
    r"\b8\+?\s*years?\b",
    r"\b9\+?\s*years?\b",
    r"\b10\+?\s*years?\b",

    # Experience ranges: 3-5, 3–5, 3 to 5 years
    r"\b3\s*(?:-|–|to)\s*\d+\s*years?\b",
    r"\b4\s*(?:-|–|to)\s*\d+\s*years?\b",
    r"\b5\s*(?:-|–|to)\s*\d+\s*years?\b",
    r"\b6\s*(?:-|–|to)\s*\d+\s*years?\b",
    r"\b7\s*(?:-|–|to)\s*\d+\s*years?\b",
    r"\b8\s*(?:-|–|to)\s*\d+\s*years?\b",

    # Minimum experience wording
    r"\bminimum\s+3\s+years?\b",
    r"\bat\s+least\s+3\s+years?\b",
    r"\b3\s+or\s+more\s+years?\b",
]


def is_senior_title(title):
    title = clean_text(title).lower()

    return any(
        re.search(
            pattern,
            title,
        )
        for pattern in SENIOR_TITLE_PATTERNS
    )


def requires_three_plus_years(job):
    title = clean_text(
        job.get("title")
        or ""
    ).lower()

    experience = clean_text(
        job.get("experience")
        or ""
    ).lower()

    description = clean_text(
        job.get("description")
        or ""
    ).lower()

    # Check title + experience + description together.
    text = " ".join(
        part
        for part in [
            title,
            experience,
            description,
        ]
        if part
    )

    return any(
        re.search(
            pattern,
            text,
        )
        for pattern in THREE_PLUS_YEAR_PATTERNS
    )


# ============================================================
# JOB NORMALIZATION
# ============================================================

def prepare_job(raw, location):
    title = clean_text(
        raw.get("title")
    )

    company_data = raw.get("company") or {}

    if isinstance(company_data, dict):
        company = clean_text(
            company_data.get("display_name")
        )
    else:
        company = clean_text(
            company_data
        )

    company = company or "Unknown"

    loc_data = raw.get("location") or {}

    if isinstance(loc_data, dict):
        job_location = (
            clean_text(
                loc_data.get("display_name")
            )
            or location
        )
    else:
        job_location = (
            clean_text(loc_data)
            or location
        )

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
        "experience": clean_text(
            raw.get("experience")
            or raw.get("contract_time")
        ),
        "description": clean_text(
            raw.get("description")
        ),
        "apply_link": clean_text(
            raw.get("redirect_url")
            or raw.get("url")
        ),
    }


def normalize_company_name(value):
    """Normalize company names for duplicate detection only.

    This does NOT change the company name written to Google Sheets.
    It only makes common legal suffix variations such as
    "Cummins", "Cummins Inc.", and "Cummins Inc" compare equally.
    """

    name = normalize_key(value)

    # Remove common company/legal suffixes from the END only.
    # Repeating the pass handles combinations such as
    # "Pvt Ltd" -> "Pvt" -> removed.
    suffix_patterns = [
        r"\bpvt\b",
        r"\bprivate\b",
        r"\blimited\b",
        r"\bltd\b",
        r"\bincorporated\b",
        r"\binc\b",
        r"\bcorporation\b",
        r"\bcorp\b",
        r"\bcompany\b",
        r"\bco\b",
        r"\bllc\b",
        r"\bllp\b",
    ]

    changed = True

    while name and changed:
        changed = False

        for pattern in suffix_patterns:
            updated = re.sub(
                rf"(?:\s+{pattern})$",
                "",
                name,
            ).strip()

            if updated != name:
                name = updated
                changed = True

    return name


def make_job_key(
    company,
    title,
    location,
):
    return (
        normalize_company_name(company),
        normalize_key(title),
        normalize_key(location),
    )


# ============================================================
# GOOGLE SHEETS
# ============================================================

def connect_google_sheet():
    raw = os.environ.get(
        "GOOGLE_SERVICE_ACCOUNT_JSON"
    )

    if not raw:
        print(
            "GOOGLE_SERVICE_ACCOUNT_JSON missing."
        )
        return None

    try:
        info = json.loads(raw)

        creds = Credentials.from_service_account_info(
            info,
            scopes=SCOPES,
        )

        client = gspread.authorize(creds)

        sheet = client.open_by_key(
            SPREADSHEET_ID
        ).worksheet(
            WORKSHEET_NAME
        )

        print(
            "Google Sheet connected successfully!"
        )

        return sheet

    except Exception as exc:
        print(
            f"Google Sheet connection failed: {exc}"
        )
        return None


def update_headers(worksheet):
    try:
        worksheet.update(
            range_name="A1:N1",
            values=[HEADERS],
        )

        print(
            "Google Sheet headers verified for V2.4!"
        )

        return True

    except Exception as exc:
        print(
            f"Google Sheet header update failed: {exc}"
        )
        return False


def load_existing_job_keys(worksheet):
    """
    Load existing jobs from the normal A:N layout.

    Also recognize the older malformed J:W layout so old jobs
    are not re-added after the sheet layout was repaired.
    """

    keys = set()

    try:
        rows = worksheet.get_all_values()

        for row in rows[1:]:
            # ------------------------------------------------
            # Normal layout:
            # A=Date, B=Company, C=Title, D=Location
            # ------------------------------------------------
            if len(row) >= 4:
                company = clean_text(
                    row[1]
                )
                title = clean_text(
                    row[2]
                )
                location = clean_text(
                    row[3]
                )

                if company or title:
                    keys.add(
                        make_job_key(
                            company,
                            title,
                            location,
                        )
                    )

            # ------------------------------------------------
            # Legacy malformed layout:
            # J=Date, K=Company, L=Title, M=Location
            # ------------------------------------------------
            if len(row) >= 13:
                legacy_company = clean_text(
                    row[10]
                )
                legacy_title = clean_text(
                    row[11]
                )
                legacy_location = clean_text(
                    row[12]
                )

                if (
                    legacy_company
                    or legacy_title
                ):
                    keys.add(
                        make_job_key(
                            legacy_company,
                            legacy_title,
                            legacy_location,
                        )
                    )

    except Exception as exc:
        print(
            f"Could not load existing sheet rows: {exc}"
        )

    return keys


def build_sheet_row(job, result):
    matched = result.get(
        "matched_skills",
        [],
    )

    row = [
        datetime.now().strftime(
            "%Y-%m-%d"
        ),
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
        ", ".join(
            result.get(
                "missing_skills",
                [],
            )
        ),
        result.get(
            "experience_match",
            "",
        ),
        result.get(
            "reason",
            "",
        ),
    ]

    if len(row) != len(HEADERS):
        raise ValueError(
            f"Sheet row has {len(row)} columns; "
            f"expected {len(HEADERS)}."
        )

    return row


def get_next_sheet_row(worksheet):
    """
    Find the next row from column A.

    This avoids gspread append_row/table detection placing
    new data into a shifted column block.
    """

    try:
        col_a = worksheet.col_values(1)

        last_nonempty = 0

        for index, value in enumerate(
            col_a,
            start=1,
        ):
            if clean_text(value):
                last_nonempty = index

        return max(
            2,
            last_nonempty + 1,
        )

    except Exception as exc:
        print(
            f"Could not determine next sheet row: {exc}"
        )
        raise


def append_and_verify_job(
    worksheet,
    row,
    job,
):
    """
    Write explicitly to A:N on the next available row.

    Then read the exact same range back and verify it.
    """

    try:
        if len(row) != len(HEADERS):
            print(
                "❌ GOOGLE SHEET ROW ERROR: "
                f"expected {len(HEADERS)} columns, "
                f"got {len(row)}."
            )
            return False

        next_row = get_next_sheet_row(
            worksheet
        )

        target_range = (
            f"A{next_row}:N{next_row}"
        )

        print(
            f"📌 Writing exactly to "
            f"{target_range}"
        )

        worksheet.update(
            range_name=target_range,
            values=[row],
            value_input_option="USER_ENTERED",
        )

        time.sleep(1)

        written = worksheet.get(
            target_range
        )

        if not written or not written[0]:
            print(
                "❌ GOOGLE SHEET VERIFICATION "
                "FAILED: row is empty."
            )
            return False

        saved = written[0]

        if len(saved) < len(HEADERS):
            print(
                "❌ GOOGLE SHEET VERIFICATION "
                f"FAILED: expected {len(HEADERS)} "
                f"columns, got {len(saved)}."
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
            print(
                "❌ GOOGLE SHEET VERIFICATION "
                "FAILED: row data mismatch."
            )
            print(
                f"Expected: {expected_key}"
            )
            print(
                f"Saved:    {saved_key}"
            )
            return False

        print(
            f"✅ Google Sheet append verified "
            f"at {target_range}!"
        )

        return True

    except Exception as exc:
        print(
            f"❌ Google Sheet append failed: {exc}"
        )
        return False


# ============================================================
# MAIN
# ============================================================

def main():
    global existing_job_keys
    global stop_ai_processing

    print("=" * 70)
    print("AI Job Tracker V2.4 Started!")
    print(
        "Gemini PRIMARY + Groq FALLBACK"
    )
    print("=" * 70)

    profile = load_candidate_profile()

    initialize_gemini()

    worksheet = connect_google_sheet()

    if worksheet is None:
        print(
            "Cannot continue without Google Sheet."
        )
        return

    update_headers(worksheet)

    existing_job_keys = load_existing_job_keys(
        worksheet
    )

    print(
        f"Existing jobs in Sheet: "
        f"{len(existing_job_keys)}"
    )

    ai_counter = 0

    # ========================================================
    # SEARCH LOOP
    # ========================================================

    for query in SEARCH_QUERIES:
        if ai_counter >= MAX_AI_JOBS:
            break

        if stop_ai_processing:
            break

        print("\n" + "=" * 70)
        print(
            f"Searching: {query}"
        )
        print("=" * 70)

        for location in LOCATIONS:
            if ai_counter >= MAX_AI_JOBS:
                break

            if stop_ai_processing:
                break

            print(
                f"\nLocation: {location}"
            )

            for page in range(
                1,
                TOTAL_PAGES + 1,
            ):
                if ai_counter >= MAX_AI_JOBS:
                    break

                if stop_ai_processing:
                    break

                jobs = get_adzuna_jobs(
                    query,
                    location,
                    page,
                )

                print(
                    f"Page {page}: "
                    f"{len(jobs)} jobs received."
                )

                if not jobs:
                    continue

                for raw in jobs:
                    # ----------------------------------------
                    # HARD STOP BEFORE ANY NEW AI ANALYSIS
                    # ----------------------------------------
                    if (
                        ai_counter
                        >= MAX_AI_JOBS
                    ):
                        break

                    if stop_ai_processing:
                        break

                    stats[
                        "total_jobs_seen"
                    ] += 1

                    job = prepare_job(
                        raw,
                        location,
                    )

                    if not job["title"]:
                        stats[
                            "jobs_rejected"
                        ] += 1
                        continue

                    # ----------------------------------------
                    # SENIOR TITLE FILTER
                    # ----------------------------------------
                    if is_senior_title(
                        job["title"]
                    ):
                        print(
                            "Rejected senior/lead "
                            f"title: {job['title']}"
                        )

                        stats[
                            "jobs_rejected"
                        ] += 1
                        continue

                    # ----------------------------------------
                    # 3+ YEARS FILTER
                    # ----------------------------------------
                    if requires_three_plus_years(
                        job
                    ):
                        print(
                            "Rejected 3+ years: "
                            f"{job['title']}"
                        )

                        stats[
                            "jobs_rejected"
                        ] += 1
                        continue

                    # ----------------------------------------
                    # DUPLICATE FILTER
                    # ----------------------------------------
                    key = make_job_key(
                        job["company"],
                        job["title"],
                        job["location"],
                    )

                    if key in existing_job_keys:
                        print(
                            "Skipping duplicate: "
                            f"{job['title']}"
                        )

                        stats[
                            "duplicate_jobs_skipped"
                        ] += 1
                        continue

                    # ----------------------------------------
                    # HARD AI COUNTER
                    # ----------------------------------------
                    if ai_counter >= MAX_AI_JOBS:
                        break

                    ai_counter += 1

                    stats[
                        "jobs_analyzed"
                    ] += 1

                    print("\n" + "-" * 70)
                    print(
                        f"AI Analysis: "
                        f"{ai_counter}/{MAX_AI_JOBS}"
                    )
                    print(
                        f"Job: {job['title']}"
                    )
                    print(
                        f"Company: "
                        f"{job['company']}"
                    )

                    result, provider = analyze_job(
                        job,
                        profile,
                    )

                    # ----------------------------------------
                    # AI ANALYSIS FAILURE / STOP HANDLING
                    # ----------------------------------------
                    if result is None:
                        stats[
                            "jobs_rejected"
                        ] += 1

                        if stop_ai_processing:
                            print(
                                "🛑 AI processing stopped after "
                                "provider rate limit."
                            )
                            break

                        print(
                            "⚠️ AI analysis failed for this job; "
                            "skipping."
                        )
                        continue

                    score = result["match_score"]

                    # ----------------------------------------
                    # V2.4 JOB REQUIREMENT GROUNDING
                    # ----------------------------------------
                    result = ground_ai_skill_lists(
                        result,
                        job,
                        profile,
                    )

                    # ----------------------------------------
                    # EXPERIENCE COMPATIBILITY FILTER
                    # ----------------------------------------
                    experience_match = clean_text(
                        result.get("experience_match")
                    ).lower()

                    experience_unsuitable_patterns = [
                        "not suitable",
                        "not suitable due",
                        "senior role requirement",
                        "senior-level mismatch",
                        "senior level mismatch",
                        "not compatible",
                        "requires more experience",
                        "experience mismatch",
                        "not suitable for a fresher",
                    ]

                    if any(
                        pattern in experience_match
                        for pattern in experience_unsuitable_patterns
                    ):
                        print(
                            "Rejected by AI due to experience mismatch: "
                            f"{job['title']}"
                        )

                        stats[
                            "jobs_rejected"
                        ] += 1
                        continue

                    # ----------------------------------------
                    # SCORE FILTER
                    # ----------------------------------------
                    if score < AI_MIN_SCORE:
                        print(
                            "Rejected by AI: "
                            f"{job['title']}"
                        )

                        stats[
                            "jobs_rejected"
                        ] += 1
                        continue

                    # ----------------------------------------
                    # NEW MATCHED JOB
                    # ----------------------------------------
                    print("\n" + "=" * 70)
                    print(
                        "🎯 NEW AI-MATCHED JOB FOUND"
                    )
                    print(
                        f"Job: {job['title']}"
                    )
                    print(
                        f"Company: "
                        f"{job['company']}"
                    )
                    print(
                        f"Location: "
                        f"{job['location']}"
                    )
                    print(
                        f"Salary: "
                        f"{job['salary']}"
                    )
                    print(
                        "Matched Skills: "
                        f"{result['matched_skills']}"
                    )
                    print(
                        "Missing Skills: "
                        f"{result['missing_skills']}"
                    )
                    print(
                        "Experience Match: "
                        f"{result['experience_match']}"
                    )
                    print(
                        f"Reason: {result['reason']}"
                    )

                    print(
                        "\n📊 Writing job "
                        "to Google Sheet..."
                    )

                    row = build_sheet_row(
                        job,
                        result,
                    )

                    if append_and_verify_job(
                        worksheet,
                        row,
                        job,
                    ):
                        existing_job_keys.add(
                            key
                        )

                        stats[
                            "new_jobs_added"
                        ] += 1

                    else:
                        print(
                            "❌ Job append could "
                            "not be verified."
                        )

                    time.sleep(2)

                    # ----------------------------------------
                    # FINAL HARD STOP
                    # ----------------------------------------
                    if (
                        ai_counter
                        >= MAX_AI_JOBS
                    ):
                        break

                if stop_ai_processing:
                    break

            if stop_ai_processing:
                break

        if stop_ai_processing:
            break

    # ========================================================
    # FINAL SUMMARY
    # ========================================================

    print("\n" + "=" * 70)
    print(
        "JOB SEARCH COMPLETED"
    )
    print("=" * 70)

    print(
        f"Total jobs seen: "
        f"{stats['total_jobs_seen']}"
    )
    print(
        f"Jobs analyzed: "
        f"{stats['jobs_analyzed']}"
    )
    print(
        f"New AI-matched jobs added: "
        f"{stats['new_jobs_added']}"
    )
    print(
        f"Duplicate jobs skipped: "
        f"{stats['duplicate_jobs_skipped']}"
    )
    print(
        f"Jobs rejected: "
        f"{stats['jobs_rejected']}"
    )
    print(
        f"Adzuna API errors: "
        f"{stats['adzuna_api_errors']}"
    )
    print(
        f"Groq fallback uses: "
        f"{stats['groq_fallback_uses']}"
    )
    print(
        f"Groq errors: "
        f"{stats['groq_errors']}"
    )
    print(
        f"Groq invalid JSON: "
        f"{stats['groq_invalid_json']}"
    )
    print(
        f"Groq rate-limit events: "
        f"{stats['groq_rate_limit']}"
    )
    print(
        f"Gemini invalid JSON: "
        f"{stats['gemini_invalid_json']}"
    )

    # Provider status
    if gemini_rate_limited:
        print(
            "Gemini status: "
            "RATE LIMIT / QUOTA REACHED"
        )
    elif gemini_available:
        print(
            "Gemini status: AVAILABLE"
        )
    else:
        print(
            "Gemini status: UNAVAILABLE"
        )

    if groq_rate_limited:
        print(
            "Groq status: "
            "RATE LIMIT REACHED → STOPPED"
        )
    elif stop_ai_processing:
        print(
            "Groq status: "
            "STOPPED"
        )
    else:
        print(
            "Groq status: AVAILABLE / NOT RATE-LIMITED"
        )

    if ai_counter >= MAX_AI_JOBS:
        print(
            f"AI limit reached cleanly: "
            f"{ai_counter}/{MAX_AI_JOBS}"
        )

    print("=" * 70)
    print(
        "AI Job Tracker V2.4 Finished!"
    )
    print("=" * 70)


if __name__ == "__main__":
    main()
