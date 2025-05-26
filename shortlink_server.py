from aiohttp import web
import requests
import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()
DB_CHANNEL_ID = int(os.getenv("DB_CHANNEL_ID", "0"))
SHORTENER_SERVICE = os.getenv("SHORTENER_SERVICE", "tinyurl")
SHORTENER_API_KEY = os.getenv("SHORTENER_API_KEY", "")
SHORTENER_API_URL = os.getenv("SHORTENER_API_URL", "")
MONGO_URL = os.getenv("MONGO_URL")

if not MONGO_URL:
    raise ValueError("MONGO_URL is not set in Heroku config vars!")
if SHORTENER_API_URL:
    print(f"Using custom SHORTENER_API_URL: {SHORTENER_API_URL}")

mongo_client = MongoClient(MONGO_URL)
db = mongo_client["file_sharing_bot"]
content_collection = db["content"]

def create_shortener_link(long_url):
    try:
        if SHORTENER_API_URL and SHORTENER_API_KEY:
            api_url = SHORTENER_API_URL.format(api_key=SHORTENER_API_KEY, url=long_url)
            response = requests.get(api_url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                return data.get("shortenedUrl", long_url) or data.get("shortUrl", long_url) or long_url
        elif SHORTENER_SERVICE == "shrinkearn":
            api_url = f"https://shrinkearn.com/api?api_key={SHORTENER_API_KEY}&url={long_url}"
            response = requests.get(api_url, timeout=5)
            return response.json().get("shortenedUrl", long_url) if response.status_code == 200 else long_url
        elif SHORTENER_SERVICE == "adshrink":
            api_url = f"https://adshrink.it/api?api_key={SHORTENER_API_KEY}&url={long_url}"
            response = requests.get(api_url, timeout=5)
            return response.json().get("shortenedUrl", long_url) if response.status_code == 200 else long_url
        elif SHORTENER_SERVICE == "bcvc":
            api_url = f"https://bc.vc/api.php?key={SHORTENER_API_KEY}&url={long_url}"
            response = requests.get(api_url, timeout=5)
            return response.json().get("short_url", long_url) if response.status_code == 200 else long_url
        elif SHORTENER_SERVICE == "tinyurl":
            return requests.get(f"https://tinyurl.com/api-create.php?url={long_url}", timeout=5).text
        elif SHORTENER_SERVICE == "rbgy":
            return requests.get(f"https://rb.gy/api/shorten?url={long_url}", timeout=5).text
        return requests.get(f"https://tinyurl.com/api-create.php?url={long_url}", timeout=5).text
    except Exception as e:
        print(f"Error with {SHORTENER_SERVICE}: {e}. Falling back to TinyURL.")
        try:
            return requests.get(f"https://tinyurl.com/api-create.php?url={long_url}", timeout=5).text
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