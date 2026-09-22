# AI Job Tracker – V1.1✔️
# AI Job Tracker – V1.2.4✔️
# AI Job Tracker – V1.3 in still working 

> An automated job discovery and tracking system for entry-level Embedded, AI, IoT and Robotics opportunities.

AI Job Tracker is a Python-based automation project that searches job listings, filters them according to predefined career criteria, calculates a relevance score, detects duplicate entries, and stores suitable opportunities in Google Sheets.

The V1 version focuses on entry-level engineering opportunities, with priority given to Pune and remote opportunities in India.

---

## 📌 Project Overview

Finding relevant engineering jobs manually across multiple job portals can be repetitive, time-consuming, and difficult to track.

This project automates the initial job-search workflow by combining:

- Job API integration
- Python-based data processing
- Role and experience filtering
- Skill-based relevance scoring
- Duplicate detection
- Google Sheets tracking
- GitHub Actions automation

The goal is to reduce repetitive job-search work and create a structured personal job-tracking pipeline.

---

## 🎯 Problem Statement

Manual job searching creates several challenges:

- Searching for jobs repeatedly every day
- Filtering irrelevant senior-level positions
- Checking whether a job matches relevant skills
- Tracking previously found opportunities
- Maintaining a structured application list
- Avoiding duplicate job entries

AI Job Tracker addresses these problems by automating the initial discovery and filtering process.

---

## 💡 Solution

The V1 pipeline performs the following steps:

1. Fetch job listings using the Adzuna Job API.
2. Process the returned job data using Python.
3. Identify relevant engineering roles.
4. Filter out senior and higher-experience positions.
5. Prioritize Pune and remote opportunities.
6. Identify relevant technical skills.
7. Calculate a Match Score.
8. Check existing Google Sheets entries to avoid duplicates.
9. Store new opportunities in Google Sheets.
10. Execute the workflow automatically using GitHub Actions.

---

## 🎯 Target Roles

V1 focuses on:

- Embedded Engineer
- Embedded AI Engineer
- IoT Engineer
- Robotics Engineer

The filtering logic can also identify related entry-level titles such as:

- Embedded Software Engineer
- Firmware Engineer
- Junior Embedded Engineer
- Embedded Systems Engineer

---

## 📍 Target Location

### Primary Focus

- Pune, Maharashtra
- Remote opportunities in India

### Experience Focus

- Fresher
- 0–2 years experience

The filtering logic excludes higher-experience positions such as:

- Senior
- Sr.
- Lead
- Manager
- Principal
- Architect
- Director
- 3+ years and above

---

## 🧠 Match Scoring

The system calculates a relevance score based on job information.

The scoring logic considers factors such as:

- Entry-level / fresher relevance
- C / C++ skills
- Python
- Embedded Systems
- ESP32 / STM32
- IoT
- Robotics

Jobs below the configured relevance threshold are not added to the tracking sheet.

This provides a simple rule-based ranking mechanism for prioritizing job opportunities.

---

## 🔄 System Architecture

```text
              Adzuna Job API
                     ↓
              Python Script
                     ↓
             Job Data Processing
                     ↓
               Job Filtering
                     ↓
              Match Scoring
                     ↓
              Duplicate Check
                     ↓
               Google Sheets
                     ↑
                     |
             GitHub Actions
                     ↓
          Automated Execution
```

---

## ⚙️ Key Features

### 🔎 Automated Job Search

Fetches job listings through the Adzuna Job API.

### 🎯 Smart Job Filtering

Filters opportunities according to:

- Target roles
- Location
- Experience level
- Technical relevance

### 📊 Match Scoring

Calculates a relevance score based on predefined technical and career criteria.

### ♻️ Duplicate Detection

Checks existing job entries using the application link before adding a new opportunity.

### 📋 Google Sheets Tracking

Stores job information in a structured format.

Tracked fields include:

