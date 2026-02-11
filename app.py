from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import json
import os
import re
app = Flask(__name__)
CORS(app)  # يسمح لملف HTML بالاتصال بالسيرفر المحلي

# مفاتيح API (تأكد أنها فعالة)
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "null")
SCRAPER_API_KEY = os.environ.get("SCRAPER_API_KEY", "null")
@app.route('/api/recommend', methods=['POST'])
def recommend_shaver():
    try:
        data = request.json
        print("🔹 Received Request:", data)
        
        hair_type = data.get('hairType')
        problem = data.get('problem')
        budget = data.get('budget')

        # ---------------------------------------------------------
        # 1. استدعاء Groq AI (تم تحديث البرومبت هنا)
        # ---------------------------------------------------------
        print("🧠 Consulting AI...")
        
        system_prompt = """You are an expert barber and dermatologist. Your task is to recommend the specific type and series of electric shaver based on the user's constraints.

INPUTS: Hair Type, Skin Problem, Budget.

STRATEGY & RULES (Follow Strictly):

1. **PROBLEM SOLVING:**
   - **Ingrown Hairs:** NEVER recommend "Lift-and-cut" or traditional Rotary. MUST recommend Foil Shavers (Braun/Panasonic) or Hybrid (Philips OneBlade).
   - **Sensitive Skin:** Recommend Foil Shavers with cooling or sensor tech (Braun Series, Panasonic Arc).
   - **Curly/Coily Hair:** Rotary shavers (Philips) are good for capturing the hair, BUT if they have ingrowns, switch to OneBlade.
   - **Thick/Coarse Hair:** Requires High-Torque motor. Disqualify weak entry-level models.
   - **Bald Head:** Skull Shaver or specialized head shavers.

2. **BUDGET FILTERING (Crucial):**
   - **Economy ($20-$60):** Look for Philips Norelco 2000/3000, Braun Series 3, Remington, or OneBlade QP2520.
   - **Mid-Range ($60-$150):** Look for Braun Series 5 or 7, Philips Norelco 5000 or 7000, Panasonic Arc5 (older gen).
   - **Premium ($150+):** Look for Braun Series 9 Pro, Philips Norelco 9000 Prestige, Panasonic Arc6.
3. **CONFLICT HANDLING (Economy + Thick Hair):**
   - IF User selects "Economy" AND "Thick/Coarse Hair":
     - This is a difficult combination. DO NOT recommend expensive Mid-range models ($60+).
     - RECOMMEND: "Philips Norelco Shaver 2300" (Best cheap rotary) OR "Remington F5-5800" (Best cheap foil for power).
     - MANDATORY WARNING: You MUST state in 'reasoning': 'Note: Budget models may struggle with very thick hair; multiple passes might be required.
4. **EDGE CASES & WARNINGS (Handle with care):**
   - **Scenario A (Sensitive + Thick + Economy):** Recommendation is RISKY. Recommend "Panasonic Arc3" or "Braun Series 3" but append warning: "Warning: For thick hair on sensitive skin, budget models may cause pulling. Use shaving cream/gel is highly recommended."
   - **Scenario B (Ingrown Hairs + "Closest Shave"):** Prioritize curing the ingrowns over close shaving. Recommend "Philips OneBlade" or "Braun Series 5". State: "Designed to cut at skin level, not below, to prevent ingrowns."
   - **Scenario C (Long Hair/Infrequent Shaving):** If user shaves infrequently, DO NOT recommend standard Foil/Rotary. MUST recommend "Philips OneBlade" or "Philips Norelco Multigroom".     
OUTPUT FORMAT:
Return ONLY a JSON object with these fields:
{
  "reasoning": "Direct explanation linking the specific Series recommended to the hair type and budget.",
  "amazon_search_query": "Specific search string including the Brand + Series Name + Key Feature (e.g., 'Braun Series 3 electric shaver foil')"
}
"""

        groq_payload = {
            "model": "llama-3.3-70b-versatile", 
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": f"Hair Type: {hair_type}\nProblem: {problem}\nBudget: {budget}"
                }
            ],
            "temperature": 0.7,
            "response_format": {"type": "json_object"}
        }
        
        groq_headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }

        groq_res = requests.post("https://api.groq.com/openai/v1/chat/completions", json=groq_payload, headers=groq_headers)
        
        if groq_res.status_code != 200:
            print(f"❌ Groq API Error: {groq_res.text}")
            return jsonify({"success": False, "error": f"Groq Error: {groq_res.status_code}"}), 500

        ai_content = groq_res.json()['choices'][0]['message']['content']
        print(f"🔹 AI Raw Response: {ai_content}")

        # محاولة استخراج JSON بشكل آمن
        try:
            ai_json = json.loads(ai_content)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', ai_content, re.DOTALL)
            if match:
                ai_json = json.loads(match.group())
            else:
                raise ValueError("Could not parse AI response as JSON")

        search_query = ai_json.get('amazon_search_query', 'electric shaver')
        reasoning = ai_json.get('reasoning', 'Selected based on your hair type.')
        print(f"✅ AI Suggested Query: {search_query}")

        # ---------------------------------------------------------
        # 2. استدعاء ScraperAPI (البحث في أمازون)
        # ---------------------------------------------------------
        print(f"🔎 Searching Amazon for: {search_query}...")
        
        scraper_payload = {
            "api_key": SCRAPER_API_KEY,
            "url": f"https://www.amazon.com/s?k={search_query.replace(' ', '+')}",
            "autoparse": "true",
            "country_code": "us"
        }

        amazon_res = requests.get("http://api.scraperapi.com", params=scraper_payload)
        
        if amazon_res.status_code != 200:
            print(f"❌ ScraperAPI Error: {amazon_res.text}")
            return jsonify({"success": False, "error": f"ScraperAPI Error: {amazon_res.status_code}"}), 500

        amazon_data = amazon_res.json()

       # التحقق هل وجدنا نتائج أم لا
        if 'results' in amazon_data and len(amazon_data['results']) > 0:
            product = amazon_data['results'][0]
            print(f"✅ Product Found: {product.get('name')[:30]}...")
            
            # --- بداية التعديل: بناء رابط تتبع نظيف واحترافي ---
            raw_url = product.get('url', '')
            # استخدام التعبير النمطي (Regex) لاستخراج كود المنتج (ASIN) المكون من 10 حروف
            asin_match = re.search(r'/([A-Z0-9]{10})(?:[/?]|$)', raw_url)
            
            if asin_match:
                asin = asin_match.group(1)
                # بناء الرابط القياسي الرسمي لأمازون
                clean_tracking_url = f"https://www.amazon.com/dp/{asin}?tag=oceansidehair-20"
            else:
                # في حالة نادرة لم نجد ASIN، نستخدم الطريقة القديمة كاحتياط
                separator = '&' if '?' in raw_url else '?'
                clean_tracking_url = f"{raw_url}{separator}tag=oceansidehair-20"
            # --- نهاية التعديل ---

            return jsonify({
                "success": True,
                "reasoning": reasoning,
                "product": {
                    "title": product.get('name', 'Recommended Shaver'),
                    "image": product.get('image', ''),
                    "price": product.get('price', 'N/A'),
                    "url": clean_tracking_url,  # الرابط الجديد النظيف
                    "rating": product.get('stars', 4.5),
                    "reviews": product.get('total_reviews', 0)
                }
            })
        else:
            print("⚠️ Amazon returned no results.")
            return jsonify({
                "success": False, 
                "reasoning": f"No direct Amazon results for '{search_query}', but here is the advice: {reasoning}"
            })

    except Exception as e:
        print(f"🔥 Critical Error: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    print("🚀 Server running on http://127.0.0.1:5000")
    app.run(host='0.0.0.0', port=5000, debug=True)
