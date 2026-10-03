# 🤖 Telegram BSB & AI Suhbat Boti

O'zbekiston ta'lim tizimi uchun **BSB (Baho baholash / Nazorat ishi / Summativ baholash)** topshiriqlarini rasm yoki matn ko'rinishida 100% aniq va to'liq yechib beruvchi hamda eng ilg'or **Google Gemini 3.8 Flash** modeli asosida ishlovchi aqlli Telegram bot.

## ✨ Imkoniyatlari

- 📝 **BSB ishlash:**
  - BSB, CHSB va nazorat ishi savollarini rasm yoki matn ko'rinishida qabul qiladi.
  - Har bir topshiriqni qadamma-qadam, formulalar va to'liq yechimlari bilan 100% aniq ishlab beradi.
  - Hatto hujjat/fayl shaklida yuborilgan rasmlarni ham tahlil qiladi.
- 🤖 **AI bilan suhbat:**
  - Dasturlash, matematika, fizika, insholar, tarjimalar, ijodiy g'oyalar va boshqa barcha sohalar bo'yicha erkin muloqot.
  - Suhbat kontekstini eslab qolish (xotira tizimi).
  - Yangi mavzuni boshlash uchun `🔄 Yangi suhbat` tugmasi.
- 🛡 **Hech qanday xatolik bermaslik (Fallback & Anti-Crash):**
  - Gemini modellari o'rtasida avtomatik zaxira (`gemini-3.8-flash` ➡️ `gemini-3.7-flash` ➡️ `gemini-3.5-flash`).
  - Telegram xabar uzunligi cheklovlarini (4096 belgi) aqlli bo'lib yuborish.
  - Markdown formatlash xatoliklariga qarshi avtomatik toza matn zaxirasi.

## 🚀 O'rnatish va Ishga tushirish

1. **Repozitoriyani yuklab oling:**
   ```bash
   git clone https://github.com/sanjarbekabdinabiyev4-jpg/bot.git
   cd bot
   ```

2. **Kutubxonalarni o'rnating:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Konfiguratsiyani sozlang:**
   `.env.example` faylidan `.env` nusxa oling va tokenlarni kiriting:
   ```env
   BOT_TOKEN=sizning_bot_tokeningiz
   AI_API_KEY=sizning_gemini_api_keyingiz
   PORT=8080
   ```

4. **Botni ishga tushiring:**
   ```bash
   python main.py
   ```