| Field | Description |
|---|---|
| Date | Date the job was added |
| Company | Company name when available |
| Job Role | Job title |
| Location | Job location |
| Salary | Salary information when available |
| Experience | Experience requirement |
| Skills | Relevant technical skills |
| Match Score | Calculated relevance score |
| Apply Link | Job application / source link |
| Status | Application tracking status |

### 🤖 Automated Execution

GitHub Actions executes the Python workflow automatically according to the configured schedule.

---

## 🛠️ Tech Stack

| Technology | Purpose |
|---|---|
| Python | Data processing and automation |
| Adzuna Job API | Job data source |
| Google Sheets | Job tracking and storage |
| GitHub Actions | Workflow automation |
| GitHub | Source code and project management |

---

## 📂 Project Structure

```text
AI-Job-Tracker/
│
├── .github/
│   └── workflows/
│       └── main.yml
│
├── 1.png
├── 2.png
├── 3.png
├── project-architecture.png
│
├── job_tracker.py
└── README.md
```

---

## 🔐 Security

API credentials and Google Service Account credentials are stored securely using GitHub Actions Secrets.

Sensitive credentials are not stored directly inside the source code.

Required secrets include:

```text
ADZUNA_APP_ID
ADZUNA_APP_KEY
GOOGLE_SERVICE_ACCOUNT_JSON
```

---

## 📸 Project Screenshots

### 🏗️ System Architecture

![AI Job Tracker V1 Architecture](./project-architecture.png)

### 1. GitHub Repository

![GitHub Repository](./1.png)

### 2. GitHub Actions – Successful Run

![GitHub Actions](./2.png)

### 3. Google Sheets – Job Data

![Google Sheets](./3.png)

### 4. Project Architecture

![AI Job Tracker V1 Architecture](./4.png)

---

## 📈 V1 Status

### ✅ Completed

- Adzuna API integration
- Python job-processing pipeline
- Role filtering
- Experience filtering
- Skill detection
- Match scoring
- Duplicate checking
- Google Sheets integration
- GitHub Actions integration
- Automated workflow execution
- GitHub project documentation

V1 is currently functional as a personal job-discovery and tracking system.

---
# AI Job Tracker – V2 🤖🚀

> An AI-assisted job search and tracking system for Embedded, AI, IoT and Robotics jobs.

AI Job Tracker V2 is a Python-based job tracking system that automatically finds job opportunities, filters irrelevant jobs, uses AI to compare jobs with a candidate profile, detects duplicates, and stores useful jobs in Google Sheets.

The project started with a basic rule-based system and was improved step by step by adding AI matching, better filtering, error handling, duplicate protection, and a pending-job processing system.





🤖 V2 AI Matching

The main improvement in V2 is AI-assisted job matching.

Instead of depending only on fixed rules, the system sends suitable job information to an AI model and compares the job with the candidate profile.

The AI analysis can provide:

Match Score
Matched Skills
Missing Skills
Experience Match
Match Reason

This helps identify how closely a job matches the candidate's skills and experience.

📌 Version History
V2 — AI-Assisted Job Matching

Status: ✅ Completed

V2 introduced AI-based job analysis.

Main Improvements
AI job matching
Candidate profile comparison
AI match score
Matched skills
Missing skills
Experience matching
Match explanation
V2.1 — Reliability Improvements

Status: ✅ Completed

V2.1 improved the reliability of the AI job-processing pipeline.

Improvements
Better job filtering
Better senior-level filtering
Improved duplicate protection
AI processing limits
Better Google Sheets handling
Better workflow statistics
V2.2 — AI Provider Improvements

Status: ✅ Completed

V2.2 improved AI provider handling and error management.

Improvements
Gemini as primary AI provider
Fallback AI support
Better API error handling
Better JSON handling
Protection against repeated API failures
Improved AI processing control
V2.3 — Matching & Reliability Improvements

Status: ✅ Completed

V2.3 improved job matching and system reliability.

