from os import system, name
from time import sleep
import requests
from bs4 import BeautifulSoup
from numpy import zeros, int16, max as nmax, add, ndenumerate
from random import sample
from datetime import timedelta, datetime
from itertools import product
from functools import reduce
from openpyxl import Workbook
from openpyxl.styles import PatternFill, Alignment
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, ConversationHandler, MessageHandler, CallbackQueryHandler, CallbackContext, ContextTypes, filters
import logging, json
import logging.handlers

CONFIRMATION = 0
ENTERING_ASSIGNATURES = 1
SELECTING_SCHEDULES = 2

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
formatter = logging.Formatter(log_format)

file_handler = logging.handlers.RotatingFileHandler('/home/sr-gus/telegram-bot-horarios/logs.log', maxBytes=1048576, backupCount=5)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        file_handler
    ]
)

global codes

def hour_to_interval(hour):
    hour, minutes = map(int, hour.split(':'))
    return hour * 4 + minutes // 15

async def load_html(codes, message):
    bar_length = 10
    step = len(codes) / bar_length
    days = {'Lun': 0, 'Mar': 1, 'Mie': 2, 'Jue': 3, 'Vie': 4, 'Sab': 5, 'Dom': 6}
    options = {}
    progress = 1
    progress_msg = await message.reply_text('▱'*bar_length + ' - 0 %')
    for code in codes:
        try:
            html_text = requests.get('https://www.ssa.ingenieria.unam.mx/cj/tmp/programacion_horarios/{}.html?_=1675362427735'.format(code), timeout=10).text
            if html_text.status_code != 200:
                await message.reply_text('No se pudieron obtener los grupos para el código {}.'.format(code))
                bar = '▰' * round(progress / step) + '▱' * round((len(codes) - progress) / step) + ' - {:.2f} %'.format(100*progress/len(codes))
                await progress_msg.edit_text(text=bar)
                progress += 1
                continue
        except requests.exceptions.Timeout:
            await message.reply_text('No se pudieron obtener los grupos para el código {}.'.format(code))
            bar = '▰' * round(progress / step) + '▱' * round((len(codes) - progress) / step) + ' - {:.2f} %'.format(100*progress/len(codes))
            await progress_msg.edit_text(text=bar)
            progress += 1
            continue
        soup = BeautifulSoup(html_text, 'html.parser')
        tracks = soup.find_all('td')
        groups = []
        group = []
        schedule = zeros((96, 7), dtype=int16)
        hours = []
        reading_schedule = False
        places = 0
        save = True
        for i in range(len(tracks)):
            text = tracks[i].get_text().strip()
            if text == 'L+' and (len(code) != 4 or (code[0] != '5' and code[0] != '6')):
                save = False
            if ':' in text:
                hours.append(text)
                reading_schedule = True
            elif reading_schedule:
                days_occupied = [days[day] for day in text.split(', ')]
                interval = hours[-1].split(' a ')
                hours[-1] = text + ' - ' + hours[-1]
                start, end = map(hour_to_interval, interval)
                for day in days_occupied:
                    schedule[start:end, day] = 1
                reading_schedule = False
            if (text == code and i > 0) or (i == (len(tracks)-1)):
                group.append(' / '.join(hours))
                hours = []
                group.append(schedule)
                schedule = zeros((96, 7), dtype=int16)
                if places > 0 and save:
                    groups.append(group.copy())
                    group = [text]
                save = True
            else:
                if text != 'L' and text != 'T' and ',' not in text and ':' not in text and text not in days.keys():
                    group.append(text)
                if text.isdigit() and len(group) >= 2:
                    places = int(text)
        if groups:
            options[code] = groups
            await message.reply_text('Se obtuvieron correctamente los grupos para {}.'.format(code))
        else:
            await message.reply_text('No hay grupos disponibles para {}.'.format(code))
        bar = '▰' * round(progress / step) + '▱' * round((len(codes) - progress) / step) + ' - {:.2f} %'.format(100*progress/len(codes))
        await progress_msg.edit_text(text=bar)
        progress += 1
    return options

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text('Usa el comando /iniciar para iniciar a usar el bot.')

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    username = update.message.chat.username
    if username != None:
        await update.message.reply_text(f'Hola {update.message.chat.username}!!!')
    await update.message.reply_text('Bienvenid@ al bot de horarios para la FI.')
    await update.message.reply_text('Ingresa los códigos de tus materias separados por comas.')
    return ENTERING_ASSIGNATURES

async def handle_codes(update: Update, _: CallbackContext) -> int:
    global codes
    codes = [code.strip() for code in update.message.text.split(',')]
    codes = [code for code in codes if code != '']
    logger.info(codes)
    if all([item.isdigit() for item in codes]):
        for i in range(len(codes)):
            if codes[i][0] == '0':
                codes[i] = codes[i][1:]
        logger.info(codes)
        reply_keyboard = [['Obtener grupos', 'Repetir selección']]
        await update.message.reply_text(
            'Se obtendrán los grupos de las materias con los siguientes códigos:\n- ' + '\n- '.join(codes), 
            reply_markup=ReplyKeyboardMarkup(
                reply_keyboard, 
                one_time_keyboard=True, 
                input_field_placeholder='¿Es correcto?'
            )
        )
        return CONFIRMATION
    else:
        await update.message.reply_text('Entrada inválida, ingresa solo números separados por comas.')
        return ENTERING_ASSIGNATURES

async def handle_schedules(update: Update, _: CallbackContext) -> None:
    pass

async def handle_confirmation(update: Update, _: CallbackContext) -> int:
    if update.message.text == 'Obtener grupos':
        global codes
        await update.message.reply_text('Obteniendo grupos para las materias seleccionadas.', reply_markup=ReplyKeyboardRemove())
        options = await load_html(codes, update.message)
        logger.info(options)
        if options:
            return SELECTING_SCHEDULES
        else:
            await update.message.reply_text('No hay grupos disponibles para ninguna materia.')
            await update.message.reply_text('Gracias por usar el bot.')
            ConversationHandler.END
    elif update.message.text == 'Repetir selección':
        await update.message.reply_text('Ingresa los códigos de tus materias separados por comas.', reply_markup=ReplyKeyboardRemove())
        return ENTERING_ASSIGNATURES
    else:
        pass

def main() -> None:
    application = Application.builder().token('6648405836:AAG0-vh6zU9yKdx3_K-PoYMyrKEvXYnI7yQ').build()
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            ENTERING_ASSIGNATURES: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_codes)],
            SELECTING_SCHEDULES: [CallbackQueryHandler(handle_schedules)],
            CONFIRMATION: [MessageHandler(filters.Regex("^(Obtener grupos|Repetir selección)$"), handle_confirmation)],
        },
        fallbacks=[]
    )
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(conv_handler)
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()