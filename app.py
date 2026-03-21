from flask import Flask, request
import requests
import os
import json

TOKEN = (os.environ.get("TOKEN") or "").strip()
if not TOKEN:
    raise RuntimeError("TOKEN environment variable is not set")

BASE_URL = f"https://api.telegram.org/bot{TOKEN}"
app = Flask(__name__)


@app.route("/", methods=["GET"])
def home():
    return "ok", 200


@app.route("/", methods=["POST"])
def webhook():
    try:
        data = request.get_json(silent=True) or {}
        print("INCOMING:", json.dumps(data, ensure_ascii=False), flush=True)

        message = data.get("message")
        if not message:
            return "ok", 200

        chat_id = message["chat"]["id"]
        text = message.get("text", "")

        r = requests.post(
            f"{BASE_URL}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": f"Бот жив. Ты написал: {text}"
            },
            timeout=20
        )

        print("TG STATUS:", r.status_code, flush=True)
        print("TG BODY:", r.text, flush=True)

        return "ok", 200

    except Exception as e:
        print("WEBHOOK ERROR:", str(e), flush=True)
        return "ok", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
