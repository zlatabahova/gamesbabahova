# bot.py
import logging
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ConversationHandler, MessageHandler, filters, ContextTypes
import config

# Включаем логирование
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Этапы разговора (состояния)
NAME, GAME, TIME = range(3)

# Твой вебхук от Make.com (если не меняла — оставляй как есть)
WEBHOOK_URL = "https://hook.eu1.make.com/p6xhpykdytosqseygbrp3zw6c7bgvypp"

# Твой Telegram ID для уведомлений
ADMIN_CHAT_ID = 518113103

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Запускает диалог, спрашивает имя."""
    await update.message.reply_text("Привет! Давай запишем тебя на игру. Введи своё имя:")
    return NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Сохраняет имя и показывает кнопки с играми."""
    context.user_data['player_name'] = update.message.text
    # Создаем кнопки с играми из config.py
    keyboard = [[InlineKeyboardButton(game, callback_data=game)] for game in config.GAME_TIMES.keys()]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Отлично! Теперь выбери игру:", reply_markup=reply_markup)
    return GAME

async def get_game(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Сохраняет выбранную игру и показывает доступное время."""
    query = update.callback_query
    await query.answer()
    chosen_game = query.data
    context.user_data['game'] = chosen_game

    # Получаем доступное время для этой игры из config.py
    available_times = config.GAME_TIMES.get(chosen_game, ["20:00"])

    # Создаем кнопки с временем
    keyboard = [[InlineKeyboardButton(time, callback_data=time)] for time in available_times]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(f"Ты выбрал(а) {chosen_game}. Теперь выбери время:", reply_markup=reply_markup)
    return TIME

async def get_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Финал: сохраняет время, отправляет подтверждение и уведомление админу."""
    query = update.callback_query
    await query.answer()
    chosen_time = query.data
    context.user_data['time'] = chosen_time

    # Получаем информацию о пользователе
    user = update.effective_user
    username = user.username if user.username else "нет username"
    user_id = user.id

    # Собираем все данные
    player_name = context.user_data['player_name']
    game = context.user_data['game']
    time = context.user_data['time']

    # Сообщение самому пользователю
    result_message = f"✅ Ты записан!\n\nИмя: {player_name}\nИгра: {game}\nВремя: {time}\n\nЖдем тебя в Дискорде!"
    await query.edit_message_text(result_message)

    # Отправляем уведомление админу (тебе)
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

    # Отправка данных в Google Sheets через Make.com
    data = {
        "name": player_name,
        "game": game,
        "time": time,
        "username": username,
        "user_id": user_id
    }
    try:
        requests.post(WEBHOOK_URL, json=data)
        logger.info("Данные отправлены в Make.com")
    except Exception as e:
        logger.error(f"Ошибка отправки в Make: {e}")

    # Завершаем разговор
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отменяет запись."""
    await update.message.reply_text("Запись отменена.")
    return ConversationHandler.END

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Помощь."""
    await update.message.reply_text("Просто нажми /start, чтобы записаться на игру.")

def main() -> None:
    """Запуск бота."""
    # Создаем приложение
    application = Application.builder().token(config.BOT_TOKEN).build()

    # Обработчик диалога
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

    # Запускаем бота
    print("Бот запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
