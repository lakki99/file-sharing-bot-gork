import os
import asyncio
import random
import string
import requests
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = os.getenv("ADMIN_IDS", "").split(",") if os.getenv("ADMIN_IDS") else []
ADMIN_IDS = [int(id) for id in ADMIN_IDS if id.strip().isdigit()]  # Safely convert to integers
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0"))
DB_CHANNEL_ID = int(os.getenv("DB_CHANNEL_ID", "0"))
DOMAIN = os.getenv("DOMAIN", "https://your-bot-name.herokuapp.com")
SHORTENER_SERVICE = os.getenv("SHORTENER_SERVICE", "tinyurl")
SHORTENER_API_KEY = os.getenv("SHORTENER_API_KEY", "")
MONGO_URL = os.getenv("MONGO_URL")

# Validate critical environment variables
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set in .env or Heroku config vars!")
if not MONGO_URL:
    raise ValueError("MONGO_URL is not set in .env or Heroku config vars!")
if not ADMIN_IDS:
    print("Warning: ADMIN_IDS is empty or invalid. No admins configured.")
if not LOG_CHANNEL_ID or not DB_CHANNEL_ID:
    print("Warning: LOG_CHANNEL_ID or DB_CHANNEL_ID is invalid. Logs or DB channel may not work.")

# Initialize Pyrogram client
app = Client("file_sharing_bot", bot_token=BOT_TOKEN)

# Initialize MongoDB client
mongo_client = MongoClient(MONGO_URL)
db = mongo_client["file_sharing_bot"]
content_collection = db["content"]

# Generate random shortlink (e.g., abc123)
def generate_shortlink():
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))

# Generate shortener link based on service
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
    except Exception as e:
        print(f"Error with {SHORTENER_SERVICE}: {e}")
        return long_url

# Check if user is admin
def is_admin(user_id):
    return user_id in ADMIN_IDS

# Log to channel
async def log_event(message):
    if LOG_CHANNEL_ID:
        try:
            await app.send_message(LOG_CHANNEL_ID, message)
        except Exception as e:
            print(f"Error logging to channel: {e}")

# Start command
@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text("Hello! I'm a file-sharing bot. Use /link to share content or /batch for multiple files (admins only).")

# /link command: Store any content (file, text, sticker, link, etc.)
@app.on_message(filters.command("link") & filters.private)
async def link_command(client, message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        await message.reply_text("Sorry, only admins can use /link!")
        await log_event(f"Non-admin {user_id} tried to use /link.")
        return

    # Forward content to database channel
    try:
        db_message = await message.forward(DB_CHANNEL_ID)
        shortlink = generate_shortlink()
        bot_link = f"{DOMAIN}/{shortlink}"
        shortener_link = create_shortener_link(bot_link)
        
        content_collection.insert_one({
            "shortlink": shortlink,
            "message_id": db_message.id,
            "uploader_id": user_id,
            "upload_time": datetime.now().isoformat(),
            "is_batch": 0
        })
        
        await message.reply_text(
            f"Content saved! Shareable link: {shortener_link}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Open Link", url=shortener_link)]])
        )
        await log_event(f"Content uploaded by {user_id}: {shortlink}")
    except Exception as e:
        await message.reply_text("Error saving content!")
        await log_event(f"Error in /link for {user_id}: {e}")

# /batch command: Store multiple files
@app.on_message(filters.command("batch") & filters.private)
async def batch_command(client, message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        await message.reply_text("Sorry, only admins can use /batch!")
        await log_event(f"Non-admin {user_id} tried to use /batch.")
        return

    try:
        args = message.text.split()
        if len(args) != 3:
            await message.reply_text("Usage: /batch <first_message_id> <last_message_id>")
            return
        
        first_id, last_id = int(args[1]), int(args[2])
        if first_id >= last_id:
            await message.reply_text("First ID must be less than last ID!")
            return

        # Forward messages in range to database channel
        shortlink = generate_shortlink()
        bot_link = f"{DOMAIN}/{shortlink}"
        shortener_link = create_shortener_link(bot_link)
        
        for msg_id in range(first_id, last_id + 1):
            try:
                await app.forward_messages(DB_CHANNEL_ID, message.chat.id, msg_id)
            except Exception:
                continue
        
        content_collection.insert_one({
            "shortlink": shortlink,
            "batch_first_id": first_id,
            "batch_last_id": last_id,
            "uploader_id": user_id,
            "upload_time": datetime.now().isoformat(),
            "is_batch": 1
        })
        
        await message.reply_text(
            f"Batch saved! Shareable link: {shortener_link}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Open Link", url=shortener_link)]])
        )
        await log_event(f"Batch uploaded by {user_id}: {shortlink} (Messages {first_id}-{last_id})")
    except Exception as e:
        await message.reply_text("Error saving batch!")
        await log_event(f"Error in /batch for {user_id}: {e}")

