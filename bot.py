import os
import random
import requests
import json
from google import genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# 1. क्रेडेंशियल्स (Railway Environment Variables से या यहाँ सीधे डालें)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "YOUR_GEMINI_KEY")
GITHUB_JSON_URL = "https://raw.githubusercontent.com/YOUR_USERNAME/YOUR_REPO/main/facts.json"

# Gemini क्लाइंट
ai_client = genai.Client(api_key=GEMINI_API_KEY)

# यूजर की प्रोग्रेस ट्रैक करने के लिए लोकल मेमोरी
# (Railway जब तक रीस्टार्ट नहीं होगा, यह याद रखेगा कि कौन से फैक्ट्स आप पढ़ चुके हैं)
USER_SEEN_FACTS = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start कमांड दबाने पर"""
    user_id = str(update.message.from_user.id)
    # यूजर का नया सेशन शुरू करना
    USER_SEEN_FACTS[user_id] = []
    
    await update.message.reply_text(
        "👋 राम राम भाई! आपका स्मार्ट फैक्ट-टू-क्विज बोट तैयार है।\n\n"
        "⏱️ हर बार आपको 20 एकदम नए और अलग तरीके से बने सवाल मिलेंगे।\n"
        "शुरू करने के लिए `/test` कमांड दबाएं।"
    )

async def generate_live_quiz(facts_list):
    """20 फैक्ट्स से Gemini द्वारा लाइव 20 MCQs तैयार करना"""
    prompt = f"""
    तुम्हें नीचे दिए गए तथ्यों (Facts) का उपयोग करके 20 बेहतरीन परीक्षा-उपयोगी (Exam-Oriented) बहुविकल्पीय प्रश्न (MCQs) तैयार करने हैं।
    प्रत्येक फैक्ट से एक प्रश्न बनाना है।
    
    सख्त नियम:
    1. उच्चारण शुद्ध रखने के लिए हिंदी अक्षर 'ड़' की जगह हमेशा 'ड' का प्रयोग करें (जैसे 'बड़ा' की जगह 'बडा', 'पकड़' की जगह 'पकड')।
    2. आउटपुट केवल और केवल एक वैध JSON Array होना चाहिए, जिसमें कोई अतिरिक्त टेक्स्ट या ```json ``` ब्लॉक न हो।
    
    JSON का फॉर्मेट:
    [
      {{
        "question_text": "प्रश्न यहाँ...",
        "options": ["A) विकल्प 1", "B) विकल्प 2", "C) विकल्प 3", "D) विकल्प 4"],
        "correct_option": "A"
      }}
    ]

    तथ्य (Facts) यहाँ हैं:
    {json.dumps(facts_list, ensure_ascii=False)}
    """
    
    response = ai_client.models.generate_content(
        model='gemini-1.5-flash',
        contents=prompt,
    )
    
    return json.loads(response.text.strip())

async def start_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/test कमांड - 20 नए सवाल लाइव लेकर आना"""
    user_id = str(update.message.from_user.id)
    message = update.message
    
    await message.reply_text("🔄 GitHub से फैक्ट्स लोड करके AI से नए सवाल बनवा रहा हूँ, कृपया 10-15 सेकंड रुकें...")

    try:
        # 1. GitHub से JSON फाइल डाउनलोड करना
        res = requests.get(GITHUB_JSON_URL)
        all_facts = res.json()
        
        # 2. वो फैक्ट्स निकालना जो यूजर ने पहले नहीं देखे हैं
        seen_list = USER_SEEN_FACTS.get(user_id, [])
        unseen_facts = [f for f in all_facts if f not in seen_list]
        
        # अगर सारे फैक्ट्स खत्म हो गए हैं तो रीसेट कर दें
        if len(unseen_facts) < 20:
            unseen_facts = all_facts
            seen_list = []
            await message.reply_text("🔄 आपने सारे फैक्ट्स पढ़ लिए हैं! प्रोग्रेस रीसेट हो रही है, अब दोबारा नए सिरे से सवाल आएंगे।")

        # 3. रैंडम 20 फैक्ट्स चुनना
        selected_facts = random.sample(unseen_facts, min(20, len(unseen_facts)))
        
        # यूजर की सीन लिस्ट में इन्हें जोड़ना ताकि अगली बार ये न आएं
        seen_list.extend(selected_facts)
        USER_SEEN_FACTS[user_id] = seen_list

        # 4. AI से लाइव सवाल बनवाना
        quiz_data = await generate_live_quiz(selected_facts)
        
        # टेस्ट का डेटा कॉन्टेक्स्ट में सेव करना ताकि एक-एक करके सवाल दिखा सकें
        context.user_data['quiz_questions'] = quiz_data
        context.user_data['current_index'] = 0
        context.user_data['score'] = 0
        
        await send_next_question(message, context)

    except Exception as e:
        await message.reply_text(f"❌ गड़बड़ हो गई भाई! कृपया चेक करें कि GitHub URL सही है या नहीं। Error: {str(e)[:100]}")

