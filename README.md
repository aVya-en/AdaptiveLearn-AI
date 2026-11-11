# AdaptiveLearn AI

AdaptiveLearn AI is an adaptive learning platform scaffold for B.Tech and
engineering students. It is built with Python and Streamlit, with PostgreSQL
support for hosted persistence, SQLite for local development, and Google Gemini
powering the AI Tutor.

## Current status

The current version provides student registration and login, an account-specific
dashboard, practice quizzes, diagnostic and adaptive learning paths, progress
reports, concept performance, recent trends, and an AI Tutor. Passwords are
stored as salted PBKDF2-HMAC-SHA256 hashes; student learning records are kept in
the configured database. Tutor chat stays in the active Streamlit session and
is not written to the database. AI generation starts only after an explicit
student action.

## Visual theme

The application uses a shared light palette and design tokens defined in
`ui/theme.py`. Streamlit controls and shared page components use the same
accessible surfaces, borders, focus states, and semantic status colors through
`ui/styles.py`.

## Project structure

```text
AdaptiveLearn-AI/
??? app.py
??? pages/
?   ??? 0_Sign_In.py
?   ??? 1_Dashboard.py
?   ??? 2_AI_Tutor.py
?   ??? 3_Practice.py
?   ??? 4_Progress.py
??? database/
?   ??? __init__.py
?   ??? db.py
??? modules/
?   ??? adaptive_learning.py
?   ??? ai_tutor.py
?   ??? auth.py
?   ??? dashboard.py
?   ??? quiz_engine.py
?   ??? quiz_generator.py
??? utils/
?   ??? auth_ui.py
?   ??? config.py
?   ??? performance.py
?   ??? streamlit_ui.py
?   ??? style.py
??? tests/
??? assets/
??? requirements.txt
??? .env.example
??? AGENTS.md
```

## Requirements

- Windows
- Python 3.10 or newer

## Run locally on Windows