# Admin panel commands
@app.on_message(filters.command("admin") & filters.private)
async def admin_panel(client, message):
    if not is_admin(message.from_user.id):
        await message.reply_text("Admins only!")
        return
    await message.reply_text(
        "Admin Panel:\n"
        "/list_content - List all stored content\n"
        "/list_users - List allowed users\n"
        "/add_user <user_id> - Add allowed user\n"
        "/remove_user <user_id> - Remove allowed user\n"
        "/broadcast <message> - Broadcast to all users"
    )

# List stored content
@app.on_message(filters.command("list_content") & filters.private)
async def list_content(client, message):
    if not is_admin(message.from_user.id):
        await message.reply_text("Admins only!")
        return
    items = content_collection.find()
    count = content_collection.count_documents({})
    if count == 0:
        await message.reply_text("No content stored!")
        return
    response = "Stored Content:\n"
    for item in items:
        bot_link = f"{DOMAIN}/{item['shortlink']}"
        shortener_link = create_shortener_link(bot_link)
        if item["is_batch"]:
            response += f"Batch: {item['shortlink']}\nMessages: {item['batch_first_id']}-{item['batch_last_id']}\nUploader: {item['uploader_id']}\nUploaded: {item['upload_time']}\nLink: {shortener_link}\n\n"
        else:
            response += f"Content: {item['shortlink']}\nMessage ID: {item['message_id']}\nUploader: {item['uploader_id']}\nUploaded: {item['upload_time']}\nLink: {shortener_link}\n\n"
    await message.reply_text(response)

# List allowed users
@app.on_message(filters.command("list_users") & filters.private)
async def list_users(client, message):
    if not is_admin(message.from_user.id):
        await message.reply_text("Admins only!")
        return
    await message.reply_text(f"Allowed Users: {', '.join(map(str, ADMIN_IDS))}")

# Add user
@app.on_message(filters.command("add_user") & filters.private)
async def add_user(client, message):
    if not is_admin(message.from_user.id):
        await message.reply_text("Admins only!")
        return
    try:
        user_id = int(message.text.split()[1])
        if user_id not in ADMIN_IDS:
            ADMIN_IDS.append(user_id)
            with open(".env", "w") as f:
                f.write(f"BOT_TOKEN={BOT_TOKEN}\nADMIN_IDS={','.join(map(str, ADMIN_IDS))}\nLOG_CHANNEL_ID={LOG_CHANNEL_ID}\nDB_CHANNEL_ID={DB_CHANNEL_ID}\nDOMAIN={DOMAIN}\nSHORTENER_SERVICE={SHORTENER_SERVICE}\nSHORTENER_API_KEY={SHORTENER_API_KEY}\nMONGO_URL={MONGO_URL}")
            await message.reply_text(f"User {user_id} added as admin!")
            await log_event(f"User {user_id} added as admin by {message.from_user.id}")
        else:
            await message.reply_text("User already an admin!")
    except Exception as e:
        await message.reply_text("Usage: /add_user <user_id>")
        await log_event(f"Error adding user: {e}")

# Remove user
@app.on_message(filters.command("remove_user") & filters.private)
async def remove_user(client, message):
    if not is_admin(message.from_user.id):
        await message.reply_text("Admins only!")
        return
    try:
        user_id = int(message.text.split()[1])
        if user_id in ADMIN_IDS:
            ADMIN_IDS.remove(user_id)
            with open(".env", "w") as f:
                f.write(f"BOT_TOKEN={BOT_TOKEN}\nADMIN_IDS={','.join(map(str, ADMIN_IDS))}\nLOG_CHANNEL_ID={LOG_CHANNEL_ID}\nDB_CHANNEL_ID={DB_CHANNEL_ID}\nDOMAIN={DOMAIN}\nSHORTENER_SERVICE={SHORTENER_SERVICE}\nSHORTENER_API_KEY={SHORTENER_API_KEY}\nMONGO_URL={MONGO_URL}")
            await message.reply_text(f"User {user_id} removed from admins!")
            await log_event(f"User {user_id} removed from admins by {message.from_user.id}")
        else:
            await message.reply_text("User not an admin!")
    except Exception as e:
        await message.reply_text("Usage: /remove_user <user_id>")
        await log_event(f"Error removing user: {e}")

# Broadcast message
@app.on_message(filters.command("broadcast") & filters.private)
async def broadcast(client, message):
    if not is_admin(message.from_user.id):
        await message.reply_text("Admins only!")
        return
    try:
        msg = message.text.split(maxsplit=1)[1]
        users = content_collection.distinct("uploader_id")
        for user_id in users:
            try:
                await app.send_message(user_id, msg)
            except Exception:
                pass
        await message.reply_text("Broadcast sent!")
        await log_event(f"Broadcast sent by {message.from_user.id}: {msg}")
    except Exception as e:
        await message.reply_text("Usage: /broadcast <message>")
        await log_event(f"Error broadcasting: {e}")

# Start bot
async def main():
    await app.start()
    await log_event("Bot started!")
    await app.run()

if __name__ == "__main__":
    asyncio.run(main())