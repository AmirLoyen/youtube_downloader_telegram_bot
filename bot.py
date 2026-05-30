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
    from telegram.error import TimedOut, NetworkError
except ImportError:
    print("❌ Install: pip install python-telegram-bot==20.7")
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
    print("   Install: pip install scrapetube")
    scrapetube = None

# ==================== CONFIG ====================
TOKEN = os.environ.get('BOT_TOKEN', '8832840308:AAERG8el8xWUhFGMivuEZiVAV42exmMMFNk')
if TOKEN == '8832840308:AAERG8el8xWUhFGMivuEZiVAV42exmMMFNk':
    print("❌ Please set BOT_TOKEN in environment variables!")
    exit(1)

PORT = int(os.environ.get('PORT', 8080))
WEBHOOK_URL = os.environ.get('WEBHOOK_URL', '')

# ==================== STATES ====================
(START_CO, GET_WORD, GET_NUMBER, GET_CHANNEL_URL, GET_URL, CONFIRMATION) = range(1, 7)

# ==================== KEYBOARDS ====================
keyboard_start = [
    ['📥 Download Channel', '🔍 Search & Download'],
    ['📹 Single Video', '📊 Active Downloads'],
    ['❌ Cancel']
]
markup_start = ReplyKeyboardMarkup(keyboard_start, resize_keyboard=True)

keyboard_back = [['🔙 Back', '🏠 Home', '❌ Cancel']]
markup_back = ReplyKeyboardMarkup(keyboard_back, resize_keyboard=True)

keyboard_confirm = [['✅ Confirm', '🏠 Home', '❌ Cancel']]
markup_confirm = ReplyKeyboardMarkup(keyboard_confirm, resize_keyboard=True)

# ==================== DOWNLOAD FOLDER ====================
BASE_DOWNLOAD_DIR = 'downloads'
os.makedirs(BASE_DOWNLOAD_DIR, exist_ok=True)

def clean_folder(user_id):
    """Clean user download folder"""
    folder = os.path.join(BASE_DOWNLOAD_DIR, str(user_id))
    if os.path.exists(folder):
        try:
            shutil.rmtree(folder)
        except:
            pass
    os.makedirs(folder, exist_ok=True)
    return folder

