# Smart City Complaint Assistant

AI-powered urban civic grievance reporting platform built for **SDG 11: Sustainable Cities and Communities**.

## What it does

Citizens upload a photo of any civic issue — pothole, garbage, waterlogging, broken streetlight. The AI automatically classifies the problem, assigns a severity level, and generates a complaint description. Every complaint is tracked on a live dashboard.

## Features

- Photo upload + GPT-4o Vision AI classification
- Auto-generated complaint description
- Severity scoring (High / Medium / Low)
- Live analytics dashboard
- Status tracking (Pending / In Progress / Resolved)
- AI chatbot assistant for citizen queries
- Filter and search complaints

## Tech Stack

| Layer | Technology |
|-------|------------|
| AI | OpenAI GPT-4o Vision API |
| Backend | Python + Flask |
| Frontend | HTML5 + CSS3 (Jinja2 templates) |
| Database | SQLite |
| Icons | Tabler Icons |

## Setup Instructions

### 1. Clone the repository
```bash
git clone https://github.com/your-username/smart-city-complaint-assistant.git
cd smart-city-complaint-assistant
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Set up your API key
```bash
cp .env.example .env
```
Open `.env` and replace `your_openai_api_key_here` with your actual OpenAI API key.

### 4. Run the app
```bash
python app.py
```

Open your browser and go to `http://localhost:5000`

## Project Structure

```
smart-city-complaint-assistant/
├── app.py                  # Main Flask application
├── complaints.db           # SQLite database (auto-created on first run)
├── requirements.txt
├── .env                    # Your API key (never commit this)
├── .env.example
├── static/
│   ├── css/
│   │   └── style.css       # All page styles
│   └── uploads/            # Uploaded complaint photos
└── templates/
    ├── base.html           # Shared layout + navbar + chatbot
    ├── index.html          # Homepage
    ├── report.html         # Submit complaint page
    ├── complaints.html     # All complaints list
    ├── detail.html         # Single complaint detail
    └── dashboard.html      # Analytics dashboard
```

## SDG Alignment

This project addresses **SDG 11: Sustainable Cities and Communities** by providing an intelligent system to report, track, and analyse urban civic complaints — directly improving transparency and responsiveness in city governance.

---

**AI Capstone Project** · Lenovo x BharatCares · 2025–2026
