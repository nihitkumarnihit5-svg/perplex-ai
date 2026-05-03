from flask import Flask, request, jsonify, session, redirect, url_for, g
from authlib.integrations.flask_client import OAuth
from werkzeug.middleware.proxy_fix import ProxyFix
import sqlite3, time, requests, json, os, datetime
from datetime import timedelta

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

app.secret_key = os.environ.get("SECRET_KEY", "perplex_ultra_pro_v10")
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

DATABASE = 'perplex_ai.db'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.execute("CREATE TABLE IF NOT EXISTS chats(id TEXT, user TEXT, title TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS messages(chat_id TEXT, role TEXT, content TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS usage(user TEXT, date TEXT, count INTEGER, PRIMARY KEY(user, date))")
        db.commit()
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None: db.close()

# --- Auth Setup ---
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={"scope": "email profile"}
)

# --- AI Engine ---
def get_ai_response(msg, chat_id, user_email):
    try:
        db = get_db()
        # Fetching context
        history = db.execute("SELECT role, content FROM messages WHERE chat_id=? ORDER BY rowid DESC LIMIT 5", (chat_id,)).fetchall()
        msgs = [{"role": h[0], "content": h[1]} for h in reversed(history)]
        
        system_msg = {"role": "system", "content": "You are Perplex AI, a helpful assistant. Use markdown for formatting."}
        msgs.insert(0, system_msg)
        msgs.append({"role": "user", "content": msg})

        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {os.environ.get('OPENROUTER_KEY')}"},
            data=json.dumps({
                "model": "google/gemini-2.0-flash-001",
                "messages": msgs
            }),
            timeout=30
        )
        
        res_json = response.json()
        if "choices" in res_json:
            return res_json["choices"][0]["message"]["content"]
        else:
            print(f"API Error: {res_json}") # Log this in Railway logs
            return "Bhai, API key check karo ya model load nahi ho raha."
    except Exception as e:
        print(f"Server Error: {str(e)}")
        return "Network issues, please try again."

# --- Routes ---
@app.route("/")
def index():
    return redirect("/chat") if "user" in session else UI_LOGIN

@app.route("/login")
def login():
    return google.authorize_redirect(url_for('callback', _external=True))

@app.route("/callback")
def callback():
    token = google.authorize_access_token()
    session["user"] = google.get("https://www.googleapis.com/oauth2/v2/userinfo").json()["email"]
    return redirect("/chat")

@app.route("/chat")
def chat_ui():
    if "user" not in session: return redirect("/")
    return UI_MAIN

@app.route("/send", methods=["POST"])
def handle_msg():
    user = session.get("user")
    data = request.json
    msg, cid = data.get("msg"), data.get("chat_id")
    db = get_db()

    if not cid:
        cid = str(int(time.time()))
        db.execute("INSERT INTO chats VALUES(?,?,?)", (cid, user, msg[:30]))
    
    reply = get_ai_response(msg, cid, user)
    db.execute("INSERT INTO messages VALUES(?,?,?)", (cid, "user", msg))
    db.execute("INSERT INTO messages VALUES(?,?,?)", (cid, "assistant", reply))
    db.commit()
    
    return jsonify({"reply": reply, "chat_id": cid})

@app.route("/history")
def get_history():
    rows = get_db().execute("SELECT id, title FROM chats WHERE user=? ORDER BY id DESC", (session.get('user'),)).fetchall()
    return jsonify([{"id": r[0], "title": r[1]} for r in rows])

# --- Minimalistic Pro UI ---
UI_LOGIN = """<body style="background:#000;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;font-family:sans-serif;">
<div style="text-align:center;"><h1>Perplex AI</h1><a href="/login" style="background:#fff;color:#000;padding:10px 20px;text-decoration:none;border-radius:5px;font-weight:bold;">Sign in with Google</a></div></body>"""

UI_MAIN = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Perplex AI</title>
    <style>
        * { box-sizing: border-box; }
        body { margin: 0; background: #131314; color: #e3e3e3; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; display: flex; height: 100vh; }
        .sidebar { width: 260px; background: #1e1f20; display: flex; flex-direction: column; padding: 15px; border-right: 1px solid #333; }
        .new-chat { background: #333; border: none; color: white; padding: 12px; border-radius: 8px; cursor: pointer; margin-bottom: 20px; font-weight: bold; }
        .history { flex: 1; overflow-y: auto; }
        .history-item { padding: 10px; border-radius: 5px; cursor: pointer; margin-bottom: 5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 14px; }
        .history-item:hover { background: #2d2e2f; }
        .main-chat { flex: 1; display: flex; flex-direction: column; }
        #chat-container { flex: 1; overflow-y: auto; padding: 40px 15% 100px 15%; display: flex; flex-direction: column; gap: 20px; }
        .bubble { max-width: 85%; padding: 12px 16px; border-radius: 15px; line-height: 1.5; font-size: 16px; }
        .user-bubble { align-self: flex-end; background: #2d2e2f; color: #fff; }
        .ai-bubble { align-self: flex-start; background: transparent; border: 1px solid #333; }
        .input-area { position: fixed; bottom: 30px; left: 50%; transform: translateX(-10%); width: 50%; background: #1e1f20; border-radius: 24px; padding: 10px 20px; display: flex; align-items: center; border: 1px solid #444; }
        input { flex: 1; background: transparent; border: none; color: white; outline: none; padding: 10px; font-size: 16px; }
        .send-btn { background: #fff; color: #000; border: none; border-radius: 50%; width: 35px; height: 35px; cursor: pointer; font-weight: bold; }
    </style>
</head>
<body>
    <div class="sidebar">
        <h2 style="margin: 0 0 20px 0; color: #4285f4;">Perplex AI</h2>
        <button class="new-chat" onclick="window.location.reload()">+ New Chat</button>
        <div class="history" id="history-list"></div>
        <div style="margin-top: auto; padding-top: 10px; font-size: 12px; color: #888;">NihitXFire Edition v10</div>
    </div>
    <div class="main-chat">
        <div id="chat-container"></div>
        <div class="input-area">
            <input type="text" id="user-input" placeholder="Ask anything..." onkeypress="if(event.key=='Enter')sendMessage()">
            <button class="send-btn" onclick="sendMessage()">➔</button>
        </div>
    </div>

    <script>
        let currentChatId = null;

        async function sendMessage() {
            const input = document.getElementById('user-input');
            const container = document.getElementById('chat-container');
            if(!input.value.trim()) return;

            const userMsg = input.value;
            input.value = '';
            
            container.innerHTML += `<div class="bubble user-bubble">${userMsg}</div>`;
            container.scrollTop = container.scrollHeight;

            const res = await fetch('/send', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({msg: userMsg, chat_id: currentChatId})
            });
            const data = await res.json();
            currentChatId = data.chat_id;

            container.innerHTML += `<div class="bubble ai-bubble">${data.reply}</div>`;
            container.scrollTop = container.scrollHeight;
            loadHistory();
        }

        async function loadHistory() {
            const res = await fetch('/history');
            const data = await res.json();
            const list = document.getElementById('history-list');
            list.innerHTML = data.map(item => `<div class="history-item"># ${item.title}</div>`).join('');
        }

        loadHistory();
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
