# bot.py
import logging
import requests
import os
import traceback
from supabase import create_client, Client
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
import config

# --- Настройка логирования ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Константы ---
NAME, GAME, TIME = range(3)
ADMIN_CHAT_ID = 518113103  # ваш Telegram ID

# --- Supabase клиент (данные берутся из переменных окружения) ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
logger.info(f"SUPABASE_URL: {SUPABASE_URL}")
logger.info(f"SUPABASE_KEY (первые 20 символов): {SUPABASE_KEY[:20] if SUPABASE_KEY else 'None'}")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Проверка подключения к Supabase ---
try:
    test = supabase.table("users").select("user_id").limit(1).execute()
    logger.info(f"✅ Подключение к Supabase успешно! Ответ: {test}")
except Exception as e:
    logger.error(f"❌ Ошибка подключения к Supabase: {e}")
    if hasattr(e, 'response') and e.response:
        logger.error(f"Детали ответа: {e.response.text[:500]}")
    # Не завершаем работу, чтобы бот хотя бы частично функционировал, но запись не будет работать

# --- Функции работы с пользователями в Supabase ---
def load_users():
    """Загружает список всех user_id из таблицы users"""
    try:
        response = supabase.table("users").select("user_id").execute()
        users = {row['user_id'] for row in response.data}
        logger.info(f"Загружено {len(users)} пользователей из Supabase")
        return users
    except Exception as e:
        logger.error(f"Ошибка загрузки пользователей из Supabase: {e}")
        return set()

def save_user(user_id, username=None, first_name=None):
    """Сохраняет нового пользователя, если его ещё нет в базе"""
    try:
        logger.info(f"Пытаюсь сохранить пользователя {user_id} в Supabase...")
        
        # Проверяем, существует ли уже такой user_id
        existing = supabase.table("users").select("user_id").eq("user_id", user_id).execute()
        logger.info(f"Результат проверки существования: {existing}")
        
        if not existing.data:
            data = {"user_id": user_id}
            if username:
                data["username"] = username
            if first_name:
                data["first_name"] = first_name
            logger.info(f"Вставляю данные: {data}")
            
            result = supabase.table("users").insert(data).execute()
            logger.info(f"✅ Результат вставки: {result}")
        else:
            logger.info(f"ℹ️ Пользователь {user_id} уже существует в базе")
    except Exception as e:
        logger.error(f"❌ ОШИБКА сохранения пользователя {user_id}: {e}")
        # Пытаемся получить детали ответа
        if hasattr(e, 'response') and e.response:
            try:
                logger.error(f"Текст ответа: {e.response.text[:500]}")
            except:
                pass

# --- Функция установки вебхука ---
def set_webhook():
    hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
    if not hostname:
        logger.error("❌ RENDER_EXTERNAL_HOSTNAME не задан. Вебхук не установлен.")
        return
    webhook_url = f"https://{hostname}/{config.BOT_TOKEN}"
    url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/setWebhook?url={webhook_url}"
    try:
        r = requests.get(url)
        if r.status_code == 200:
            logger.info(f"✅ Вебхук установлен на {webhook_url}")
        else:
            logger.error(f"❌ Ошибка установки вебхука: {r.text}")
    except Exception as e:
        logger.error(f"❌ Ошибка при запросе к Telegram: {e}")

# --- ОСНОВНЫЕ ОБРАБОТЧИКИ ДИАЛОГА ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    save_user(user.id, user.username, user.first_name)
    await update.message.reply_text("Привет! Давай запишем тебя на игру. Введи своё имя:")
    return NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["player_name"] = update.message.text
    keyboard = [
        [InlineKeyboardButton(game, callback_data=game)]
        for game in config.GAME_TIMES.keys()
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Отлично! Теперь выбери игру:", reply_markup=reply_markup
    )
    return GAME

async def get_game(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    chosen_game = query.data
    context.user_data["game"] = chosen_game

    available_times = config.GAME_TIMES.get(chosen_game, ["20:00"])
    keyboard = [
        [InlineKeyboardButton(time, callback_data=time)] for time in available_times
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"Ты выбрал(а) {chosen_game}. Теперь выбери время:",
        reply_markup=reply_markup,
    )
    return TIME

async def get_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    chosen_time = query.data
    context.user_data["time"] = chosen_time

    user = update.effective_user
    username = user.username if user.username else "нет username"
    user_id = user.id

    player_name = context.user_data["player_name"]
    game = context.user_data["game"]
    time = context.user_data["time"]

    result_message = (
        f"✅ Ты записан!\n\n"
        f"Имя: {player_name}\n"
        f"Игра: {game}\n"
        f"Время: {time}\n\n"
        f"Ждем тебя в Дискорде!"
    )
    await query.edit_message_text(result_message)

    admin_message = (
        f"📝 Новая запись!\n\n"
        f"Имя: {player_name}\n"
        f"Игра: {game}\n"
        f"Время: {time}\n"
        f"Username: @{username}\n"
        f"Telegram ID: {user_id}"
    )
    try:
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_message)
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение админу: {e}")

    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Запись отменена.")
    return ConversationHandler.END

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Просто нажми /start, чтобы записаться на игру.")

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("pong 🏓")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ У вас нет прав для этой команды.")
        return

    message_text = " ".join(context.args)
    if not message_text:
        await update.message.reply_text(
            "❓ Использование: /broadcast Текст сообщения\n\n"
            "Например: /broadcast Напоминаю об игре сегодня в 20:00!"
        )
        return

    users = load_users()
    if not users:
        await update.message.reply_text("📭 В базе пока нет пользователей для рассылки.")
        return

    status_msg = await update.message.reply_text(
        f"📨 Начинаю рассылку {len(users)} пользователям..."
    )

    success = 0
    failed = 0
    for uid in users:
        try:
            await context.bot.send_message(chat_id=uid, text=message_text)
            success += 1
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение пользователю {uid}: {e}")
            failed += 1

    await status_msg.edit_text(
        f"✅ Рассылка завершена!\n\n"
        f"📊 Всего: {len(users)}\n"
        f"✅ Успешно: {success}\n"
        f"❌ Ошибок: {failed}"
    )

    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=f"📊 Отчёт о рассылке:\nУспешно: {success}, Ошибок: {failed}",
    )

# --- Глобальный обработчик ошибок ---
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    tb = traceback.format_exception(
        None, context.error, context.error.__traceback__
    )
    tb_string = "".join(tb)
    try:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"⚠️ Ошибка в боте:\n`{tb_string[:3000]}`",
            parse_mode="Markdown",
        )
    except:
        pass

# --- Функция создания приложения ---
def create_application():
    application = Application.builder().token(config.BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            GAME: [CallbackQueryHandler(get_game)],
            TIME: [CallbackQueryHandler(get_time)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("ping", ping))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_error_handler(error_handler)

    return application

# --- Точка входа ---
if __name__ == "__main__":
    app = create_application()
    set_webhook()
    port = int(os.environ.get("PORT", 10000))
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=config.BOT_TOKEN,
        webhook_url=f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME')}/{config.BOT_TOKEN}",
    )
