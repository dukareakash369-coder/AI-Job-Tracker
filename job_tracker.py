# AI Job Tracker V3 - Persistent Queue + Gemini + Groq + OpenAI
# V3: persistent queue, retry/backoff, provider health, recovery
#
# V2.2.1 fixes:
# 1) Hard MAX_AI_JOBS limit - never analyzes more than the configured limit
# 2) Groq HTTP 429 disables Groq for the current run without stopping job collection
# 3) No duplicate Groq retry for invalid JSON
# 4) Reliable Google Sheets A:N write + verification
# 5) Existing legacy J:W records are recognized for duplicate protection
# 6) Cleaner final statistics and provider status
# 7) Existing filtering / duplicate logic retained
# 8) OpenRouter removed; Groq + OpenAI are fallback providers
# 9) Company-name normalization improves duplicate detection (e.g. Cummins vs Cummins Inc.)
# 10) Sheet header/version log updated to V2.4
# 11) 3+ years filter checks title + experience + description
# 12) AI experience mismatch filter rejects unsuitable AI assessments
# 13) Matched skills are restricted to skills explicitly supported by the job
# 14) V2.4 deterministic skill grounding removes AI-overclaimed matched skills
# 15) Missing skills are kept only when explicitly supported by the job text
# 16) AI-unavailable jobs are preserved in Pending_AI instead of being lost
# 18) Pending jobs are processed before new job discovery
# 19) Retry/backoff, attempt history and stale PROCESSING recovery
# 20) COMPLETED / REJECTED / FAILED lifecycle states
# 17) V3 upgrades Pending_AI into a persistent processing queue

import os
import re
import json
import time
from datetime import datetime, timedelta

import requests
import gspread
from gspread.exceptions import WorksheetNotFound
from google.oauth2.service_account import Credentials
from google import genai


# ============================================================
# CONFIGURATION
# ============================================================

SPREADSHEET_ID = "1TeQSVAHVitgB2T6iBte-MOjHQeyHR-RS0HwTltgjIRo"
WORKSHEET_NAME = "Sheet1"
PENDING_WORKSHEET_NAME = "Pending_AI"
FAILED_WORKSHEET_NAME = "Failed_AI"

AI_MODEL = "gemini-3.6-flash"
GROQ_MODEL = "openai/gpt-oss-20b"
OPENAI_MODEL = "gpt-5.6-luna"

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

# V3 persistent queue schema.
# Existing V2.4 rows remain compatible because the first 11 columns
# keep their original positions; new queue metadata is appended.
PENDING_HEADERS = [
    "Job ID",
    "Date Added",
    "Company",
    "Job Role",
    "Location",
    "Salary",
    "Experience",
    "Description",
    "Apply Link",
    "Status",
    "Failure Reason",
    "Retry Count",
    "Last Attempt",
    "Next Retry",
    "Last Provider",
    "Attempt History",
]

# V3 queue / reliability controls.
MAX_RETRIES = 3
MAX_PENDING_AI_JOBS = 10
RETRY_BACKOFF_MINUTES = [5, 15, 60]

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

openai_available = False
openai_rate_limited = False

groq_rate_limited = False

provider_health = {
    "Gemini": "UNKNOWN",
    "Groq": "UNKNOWN",
    "OpenAI": "UNKNOWN",
}

