# run_all.py
import subprocess
import sys
import os
import time

# Environment variable larni o'rnating (agar kerak bo'lsa)
# os.environ['BOT_TOKEN'] = "admin_token"
# os.environ['BOT_TOKEN_USER'] = "user_token"
# os.environ['BOT_TOKEN_KURYER'] = "kuryer_token"
# os.environ['API_BASE_URL'] = "https://shukrona-backend-production.up.railway.app"

processes = []

# Har bir bot uchun alohida process
files = [
    ("Admin Bot", "main.py"),
    ("User Bot", "user_bot.py"),
    ("Kuryer Bot", "Kuryer.py")
]

for name, file in files:
    if os.path.exists(file):
        print(f"🚀 {name} ishga tushmoqda: {file}")
        try:
            p = subprocess.Popen([sys.executable, file])
            processes.append((name, p))
            time.sleep(2)  # Har bir bot uchun 2 soniya kutish
        except Exception as e:
            print(f"❌ {name} ishga tushirishda xatolik: {e}")
    else:
        print(f"❌ Fayl topilmadi: {file}")

print("\n✅ Barcha botlar ishga tushirildi")
print("❌ To'xtatish uchun Ctrl+C bosing\n")

try:
    # Hammasi o'chib ketmasligi uchun kutib turadi
    for name, p in processes:
        p.wait()
except KeyboardInterrupt:
    print("\n🛑 Botlar to'xtatilmoqda...")
    for name, p in processes:
        p.terminate()
    print("👋 Botlar to'xtatildi")