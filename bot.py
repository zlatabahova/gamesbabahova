# bot.py
import logging
import requests
import os
import sys
import pickle
import traceback
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ConversationHandler, MessageHandler, filters, ContextTypes
import config

# --- Настройка логирования ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Константы ---
NAME, GAME, TIME = range(3)
ADMIN_CHAT_ID = 518113103          # ваш Telegram ID

# --- Работа с файлом пользователей (для рассылки) ---
USERS_FILE = "users.pkl"

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'rb') as f:
            return pickle.load(f)
    return set()

def save_user(user_id):
    users = load_users()
    users.add(user_id)
    with open(USERS_FILE, 'wb') as f:
        pickle.dump(users, f)

# --- Flask для приёма вебхуков от Telegram ---
flask_app = Flask(__name__)

# --- Telegram Application (будет инициализирован в run_bot) ---
application = None

# --- Функция установки вебхука ---
def set_webhook():
    hostname = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
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

# --- Маршрут для вебхуков ---
@flask_app.route(f'/{config.BOT_TOKEN}', methods=['POST'])
def webhook():
    if application is None:
        return "Application not ready", 503
    update = Update.de_json(request.get_json(force=True), application.bot)
    application.update_queue.put(update)
    return "OK", 200

# --- Маршрут для проверки здоровья ---
@flask_app.route('/health', methods=['GET'])
def health():
    return "OK", 200

# --- ОСНОВНЫЕ ОБРАБОТЧИКИ ДИАЛОГА ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    save_user(user_id)
    await update.message.reply_text("Привет! Давай запишем тебя на игру. Введи своё имя:")
    return NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['player_name'] = update.message.text
    keyboard = [[InlineKeyboardButton(game, callback_data=game)] for game in config.GAME_TIMES.keys()]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Отлично! Теперь выбери игру:", reply_markup=reply_markup)
    return GAME

async def get_game(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    chosen_game = query.data
    context.user_data['game'] = chosen_game

    available_times = config.GAME_TIMES.get(chosen_game, ["20:00"])
    keyboard = [[InlineKeyboardButton(time, callback_data=time)] for time in available_times]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(f"Ты выбрал(а) {chosen_game}. Теперь выбери время:", reply_markup=reply_markup)
    return TIME

async def get_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    chosen_time = query.data
    context.user_data['time'] = chosen_time

    user = update.effective_user
    username = user.username if user.username else "нет username"
    user_id = user.id

    player_name = context.user_data['player_name']
    game = context.user_data['game']
    time = context.user_data['time']

    # Подтверждение пользователю
    result_message = f"✅ Ты записан!\n\nИмя: {player_name}\nИгра: {game}\nВремя: {time}\n\nЖдем тебя в Дискорде!"
    await query.edit_message_text(result_message)

    # Уведомление админу (вам) — теперь только сюда
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

    message_text = ' '.join(context.args)
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

    status_msg = await update.message.reply_text(f"📨 Начинаю рассылку {len(users)} пользователям...")

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
        text=f"📊 Отчёт о рассылке:\nУспешно: {success}, Ошибок: {failed}"
    )

# --- Глобальный обработчик ошибок ---
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    tb = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = ''.join(tb)
    try:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"⚠️ Ошибка в боте:\n`{tb_string[:3000]}`",
            parse_mode='Markdown'
        )
    except:
        pass

# --- Функция инициализации и запуска бота ---
def run_bot():
    global application
    # Создаём Application
    application = Application.builder().token(config.BOT_TOKEN).build()

    # Диалог записи
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            GAME: [CallbackQueryHandler(get_game)],
            TIME: [CallbackQueryHandler(get_time)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("ping", ping))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_error_handler(error_handler)

    # Устанавливаем вебхук
    set_webhook()

    # Запускаем обработку обновлений
    application.initialize()
    application.start()
    logger.info("✅ Бот запущен и готов принимать вебхуки")

# --- Точка входа ---
if __name__ == "__main__":
    # Инициализируем бота ДО запуска Flask
    run_bot()
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port)
