from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
import requests
import os
import time
import logging

load_dotenv()

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -----------------------------
# Config
# -----------------------------
ENDPOINT = os.getenv("LANGUAGE_ENDPOINT", "").rstrip("/")
KEY = os.getenv("LANGUAGE_KEY", "")

API_VERSION = "2024-11-01"        # for language detection / PII (sync endpoint)
JOB_API_VERSION = "2024-11-01"    # for summarization (async job endpoint)

REQUEST_TIMEOUT = 15              # seconds, per HTTP call
MAX_POLL_ATTEMPTS = 30            # ~60s max wait for summarization job
POLL_INTERVAL = 2                 # seconds between polls
MAX_TEXT_LENGTH = 5000            # Azure AI Language doc size guardrail

HEADERS = {
    "Ocp-Apim-Subscription-Key": KEY,
    "Content-Type": "application/json"
}

POLL_HEADERS = {
    "Ocp-Apim-Subscription-Key": KEY
}


def get_json_text():
    """Safely extract 'text' from the request body. Returns (text, error_response)."""
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()

    if not ENDPOINT or not KEY:
        return None, (jsonify({"error": "Azure credentials missing"}), 500)

    if not text:
        return None, (jsonify({"error": "Please enter text"}), 400)

    if len(text) > MAX_TEXT_LENGTH:
        return None, (jsonify({
            "error": f"Text too long ({len(text)} chars). Max {MAX_TEXT_LENGTH} characters."
        }), 400)

    return text, None


def detect_language_code(text):
    """Helper: returns ISO 639-1 code (e.g. 'en') for given text, defaults to 'en' on failure."""
    try:
        url = f"{ENDPOINT}/language/:analyze-text?api-version={API_VERSION}"
        body = {
            "kind": "LanguageDetection",
            "analysisInput": {"documents": [{"id": "1", "text": text}]}
        }
        response = requests.post(url, headers=HEADERS, json=body, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        document = response.json()["results"]["documents"][0]
        return document["detectedLanguage"]["iso6391Name"]
    except Exception as e:
        logger.warning(f"Language auto-detect failed, defaulting to 'en': {e}")
        return "en"


@app.route("/")
def home():
    return render_template("index.html")


# -----------------------------
# Language Detection
# -----------------------------
@app.route("/api/language", methods=["POST"])
def detect_language():
    text, err = get_json_text()
    if err:
        return err

    url = f"{ENDPOINT}/language/:analyze-text?api-version={API_VERSION}"
    body = {
        "kind": "LanguageDetection",
        "analysisInput": {"documents": [{"id": "1", "text": text}]}
    }

    try:
        response = requests.post(url, headers=HEADERS, json=body, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.RequestException as e:
        logger.error(f"Language detection request failed: {e}")
        return jsonify({"error": "Failed to reach Azure AI Language service"}), 502

    if response.status_code != 200:
        logger.error(f"Language detection error: {response.text}")
        return jsonify({"error": "Language detection failed"}), response.status_code

    document = response.json()["results"]["documents"][0]

    return jsonify({
        "language": document["detectedLanguage"]["name"],
        "iso6391": document["detectedLanguage"]["iso6391Name"],
        "confidence": round(document["detectedLanguage"]["confidenceScore"] * 100, 2)
    })


# -----------------------------
# PII Redaction
# -----------------------------
@app.route("/api/pii", methods=["POST"])
def redact_pii():
    text, err = get_json_text()
    if err:
        return err

    lang_code = detect_language_code(text)

    url = f"{ENDPOINT}/language/:analyze-text?api-version={API_VERSION}"
    body = {
        "kind": "PiiEntityRecognition",
        "analysisInput": {
            "documents": [{"id": "1", "language": lang_code, "text": text}]
        }
    }

    try:
        response = requests.post(url, headers=HEADERS, json=body, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.RequestException as e:
        logger.error(f"PII request failed: {e}")
        return jsonify({"error": "Failed to reach Azure AI Language service"}), 502

    if response.status_code != 200:
        logger.error(f"PII error: {response.text}")
        return jsonify({"error": "PII redaction failed"}), response.status_code

    document = response.json()["results"]["documents"][0]

    return jsonify({
        "language": lang_code,
        "redactedText": document["redactedText"],
        "entities": document["entities"]
    })


# -----------------------------
# Abstractive Summarization
# -----------------------------
@app.route("/api/summarize", methods=["POST"])
def summarize():
    text, err = get_json_text()
    if err:
        return err

    lang_code = detect_language_code(text)

    url = f"{ENDPOINT}/language/analyze-text/jobs?api-version={JOB_API_VERSION}"
    body = {
        "displayName": "summary",
        "analysisInput": {
            "documents": [{"id": "1", "language": lang_code, "text": text}]
        },
        "tasks": [
            {
                "kind": "AbstractiveSummarization",
                "parameters": {"summaryLength": "medium"}
            }
        ]
    }

    try:
        response = requests.post(url, headers=HEADERS, json=body, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.RequestException as e:
        logger.error(f"Summarization submit failed: {e}")
        return jsonify({"error": "Failed to reach Azure AI Language service"}), 502

    if response.status_code not in (200, 202):
        logger.error(f"Summarization submit error: {response.text}")
        return jsonify({"error": "Failed to start summarization job"}), response.status_code

    operation_url = response.headers.get("operation-location")
    if not operation_url:
        return jsonify({"error": "No operation-location returned by Azure"}), 502

    result = None
    for attempt in range(MAX_POLL_ATTEMPTS):
        try:
            poll = requests.get(operation_url, headers=POLL_HEADERS, timeout=REQUEST_TIMEOUT)
        except requests.exceptions.RequestException as e:
            logger.error(f"Polling failed on attempt {attempt}: {e}")
            return jsonify({"error": "Failed to poll summarization job"}), 502

        if poll.status_code != 200:
            logger.error(f"Polling error: {poll.text}")
            return jsonify({"error": "Summarization polling failed"}), poll.status_code

        result = poll.json()
        status = result.get("status")

        if status == "succeeded":
            break
        if status == "failed":
            logger.error(f"Summarization job failed: {result}")
            return jsonify({"error": "Summarization job failed"}), 500

        time.sleep(POLL_INTERVAL)
    else:
        return jsonify({"error": "Summarization timed out. Try shorter text."}), 504

    try:
        document = result["tasks"]["items"][0]["results"]["documents"][0]
        summary_text = document["summaries"][0]["text"]
    except (KeyError, IndexError) as e:
        logger.error(f"Unexpected summarization response shape: {e} | {result}")
        return jsonify({"error": "Unexpected response from summarization service"}), 502

    return jsonify({
        "language": lang_code,
        "summary": summary_text
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # NOTE: this dev server is fine for local testing only.
    # On Azure App Service, run via Gunicorn instead, e.g.:
    #   gunicorn --bind=0.0.0.0 --timeout 120 app:app
    app.run(host="0.0.0.0", port=port, debug=False)
