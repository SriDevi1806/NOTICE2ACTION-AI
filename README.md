# NOTICE2ACTION AI

**From Notifications to Action**

INNOVATE INDIA 2026 | Team DevHarbour

## Overview

NOTICE2ACTION AI is an AI-powered notification assistant that helps students understand scholarship and government notifications.

It extracts information from PDF documents, identifies scholarship schemes, summarizes eligibility criteria, and compares them with a student's profile to generate a preliminary eligibility report.

## Key Features

- PDF notification upload and text extraction
- OCR support for scanned documents
- AI-powered notification analysis using Gemini
- Rule-based fallback when Gemini is unavailable
- Scholarship scheme detection
- Student profile creation
- Personalized eligibility matching
- Matched, Not Matched, and Unverified criteria
- Detailed eligibility report with explanations and evidence
- Error handling for invalid and unreadable PDFs

## Technology Stack

- Python
- FastAPI
- Streamlit
- Google Gemini API
- PyMuPDF
- Tesseract OCR
- Requests

## Project Structure

```text
NOTICE2ACTION-AI/
│
├── app.py
├── main.py
├── requirements.txt
├── README.md
├── .env
│
└── backend/
    └── main.py
```

*Adjust this structure to match your actual project files.*

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/SriDevi1806/NOTICE2ACTION-AI.git
cd YOUR_PROJECT_FOLDER
```

### 2. Create a virtual environment

```bash
python -m venv .venv
```

Activate it on Windows:

```bash
.venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file in the project directory and add your Gemini API key:

```env
GEMINI_API_KEY=your_gemini_api_key
```

Never share or commit your API key.

## Run the Application

### Start the FastAPI backend

From the project root, run:

```bash
python -m uvicorn backend.main:app --reload
```

### Start the Streamlit frontend

Open another terminal in the project root and run:

```bash
streamlit run app.py
```

Open the local Streamlit URL displayed in your terminal.

## How It Works

1. Upload a scholarship or government notification PDF.
2. Extract the document text.
3. Analyze the notification and identify scholarship schemes.
4. Create or complete the student profile.
5. Select a scholarship scheme.
6. Compare the student's information against eligibility criteria.
7. View the preliminary eligibility report.

## Eligibility Status

- **Matched:** The available student information satisfies the criterion.
- **Not Matched:** The available information does not satisfy the criterion.
- **Unverified:** There is insufficient information to confirm the criterion.

## Important Disclaimer

NOTICE2ACTION AI provides a preliminary automated assessment. It does not guarantee scholarship approval or replace the official eligibility decision.

Students should verify all eligibility conditions, deadlines, and required documents with the official notification and issuing authority.

## Team

**Team DevHarbour**  
INNOVATE INDIA 2026

*From Notifications to Action.*
