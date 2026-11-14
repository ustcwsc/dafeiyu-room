from threading import Thread

from app import app, check_evening, initialize

initialize()
Thread(target=check_evening, daemon=True).start()