Improvements
Company-name normalization
Better duplicate detection
Improved experience filtering
Better AI scoring
Improved job filtering
Better fallback handling
More reliable Google Sheets updates
V2.4 — AI + Pending Job Queue

Status: ✅ Current

V2.4 is the current version of the project.

The main improvement is the Pending_AI queue.

When a job is discovered but AI analysis cannot be completed, the job can be saved for future processing instead of being lost.

Main Features
Gemini as primary AI provider
Groq as fallback provider
AI rate-limit handling
Continued job collection
Pending_AI queue
Skill grounding
Job requirement grounding
Duplicate protection
AI processing limits
Better error handling
⏳ Pending_AI Queue

The Pending_AI queue stores jobs that need AI processing but could not be completely processed during the current run.

Example:

Job Found
   ↓
Initial Filtering
   ↓
AI Processing
   ↓
AI Unavailable
   ↓
Pending_AI

This means the system does not simply lose a useful job when an AI provider is temporarily unavailable.

Sheet1 vs Pending_AI
Sheet	Purpose
Sheet1	Successfully analyzed and qualified jobs
Pending_AI	Jobs waiting for future AI processing
🧠 Skill Grounding

V2.4 also improves the reliability of AI-generated skill information.

The system checks whether reported matched skills are actually supported by:

Candidate profile
Job requirements

This helps reduce incorrect or unsupported skill matches.

🎯 Target Roles

The system focuses mainly on entry-level roles such as:

Embedded Engineer
Embedded Software Engineer
Embedded Systems Engineer
Firmware Engineer
Junior Embedded Engineer
Embedded AI Engineer
Edge AI Engineer
IoT Engineer
Junior IoT Engineer
Robotics Engineer
Junior Robotics Engineer
📍 Target Location
Main Locations
Pune, Maharashtra
Remote opportunities in India
Experience
Fresher
Entry Level
0–2 years experience

The filtering system removes higher-level positions such as:

Senior
Lead
Manager
Principal
Architect
Director
Higher-experience roles
🔄 V2 System Architecture
                    Adzuna Job API
                           ↓
                    Python Pipeline
                           ↓
                 Job Data Processing
                           ↓
              Role / Experience Filter
                           ↓
                    Duplicate Check
                           ↓
                     AI Analysis
                    ↙           ↘
                Gemini          Groq
                    ↘           ↙
                     AI Result
                         ↓
                Skill Grounding
                         ↓
                 Result Validation
                         ↓
                ┌────────┴────────┐
                ↓                 ↓
            Qualified           Pending
                ↓                 ↓
             Sheet1           Pending_AI
⚙️ Key Features
🔎 Automated Job Search

Fetches job listings using the Adzuna Job API.

🎯 Smart Job Filtering

Filters jobs according to:

Target role
Location
Experience
Technical relevance
🤖 AI Job Matching

Compares job requirements with the candidate profile.

📊 AI Match Information

Provides:

Match Score
Matched Skills
Missing Skills
Experience Match
Match Reason
♻️ Duplicate Detection

Prevents previously processed jobs from being added again.

📋 Google Sheets Tracking

Stores processed job opportunities in a structured format.

⏳ Pending Job Queue

Stores jobs that could not be processed by AI.

🔄 Automated Execution

GitHub Actions runs the job tracker automatically.

📊 Google Sheets

The project uses Google Sheets to store and track job opportunities.

Sheet1

Sheet1 contains successfully processed and qualified jobs.

Field	Description
Date	Date the job was added
Company	Company name
Job Role	Job title
Location	Job location
Salary	Salary information
Experience	Experience requirement
Skills	Job skills
Match Score	AI match score
Apply Link	Job application link
Status	Application status
Matched Skills	Matching skills
Missing Skills	Missing skills
Experience Match	Experience compatibility
Match Reason	Reason for the match
Pending_AI

Pending_AI contains jobs that were found but could not be completely processed by AI.

