import re
import time
import threading
from telegram.client import Telegram
import brightid_tools
import config

brightid_bot = brightid_tools.load_brightid()

connection_requests = set()


def monitor_service():
    tg = Telegram(
        api_id=config.TELEGRAM_API_ID,
        api_hash=config.TELEGRAM_API_HASH,
        phone=config.TELEGRAM_PHONE,
        database_encryption_key=config.TELEGRAM_DB_ENCRYPTION_KEY,
    )
    tg.login()

    def find_brightid_connection(update):
        msg = update['message']['content'].get('text', {}).get('text', '')
        p = re.compile(config.CONN_PATTERN)
        result = p.search(msg)
        if result:
            connection_url = result.group()
            print(f'connection request has been received: {connection_url}')
            connection_requests.add(connection_url)
    tg.add_message_handler(find_brightid_connection)
    tg.idle()


def report_service():
    while True:
        brightid_tools.react_to_connection_requests(
            brightid_bot, connection_requests)
        brightid_tools.check_just_met_conns(brightid_bot)
        time.sleep(config.CHECK_INTERVAL)


if __name__ == '__main__':
    print('start monitoring...')
    service1 = threading.Thread(target=report_service)
    service1.start()
    monitor_service()
