from flask import Flask, request, jsonify
import os
import openai
import psycopg2  
from urllib.parse import urlparse
import requests
import json
import logging

app = Flask(__name__)

# 從環境變數獲取 OpenAI API 金鑰
openai_api_key = os.environ.get("OPENAI_API_KEY")
if not openai_api_key:
    print("OPENAI_API_KEY 環境變數未設定！")
    exit()
client = openai.OpenAI(api_key=openai_api_key)

# 從環境變數獲取資料庫連線資訊 
DATABASE_URL = os.environ.get("DATABASE_URL")

def connect_to_database():
    """Connect to PostgreSQL database using DATABASE_URL"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except psycopg2.Error as e:
        print(f"PostgreSQL database connection error: {e}")
        return None

def get_final_url(url):
    """Get the final redirect URL"""
    try:
        response = requests.get(url, allow_redirects=True, timeout=5)
        return response.url
    except requests.RequestException as e:
        return url


def check_company_in_database(conn, company_name, company_url):
    """Check if company exists in PostgreSQL database"""
    parsed_url = urlparse(company_url)
    scheme_netloc = f"{parsed_url.scheme}://{parsed_url.netloc}"
    query = "SELECT * FROM Company WHERE name = %s AND (URL = %s OR URL = %s || '/')"
    try:
        with conn.cursor() as cursor:
            cursor.execute(query, (company_name, company_url, company_url))
            result = cursor.fetchall()
            return bool(result)
    except psycopg2.Error as e:
        print(f"PostgreSQL database query error: {e}")
        return False

def extract_company_info_with_gpt(text):
    """Extract company name and URL using OpenAI GPT"""
    prompt = "你可以幫我從下列一段文字中，擷取出公司名稱與公司網址的資料嗎：\n(也可以是政府單位或部門)"
    prompt2 = "回答格式只需回答\n公司名稱：\n公司網址：\n即可。\n"
    prompt4 = "如果有兩個以上的網址，幫我找一個簡訊中要使用者點擊的連結即可。\n同理，如果有兩個以上的公司，選出簡訊中要使用者點擊的網址相關公司即可。\n"
    prompt5 = "如果公司名稱是某某融控股股份有限公司、某某金證券時、或明顯是金融業，回覆成某某銀行即可。同理，如果某某公司是電信類的公司時，回覆成某某電信即可。同理，如果某某公司是找工作的公司時，回覆成某某人力銀行即可。"
    TOTAL_prompt = prompt + text + prompt2 + prompt4 + prompt5
    print(f"GPT Prompt: {TOTAL_prompt}")
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "你是一個幫助用戶的助手。"},
            {"role": "user", "content": TOTAL_prompt}
        ]
    )

    # Extract response lines
    for i in range(len(response.choices)):
        lines = response.choices[i].message.content.split('\n')
        if len(lines) == 2:
            return parse_company_info(lines)
    print("Could not parse GPT response")
    return None, None

def parse_company_info(lines):
    """Parse company name and URL from response lines"""
    try:
        # Handle both full-width and half-width colons
        if '：' in lines[0]:
            company_name = lines[0].split('：')[1].strip()
            company_url = lines[1].split('：')[1].strip()
        else:
            company_name = lines[0].split(':')[1].strip()
            company_url = lines[1].split(':')[1].strip()

        # Normalize URL format  
        company_url = normalize_url(company_url)
        
        return company_name, company_url
    except (IndexError, ValueError) as e:
        print(f"Error parsing company info: {e}")
        return None, None

def normalize_url(url):
    """Ensure URL has proper scheme"""
    parsed_url = urlparse(url)
    if not parsed_url.scheme:
        url = f"https://{url}"
    return url

@app.route('/analyze_sms', methods=['POST'])
def analyze_sms():
    data = request.get_json()
    sms_content = data.get('sms_content')
    if not sms_content:
        return jsonify({'error': 'Missing sms_content'}), 400

    company_name, company_url = extract_company_info_with_gpt(sms_content)
    if not company_name or not company_url:
        return jsonify({'result': 'Failed to extract company information'}), 200

    conn = connect_to_database()
    if conn:
        is_legitimate = check_company_in_database(conn, company_name, company_url)
        conn.close()
        if is_legitimate:
            result_message = f"該公司與網站存在於資料庫中，並確認此網站為合法正常網址可安心前往:))"
        else:
            result_message = f"該公司與網站「沒有」在資料庫中，資料庫中找不到相關資料，請小心詐騙訊息！！！"
        return jsonify({'result': result_message}), 200
    else:
        return jsonify({'error': 'Database connection failed'}), 500

if __name__ == '__main__':
    app.run(debug=True)