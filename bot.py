import os
import re
import shutil
import threading
import asyncio
from telegram import Update, ReplyKeyboardRemove, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    filters,
    ContextTypes
)
from telegram.error import TimedOut, NetworkError

# ==================== YOUTUBE FUNCTIONS ====================
import yt_dlp
from pytube import YouTube, Search
import scrapetube
from bs4 import BeautifulSoup
import requests

def find_channel_id(url):
    """Extract channel ID from YouTube URL"""
    try:
        ydl_opts = {'quiet': True, 'no_warnings': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get('channel_id') or info.get('uploader_id')
    except:
        return None

def get_videos_from_channel(channel_id):
    """Get all videos from a channel"""
    try:
        videos = scrapetube.get_channel(channel_id)
        result = []
        for video in videos:
            result.append({
                'url': f"https://youtube.com/watch?v={video['videoId']}",
                'title': video.get('title', {}).get('runs', [{}])[0].get('text', 'Unknown')
            })
        return result
    except:
        return []

def find_videos_with_search(word, number):
    """Search YouTube and return video URLs"""
    try:
        search = Search(word)
        results = []
        count = 0
        for video in search.results:
            if count >= number:
                break
            results.append({
                'url': video.watch_url,
                'title': video.title
            })
            count += 1
        return results
    except:
        return []

def Download(url, user_id):
    """Download a single YouTube video"""
    try:
        folder = f'Downloads/{user_id}'
        os.makedirs(folder, exist_ok=True)
        
        ydl_opts = {
            'format': 'best[height<=720]',
            'outtmpl': f'{folder}/%(title)s.%(ext)s',
            'quiet': True,
            'no_warnings': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            # Find the actual file
            import glob
            base = os.path.splitext(filename)[0]
            files = glob.glob(f"{base}.*")
            if files:
                return files[0]
        return None
    except Exception as e:
        print(f"Download error: {e}")
        return None

# ==================== CONFIG ====================
TOKEN = os.environ.get('BOT_TOKEN', '8832840308:AAERG8el8xWUhFGMivuEZiVAV42exmMMFNk')
PORT = int(os.environ.get('PORT', 5000))
WEBHOOK_URL = os.environ.get('WEBHOOK_URL', '')

# ==================== STATES ====================
START_CO, GET_WORD, GET_NUMBER, GET_CHANNEL_URL, GET_URL, CONFIRMATION = range(1, 7)

# ==================== KEYBOARDS ====================
reply_keyboard_start = [
    ['📥 Download entire channel'],
    ['🔍 Download with searching word'],
    ['📹 Download one video'],
    ['📊 See processes'],
    ['❌ Exit']
]
markup_start = ReplyKeyboardMarkup(reply_keyboard_start, resize_keyboard=True, one_time_keyboard=True)

reply_keyboard_back = [['🔙 Back', '🏠 Home', '❌ Exit']]
markup_back = ReplyKeyboardMarkup(reply_keyboard_back, resize_keyboard=True, one_time_keyboard=True)

reply_keyboard_confirmation = [['✅ I confirm'], ['🏠 Home', '❌ Exit']]
markup_confirmation = ReplyKeyboardMarkup(reply_keyboard_confirmation, resize_keyboard=True, one_time_keyboard=True)

# ==================== HELPERS ====================
def remake_folder(folder_name):
    """Clean or create download folder"""
    folder = f'Downloads/{folder_name}'
    if os.path.exists(folder):
        try:
            shutil.rmtree(folder)
        except:
            pass
    os.makedirs(folder, exist_ok=True)

async def do_downloading(user_data, user, update):
    """Download all videos in background thread"""
    for url in user_data['list_of_urls']:
        try:
            status = Download(url['url'], user.id)
            if status:
                try:
                    with open(status, 'rb') as video:
                        await update.message.reply_video(
                            video=video,
                            caption=url.get('title', 'Video')
                        )
                except:
                    pass
                try:
                    os.remove(status)
                except:
                    pass
            else:
                await update.message.reply_text(f"❌ Failed: {url['url']}")
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {url['url']}")
            continue

def run_async_download(user_data, user, update, loop):
    """Run async download in thread"""
    asyncio.set_event_loop(loop)
    loop.run_until_complete(do_downloading(user_data, user, update))

# ==================== HANDLERS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    remake_folder(str(user.id))
    await update.message.reply_text(
        f'👋 Welcome {user.first_name}!\nChoose an option:',
        reply_markup=markup_start
    )
    return START_CO

async def start_co(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text
    remake_folder(str(user.id))

    if 'entire channel' in text.lower():
        await update.message.reply_text(
            '🔗 Send URL of one video from the channel:',
            reply_markup=markup_back
        )
        return GET_CHANNEL_URL

    elif 'searching word' in text.lower():
        await update.message.reply_text(
            '🔤 Enter search word:',
            reply_markup=markup_back
        )
        return GET_WORD

    elif 'one video' in text.lower():
        await update.message.reply_text(
            '🔗 Send video link:',
            reply_markup=markup_back
        )
        return GET_URL

    elif 'processes' in text.lower():
        return await see_processes(update, context)

    elif 'home' in text.lower():
        await update.message.reply_text('Choose an option:', reply_markup=markup_start)
        return START_CO
    
    else:
        await update.message.reply_text('Choose an option:', reply_markup=markup_start)
        return START_CO

async def get_channel_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data = context.user_data
    text = update.message.text

    if text in ['🔙 Back', '🏠 Home']:
        await update.message.reply_text('Choose an option:', reply_markup=markup_start)
        return START_CO

    await update.message.reply_text('🔍 Finding channel...')
    channel_id = find_channel_id(text)
    
    if channel_id:
        await update.message.reply_text('📊 Getting video list...')
        list_of_urls = get_videos_from_channel(channel_id)
        if list_of_urls:
            user_data['list_of_urls'] = list_of_urls
            await update.message.reply_text(
                f'📊 Found **{len(list_of_urls)}** videos.\n✅ Confirm download?',
                reply_markup=markup_confirmation
            )
            return CONFIRMATION
    
    await update.message.reply_text('❌ Could not find channel!', reply_markup=markup_start)
    return START_CO

async def get_word_for_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data = context.user_data
    text = update.message.text

    if text in ['🔙 Back', '🏠 Home']:
        await update.message.reply_text('Choose an option:', reply_markup=markup_start)
        return START_CO

    user_data['search_word'] = text
    await update.message.reply_text(
        '🔢 How many videos? (number only)',
        reply_markup=markup_back
    )
    return GET_NUMBER

async def get_number_of_videos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data = context.user_data
    text = update.message.text

    if text in ['🔙 Back', '🏠 Home']:
        await update.message.reply_text('Enter search word:', reply_markup=markup_back)
        return GET_WORD

    try:
        number = int(text)
        if number > 50:
            await update.message.reply_text('⚠️ Max 50 videos! Try again:')
            return GET_NUMBER
        
        await update.message.reply_text(f'🔍 Searching for: **{user_data["search_word"]}**')
        list_of_urls = find_videos_with_search(user_data['search_word'], number)
        
        if list_of_urls:
            user_data['list_of_urls'] = list_of_urls
            await update.message.reply_text(
                f'📊 Found **{len(list_of_urls)}** videos.\n✅ Confirm download?',
                reply_markup=markup_confirmation
            )
            return CONFIRMATION
        else:
            await update.message.reply_text('❌ No videos found!', reply_markup=markup_start)
            return START_CO
    
    except ValueError:
        await update.message.reply_text('❌ Please enter a number!')
        return GET_NUMBER

async def get_one_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text

    if text in ['🔙 Back', '🏠 Home']:
        await update.message.reply_text('Choose an option:', reply_markup=markup_start)
        return START_CO

    await update.message.reply_text('⬇️ Downloading video...')
    
    try:
        status = Download(text, user.id)
        if status:
            try:
                with open(status, 'rb') as video:
                    await update.message.reply_video(
                        video=video,
                        reply_markup=markup_start
                    )
                os.remove(status)
                return START_CO
            except Exception as e:
                await update.message.reply_text(f'❌ Upload failed: {e}', reply_markup=markup_start)
                return START_CO
        else:
            await update.message.reply_text('❌ Download failed!', reply_markup=markup_start)
            return START_CO
    except Exception as e:
        await update.message.reply_text(f'❌ Error: {e}', reply_markup=markup_start)
        return START_CO

async def confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data = context.user_data
    user = update.effective_user

    if 'I confirm' not in update.message.text:
        await update.message.reply_text('Choose an option:', reply_markup=markup_start)
        return START_CO

    await update.message.reply_text('⬇️ Starting downloads... This may take a while.')

    # Run in thread to not block
    loop = asyncio.new_event_loop()
    thread = threading.Thread(
        target=run_async_download,
        args=(user_data, user, update, loop)
    )
    thread.start()

    await update.message.reply_text('✅ Download started in background!', reply_markup=markup_start)
    return START_CO

async def see_processes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    active = threading.active_count() - 1  # minus main thread
    await update.message.reply_text(
        f'📊 Active threads: **{active}**',
        reply_markup=markup_start
    )
    return START_CO

async def stop_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('👋 Goodbye!', reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def timeout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    try:
        remake_folder(str(user.id))
    except:
        pass
    await update.message.reply_text('⏰ Timeout! /start to begin again.', reply_markup=ReplyKeyboardRemove())

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"Error: {context.error}")
    if update:
        try:
            await update.message.reply_text('❌ An error occurred. Please /start again.')
        except:
            pass

# ==================== MAIN ====================
def main():
    app = Application.builder().token(TOKEN).build()

    # States
    states = {
        START_CO: [
            MessageHandler(filters.Regex('(?i)entire channel'), start_co),
            MessageHandler(filters.Regex('(?i)searching word'), start_co),
            MessageHandler(filters.Regex('(?i)one video'), start_co),
            MessageHandler(filters.Regex('(?i)processes'), see_processes),
            MessageHandler(filters.Regex('(?i)home'), start_co),
        ],
        GET_WORD: [
            MessageHandler(filters.Regex('(?i)(back|home)'), start_co),
            MessageHandler(filters.TEXT & ~filters.COMMAND, get_word_for_search),
        ],
        GET_NUMBER: [
            MessageHandler(filters.Regex('(?i)(back|home)'), start_co),
            MessageHandler(filters.TEXT & ~filters.COMMAND, get_number_of_videos),
        ],
        GET_CHANNEL_URL: [
            MessageHandler(filters.Regex('(?i)(back|home)'), start_co),
            MessageHandler(filters.TEXT & ~filters.COMMAND, get_channel_url),
        ],
        GET_URL: [
            MessageHandler(filters.Regex('(?i)(back|home)'), start_co),
            MessageHandler(filters.TEXT & ~filters.COMMAND, get_one_video),
        ],
        CONFIRMATION: [
            MessageHandler(filters.Regex('(?i)i confirm'), confirmation),
            MessageHandler(filters.Regex('(?i)home'), start_co),
        ],
    }

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states=states,
        fallbacks=[
            CommandHandler('start', start),
            MessageHandler(filters.Regex('(?i)exit'), stop_conversation),
            MessageHandler(filters.Regex('(?i)home'), start_co),
        ],
        conversation_timeout=300,
    )

    app.add_handler(conv_handler)
    app.add_error_handler(error_handler)

    print('🤖 Bot is running...')
    
    # Railway uses webhook or polling
    if WEBHOOK_URL:
        app.run_webhook(
            listen='0.0.0.0',
            port=PORT,
            url_path=TOKEN,
            webhook_url=f'{WEBHOOK_URL}/{TOKEN}'
        )
    else:
        app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