It can contain:

Job ID
Date Added
Company
Job Role
Location
Salary
Experience
Description
Apply Link
AI Status
Failure Reason
🛠️ Technology Stack
Technology	Purpose
Python	Main programming language
Adzuna API	Job data source
Google Gemini	Primary AI analysis
Groq	Fallback AI provider
Google Sheets	Job tracking
GitHub Actions	Automation
GitHub	Source control
📂 Project Structure
AI-Job-Tracker/
│
├── .github/
│   └── workflows/
│       └── main.yml
│
├── job_tracker.py
├── gemini_test.py
├── profile.json
├── README.md
│
├── 1.png
├── 2.png
├── 3.png
├── 4.png
├── output.png
└── project-architecture.png
🔐 Security

API keys and Google Service Account credentials are stored securely using GitHub Actions Secrets.

Sensitive credentials are not stored directly in the source code.

The project uses protected secrets for:

ADZUNA_APP_ID
ADZUNA_APP_KEY
GOOGLE_SERVICE_ACCOUNT_JSON
GEMINI_API_KEY
GROQ_API_KEY
📸 Project Screenshots & Output
1. System Architecture

2. GitHub Repository

3. GitHub Actions — Successful Run

4. Google Sheets — Sheet1

5. Pending_AI Queue

6. Project Output

📈 V2 Project Status
V2

✅ Completed

AI job matching
Candidate profile comparison
Match score
Matched skills
Missing skills
Experience matching
Match explanation
V2.1

✅ Completed

Improved filtering
Better duplicate protection
Better workflow handling
V2.2

✅ Completed

AI provider fallback
Better API error handling
Better JSON handling
V2.3

✅ Completed

Company normalization
Improved experience filtering
Better AI scoring
Improved duplicate detection
V2.4

✅ Current

Gemini + Groq pipeline
AI rate-limit handling
Continued job collection
Pending_AI queue
Skill grounding
Job requirement grounding
Improved duplicate protection
---

## 📌 Project Overview

Finding suitable engineering jobs manually can be time-consuming.

A candidate needs to:

- Search different job websites
- Check job requirements
- Remove senior-level jobs
- Compare required skills with personal skills
- Save useful jobs
- Avoid duplicate jobs
- Track application status

AI Job Tracker V2 automates many of these repetitive tasks.

The system combines:

- Job API integration
- Python automation
- Job filtering
- Candidate profile matching
- AI-based job analysis
- Duplicate detection
- Google Sheets
- GitHub Actions

---

## 🎯 Problem Statement

Manual job searching has several problems:

- Too many irrelevant job listings
- Senior-level jobs mixed with entry-level jobs
- Difficult to compare every job with personal skills
- Repeated jobs
- Manual tracking
- Time-consuming daily searching

The goal of this project is to automate the initial job discovery and matching process.

---

# 💡 V2 Solution

The V2 system follows this workflow:

```text
Job API
   ↓
Python Job Processing
   ↓
Role & Experience Filtering
   ↓
Duplicate Check
   ↓
AI Job Analysis
   ↓
Candidate Profile Matching
   ↓
Skill & Experience Analysis
   ↓
Google Sheets
## 🎓 Learning Outcomes

This project provided practical experience with:

- REST API integration
- Python automation
- JSON data processing
- Regular expressions
- Data filtering
- Rule-based scoring
- Google APIs
- Google Sheets automation
- GitHub Actions
- Secrets management
- Workflow automation
- Project documentation

---

## 👨‍💻 Author

**Akash Dukare**

ENTC Engineering Student

Interested in:

- Embedded Systems
- Embedded AI
- Edge AI
- IoT
- Robotics
- Automation

---

## ⭐ Project Goal

> Automate repetitive job discovery, identify relevant opportunities, and maintain a structured job-tracking workflow.

**AI Job Tracker V1.1 — Automate the Search. Focus on the Opportunity. 🚀**
