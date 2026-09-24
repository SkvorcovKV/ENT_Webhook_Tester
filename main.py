from flask import Flask, render_template, request, jsonify, Response
from datetime import datetime
import time
import json
import os
import sys
import webbrowser
import threading
import subprocess
# --- Импорты для системного трея ---
import pystray
from PIL import Image

# --- ГЛОБАЛЬНАЯ ПЕРЕМЕННАЯ ДЛЯ ТРЕЯ ---
# Мы создаем "пустую коробку", чтобы позже положить в неё иконку.
# Это нужно, чтобы мы могли выключить иконку из любого места программы.
tray_icon = None

# --- СЛОВАРЬ ПЕРЕВОДЧИКА ---
PARAM_HINTS = {
    'time': '🕒 Время', 'te': '🕒 Время', 'datetime': '🕒 Дата и время', 'dt': '🕒 Дата',
    'event': '⚡ Событие', 'ev': '⚡ Событие', 'type': '⚡ Тип события',
    'door': '🚪 Контроллер/Дверь', 'dv': '🚪 Контроллер/Дверь', 'device': '🚪 Устройство',
    'user': '👤 Сотрудник', 'us': '👤 Сотрудник', 'employee': '👤 Сотрудник', 'name': '👤 Имя',
    'card': '💳 Карта', 'cr': '💳 Карта', 'code': '🔢 Код', 'cd': '🔢 Код карты',
    'ip': '🌐 IP-адрес', 'address': '📍 Адрес',
    'token': '🔑 Токен', 'key': '🔑 Ключ', 'secret': '🔑 Секрет',
    'arg1': '📎 Аргумент 1', 'arg2': '📎 Аргумент 2', 'arg3': '📎 Аргумент 3',
    'arg4': '📎 Аргумент 4', 'arg5': '📎 Аргумент 5', 'arg6': '📎 Аргумент 6',
    'arg7': '📎 Аргумент 7', 'arg8': '📎 Аргумент 8', 'arg9': '📎 Аргумент 9',
    'arg10': '📎 Аргумент 10', 'arg11': '📎 Аргумент 11', 'arg12': '📎 Аргумент 12'
}

def beautify_data(data):
    if not isinstance(data, dict): return data
    beautiful = []
    for key, value in data.items():
        pretty_key = PARAM_HINTS.get(key.lower(), key)
        beautiful.append({"k": pretty_key, "v": str(value)})
    return beautiful

# --- МАГИЯ PYINSTALLER ---
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

if getattr(sys, 'frozen', False):
    template_dir = resource_path('templates')
    static_dir = resource_path('static')
    app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
else:
    app = Flask(__name__)

logs = []
MAX_LOGS = 100
CONFIG_FILE = 'config.json'

# --- РАБОТА С НАСТРОЙКАМИ ---
def load_config():
    default_settings = {
        "response_mode": "success", "preset": "bitrix24",
        "custom_text": '{"STATUS":"OPENED"}', "port": 8080, "expected_token": "secret"
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
                default_settings.update(saved)
        except Exception as e:
            print(f"Ошибка чтения конфига: {e}")
    return default_settings

settings = load_config()

def save_config():
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"Ошибка записи конфига: {e}")

actual_running_port = settings.get('port', 8080)

PRESETS = {
    "bitrix24": '{"STATUS":"OPENED"}',
    "amocrm": "success",
    "universal": "OK"
}

# --- МАРШРУТЫ FLASK ---

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/shutdown', methods=['POST'])
def shutdown():
    """Маршрут для остановки сервера по кнопке из веб-интерфейса"""
    print("🛑 Получена команда на остановку сервера из веб-интерфейса...")
    
    # Создаем функцию, которая корректно всё завершит
    def kill_all():
        global tray_icon
        # 1. Вежливо просим иконку в трее закрыться (чтобы она исчезла и отпустила Windows)
        if tray_icon:
            tray_icon.stop()
        # 2. Даем системе полсекунды на очистку ресурсов
        time.sleep(0.5)
        # 3. Жестко завершаем процесс
        os._exit(0)

    # Запускаем эту функцию через 1 секунду (чтобы браузер успел получить ответ)
    threading.Timer(1.0, kill_all).start()
    
    return jsonify({"status": "shutting_down"}), 200

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'POST':
        data = request.args.to_dict() if request.args else (request.get_json(silent=True) or request.data.decode('utf-8'))
    else:
        data = request.args.to_dict()

    token_status = "⚪ Не указан"
    if isinstance(data, dict) and 'token' in data:
        if str(data['token']).strip() == str(settings['expected_token']).strip():
            token_status = "✅ Токен совпал"
        else:
            token_status = f"❌ Токен НЕ совпал (ожидается: '{settings['expected_token']}')"

    log_entry = {
        "time": datetime.now().strftime("%H:%M:%S"),
        "method": request.method,
        "ip": request.remote_addr,
        "data": beautify_data(data),
        "user_agent": request.headers.get('User-Agent', 'Неизвестно'),
        "token_check": token_status,
        "full_url": request.url
    }
    logs.insert(0, log_entry)
    if len(logs) > MAX_LOGS: logs.pop()

    mode = settings["response_mode"]
    if mode == "error_500": return "Internal Server Error", 500
    elif mode == "error_301": return "", 301, {"Location": "http://example.com"}
    elif mode == "timeout":
        time.sleep(35)
        return "OK", 200
    else:
        response_text = settings["custom_text"] if settings["preset"] == "custom_text" else PRESETS.get(settings["preset"], "OK")
        return response_text, 200

