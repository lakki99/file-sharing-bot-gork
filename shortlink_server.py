from aiohttp import web
import aiosqlite
import requests

async def serve_link(request):
    shortlink = request.match_info['shortlink']
    async with aiosqlite.connect("database.db") as db:
        async with db.execute("SELECT message_id, batch_first_id, batch_last_id, is_batch FROM content WHERE shortlink = ?", (shortlink,)) as cursor:
            row = await cursor.fetchone()
            if row:
                message_id, first_id, last_id, is_batch = row
                bot_link = f"https://t.me/c/{str(DB_CHANNEL_ID)[4:]}/{message_id}" if not is_batch else f"https://t.me/c/{str(DB_CHANNEL_ID)[4:]}/{first_id}-{last_id}"
                tinyurl_link = requests.get(f"https://tinyurl.com/api-create.php?url={bot_link}").text
                raise web.HTTPFound(tinyurl_link)  # Redirect to TinyURL
            else:
                return web.Response(text="Invalid shortlink!", status=404)

app = web.Application()
app.router.add_get("/{shortlink}", serve_link)

if __name__ == "__main__":
    web.run_app(app, port=int(os.getenv("PORT", 8000)))
