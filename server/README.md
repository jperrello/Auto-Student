This weather tool server example was cloned from https://github.com/open-webui/openapi-servers as a baseline
for setting up a quick server to access canvas. assignment.py contains the server project - you can run it with

uvicorn assignment:app --host 0.0.0.0 --reload

Oh, and the requirements file should cover what's needed if something's missing.

################################

# ⛅ Weather Tool Server

A sleek and simple FastAPI-based server to provide weather data using OpenAPI standards.

📦 Built with:  
⚡️ FastAPI • 📜 OpenAPI • 🧰 Python  

---

## 🚀 Quickstart

Clone the repo and get started in seconds:

```bash
git clone https://github.com/open-webui/openapi-servers
cd openapi-servers/servers/weather

# Install dependencies
pip install -r requirements.txt

# Run the server
uvicorn main:app --host 0.0.0.0 --reload
```

---

## 🔍 About

This server is part of the OpenAPI Tools Collection. Use it to fetch real-time weather information, location-based forecasts, and more — all wrapped in a developer-friendly OpenAPI interface.

Compatible with any OpenAPI-supported ecosystem, including:

- 🌀 FastAPI
- 📘 Swagger UI
- 🧪 API testing tools

---

## 🚧 Customization

Plug in your favorite weather provider API, tailor endpoints, or extend the OpenAPI spec. Ideal for integration into AI agents, automated dashboards, or personal assistants.

---

## 🌐 API Documentation

Once running, explore auto-generated interactive docs:

🖥️ Swagger UI: http://localhost:8000/docs  
📄 OpenAPI JSON: http://localhost:8000/openapi.json

---

Made with ❤️ by the Open WebUI community 🌍  
Explore more tools ➡️ https://github.com/open-webui/openapi-servers
