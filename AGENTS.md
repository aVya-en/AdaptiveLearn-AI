# Development guidance

- Keep the Streamlit entry point in `app.py` and user-facing pages in `pages/`.
- Put SQLite connection and persistence code in `database/`.
- Put learning features in `modules/` and shared configuration/helpers in `utils/`.
- Keep page files focused on presentation and delegate application logic to modules.
- Read API credentials from environment variables; never hardcode or log secrets.
- Do not simulate Gemini responses. If an external API is unavailable, show a clear
  error rather than presenting fabricated output.
- Keep local student data in SQLite and avoid committing database files.
- Favor small, beginner-friendly changes and document setup or behavior changes in
  `README.md`.