@app.route('/get_logs')
def get_logs(): return jsonify(logs)

@app.route('/clear_logs', methods=['POST'])
def clear_logs():
    global logs
    logs = []
    return jsonify({"status": "success"})

@app.route('/export_logs')
def export_logs():
    if not logs: return "Нет данных для экспорта", 404
    lines = ["=" * 80, "ЖУРНАЛ ЗАПРОСОВ ЭНТ WEBHOOK TESTER", f"Экспортировано: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", "=" * 80, ""]
    for i, log in enumerate(logs, 1):
        lines.append(f"[{i}] {log['time']} | {log['method']} | IP: {log['ip']}")
        if isinstance(log['data'], list):
            for item in log['data']: lines.append(f"    {item['k']}: {item['v']}")
        else: lines.append(f"    Данные: {log['data']}")
        lines.append(f"    User-Agent: {log['user_agent']}")
        lines.append("-" * 80)
    content = "\n".join(lines)
    return Response(content, mimetype='text/plain', headers={'Content-Disposition': f'attachment;filename=ent_webhook_logs_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt'})

@app.route('/get_settings')
def get_settings():
    return jsonify({**settings, "actual_running_port": actual_running_port, "needs_restart": settings.get('port') != actual_running_port})

@app.route('/set_settings', methods=['POST'])
def set_settings():
    global settings
    data = request.json
    old_port = settings.get('port')
    new_port = data.get('port')
    settings.update(data)
    save_config()
    if new_port and old_port != new_port: print(f"⚠️ Порт изменен с {old_port} на {new_port}. Перезапустите сервер!")
    return jsonify({"status": "success"})

# ====================================================================
# === СИСТЕМНЫЙ ТРЕЙ (НОВАЯ ЧАСТЬ) ===
# ====================================================================

def open_browser_action(icon, item):
    """Действие для меню 'Открыть интерфейс'."""
    webbrowser.open(f"http://127.0.0.1:{actual_running_port}")

def restart_program(icon, item):
    """Действие для меню 'Перезапустить'. Запускает новый процесс и закрывает старый."""
    icon.stop() # Закрываем иконку в трее
    
    # 1. Даём системе 1 секунду, чтобы старый процесс освободил файлы
    time.sleep(1)
    
    # 2. Запускаем новый, независимый экземпляр программы
    subprocess.Popen([sys.executable] + sys.argv)
    
    # 3. Даём системе 0.5 секунды на переключение
    time.sleep(0.5)
    
    # 4. Жёстко завершаем текущий процесс, чтобы он освободил временную папку _MEI...
    os._exit(0)

def quit_program(icon, item):
    """Действие для меню 'Выход'. Останавливает всё."""
    icon.stop() # Закрываем иконку
    time.sleep(1) # Даём Windows секунду освободить файлы
    os._exit(0) # Принудительно завершаем все потоки

def run_tray():
    """Создает и запускает иконку в трее."""
    try:
        image = Image.open(resource_path('static/logo.png'))
    except Exception:
        image = Image.new('RGBA', (64, 64), (108, 79, 159, 255))

    # УБРАЛИ КНОПКУ ПЕРЕЗАПУСКА, ОСТАВИЛИ ТОЛЬКО ОТКРЫТЬ И ВЫХОД
    menu = pystray.Menu(
        pystray.MenuItem("🌐 Открыть веб-интерфейс", open_browser_action, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("❌ Выход", quit_program)
    )

    # Создаем саму иконку
    icon = pystray.Icon("ent_webhook_tester", image, "ENT Webhook Tester", menu)
    
    # === НОВЫЙ КОД ===
    # Сохраняем иконку в нашу глобальную "коробку", чтобы иметь к ней доступ
    global tray_icon
    tray_icon = icon
    # === КОНЕЦ НОВОГО КОДА ===
    
    # Запускаем её (эта строка блокирует поток дальше)
    icon.run()

# ====================================================================
# === ТОЧКА ВХОДА ===
# ====================================================================

if __name__ == '__main__':
    print(f"🚀 Сервер запускается на порту: {actual_running_port}")
    
    # 1. Запускаем Flask в фоновом потоке
    def start_flask():
        try:
            # Убрали allow_unsafe_werkzeug=True, так как он вызывает ошибку в твоей версии Flask
            app.run(host='0.0.0.0', port=actual_running_port, debug=False)
        except OSError as e:
            print(f"❌ ОШИБКА: Не удалось запустить сервер. Возможно, порт {actual_running_port} занят другой программой!")
            print(f"Текст ошибки: {e}")
            
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()
    
    # 2. Автоматически открываем браузер, если это .exe
    if getattr(sys, 'frozen', False):
        print("📦 Запуск в режиме .exe. Ждем инициализации сервера...")
        time.sleep(3) # Увеличили задержку с 1.5 до 3 секунд для надежности
        webbrowser.open(f"http://127.0.0.1:{actual_running_port}")
    else:
        print(f"💻 Режим разработчика. Откройте браузер вручную: http://127.0.0.1:{actual_running_port}")
        
    # 3. Запускаем системный трей
    run_tray()