pending_job_keys = set()

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
    "openai_fallback_uses": 0,
    "openai_errors": 0,
    "openai_invalid_json": 0,
    "openai_rate_limit": 0,
    "pending_processed": 0,
    "pending_completed": 0,
    "pending_retried": 0,
    "pending_rejected": 0,
    "pending_failed": 0,
    "pending_skipped_backoff": 0,
    "queue_recovered": 0,
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
        provider_health["Gemini"] = "DISABLED"
        print("Gemini API key not found. Groq fallback will be used.")
        return

    try:
        gemini_client = genai.Client(api_key=key)
        gemini_available = True
        provider_health["Gemini"] = "AVAILABLE"
        print("Gemini client initialized successfully!")

    except Exception as exc:
        print(f"Gemini initialization failed: {exc}")
        gemini_available = False
        provider_health["Gemini"] = "FAILED"


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

    if (
        not gemini_available
        or gemini_rate_limited
        or gemini_client is None
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
            provider_health["Gemini"] = "RATE_LIMITED"

            print("⚠️ GEMINI RATE LIMIT / QUOTA REACHED")
            print("➡️ Switching to Groq fallback.")

        else:
            print(f"Gemini error: {exc}")
            gemini_available = False
            provider_health["Gemini"] = "FAILED"

        return None


# ============================================================
# GROQ ANALYSIS
# ============================================================

def analyze_with_groq(job, profile):
    global groq_rate_limited

    if groq_rate_limited:
        provider_health["Groq"] = "RATE_LIMITED"
        return None

    key = os.environ.get("GROQ_API_KEY")

    if not key:
        provider_health["Groq"] = "DISABLED"
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
        # GROQ 429: DISABLE GROQ FOR THIS RUN ONLY
        # ----------------------------------------------------
        if response.status_code == 429:
            groq_rate_limited = True
            provider_health["Groq"] = "RATE_LIMITED"
            stats["groq_rate_limit"] += 1

            print(
                "🛑 Groq HTTP 429: rate limit reached."
            )
            print(
                "➡️ Groq disabled for this run. "
                "Job collection will continue."
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
            provider_health["Groq"] = "FAILED"
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
            provider_health["Groq"] = "AVAILABLE"
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
        provider_health["Groq"] = "FAILED"
        return None

    except Exception as exc:
        print(f"Groq processing error: {exc}")
        stats["groq_errors"] += 1
        provider_health["Groq"] = "FAILED"
        return None


# ============================================================
# AI ROUTER
# ============================================================

def analyze_job(job, profile):
    # Primary: Gemini
    if gemini_available and not gemini_rate_limited:
        result = analyze_with_gemini(job, profile)

        if result is not None:
            print("AI Provider: Gemini")
            return result, "Gemini"

    # Fallback: Groq
    if not groq_rate_limited:
        stats["groq_fallback_uses"] += 1

        result = analyze_with_groq(
            job,
            profile,
        )

        if result is not None:
            print("AI Provider: Groq")
            return result, "Groq"

    # Third provider: OpenAI
    if openai_available and not openai_rate_limited:
        stats["openai_fallback_uses"] += 1

        result = analyze_with_openai(
            job,
            profile,
        )

        if result is not None:
            print("AI Provider: OpenAI")
            return result, "OpenAI"

    return None, "None"


# ============================================================
# OPENAI ANALYSIS
# ============================================================

def analyze_with_openai(job, profile):
    """Use OpenAI as the third AI fallback provider."""
    global openai_available
    global openai_rate_limited

    if not openai_available or openai_rate_limited:
        return None

    key = os.environ.get("OPENAI_API_KEY")

    if not key:
        provider_health["OpenAI"] = "DISABLED"
        return None

    print("🔄 Trying OpenAI fallback...")

    strict_prompt = build_ai_prompt(job, profile) + """
IMPORTANT:
Return exactly ONE JSON object and nothing else.
Use double quotes for every JSON key and string.
Do not use Markdown, code fences, commentary, reasoning, or bullet points.
"""

    payload = {
        "model": OPENAI_MODEL,
        "input": [
            {
                "role": "user",
                "content": strict_prompt,
            }
        ],
        "text": {
            "format": {
                "type": "json_object",
            }
        },
    }

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        response = requests.post(
            "https://api.openai.com/v1/responses",
            headers=headers,
            json=payload,
            timeout=60,
        )

        if response.status_code == 429:
            openai_rate_limited = True
            openai_available = False
            provider_health["OpenAI"] = "RATE_LIMITED"
            stats["openai_rate_limit"] += 1

            print("🛑 OpenAI HTTP 429: rate limit reached.")
            print("➡️ OpenAI disabled for this run.")
            return None

        if response.status_code != 200:
            print(
                f"OpenAI HTTP {response.status_code}: "
                f"{response.text[:500]}"
            )
            stats["openai_errors"] += 1
            provider_health["OpenAI"] = "FAILED"
            return None

        data = response.json()

        content = data.get("output_text", "")

        if not content:
            parts = []
            for item in data.get("output", []) or []:
                for part in item.get("content", []) or []:
                    text = part.get("text")
                    if text:
                        parts.append(str(text))
            content = "\n".join(parts)

        result = normalize_ai_result(
            extract_json_object(content)
        )

        if result is not None:
            provider_health["OpenAI"] = "AVAILABLE"
            print("✅ OpenAI fallback analysis successful!")
            return result

        stats["openai_invalid_json"] += 1
        print("⚠️ OpenAI returned invalid JSON.")
        print(f"Raw response: {str(content)[:700]}")
        print("➡️ Skipping this job without another OpenAI retry.")
        return None

    except requests.RequestException as exc:
        print(f"OpenAI request error: {exc}")
        stats["openai_errors"] += 1
        provider_health["OpenAI"] = "FAILED"
        return None

    except Exception as exc:
        print(f"OpenAI processing error: {exc}")
        stats["openai_errors"] += 1
        provider_health["OpenAI"] = "FAILED"
        return None


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
        "job_id": clean_text(raw.get("id")),
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
# V3 PERSISTENT PENDING AI QUEUE
# ============================================================

ACTIVE_PENDING_STATUSES = {"PENDING", "PROCESSING", "RETRY"}
FINAL_PENDING_STATUSES = {"COMPLETED", "REJECTED", "FAILED"}


def utc_now():
    """Return a consistent UTC timestamp for queue scheduling."""
    return datetime.utcnow()


def format_timestamp(value):
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return clean_text(value)


def parse_timestamp(value):
    value = clean_text(value)
    if not value:
        return None

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue

    return None


def get_or_create_pending_worksheet(worksheet):
    """Get or create the V3 Pending_AI worksheet and upgrade its header."""
    spreadsheet = worksheet.spreadsheet

    try:
        pending = spreadsheet.worksheet(PENDING_WORKSHEET_NAME)
        print("Pending_AI worksheet found.")
    except WorksheetNotFound:
        print("Creating Pending_AI worksheet...")
        pending = spreadsheet.add_worksheet(
            title=PENDING_WORKSHEET_NAME,
            rows=2000,
            cols=len(PENDING_HEADERS),
        )

    if pending.col_count < len(PENDING_HEADERS):
        pending.resize(cols=len(PENDING_HEADERS))

    pending.update(
        range_name=f"A1:{chr(64 + len(PENDING_HEADERS))}1",
        values=[PENDING_HEADERS],
    )
    return pending


def get_or_create_failed_worksheet(worksheet):
    """Get or create the V3 dead-letter worksheet."""
    spreadsheet = worksheet.spreadsheet

    try:
        failed = spreadsheet.worksheet(FAILED_WORKSHEET_NAME)
        print("Failed_AI worksheet found.")
    except WorksheetNotFound:
        print("Creating Failed_AI worksheet...")
        failed = spreadsheet.add_worksheet(
            title=FAILED_WORKSHEET_NAME,
            rows=2000,
            cols=len(PENDING_HEADERS),
        )

    if failed.col_count < len(PENDING_HEADERS):
        failed.resize(cols=len(PENDING_HEADERS))

    failed.update(
        range_name=f"A1:{chr(64 + len(PENDING_HEADERS))}1",
        values=[PENDING_HEADERS],
    )
    return failed


def pending_row_to_record(row, row_number):
    """Convert a Pending_AI spreadsheet row into a V3 queue record."""
    values = list(row) + [""] * max(0, len(PENDING_HEADERS) - len(row))

    return {
        "row_number": row_number,
        "job_id": clean_text(values[0]),
        "date_added": clean_text(values[1]),
        "company": clean_text(values[2]),
        "title": clean_text(values[3]),
        "location": clean_text(values[4]),
        "salary": clean_text(values[5]),
        "experience": clean_text(values[6]),
        "description": clean_text(values[7]),
        "apply_link": clean_text(values[8]),
        "status": clean_text(values[9]).upper() or "PENDING",
        "failure_reason": clean_text(values[10]),
        "retry_count": safe_int(values[11], 0),
        "last_attempt": clean_text(values[12]),
        "next_retry": clean_text(values[13]),
        "last_provider": clean_text(values[14]),
        "attempt_history": clean_text(values[15]),
    }


def pending_record_to_job(record):
    return {
        "job_id": record["job_id"],
        "title": record["title"],
        "company": record["company"],
        "location": record["location"],
        "salary": record["salary"],
        "experience": record["experience"],
        "description": record["description"],
        "apply_link": record["apply_link"],
    }


def load_pending_records(pending_worksheet):
    """Load all pending records and recover stale PROCESSING rows."""
    records = []

    try:
        rows = pending_worksheet.get_all_values()

        for row_number, row in enumerate(rows[1:], start=2):
            if not row or not any(clean_text(x) for x in row):
                continue

            record = pending_row_to_record(row, row_number)

            # V2.4 rows have PENDING in column J and no retry metadata.
            if not record["status"]:
                record["status"] = "PENDING"

            # A previous GitHub Actions run may have died after setting
            # PROCESSING. Recover it instead of leaving the job stuck forever.
            if record["status"] == "PROCESSING":
                record["status"] = "RETRY"
                record["failure_reason"] = (
                    "Recovered stale PROCESSING state from previous run"
                )
                record["next_retry"] = format_timestamp(utc_now())
                stats["queue_recovered"] += 1
                update_pending_record(
                    pending_worksheet,
                    record,
                    status="RETRY",
                    failure_reason=record["failure_reason"],
                    next_retry=record["next_retry"],
                    append_history="RECOVERED",
                )

            records.append(record)

    except Exception as exc:
        print(f"Could not load Pending_AI records: {exc}")

    return records


def load_pending_job_keys(pending_worksheet):
    """Load active pending jobs only; completed/final records do not block rediscovery."""
    keys = set()

    for record in load_pending_records(pending_worksheet):
        if record["status"] in ACTIVE_PENDING_STATUSES:
            if record["company"] or record["title"]:
                keys.add(
                    make_job_key(
                        record["company"],
                        record["title"],
                        record["location"],
                    )
                )

    return keys


def build_pending_row(
    job,
    failure_reason="",
    status="PENDING",
    retry_count=0,
    last_attempt="",
    next_retry="",
    last_provider="",
    attempt_history="",
    date_added=None,
):
    """Build a durable V3 queue row."""
    job_id = clean_text(job.get("job_id")) or "|".join([
        clean_text(job.get("company")),
        clean_text(job.get("title")),
        clean_text(job.get("location")),
    ])

    row = [
        job_id,
        date_added or format_timestamp(utc_now()),
        job.get("company", ""),
        job.get("title", ""),
        job.get("location", ""),
        job.get("salary", ""),
        job.get("experience", ""),
        clean_text(job.get("description", ""))[:20000],
        job.get("apply_link", ""),
        status,
        failure_reason,
        retry_count,
        last_attempt,
        next_retry,
        last_provider,
        attempt_history,
    ]

    if len(row) != len(PENDING_HEADERS):
        raise ValueError(
            f"Pending_AI row has {len(row)} columns; "
            f"expected {len(PENDING_HEADERS)}."
        )

    return row


def update_pending_record(
    pending_worksheet,
    record,
    status=None,
    failure_reason=None,
    retry_count=None,
    last_attempt=None,
    next_retry=None,
    last_provider=None,
    append_history=None,
):
    """Update one queue record in-place and preserve all job data."""
    if status is not None:
        record["status"] = status
    if failure_reason is not None:
        record["failure_reason"] = failure_reason
    if retry_count is not None:
        record["retry_count"] = retry_count
    if last_attempt is not None:
        record["last_attempt"] = last_attempt
    if next_retry is not None:
        record["next_retry"] = next_retry
    if last_provider is not None:
        record["last_provider"] = last_provider

    if append_history:
        timestamp = format_timestamp(utc_now())
        event = f"{timestamp} | {append_history}"
        if record["attempt_history"]:
            record["attempt_history"] += " || " + event
        else:
            record["attempt_history"] = event

    row = [
        record["job_id"],
        record["date_added"],
        record["company"],
        record["title"],
        record["location"],
        record["salary"],
        record["experience"],
        record["description"][:20000],
        record["apply_link"],
        record["status"],
        record["failure_reason"],
        record["retry_count"],
        record["last_attempt"],
        record["next_retry"],
        record["last_provider"],
        record["attempt_history"],
    ]

    target_range = f"A{record['row_number']}:{chr(64 + len(PENDING_HEADERS))}{record['row_number']}"

    pending_worksheet.update(
        range_name=target_range,
        values=[row],
        value_input_option="USER_ENTERED",
    )

    return True


def append_pending_job(
    pending_worksheet,
    job,
    failure_reason,
    status="PENDING",
    retry_count=0,
    next_retry=None,
    last_provider="",
):
    """Add a new job to the persistent queue and verify the write."""
    global pending_job_keys

    key = make_job_key(
        job["company"],
        job["title"],
        job["location"],
    )

    if key in pending_job_keys:
        print(
            "Skipping duplicate Pending_AI job: "
            f"{job['title']}"
        )
        return False

    try:
        now = format_timestamp(utc_now())
        row = build_pending_row(
            job,
            failure_reason=failure_reason,
            status=status,
            retry_count=retry_count,
            last_attempt="",
            next_retry=next_retry or now,
            last_provider=last_provider,
            attempt_history="QUEUED",
        )

        next_row = get_next_sheet_row(pending_worksheet)
        target_range = f"A{next_row}:P{next_row}"

        print(
            f"📥 Writing pending job to "
            f"Pending_AI!{target_range}"
        )

        pending_worksheet.update(
            range_name=target_range,
            values=[row],
            value_input_option="USER_ENTERED",
        )

        time.sleep(1)
        written = pending_worksheet.get(target_range)

        if not written or not written[0]:
            print("❌ Pending_AI verification failed.")
            return False

        saved = written[0]

        if len(saved) < len(PENDING_HEADERS):
            print(
                "❌ Pending_AI verification failed: "
                f"expected {len(PENDING_HEADERS)} columns, "
                f"got {len(saved)}."
            )
            return False

        expected_key = key
        saved_key = make_job_key(saved[2], saved[3], saved[4])

        if saved_key != expected_key:
            print("❌ Pending_AI verification failed: job key mismatch.")
            return False

        pending_job_keys.add(key)
        print("✅ Job saved successfully to Pending_AI.")
        return True

    except Exception as exc:
        print(f"❌ Pending_AI append failed: {exc}")
        return False


def get_ai_failure_reason():
    """Return the current provider-health reason."""
    reasons = []

    if not gemini_available:
        if gemini_rate_limited:
            reasons.append("Gemini rate limit/quota reached")
        else:
            reasons.append("Gemini unavailable")

    if groq_rate_limited:
        reasons.append("Groq rate limit reached")
    elif not os.environ.get("GROQ_API_KEY"):
        reasons.append("Groq API key unavailable")

    if not openai_available:
        if openai_rate_limited:
            reasons.append("OpenAI rate limit reached")
        else:
            reasons.append("OpenAI unavailable")

    return " + ".join(reasons) if reasons else "AI analysis failed"


def get_retry_delay_minutes(retry_count):
    index = min(max(retry_count, 0), len(RETRY_BACKOFF_MINUTES) - 1)
    return RETRY_BACKOFF_MINUTES[index]


def calculate_next_retry(retry_count):
    return format_timestamp(
        utc_now() + timedelta(minutes=get_retry_delay_minutes(retry_count))
    )


def is_retry_due(record):
    next_retry = parse_timestamp(record.get("next_retry", ""))
    if next_retry is None:
        return True
    return utc_now() >= next_retry


def append_failed_record(failed_worksheet, record, reason, provider=""):
    """Persist a terminally failed job in the V3 dead-letter queue."""
    failed_record = dict(record)
    failed_record["status"] = "FAILED"
    failed_record["failure_reason"] = reason
    failed_record["next_retry"] = ""
    failed_record["last_provider"] = provider or record.get("last_provider", "")
    failed_record["attempt_history"] = (
        record.get("attempt_history", "")
        + (
            " || " if record.get("attempt_history") else ""
        )
        + f"{format_timestamp(utc_now())} | DEAD_LETTER"
    )

    try:
        next_row = get_next_sheet_row(failed_worksheet)
        row = [
            failed_record["job_id"],
            failed_record["date_added"],
            failed_record["company"],
            failed_record["title"],
            failed_record["location"],
            failed_record["salary"],
            failed_record["experience"],
            failed_record["description"][:20000],
            failed_record["apply_link"],
            failed_record["status"],
            failed_record["failure_reason"],
            failed_record["retry_count"],
            failed_record["last_attempt"],
            failed_record["next_retry"],
            failed_record["last_provider"],
            failed_record["attempt_history"],
        ]
        target_range = f"A{next_row}:P{next_row}"
        failed_worksheet.update(
            range_name=target_range,
            values=[row],
            value_input_option="USER_ENTERED",
        )
        print(f"☠️ Job copied to Failed_AI!{target_range}")
        return True
    except Exception as exc:
        print(f"❌ Failed_AI append failed: {exc}")
        return False


def queue_retry_or_fail(
    pending_worksheet,
    failed_worksheet,
    record,
    reason,
    provider="",
):
    """Retry temporary failures with backoff; then move to Failed_AI."""
    new_retry_count = record["retry_count"] + 1
    now = format_timestamp(utc_now())

    if new_retry_count <= MAX_RETRIES:
        next_retry = calculate_next_retry(new_retry_count - 1)

        update_pending_record(
            pending_worksheet,
            record,
            status="RETRY",
            failure_reason=reason,
            retry_count=new_retry_count,
            last_attempt=now,
            next_retry=next_retry,
            last_provider=provider,
            append_history=(
                f"RETRY #{new_retry_count}; "
                f"provider={provider or 'None'}; reason={reason}"
            ),
        )

        stats["pending_retried"] += 1
        print(
            f"🔁 Pending job scheduled for retry #{new_retry_count} "
            f"at {next_retry}"
        )
        return "RETRY"

    update_pending_record(
        pending_worksheet,
        record,
        status="FAILED",
        failure_reason=reason,
        retry_count=new_retry_count,
        last_attempt=now,
        next_retry="",
        last_provider=provider,
        append_history=(
            f"FAILED after {new_retry_count} attempts; "
            f"provider={provider or 'None'}; reason={reason}"
        ),
    )

    if append_failed_record(
        failed_worksheet,
        record,
        reason,
        provider=provider,
    ):
        stats["pending_failed"] += 1
        print("☠️ Pending job moved to Failed_AI dead-letter queue.")
    else:
        print("⚠️ Failed_AI copy failed; FAILED state remains in Pending_AI.")

    return "FAILED"


def mark_pending_processing(pending_worksheet, record):
    """Transition a queue item into PROCESSING before calling an AI provider."""
    now = format_timestamp(utc_now())

    update_pending_record(
        pending_worksheet,
        record,
        status="PROCESSING",
        last_attempt=now,
        append_history="PROCESSING",
    )


def complete_pending_job(pending_worksheet, record):
    """Mark a successfully written Sheet1 job as COMPLETED."""
    update_pending_record(
        pending_worksheet,
        record,
        status="COMPLETED",
        failure_reason="",
        next_retry="",
        append_history="COMPLETED → Sheet1",
    )
    stats["pending_completed"] += 1


def reject_pending_job(pending_worksheet, record, reason):
    """Mark an unsuitable job as REJECTED; do not retry deterministic rejection."""
    update_pending_record(
        pending_worksheet,
        record,
        status="REJECTED",
        failure_reason=reason,
        next_retry="",
        append_history=f"REJECTED; reason={reason}",
    )
    stats["pending_rejected"] += 1


def analyze_pending_job(pending_worksheet, failed_worksheet, record, profile):
    """
    Process one persisted queue item.
    Returns True when the item reached a final state or a retry was scheduled.
    """
    global existing_job_keys

    if record["status"] in FINAL_PENDING_STATUSES:
        return True

    if not is_retry_due(record):
        stats["pending_skipped_backoff"] += 1
        return False

    job = pending_record_to_job(record)
    key = make_job_key(job["company"], job["title"], job["location"])

    # A job may already have reached Sheet1 after a previous partial failure.
    if key in existing_job_keys:
        complete_pending_job(pending_worksheet, record)
        return True

    mark_pending_processing(pending_worksheet, record)
    stats["pending_processed"] += 1
    stats["jobs_analyzed"] += 1

    print("\n" + "-" * 70)
    print("🔄 V3 PENDING JOB PROCESSING")
    print(f"Job: {job['title']}")
    print(f"Company: {job['company']}")
    print(f"Retry Count: {record['retry_count']}")

    result, provider = analyze_job(job, profile)

    if result is None:
        queue_retry_or_fail(
            pending_worksheet,
            failed_worksheet,
            record,
            get_ai_failure_reason(),
            provider=provider,
        )
        return True

    result = ground_ai_skill_lists(result, job, profile)
    score = result["match_score"]

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
        reason = "AI experience mismatch"
        print(f"⛔ Pending job rejected: {job['title']}")
        reject_pending_job(pending_worksheet, record, reason)
        return True

    if score < AI_MIN_SCORE:
        reason = f"AI match score below threshold ({score} < {AI_MIN_SCORE})"
        print(f"⛔ Pending job rejected: {job['title']} | {reason}")
        reject_pending_job(pending_worksheet, record, reason)
        return True

    print("🎯 Pending job qualified.")
    row = build_sheet_row(job, result)

    if append_and_verify_job(worksheet_global, row, job):
        existing_job_keys.add(key)
        stats["new_jobs_added"] += 1
        complete_pending_job(pending_worksheet, record)
        return True

    queue_retry_or_fail(
        pending_worksheet,
        failed_worksheet,
        record,
        "Sheet1 append verification failed",
        provider=provider,
    )
    return True


# Global reference used only by the pending processor after Google Sheet connection.
worksheet_global = None


def process_pending_queue(pending_worksheet, failed_worksheet, profile, ai_budget):
    """Process eligible pending jobs before discovering new jobs."""
    global worksheet_global

    records = load_pending_records(pending_worksheet)

    eligible = [
        record
        for record in records
        if record["status"] in {"PENDING", "RETRY"}
        and is_retry_due(record)
    ]

    if not eligible:
        print("📭 No pending jobs are currently due for processing.")
        return ai_budget

    print("\n" + "=" * 70)
    print(f"🔄 V3 PENDING QUEUE: {len(eligible)} job(s) due")
    print("=" * 70)

    processed = 0

    for record in eligible:
        if processed >= min(MAX_PENDING_AI_JOBS, ai_budget):
            print("⚠️ Pending AI budget reached for this run.")
            break

        # Every actual AI attempt consumes one run-level budget unit.
        before_analyzed = stats["jobs_analyzed"]

        analyze_pending_job(
            pending_worksheet,
            failed_worksheet,
            record,
            profile,
        )

        if stats["jobs_analyzed"] > before_analyzed:
            processed += 1

        # If the provider became unavailable, remaining pending jobs stay queued.
        if (
            not gemini_available
            and groq_rate_limited
            and not openai_available
        ):
            print("⚠️ All AI providers unavailable; remaining pending jobs stay queued.")
            break

    return max(0, ai_budget - processed)


def main():
    global existing_job_keys
    global pending_job_keys
    global worksheet_global

    print("=" * 70)
    print("AI Job Tracker V3 Started!")
    print("Persistent Queue + Retry + AI Router + Recovery")
    print("=" * 70)

    profile = load_candidate_profile()
    initialize_gemini()

    global openai_available
    global openai_rate_limited

    if os.environ.get("OPENAI_API_KEY"):
        openai_available = True
        provider_health["OpenAI"] = "AVAILABLE"
        print("OpenAI provider configured successfully!")
    else:
        openai_available = False
        provider_health["OpenAI"] = "DISABLED"
        print("OpenAI API key not found. OpenAI fallback disabled.")

    worksheet = connect_google_sheet()
    worksheet_global = worksheet

    if worksheet is None:
        print("Cannot continue without Google Sheet.")
        return

    update_headers(worksheet)

    pending_worksheet = get_or_create_pending_worksheet(worksheet)
    failed_worksheet = get_or_create_failed_worksheet(worksheet)

    existing_job_keys = load_existing_job_keys(worksheet)
    pending_job_keys = load_pending_job_keys(pending_worksheet)

    print(
        f"Existing jobs in Sheet: "
        f"{len(existing_job_keys)}"
    )
    print(
        f"Existing active pending jobs: "
        f"{len(pending_job_keys)}"
    )

    ai_counter = 0

    # ========================================================
    # V3 PRIORITY 1: PROCESS PERSISTENT PENDING QUEUE FIRST
    # ========================================================

    pending_budget = min(MAX_PENDING_AI_JOBS, MAX_AI_JOBS)
    pending_before = stats["jobs_analyzed"]

    # analyze_job increments jobs_analyzed only inside the provider call.
    process_pending_queue(
        pending_worksheet,
        failed_worksheet,
        profile,
        pending_budget,
    )

    ai_counter += stats["jobs_analyzed"] - pending_before

    # ========================================================
    # V3 PRIORITY 2: DISCOVER NEW JOBS
    # ========================================================

    for query in SEARCH_QUERIES:
        print("\n" + "=" * 70)
        print(f"Searching: {query}")
        print("=" * 70)

        for location in LOCATIONS:
            print(f"\nLocation: {location}")

            for page in range(1, TOTAL_PAGES + 1):
                jobs = get_adzuna_jobs(query, location, page)

                print(
                    f"Page {page}: {len(jobs)} jobs received."
                )

                if not jobs:
                    continue

                for raw in jobs:
                    stats["total_jobs_seen"] += 1

                    job = prepare_job(raw, location)

                    if not job["title"]:
                        stats["jobs_rejected"] += 1
                        continue

                    # ----------------------------------------
                    # SENIOR TITLE FILTER
                    # ----------------------------------------
                    if is_senior_title(job["title"]):
                        print(
                            "Rejected senior/lead title: "
                            f"{job['title']}"
                        )
                        stats["jobs_rejected"] += 1
                        continue

                    # ----------------------------------------
                    # 3+ YEARS FILTER
                    # ----------------------------------------
                    if requires_three_plus_years(job):
                        print(
                            "Rejected 3+ years: "
                            f"{job['title']}"
                        )
                        stats["jobs_rejected"] += 1
                        continue

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
                        stats["duplicate_jobs_skipped"] += 1
                        continue

                    if key in pending_job_keys:
                        print(
                            "Skipping existing Pending_AI job: "
                            f"{job['title']}"
                        )
                        stats["duplicate_jobs_skipped"] += 1
                        continue

                    # ----------------------------------------
                    # AI AVAILABILITY
                    # ----------------------------------------
                    ai_provider_available = (
                        (gemini_available and not gemini_rate_limited)
                        or (
                            bool(os.environ.get("GROQ_API_KEY"))
                            and not groq_rate_limited
                        )
                        or (
                            bool(os.environ.get("OPENAI_API_KEY"))
                            and openai_available
                            and not openai_rate_limited
                        )
                    )

                    if not ai_provider_available:
                        print("⚠️ No AI provider available.")
                        print("➡️ Saving job to Pending_AI.")
                        append_pending_job(
                            pending_worksheet,
                            job,
                            get_ai_failure_reason(),
                            status="PENDING",
                        )
                        continue

                    # ----------------------------------------
                    # HARD AI ATTEMPT LIMIT
                    # ----------------------------------------
                    if ai_counter >= MAX_AI_JOBS:
                        print(
                            f"⚠️ AI attempt limit reached "
                            f"({MAX_AI_JOBS})."
                        )
                        print("➡️ Saving job to Pending_AI.")
                        append_pending_job(
                            pending_worksheet,
                            job,
                            "Maximum AI analysis limit reached "
                            f"({MAX_AI_JOBS})",
                            status="PENDING",
                        )
                        continue

                    # ----------------------------------------
                    # NEW JOB AI ANALYSIS
                    # ----------------------------------------
                    ai_counter += 1
                    stats["jobs_analyzed"] += 1

                    print("\n" + "-" * 70)
                    print(
                        f"AI Analysis: "
                        f"{ai_counter}/{MAX_AI_JOBS}"
                    )
                    print(f"Job: {job['title']}")
                    print(f"Company: {job['company']}")

                    result, provider = analyze_job(job, profile)

                    if result is None:
                        print(
                            "⚠️ AI analysis unavailable for this job."
                        )
                        print("➡️ Saving job to Pending_AI.")
                        append_pending_job(
                            pending_worksheet,
                            job,
                            get_ai_failure_reason(),
                            status="PENDING",
                            last_provider=provider,
                        )
                        continue

                    result = ground_ai_skill_lists(
                        result,
                        job,
                        profile,
                    )

                    score = result["match_score"]

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
                        stats["jobs_rejected"] += 1
                        continue

                    if score < AI_MIN_SCORE:
                        print(
                            "Rejected by AI: "
                            f"{job['title']}"
                        )
                        stats["jobs_rejected"] += 1
                        continue

                    print("\n" + "=" * 70)
                    print("🎯 NEW AI-MATCHED JOB FOUND")
                    print(f"Job: {job['title']}")
                    print(f"Company: {job['company']}")
                    print(f"Location: {job['location']}")
                    print(f"Salary: {job['salary']}")
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
                    print(f"Reason: {result['reason']}")

                    print("\n📊 Writing job to Google Sheet...")

                    row = build_sheet_row(job, result)

                    if append_and_verify_job(
                        worksheet,
                        row,
                        job,
                    ):
                        existing_job_keys.add(key)
                        stats["new_jobs_added"] += 1
                    else:
                        # The job itself was valid; only persistence failed.
                        # Keep it in the durable queue so it is not lost.
                        append_pending_job(
                            pending_worksheet,
                            job,
                            "Sheet1 append verification failed",
                            status="RETRY",
                            retry_count=1,
                            next_retry=calculate_next_retry(0),
                            last_provider=provider,
                        )

                    time.sleep(2)

    # ========================================================
    # FINAL SUMMARY
    # ========================================================

    print("\n" + "=" * 70)
    print("V3 JOB SEARCH COMPLETED")
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
        f"Pending processed: "
        f"{stats['pending_processed']}"
    )
    print(
        f"Pending completed: "
        f"{stats['pending_completed']}"
    )
    print(
        f"Pending retried: "
        f"{stats['pending_retried']}"
    )
    print(
        f"Pending rejected: "
        f"{stats['pending_rejected']}"
    )
    print(
        f"Pending failed: "
        f"{stats['pending_failed']}"
    )
    print(
        f"Pending skipped due to backoff: "
        f"{stats['pending_skipped_backoff']}"
    )
    print(
        f"Queue recoveries: "
        f"{stats['queue_recovered']}"
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
        f"OpenAI fallback uses: "
        f"{stats['openai_fallback_uses']}"
    )
    print(
        f"OpenAI errors: "
        f"{stats['openai_errors']}"
    )
    print(
        f"OpenAI invalid JSON: "
        f"{stats['openai_invalid_json']}"
    )
    print(
        f"OpenAI rate-limit events: "
        f"{stats['openai_rate_limit']}"
    )
    print(
        f"Gemini invalid JSON: "
        f"{stats['gemini_invalid_json']}"
    )

    # Reload active queue count after all updates.
    final_pending_records = load_pending_records(pending_worksheet)
    active_pending = [
        r for r in final_pending_records
        if r["status"] in ACTIVE_PENDING_STATUSES
    ]

    print(
        f"Active pending jobs: "
        f"{len(active_pending)}"
    )

    failed_records = failed_worksheet.get_all_values()
    print(
        f"Dead-letter Failed_AI jobs: "
        f"{max(0, len(failed_records) - 1)}"
    )

    print(
        f"Gemini provider health: "
        f"{provider_health.get('Gemini', 'UNKNOWN')}"
    )
    print(
        f"Groq provider health: "
        f"{provider_health.get('Groq', 'UNKNOWN')}"
    )
    print(
        f"OpenAI provider health: "
        f"{provider_health.get('OpenAI', 'UNKNOWN')}"
    )

    print(
        f"AI budget used: "
        f"{ai_counter}/{MAX_AI_JOBS}"
    )

    print("=" * 70)
    print("AI Job Tracker V3 Finished!")
    print("=" * 70)

if __name__ == "__main__":
    main()