async def send_next_question(message, context: ContextTypes.DEFAULT_TYPE):
    """अगला सवाल दिखाने के लिए"""
    questions = context.user_data.get('quiz_questions', [])
    index = context.user_data.get('current_index', 0)
    
    if index >= len(questions):
        score = context.user_data.get('score', 0)
        await message.reply_text(f"🏁 **टेस्ट समाप्त भाई!**\n\n📊 आपका स्कोर: {score}/{len(questions)}\n\nअगले 20 नए सवालों के लिए फिर से `/test` दबाएं।")
        return

    q = questions[index]
    text = f"📝 **प्रश्न {index + 1}:** {q['question_text']}\n\n"
    
    # बटन्स तैयार करना
    keyboard = []
    # हर रो में 2 बटन (A और B एक लाइन में, C और D दूसरी लाइन में)
    keyboard.append([
        InlineKeyboardButton("A", callback_data=f"ans_A_{q['correct_option']}"),
        InlineKeyboardButton("B", callback_data=f"ans_B_{q['correct_option']}")
    ])
    keyboard.append([
        InlineKeyboardButton("C", callback_data=f"ans_C_{q['correct_option']}"),
        InlineKeyboardButton("D", callback_data=f"ans_D_{q['correct_option']}")
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # अगर यह पहला सवाल है तो नया मैसेज भेजें, नहीं तो पुराने को एडिट करें
    if hasattr(message, 'edit_text'):
        await message.edit_text(text, reply_markup=reply_markup)
    else:
        await message.reply_text(text, reply_markup=reply_markup)

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """जब यूजर A, B, C, D बटन पर क्लिक करे"""
    query = update.callback_query
    await query.answer()
    
    # डेटा निकालना (जैसे: ans_A_B -> यूजर ने A चुना, सही B था)
    data = query.data.split('_')
    user_choice = data[1]
    correct_choice = data[2]
    
    index = context.user_data.get('current_index', 0)
    questions = context.user_data.get('quiz_questions', [])
    q = questions[index]
    
    # सही/गलत का फैसला
    if user_choice == correct_choice:
        context.user_data['score'] += 1
        result_text = f"✅ **सही उत्तर भाई!**\n\n"
    else:
        result_text = f"❌ **गलत जवाब!**\n\n👉 सही उत्तर **{correct_choice}** था।\n\n"
        
    # पुराना सवाल दिखाना और उसके नीचे रिजल्ट जोड़ना
    full_text = f"📝 **प्रश्न {index + 1}:** {q['question_text']}\n"
    for opt in q['options']:
        full_text += f"\n{opt}"
    
    full_text += f"\n\n--- \n{result_text}"
    
    # अगला सवाल देखने के लिए एक 'Next ➡️' बटन देना
    keyboard = [[InlineKeyboardButton("अगला प्रश्न ➡️", callback_data="next_question")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text=full_text, reply_markup=reply_markup)

async def next_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """जब यूजर 'Next' बटन दबाए"""
    query = update.callback_query
    await query.answer()
    
    context.user_data['current_index'] += 1
    await send_next_question(query.message, context)

def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("test", start_test))
    application.add_handler(CallbackQueryHandler(next_callback, pattern="^next_question$"))
    application.add_handler(CallbackQueryHandler(handle_answer, pattern="^ans_"))

    print("🤖 बोट Railway पर लाइव होने के लिए तैयार है...")
    application.run_polling()

if __name__ == "__main__":
    main()