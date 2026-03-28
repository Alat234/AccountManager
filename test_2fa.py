import pyotp
import time
import sys

# Твій ключ зі скріншота MEXC
secret_key = "64RUMQIHG6TRFPCB"

# Створюємо генератор кодів
totp = pyotp.TOTP(secret_key)

print("=== ТЕСТУВАННЯ GOOGLE AUTHENTICATOR ===")
print(f"Секретний ключ: {secret_key}")
print("Відкрий Google Authenticator на телефоні і порівняй цифри!\n")

try:
    while True:
        # Отримуємо поточний 6-значний код
        current_code = totp.now()

        # Рахуємо, скільки секунд залишилося до зміни коду (цикл 30 секунд)
        time_remaining = 30 - (int(time.time()) % 30)

        # Виводимо в консоль так, щоб рядок оновлювався на місці
        sys.stdout.write(f"\rПоточний код: [ {current_code} ]  (Оновиться через {time_remaining:02d} сек)   ")
        sys.stdout.flush()

        time.sleep(1)

except KeyboardInterrupt:
    print("\n\nТестування завершено.")