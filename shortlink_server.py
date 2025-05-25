from aiohttp import web
import requests
import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()
DB_CHANNEL_ID = int(os.getenv("DB_CHANNEL_ID", "0"))
SHORTENER_SERVICE = os.getenv("SHORTENER_SERVICE", "tinyurl")
SHORTENER_API_KEY = os.getenv("SHORTENER_API_KEY", "")
MONGO_URL = os.getenv("MONGO_URL")

if not MONGO_URL:
    raise ValueError("MONGO_URL is not set in .env or Heroku config vars!")

mongo_client = MongoClient(MONGO_URL)
db = mongo_client["file_sharing_bot"]
content_collection = db["content"]

def create_shortener_link(long_url):
    try:
        if SHORTENER_SERVICE == "rebrandly":
            url = "https://api.rebrandly.com/v1/links"
            headers = {"Authorization": f"Bearer {SHORTENER_API_KEY}", "Content-Type": "application/json"}
            data = {"destination": long_url}
            response = requests.post(url, json=data, headers=headers)
            return response.json().get("shortUrl", long_url) if response.status_code == 200 else long_url
        elif SHORTENER_SERVICE == "shortio":
            url = f"https://api.short.io/links"
            headers = {"Authorization": SHORTENER_API_KEY, "Content-Type": "application/json"}
            data = {"domain": "yourdomain.short.io", "originalURL": long_url}
            response = requests.post(url, json=data, headers=headers)
            return response.json().get("shortURL", long_url) if response.status_code == 200 else long_url
        elif SHORTENER_SERVICE == "cuttly":
            url = f"https://cutt.ly/api/api.php?key={SHORTENER_API_KEY}&short={long_url}"
            response = requests.get(url)
            return response.json().get("url", {}).get("shortLink", long_url) if response.status_code == 200 else long_url
        elif SHORTENER_SERVICE == "tinyurl":
            return requests.get(f"https://tinyurl.com/api-create.php?url={long_url}").text
        elif SHORTENER_SERVICE == "rbgy":
            return requests.get(f"https://rb.gy/api/shorten?url={long_url}").text
        else:
            return long_url
    except Exception:
        return long_url

async def serve_link(request):
    shortlink = request.match_info['shortlink']
    item = content_collection.find_one({"shortlink": shortlink})
    if item:
        bot_link = f"https://t.me/c/{str(DB_CHANNEL_ID)[4:]}/{item['message_id']}" if not item["is_batch"] else f"https://t.me/c/{str(DB_CHANNEL_ID)[4:]}/{item['batch_first_id']}-{item['batch_last_id']}"
        shortener_link = create_shortener_link(bot_link)
        raise web.HTTPFound(shortener_link)
    else:
        return web.Response(text="Invalid shortlink!", status=404)

app = web.Application()
app.router.add_get("/{shortlink}", serve_link)

if __name__ == "__main__":
    web.run_app(app, port=int(os.getenv("PORT", 8000)))