# ==================== YOUTUBE FUNCTIONS ====================
def get_channel_id(url):
    """Get channel ID from video URL"""
    try:
        ydl_opts = {'quiet': True, 'extract_flat': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get('channel_id') or info.get('uploader_id')
    except:
        return None

def get_channel_videos(channel_id):
    """Get all videos from channel"""
    if not scrapetube:
        return None
    try:
        videos = scrapetube.get_channel(channel_id)
        result = []
        for v in videos:
            vid = v.get('videoId', '')
            title = 'Unknown'
            try:
                title = v['title']['runs'][0]['text']
            except:
                pass
            if vid:
                result.append({
                    'url': f'https://youtube.com/watch?v={vid}',
                    'title': title
                })
        return result
    except:
        return None

def search_videos(query, limit=10):
    """Search YouTube videos"""
    try:
        search = Search(query)
        result = []
        for i, video in enumerate(search.results):
            if i >= limit:
                break
            result.append({
                'url': video.watch_url,
                'title': video.title or 'Unknown'
            })
        return result
    except:
        return None

def download_video(url, user_id):
    """Download single video"""
    try:
        folder = clean_folder(user_id)
        
        ydl_opts = {
            'format': 'best[height<=720][ext=mp4]/best[height<=720]/best',
            'outtmpl': os.path.join(folder, '%(title).100s.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
            'merge_output_format': 'mp4',
            'max_filesize': 1900000000,  # ~1.9GB
            'retries': 3,
            'fragment_retries': 3,
            'socket_timeout': 30,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        # Find downloaded file
        files = glob.glob(os.path.join(folder, '*'))
        if files:
            # Return largest file (most likely the video)
            return max(files, key=os.path.getsize)
        return None
    except Exception as e:
        print(f"Download error: {e}")
        return None

# ==================== BACKGROUND DOWNLOAD ====================
def background_download(loop, user_data, user_id, context):
    """Run download in background thread"""
    asyncio.set_event_loop(loop)
    
    async def download_all():
        videos = user_data.get('list_of_urls', [])
        total = len(videos)
        
        for i, video in enumerate(videos, 1):
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f'⬇️ Downloading {i}/{total}: {video["title"][:50]}...'
                )
                
                filepath = download_video(video['url'], user_id)
                
                if filepath and os.path.exists(filepath):
                    file_size = os.path.getsize(filepath) / (1024 * 1024)
                    
                    if file_size < 1900:
                        try:
                            with open(filepath, 'rb') as f:
                                await context.bot.send_video(
                                    chat_id=user_id,
                                    video=f,
                                    caption=video['title'][:200],
                                    supports_streaming=True
                                )
                        except Exception as e:
                            await context.bot.send_message(
                                chat_id=user_id,
                                text=f'❌ Upload failed: {video["title"][:50]}'
                            )
                    else:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text=f'⚠️ Too large ({file_size:.0f}MB): {video["title"][:50]}'
                        )
                    
                    try:
                        os.remove(filepath)
                    except:
                        pass
                else:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f'❌ Failed: {video["title"][:50]}'
                    )
                    
            except Exception as e:
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f'❌ Error downloading video {i}'
                    )
                except:
                    pass
        
        # Cleanup
        try:
            clean_folder(user_id)
        except:
            pass
        
        await context.bot.send_message(
            chat_id=user_id,
            text=f'✅ Download complete! {total} videos processed.'
        )
    
    loop.run_until_complete(download_all())

# ==================== HANDLERS ====================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler"""
    user = update.effective_user
    clean_folder(user.id)
    
    await update.message.reply_text(
        f'👋 **Welcome {user.first_name}!**\n\n'
        f'📥 Download entire YouTube channels\n'
        f'🔍 Search and download videos\n'
        f'📹 Download single videos\n\n'
        f'Choose an option below:',
        reply_markup=markup_start
    )
    return START_CO

async def handle_start_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle main menu choices"""
    user = update.effective_user
    text = update.message.text.lower()
    clean_folder(user.id)
    
    if 'channel' in text:
        await update.message.reply_text(
            '🔗 Send me a video URL from the channel you want to download:',
            reply_markup=markup_back
        )
        return GET_CHANNEL_URL
    
    elif 'search' in text:
        await update.message.reply_text(
            '🔤 What do you want to search for?',
            reply_markup=markup_back
        )
        return GET_WORD
    
    elif 'single' in text:
        await update.message.reply_text(
            '🔗 Send me the YouTube video URL:',
            reply_markup=markup_back
        )
        return GET_URL
    
    elif 'active' in text:
        active_threads = threading.active_count() - 1
        await update.message.reply_text(
            f'📊 **Active downloads:** {active_threads}\n\nChoose an option:',
            reply_markup=markup_start
        )
        return START_CO
    
    elif 'cancel' in text:
        return await cmd_cancel(update, context)
    
    elif 'home' in text:
        await update.message.reply_text('🏠 Main menu:', reply_markup=markup_start)
        return START_CO
    
    else:
        await update.message.reply_text('Choose an option:', reply_markup=markup_start)
        return START_CO

async def handle_channel_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle channel URL input"""
    text = update.message.text
    
    if text in ['🔙 Back', '🏠 Home', '❌ Cancel']:
        await update.message.reply_text('🏠 Main menu:', reply_markup=markup_start)
        return START_CO
    
    await update.message.reply_text('🔍 Finding channel information...')
    
    channel_id = get_channel_id(text)
    if not channel_id:
        await update.message.reply_text(
            '❌ Could not find channel!\nPlease send a valid YouTube video URL.',
            reply_markup=markup_back
        )
        return GET_CHANNEL_URL
    
    await update.message.reply_text('📊 Getting video list...')
    videos = get_channel_videos(channel_id)
    
    if not videos:
        await update.message.reply_text(
            '❌ Could not get videos!\nChannel might be empty or private.',
            reply_markup=markup_start
        )
        return START_CO
    
    context.user_data['list_of_urls'] = videos
    await update.message.reply_text(
        f'📊 **Channel found!**\n'
        f'📹 Videos: **{len(videos)}**\n\n'
        f'✅ Confirm to start download?',
        reply_markup=markup_confirm
    )
    return CONFIRMATION

