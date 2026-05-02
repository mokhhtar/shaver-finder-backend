from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import requests
import json
import os
import re

app = Flask(__name__)

# 1. إعدادات قاعدة البيانات (SQLite)
# بدلاً من هذا الكود القديم:
# app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///shaver_recommendations.db'

# استخدم هذا الكود الجديد:
# نقوم بجلب رابط قاعدة البيانات السحابية من إعدادات السيرفر
# وإذا لم يجده (مثل حالة التجربة على حاسوبك)، يستخدم SQLite كاحتياط
DB_URL = os.environ.get("DATABASE_URL", "sqlite:///shaver_recommendations.db")

# بعض الاستضافات تعطي الرابط بصيغة postgres:// بدلاً من postgresql:// وهذا يسبب خطأ في Flask
# هذا السطر يحل المشكلة تلقائياً
if DB_URL.startswith("postgres://"):
    DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = DB_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# حماية الـ API ليقبل الطلبات من نطاقك فقط (قم بتغييره إلى دومين موقعك لاحقاً)
CORS(app, resources={r"/api/*": {"origins": "*"}}) 

# مفاتيح API 
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "null")
SCRAPER_API_KEY = os.environ.get("SCRAPER_API_KEY", "null")

# 2. إنشاء نموذج (جدول) قاعدة البيانات
class RecommendationLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    hair_type = db.Column(db.String(50), nullable=False)
    problem = db.Column(db.String(50), nullable=False)
    budget = db.Column(db.String(50), nullable=False)
    ai_query = db.Column(db.String(255))
    recommended_product = db.Column(db.String(255))
    amazon_url = db.Column(db.String(500))
    ai_reasoning = db.Column(db.Text)  # <--- هذا هو العمود الجديد
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# إنشاء ملف قاعدة البيانات والجداول إذا لم تكن موجودة
with app.app_context():
    db.create_all()

@app.route('/api/recommend', methods=['POST'])
def recommend_shaver():
    try:
        data = request.json
        print("🔹 Received Request:", data)
        
        hair_type = data.get('hairType')
        problem = data.get('problem')
        budget = data.get('budget')

        # التحقق من وجود البيانات الأساسية
        if not hair_type or not problem or not budget:
            return jsonify({"success": False, "error": "Missing required fields"}), 400

        # ---------------------------------------------------------
        # 1. استدعاء Groq AI 
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
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Hair Type: {hair_type}\nProblem: {problem}\nBudget: {budget}"}
            ],
            "temperature": 0.7,
            "response_format": {"type": "json_object"}
        }
        
        groq_headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }

        # أضفنا timeout=10 لمنع تعليق السيرفر
        groq_res = requests.post("https://api.groq.com/openai/v1/chat/completions", json=groq_payload, headers=groq_headers, timeout=10)
        
        if groq_res.status_code != 200:
            print(f"❌ Groq API Error: {groq_res.text}")
            return jsonify({"success": False, "error": f"Groq Error: {groq_res.status_code}"}), 500

        ai_content = groq_res.json()['choices'][0]['message']['content']
        
        try:
            ai_json = json.loads(ai_content)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', ai_content, re.DOTALL)
            if match:
                ai_json = json.loads(match.group())
            else:
                raise ValueError("Could not parse AI response as JSON")

        search_query = ai_json.get('amazon_search_query', 'electric shaver')
        reasoning = ai_json.get('reasoning', 'Selected based on your constraints.')

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

        # أضفنا timeout=15 لأن عملية الـ Scraping قد تأخذ وقتاً
        amazon_res = requests.get("http://api.scraperapi.com", params=scraper_payload, timeout=15)
        
        if amazon_res.status_code != 200:
            print(f"❌ ScraperAPI Error: {amazon_res.text}")
            return jsonify({"success": False, "error": f"ScraperAPI Error: {amazon_res.status_code}"}), 500

        amazon_data = amazon_res.json()

        if 'results' in amazon_data and len(amazon_data['results']) > 0:
            product = amazon_data['results'][0]
            product_title = product.get('name', 'Recommended Shaver')
            
            raw_url = product.get('url', '')
            asin_match = re.search(r'/([A-Z0-9]{10})(?:[/?]|$)', raw_url)
            
            if asin_match:
                asin = asin_match.group(1)
                clean_tracking_url = f"https://www.amazon.com/dp/{asin}?tag=oceansidehair-20"
            else:
                separator = '&' if '?' in raw_url else '?'
                clean_tracking_url = f"{raw_url}{separator}tag=oceansidehair-20"

            # ---------------------------------------------------------
            # 3. حفظ البيانات في قاعدة البيانات
            # ---------------------------------------------------------
            try:
                new_log = RecommendationLog(
                    hair_type=hair_type,
                    problem=problem,
                    budget=budget,
                    ai_query=search_query,
                    recommended_product=product_title,
                    amazon_url=clean_tracking_url,
                    ai_reasoning=reasoning  # <--- إضافة النص هنا
                )
                db.session.add(new_log)
                db.session.commit()
                print("✅ Data successfully saved to DB.")
            except Exception as db_error:
                print(f"⚠️ Database Error: {db_error}")

            return jsonify({
                "success": True,
                "reasoning": reasoning,
                "product": {
                    "title": product_title,
                    "image": product.get('image', ''),
                    "price": product.get('price', 'N/A'),
                    "url": clean_tracking_url,
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

@app.route('/', methods=['GET'])
def health_check():
    return "Server is awake!", 200

# 4. مسار جديد لرؤية الإحصائيات (يمكنك حذفه لاحقاً أو حمايته بكلمة مرور)
@app.route('/api/stats', methods=['GET'])
def get_stats():
    logs = RecommendationLog.query.order_by(RecommendationLog.timestamp.desc()).limit(20).all()
    results = []
    for log in logs:
        results.append({
            "id": log.id,
            "hair_type": log.hair_type,
            "problem": log.problem,
            "budget": log.budget,
            "recommended": log.recommended_product,
            "time": log.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        })
    return jsonify({"total_searches": len(results), "recent_logs": results})

if __name__ == '__main__':
    print("🚀 Server running on http://127.0.0.1:5000")
    app.run(host='0.0.0.0', port=5000, debug=True)