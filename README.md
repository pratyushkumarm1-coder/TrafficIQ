# 🚦 TrafficIQ: Intelligent Traffic Safety & Flow Management System

[![FastAPI](https://img.shields.io/badge/FastAPI-0.104.1-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![YOLOv8](https://img.shields.io/badge/YOLOv8-Ultralytics-00ffff?logo=yolo&logoColor=black)](https://github.com/ultralytics/ultralytics)
[![React](https://img.shields.io/badge/React-18.3-61dafb?logo=react&logoColor=black)](https://react.dev/)
[![Gemini AI](https://img.shields.io/badge/Google%20Gemini-3.6%20Flash-4285f4?logo=google&logoColor=white)](https://ai.google.dev/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](#license)

An end-to-end Smart City Intelligent Transportation System (ITS) combining **Edge Computer Vision (YOLOv8)**, **Multimodal Generative AI (Google Gemini)**, and **Predictive Weather-Traffic Correlation** to optimize urban traffic flow, detect violations, and automate safety alerts.

---

## 🌟 Key Features

* **Real-Time Edge Vehicle Detection & Tracking:** Multi-class classification (Cars, Motorcycles, Buses, Trucks) via YOLOv8 with centroid-based tracking and speed estimation ($\text{km/h}$).
* **Predictive Weather & Hazard Forecasting:** Integrates live OpenWeatherMap 24–48h meteorological data to calculate dynamic driving risk levels (`LOW`, `MODERATE`, `HIGH`, `SEVERE`) and hydroplaning/fog advisories.
* **Multimodal Generative AI (Gemini 3.6 Flash):**
  * **AI Jam Cause Analysis:** Visual diagnosis of congestion causes (accidents, construction, stalled vehicles) from camera frames.
  * **Interactive Operator Copilot:** Grounded conversational assistant aware of real-time traffic telemetry.
* **Wrong-Way Driving Detection:** Trajectory vector analysis flagging vehicles traveling counter to dominant flow.
* **Emergency Vehicle Green Corridor:** Automatic detection of priority emergency vehicles with signal-clearing triggers.
* **Interactive GIS Map:** Real-time multi-intersection monitoring for urban corridors (tested on Cuttack & Bhubaneswar road networks).
* **Automated Telegram Bot Alerts:** Immediate incident dispatch to subscribers for high-risk events + daily evening briefings.
* **Telemetry Export & Health Monitoring:** Self-diagnostic health endpoints, real-time CSV/JSON history export, and printable audit reports.
* **Multilingual Localization:** Live dashboard switching between **English**, **Hindi (हिन्दी)**, and **Odia (ଓଡ଼ିଆ)**.

---

## 🛠️ Tech Stack

| Domain | Technologies |
| :--- | :--- |
| **Backend & API** | Python 3.10+, FastAPI, Uvicorn, SQLite, Supabase (Cloud PostgreSQL) |
| **Computer Vision** | YOLOv8 Nano (`ultralytics`), OpenCV (`opencv-python`), NumPy |
| **Generative AI** | Google Gemini API (`gemini-3.6-flash`), REST API |
| **Frontend** | React 18, Vite 5, Leaflet (GIS Map), Chart.js, Bootstrap 5 / Glassmorphism UI |
| **Integrations** | OpenWeatherMap API, Telegram Bot API |

---

## 📂 Project Directory Structure

```text
Traffic Relief/
├── backend/
│   ├── main.py              # FastAPI application server & routing
│   ├── cv_engine.py         # YOLOv8 vehicle detection & speed tracking
│   ├── weather.py           # OpenWeather API & predictive hazard scoring
│   ├── gemini.py            # Google Gemini multimodal vision & chat
│   ├── advanced.py          # Wrong-way trajectory analysis & ML capacity regression
│   ├── features2.py         # Jam cause diagnosis & risk pattern discovery
│   ├── database.py          # SQLite & Supabase persistence layer
│   ├── telegram_bot.py      # Automated alert dispatcher daemon
│   ├── requirements.txt     # Python backend dependencies
│   └── yolov8n.pt           # YOLOv8 nano model weights
├── frontend-react/
│   ├── src/
│   │   ├── components/      # UI Panels (Map, Feed, Charts, Forecast, etc.)
│   │   ├── App.jsx          # Main dashboard container & balanced layout
│   │   └── styles.css       # Dark glassmorphism theme styling
│   ├── dist/                # Production build served directly by FastAPI
│   └── package.json         # Node.js dependencies & scripts
├── start_server.bat         # Single-click Windows server launcher
└── README.md                # Project documentation
```

---

## 🚀 Quick Start Guide

### 1. Prerequisites
* **Python 3.10+**
* **Node.js 18+** & npm

### 2. Backend Setup
```bash
# Navigate to backend directory
cd backend

# Create and activate virtual environment
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Environment Variables (`backend/.env`)
Create a `.env` file in the `backend/` directory:
```env
OPENWEATHER_API_KEY=your_openweather_api_key
WEATHER_CITY=Bhubaneswar,IN
GEMINI_API_KEY=your_google_gemini_api_key
TELEGRAM_BOT_TOKEN=your_telegram_bot_token   # Optional
SUPABASE_URL=                                # Optional
SUPABASE_KEY=                                # Optional
```

### 4. Build Frontend (React + Vite)
```bash
cd frontend-react
npm install
npm run build
cd ..
```

### 5. Run Application
Run using the automated batch script (Windows):
```cmd
start_server.bat
```
Or start manually:
```bash
cd backend
python main.py
```

---

## 🌐 Endpoints & Navigation

* **Web Dashboard:** [http://localhost:8000/dashboard](http://localhost:8000/dashboard)
* **Live Video Feed:** [http://localhost:8000/video_feed](http://localhost:8000/video_feed)
* **Interactive API Docs (Swagger):** [http://localhost:8000/docs](http://localhost:8000/docs)
* **System Health Check:** [http://localhost:8000/health](http://localhost:8000/health)
* **Weather Forecast API:** [http://localhost:8000/weather/forecast](http://localhost:8000/weather/forecast)

---

## 📄 License
This project is open-source and available under the [MIT License](LICENSE).