From the project directory, run these commands in PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
streamlit run app.py
```

Streamlit opens the application in your browser. The SQLite database is created
automatically at `database/adaptivelearn.db`. Register with your name, email,
and a password of at least eight characters. The dashboard displays only data
associated with the signed-in student's ID.

## Database configuration

SQLite remains the default when `DATABASE_URL` is unset. To use PostgreSQL,
set `DATABASE_URL` to a PostgreSQL connection URL in the process environment.
For Streamlit Community Cloud, add `DATABASE_URL` to the app's Secrets settings;
the application reads that setting without displaying or logging it. PostgreSQL
schema initialization is versioned and safe to run concurrently across app
workers. PostgreSQL writes commit transactionally and student-scoped learning
queries bypass the SQLite file cache to avoid stale results across workers.

Choosing PostgreSQL does not import, copy, or modify the local SQLite database.
Existing local accounts and learning history remain in SQLite until a separately
planned data migration is performed.

## Authentication and local data

The `students` table stores profile fields, a unique normalized email, and the
password hash. `learning_progress` and `quiz_attempts` each include a required
`student_id` foreign key. Quiz attempts also record difficulty, question count,
correct count, score percentage, and completion time. The schema initializer
migrates existing tables in place and keeps old records. The local database is
ignored by Git and should not be shared.

Run the authentication and database checks from PowerShell with:

```powershell
python -m unittest discover -s tests -v
```

The tests use temporary SQLite databases and cover registration, login,
student-specific metrics, foreign-key enforcement, and the Streamlit sign-out
flow. You can also verify it manually by creating an account, signing out from
the sidebar, and signing back in.

## AI Tutor configuration

For local development, copy `.env.example` to `.env` and set one or more
`GEMINI_API_KEY_1` through `GEMINI_API_KEY_3` values. For Streamlit Community
Cloud, configure the same names in the app's Secrets settings. Environment
variables take precedence over Streamlit secrets. The legacy
`GEMINI_API_KEY` value remains supported. `GEMINI_MODEL` defaults to
`gemini-3.6-flash`; `GEMINI_FALLBACK_MODEL` defaults to `gemini-3.5-flash`.
Optional `GEMINI_PROJECT_ID_1` through `_3` labels let the app suppress keys
from a known exhausted Google Cloud project together. Empty key slots are ignored.
`GEMINI_FALLBACK_COOLDOWN_SECONDS`, `GEMINI_MAX_COOLDOWN_SECONDS`, and
`GEMINI_CREDENTIAL_WAIT_SECONDS` configure process-local cooldown backoff and
how long a concurrent request waits for a reserved credential. Provider retry
delays take precedence over local cooldown values, including when a provider
delay exceeds the local fallback maximum. Adaptive in-flight coalescing requires
the caller to supply that student's scope and never retains completed results.
The key stays on the server and is never
shown in the page. The tutor reports setup or API errors instead of generating
placeholder responses.

Gemini generation disables the SDK's built-in HTTP retries so recovery is
bounded in one place. HTTP 503/504 and network timeouts get one same-model
retry with exponential jitter (up to one second); supplied Google retry delays
are used as given up to 30 seconds, and longer delays skip that same-model
retry. The configured Gemini fallback model is then tried once for eligible
transient failures before the credential pool rotates to another key. Temporary
429 rate limits remain distinct from HTTP 503 service outages, while daily or
shared quota errors and authentication failures are not treated as outages.
Tutor and quiz requests stay Gemini-only. Generation is still initiated by an
explicit student action; refreshing a page does not start it again.

Run all automated checks from PowerShell with:

```powershell
python -m unittest discover -s tests -v
```

The AI Tutor tests mock the Gemini client; they do not require an API key or
make network requests.

To check a real Gemini connection, run from the project root after configuring
`.env`:

```powershell
.\.venv\Scripts\python.exe -c "from modules.ai_tutor import test_gemini_connection; print(test_gemini_connection())"
```

Provider status codes and redacted diagnostic details are logged to the
terminal; the page shows a sanitized action message.

For a one-request connectivity check of each configured numbered Gemini slot,
run `python -m utils.provider_diagnostics` from the project root. The report
shows slot and project-group labels without credentials or project IDs. It
does not alter Gemini cooldown state. If `GROQ_ALLOW_API_USAGE=true`, the tool
also sends one minimal request using `GROQ_MODEL`; provider requests may use
quota or incur charges. Use `python -m utils.provider_diagnostics --groq-only`
to check Groq without repeating Gemini connectivity requests.

Adaptive requests use GroqCloud as the primary provider only when both
`GROQ_API_KEY` is configured and `GROQ_ALLOW_API_USAGE=true`. Otherwise they
use Gemini. Recoverable Groq rate-limit, quota, network, or server failures
fall back to Gemini. The Groq SDK's internal retries are disabled so a single
adaptive request is not duplicated; rate-limit `retry-after` values establish
a process-local cooldown. AI Tutor and quiz generation remain Gemini-only.
Usage counters separately report Groq token metadata and Gemini usage.

Groq settings are `GROQ_API_KEY`, `GROQ_MODEL`, and
`GROQ_ALLOW_API_USAGE=false`; configure them in environment variables or
Streamlit secrets, with environment variables taking precedence. The 120B GPT-OSS model is the default recommendation
for adaptive reasoning; the 20B variant can be a faster, lighter alternative.
Groq documents strict JSON Schema output for these GPT-OSS models. Its published
Free Plan limits view lists 30 RPM, 1,000 RPD, 8,000 TPM, and 200,000 TPD for
the listed models, but availability and effective limits depend on the account
and can change. Confirm model access and current limits in the Groq Console
before enabling calls. The Qwen model is listed as preview, so it is a less
stable default for production. The application does not make a paid request or
enable Groq automatically.

## Quiz Engine

Sign in and open Practice. Choose DSA, Python, or DBMS; select a listed topic,
difficulty, and 5, 10, or 15 questions; then generate the quiz. Answer one
question at a time, use Previous and Next to review selections, and submit.
Blank answers can be submitted; they are saved as unanswered and earn no points.
Correct answers and explanations appear only after submission. Completed
attempts appear in the dashboard's recent attempts and subject averages.
Question generation requires the configured Gemini key and model; failed or
invalid Gemini output does not create a substitute quiz.

Quiz submissions now store a response row for each question, including unanswered
questions, linked to the owning student and quiz attempt. Unanswered rows have a
NULL correctness value and are excluded from concept attempt accuracy. A versioned,
additive SQLite migration creates `quiz_responses` and its indexes without removing
existing accounts or attempts. Existing attempts retain their aggregate totals and
scores; no individual answers or concept labels are inferred for historical rows.
Schema version 3 adds student/topic/time lookup indexes for adaptive difficulty and
latest-response retrieval. The additive migration preserves existing records.

`modules.learning_profile.get_student_learning_profile(student_id)` provides a
compact student-scoped profile from SQL aggregates. Concept accuracy uses answered
responses with actual non-empty concept metadata only. Responses without a concept
remain outside concept aggregates; their separately grouped topic performance is
available in `topic_performance`. Each subject reports `concept_metadata_status`
(`available`, `partial`, or `unavailable`) and the count of responses missing that
metadata. No topic label is substituted into the concept field. A concept needs at
least five answered questions before it can be
classified: at least 80% is strong, at most 50% is weak, and other adequately
assessed concepts are developing. Concepts below that sample size are reported as
insufficiently assessed. Concept recent accuracy uses the latest five answered
responses. Subject trend compares the latest five completed quiz scores with the
previous five, and reports insufficient history if either window is unavailable;
changes of five percentage points or more indicate an improving or declining trend.
Subject totals and accuracy use existing attempt aggregates for compatibility,
including unanswered quiz questions in the denominator. The profile is a data-layer
API for later phases and does not add dashboard UI or AI calls.

## Adaptive learning path

The Learning Path page lets a signed-in student choose a subject and self-assessed
level, then start a ten-question diagnostic that samples the subject's available
topic metadata at Beginner, Intermediate, and Advanced levels. There is currently
no syllabus ingestion; the diagnostic uses the topics in `modules.quiz_engine`.
Responses are scored by the existing Python quiz scorer and saved by the same
student-scoped attempt/response transaction. Self-assessment and demonstrated
proficiency are stored separately. Demonstrated proficiency is reported as
insufficient evidence unless at least eight questions were answered; the estimate
is not a mastery claim.

The page presents measured concept strengths, weaknesses, developing areas, and
insufficient samples. A personalized next step is generated only after the student
clicks the generate/refresh action. The request sends a compact subject profile
through the shared Groq/Gemini adaptive provider adapter, validates the returned
topic against available metadata, and persists the validated result for that
student and subject. New quiz submissions mark that student's subject path stale.
Provider, task, fallback, and reported token usage are stored when available;
missing usage metadata remains unavailable. Learning Path page loads only read the
saved result and do not call a provider. Diagnostic output is capped at 3,500 tokens
and recommendation output at 700 tokens for both provider paths where supported.

Practice now defaults to a bounded difficulty derived from that student's recent
topic performance: five recent answers at 80% or higher raise one level; three or
more at 50% or lower lower one level. Otherwise the last practice level is retained.
The choice is capped at Beginner and Advanced. Starting practice from a learning
path carries its selected subject, topic, and difficulty into the existing Practice
page.

Successfully generated, strictly validated quizzes are cached in process memory
for one hour by subject, topic, difficulty, question count, and quiz prompt/schema
version. The cache contains generic question content only; answers and attempts
remain in each student's session and SQLite records. Use **Generate New Quiz**
to bypass the cache and request fresh questions. The cache is cleared when the
app process restarts. Concurrent requests for the same configuration share one
generation request.

The app entry point uses Streamlit's native `st.navigation` pages with explicit
Dashboard, AI Tutor, Practice, Progress, and Sign in labels, so the entry script
name is not shown as a workspace page.

The AI Tutor retains the full chat in the active student session but sends only
the latest five exchanges to Gemini on each turn. A submitted prompt is kept in
the conversation before its request starts; if Gemini fails, the student can
retry it without adding a duplicate turn. The authenticated sidebar contains
workspace branding, account status, logout, and a compact usage panel. Usage
counters separate tutor and quiz requests, show quiz cache reuse, and use
Gemini-reported token metadata when available. Missing token metadata is shown
as unavailable. These process-local counters are not Google's official quota
measurements and reset when the app restarts.

Navigation timing diagnostics are logged locally under the
`adaptivelearn.performance` logger. They report fixed operation names and
durations only; they do not include student identifiers, credentials, or
content. Set `$env:ADAPTIVELEARN_PERF_LOG = "0"` in PowerShell before launching
Streamlit to disable these logs.