async def handle_search_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle search word input"""
    text = update.message.text
    
    if text in ['🔙 Back', '🏠 Home', '❌ Cancel']:
        await update.message.reply_text('🏠 Main menu:', reply_markup=markup_start)
        return START_CO
    
    context.user_data['search_word'] = text
    await update.message.reply_text(
        f'🔤 Search: **{text}**\n'
        f'🔢 How many videos to download? (1-20)',
        reply_markup=markup_back
    )
    return GET_NUMBER

async def handle_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle number input"""
    text = update.message.text
    
    if text in ['🔙 Back', '🏠 Home', '❌ Cancel']:
        await update.message.reply_text('🏠 Main menu:', reply_markup=markup_start)
        return START_CO
    
    try:
        count = int(text)
        if count < 1 or count > 20:
            await update.message.reply_text('❌ Please enter a number between 1 and 20:')
            return GET_NUMBER
    except ValueError:
        await update.message.reply_text('❌ Please enter a valid number:')
        return GET_NUMBER
    
    query = context.user_data.get('search_word', '')
    await update.message.reply_text(f'🔍 Searching YouTube for: **{query}**...')
    
    videos = search_videos(query, count)
    
    if not videos:
        await update.message.reply_text(
            '❌ No videos found! Try a different search.',
            reply_markup=markup_start
        )
        return START_CO
    
    context.user_data['list_of_urls'] = videos
    
    # Show preview
    preview = '\n'.join([f'{i+1}. {v["title"][:60]}' for i, v in enumerate(videos[:5])])
    if len(videos) > 5:
        preview += f'\n... and {len(videos) - 5} more'
    
    await update.message.reply_text(
        f'📊 **Search Results:**\n\n{preview}\n\n'
        f'✅ Confirm to download **{len(videos)}** videos?',
        reply_markup=markup_confirm
    )
    return CONFIRMATION

