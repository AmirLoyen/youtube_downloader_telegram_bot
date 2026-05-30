import os
import re
import shutil
import threading
import asyncio
import glob
import traceback

# ==================== IMPORTS ====================
try:
    from telegram import Update, ReplyKeyboardRemove, ReplyKeyboardMarkup
    from telegram.ext import (
        Application,
        CommandHandler,
        MessageHandler,
        ConversationHandler,
        filters,
        ContextTypes
    )
except ImportError:
    print("❌ Install: pip install python-telegram-bot>=21.0")
    exit(1)

try:
    import yt_dlp
except ImportError:
    print("❌ Install: pip install yt-dlp")
    exit(1)

try:
    from pytube import Search
except ImportError:
    print("❌ Install: pip install pytube")
    exit(1)

try:
    import scrapetube
except ImportError:
    print("⚠️ scrapetube not installed. Channel download disabled.")
    scrapetube = None

# ==================== CONFIG ====================
TOKEN = os.environ.get('BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
if TOKEN == 'YOUR_BOT_TOKEN_HERE':
    print("❌ Please set BOT_TOKEN!")
    exit(1)

PORT = int(os.environ.get('PORT', 8080))
WEBHOOK_URL = os.environ.get('WEBHOOK_URL', '')

# ==================== STATES ====================
(START_CO, GET_WORD, GET_NUMBER, GET_CHANNEL_URL, GET_URL, CONFIRMATION) = range(1, 7)

# ==================== KEYBOARDS ====================
markup_start = ReplyKeyboardMarkup([
    ['📥 Download Channel', '🔍 Search & Download'],
    ['📹 Single Video', '📊 Active Downloads'],
    ['❌ Cancel']
], resize_keyboard=True)

markup_back = ReplyKeyboardMarkup([
    ['🔙 Back', '🏠 Home', '❌ Cancel']
], resize_keyboard=True)

markup_confirm = ReplyKeyboardMarkup([
    ['✅ Confirm', '🏠 Home', '❌ Cancel']
], resize_keyboard=True)

# ==================== HELPERS ====================
BASE_DIR = 'downloads'
os.makedirs(BASE_DIR, exist_ok=True)

def clean_folder(user_id):
    folder = os.path.join(BASE_DIR, str(user_id))
    if os.path.exists(folder):
        try: shutil.rmtree(folder)
        except: pass
    os.makedirs(folder, exist_ok=True)
    return folder

# ==================== YOUTUBE ====================
def get_channel_id(url):
    try:
        opts = {'quiet': True, 'extract_flat': True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get('channel_id') or info.get('uploader_id')
    except: return None

def get_channel_videos(channel_id):
    if not scrapetube: return None
    try:
        videos = scrapetube.get_channel(channel_id)
        result = []
        for v in videos:
            vid = v.get('videoId', '')
            title = 'Unknown'
            try: title = v['title']['runs'][0]['text']
            except: pass
            if vid: result.append({'url': f'https://youtube.com/watch?v={vid}', 'title': title})
        return result
    except: return None

def search_videos(query, limit=10):
    try:
        search = Search(query)
        result = []
        for i, video in enumerate(search.results):
            if i >= limit: break
            result.append({'url': video.watch_url, 'title': video.title or 'Unknown'})
        return result
    except: return None

def download_video(url, user_id):
    try:
        folder = clean_folder(user_id)
        opts = {
            'format': 'best[height<=720][ext=mp4]/best[height<=720]/best',
            'outtmpl': os.path.join(folder, '%(title).100s.%(ext)s'),
            'quiet': True, 'no_warnings': True,
            'merge_output_format': 'mp4',
            'max_filesize': 1900000000,
            'retries': 3, 'socket_timeout': 30,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        files = glob.glob(os.path.join(folder, '*'))
        return max(files, key=os.path.getsize) if files else None
    except: return None

def background_download(loop, user_data, user_id, context):
    asyncio.set_event_loop(loop)
    
    async def run():
        videos = user_data.get('list_of_urls', [])
        total = len(videos)
        for i, v in enumerate(videos, 1):
            try:
                await context.bot.send_message(user_id, f'⬇️ {i}/{total}: {v["title"][:50]}...')
                fp = download_video(v['url'], user_id)
                if fp and os.path.exists(fp):
                    if os.path.getsize(fp) < 1900000000:
                        with open(fp, 'rb') as f:
                            await context.bot.send_video(user_id, video=f, caption=v['title'][:200], supports_streaming=True)
                    else:
                        await context.bot.send_message(user_id, f'⚠️ Too large: {v["title"][:50]}')
                    try: os.remove(fp)
                    except: pass
                else:
                    await context.bot.send_message(user_id, f'❌ Failed: {v["title"][:50]}')
            except:
                pass
        clean_folder(user_id)
        await context.bot.send_message(user_id, f'✅ Done! {total} videos processed.')
    
    loop.run_until_complete(run())

# ==================== HANDLERS ====================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    clean_folder(user.id)
    await update.message.reply_text(f'👋 Welcome {user.first_name}!\nChoose:', reply_markup=markup_start)
    return START_CO

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.lower()
    clean_folder(user.id)
    
    if 'channel' in text:
        await update.message.reply_text('🔗 Send video URL from channel:', reply_markup=markup_back)
        return GET_CHANNEL_URL
    elif 'search' in text:
        await update.message.reply_text('🔤 Search word:', reply_markup=markup_back)
        return GET_WORD
    elif 'single' in text:
        await update.message.reply_text('🔗 Send YouTube URL:', reply_markup=markup_back)
        return GET_URL
    elif 'active' in text:
        n = threading.active_count() - 1
        await update.message.reply_text(f'📊 Active: {n}', reply_markup=markup_start)
        return START_CO
    elif 'cancel' in text:
        return await cmd_cancel(update, context)
    else:
        await update.message.reply_text('Choose:', reply_markup=markup_start)
        return START_CO

async def channel_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text in ['🔙 Back', '🏠 Home', '❌ Cancel']:
        await update.message.reply_text('🏠 Menu:', reply_markup=markup_start)
        return START_CO
    
    await update.message.reply_text('🔍 Finding...')
    cid = get_channel_id(update.message.text)
    if not cid:
        await update.message.reply_text('❌ Not found!', reply_markup=markup_back)
        return GET_CHANNEL_URL
    
    videos = get_channel_videos(cid)
    if not videos:
        await update.message.reply_text('❌ No videos!', reply_markup=markup_start)
        return START_CO
    
    context.user_data['list_of_urls'] = videos
    await update.message.reply_text(f'📊 {len(videos)} videos. Confirm?', reply_markup=markup_confirm)
    return CONFIRMATION

async def search_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text in ['🔙 Back', '🏠 Home', '❌ Cancel']:
        await update.message.reply_text('🏠 Menu:', reply_markup=markup_start)
        return START_CO
    
    context.user_data['search_word'] = update.message.text
    await update.message.reply_text(f'🔤 "{update.message.text}" - How many? (1-20)', reply_markup=markup_back)
    return GET_NUMBER

async def number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text in ['🔙 Back', '🏠 Home', '❌ Cancel']:
        await update.message.reply_text('🏠 Menu:', reply_markup=markup_start)
        return START_CO
    
    try:
        n = int(update.message.text)
        if n < 1 or n > 20:
            raise ValueError
    except:
        await update.message.reply_text('❌ Number 1-20:', reply_markup=markup_back)
        return GET_NUMBER
    
    q = context.user_data.get('search_word', '')
    await update.message.reply_text(f'🔍 Searching: {q}...')
    videos = search_videos(q, n)
    
    if not videos:
        await update.message.reply_text('❌ No results!', reply_markup=markup_start)
        return START_CO
    
    context.user_data['list_of_urls'] = videos
    preview = '\n'.join([f'{i+1}. {v["title"][:50]}' for i, v in enumerate(videos[:5])])
    await update.message.reply_text(f'📊 Results:\n{preview}\n\nConfirm {len(videos)} videos?', reply_markup=markup_confirm)
    return CONFIRMATION

async def single_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if update.message.text in ['🔙 Back', '🏠 Home', '❌ Cancel']:
        await update.message.reply_text('🏠 Menu:', reply_markup=markup_start)
        return START_CO
    
    if 'youtube.com' not in update.message.text and 'youtu.be' not in update.message.text:
        await update.message.reply_text('❌ Invalid URL!', reply_markup=markup_back)
        return GET_URL
    
    msg = await update.message.reply_text('⬇️ Downloading...')
    fp = download_video(update.message.text, user.id)
    
    if fp and os.path.exists(fp):
        try:
            with open(fp, 'rb') as f:
                await update.message.reply_video(video=f, reply_markup=markup_start, supports_streaming=True)
            await msg.delete()
        except:
            await msg.edit_text('❌ Upload failed!')
        try: os.remove(fp)
        except: pass
    else:
        await msg.edit_text('❌ Download failed!', reply_markup=markup_start)
    return START_CO

async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if 'confirm' not in update.message.text.lower():
        await update.message.reply_text('🏠 Menu:', reply_markup=markup_start)
        return START_CO
    
    videos = context.user_data.get('list_of_urls', [])
    if not videos:
        await update.message.reply_text('❌ No videos!', reply_markup=markup_start)
        return START_CO
    
    await update.message.reply_text(f'⬇️ Downloading {len(videos)} videos in background...', reply_markup=markup_start)
    
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=background_download, args=(loop, context.user_data, user.id, context), daemon=True)
    t.start()
    return START_CO

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('👋 Bye! /start', reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print(f"Error: {context.error}")
    if update and hasattr(update, 'message') and update.message:
        await update.message.reply_text('❌ Error! /start again')

# ==================== MAIN ====================
def main():
    print('🤖 Starting...')
    app = Application.builder().token(TOKEN).build()
    
    conv = ConversationHandler(
        entry_points=[CommandHandler('start', cmd_start)],
        states={
            START_CO: [MessageHandler(filters.TEXT & ~filters.COMMAND, menu)],
            GET_CHANNEL_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, channel_url)],
            GET_WORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_word)],
            GET_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, number)],
            GET_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, single_url)],
            CONFIRMATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm)],
        },
        fallbacks=[
            CommandHandler('cancel', cmd_cancel),
            CommandHandler('start', cmd_start),
        ],
        conversation_timeout=600,
    )
    
    app.add_handler(conv)
    app.add_error_handler(error_handler)
    
    print('✅ Ready!')
    
    if WEBHOOK_URL:
        app.run_webhook(listen='0.0.0.0', port=PORT, webhook_url=f'{WEBHOOK_URL}/{TOKEN}')
    else:
        app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == '__main__':
    main()