async def handle_single_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle single video URL"""
    user = update.effective_user
    text = update.message.text
    
    if text in ['🔙 Back', '🏠 Home', '❌ Cancel']:
        await update.message.reply_text('🏠 Main menu:', reply_markup=markup_start)
        return START_CO
    
    if 'youtube.com' not in text and 'youtu.be' not in text:
        await update.message.reply_text(
            '❌ Invalid YouTube URL!\nSend a valid link:',
            reply_markup=markup_back
        )
        return GET_URL
    
    msg = await update.message.reply_text('⬇️ Downloading video...')
    
    try:
        filepath = download_video(text, user.id)
        
        if filepath and os.path.exists(filepath):
            file_size = os.path.getsize(filepath) / (1024 * 1024)
            
            if file_size > 1900:
                await msg.edit_text(f'⚠️ Video too large ({file_size:.0f}MB)!')
                os.remove(filepath)
                return START_CO
            
            await msg.edit_text(f'📤 Uploading ({file_size:.0f}MB)...')
            
            try:
                with open(filepath, 'rb') as f:
                    await update.message.reply_video(
                        video=f,
                        supports_streaming=True,
                        reply_markup=markup_start
                    )
                await msg.delete()
            except Exception as e:
                await msg.edit_text(f'❌ Upload failed! Video might be too long.')
            
            try:
                os.remove(filepath)
            except:
                pass
            
            return START_CO
        else:
            await msg.edit_text(
                '❌ Download failed! Try a different video.',
                reply_markup=markup_start
            )
            return START_CO
    except Exception as e:
        await msg.edit_text(f'❌ Error: {str(e)[:100]}')
        return START_CO

async def handle_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle download confirmation"""
    user = update.effective_user
    user_data = context.user_data
    
    if 'confirm' not in update.message.text.lower():
        await update.message.reply_text('🏠 Main menu:', reply_markup=markup_start)
        return START_CO
    
    videos = user_data.get('list_of_urls', [])
    if not videos:
        await update.message.reply_text('❌ No videos to download!', reply_markup=markup_start)
        return START_CO
    
    await update.message.reply_text(
        f'⬇️ Starting download of **{len(videos)}** videos...\n'
        f'This will run in the background.\n'
        f'You can continue using the bot.',
        reply_markup=markup_start
    )
    
    # Start download in background thread
    loop = asyncio.new_event_loop()
    thread = threading.Thread(
        target=background_download,
        args=(loop, user_data, user.id, context),
        daemon=True
    )
    thread.start()
    
    return START_CO

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel and return to start"""
    user = update.effective_user
    clean_folder(user.id)
    await update.message.reply_text(
        '👋 Operation cancelled! /start to begin again.',
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command"""
    await update.message.reply_text(
        '📚 **YouTube Downloader Bot**\n\n'
        '**Commands:**\n'
        '/start - Start the bot\n'
        '/help - Show this help\n'
        '/cancel - Cancel current operation\n\n'
        '**Features:**\n'
        '📥 Download entire YouTube channels\n'
        '🔍 Search and download videos\n'
        '📹 Download single videos by URL\n\n'
        '**Limits:**\n'
        '• Max 20 videos per search\n'
        '• Max ~1.9GB per video\n'
        '• Max 720p quality'
    )

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    print(f"Error: {context.error}")
    print(traceback.format_exc())
    
    try:
        if update and hasattr(update, 'message') and update.message:
            await update.message.reply_text(
                '❌ An error occurred! Please /start again.'
            )
    except:
        pass

# ==================== MAIN ====================
def main():
    """Start the bot"""
    print('🤖 Starting YouTube Downloader Bot...')
    
    # Build application
    app = Application.builder().token(TOKEN).build()
    
    # Add help handler
    app.add_handler(CommandHandler('help', cmd_help))
    
    # Add conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', cmd_start)],
        states={
            START_CO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_start_menu),
            ],
            GET_CHANNEL_URL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_channel_url),
            ],
            GET_WORD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search_word),
            ],
            GET_NUMBER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_number),
            ],
            GET_URL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_single_url),
            ],
            CONFIRMATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_confirm),
            ],
        },
        fallbacks=[
            CommandHandler('cancel', cmd_cancel),
            CommandHandler('start', cmd_start),
            MessageHandler(filters.Regex('(?i)^(cancel|exit)$'), cmd_cancel),
            MessageHandler(filters.Regex('(?i)^home$'), handle_start_menu),
        ],
        conversation_timeout=600,  # 10 minutes
        name="youtube_downloader",
        persistent=False,
    )
    
    app.add_handler(conv_handler)
    app.add_error_handler(error_handler)
    
    print('✅ Bot is ready!')
    
    # Start bot
    if WEBHOOK_URL and WEBHOOK_URL.strip():
        print(f'🌐 Webhook mode: {WEBHOOK_URL}')
        app.run_webhook(
            listen='0.0.0.0',
            port=PORT,
            url_path=TOKEN,
            webhook_url=f'{WEBHOOK_URL}/{TOKEN}'
        )
    else:
        print('📡 Polling mode')
        app.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )

if __name__ == '__main__':
    main()
