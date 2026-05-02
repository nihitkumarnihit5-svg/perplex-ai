from flask import Flask, request, jsonify, session, redirect, url_for
from authlib.integrations.flask_client import OAuth
import sqlite3, time, requests, json, os, base64
from datetime import timedelta, datetime

app = Flask(__name__)
app.secret_key = "nihit_x_fire_ultra_pro_max_key"
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

# ================= DATABASE (Only Memory & History) =================
def init_db():
    conn = sqlite3.connect("perplex_ai.db", check_same_thread=False)
    conn.execute("CREATE TABLE IF NOT EXISTS chats(id TEXT, user TEXT, title TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS messages(chat_id TEXT, role TEXT, content TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS user_memory(user TEXT PRIMARY KEY, memory_data TEXT)")
    conn.commit()
    return conn

db = init_db()

# ================= GOOGLE AUTH =================
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={"scope": "email profile"}
)

# ================= AI ENGINE (With Memory Only) =================
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")

def get_ai_response(msg, chat_id, user_email, base64_image=None):
    try:
        # Memory Retrieval
        mem_res = db.execute("SELECT memory_data FROM user_memory WHERE user=?", (user_email,)).fetchone()
        user_context = mem_res[0] if mem_res else "No previous memory."

        # History for Context
        history_rows = db.execute("SELECT role, content FROM messages WHERE chat_id=? ORDER BY rowid DESC LIMIT 6", (chat_id,)).fetchall()
        chat_history = [{"role": h[0], "content": h[1]} for h in reversed(history_rows)]

        # Updated System Prompt: Removed 'Sense', Kept 'Memory'
        system_prompt = f"""
        Identity: You are 'Perplex AI', created by Nihit kr.
        Tone: Friendly Hinglish (Hindi + English). Talk like a brother/friend.
        Memory: {user_context}
        
        Instructions:
        - Just be a helpful AI friend.
        - Use the memory provided above to personalize your talk.
        - If the user tells you to remember something, save it in your head.
        - No 'Powered by Gemini' mentions.
        """

        headers = {"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"}
        
        user_content = [{"type": "text", "text": msg}]
        if base64_image:
            user_content.append({"type": "image_url", "image_url": {"url": base64_image}})

        payload = {
            "model": "google/gemini-2.0-flash-001",
            "messages": [{"role": "system", "content": system_prompt}] + chat_history + [{"role": "user", "content": user_content}],
            "temperature": 0.8
        }

        r = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=60)
        reply = r.json()["choices"][0]["message"]["content"]

        # Update Memory if needed
        if any(x in msg.lower() for x in ["yaad rakhna", "remember", "save this"]):
            new_mem = f"{user_context} | {msg}"
            db.execute("INSERT OR REPLACE INTO user_memory VALUES(?,?)", (user_email, new_mem[-1500:]))
            db.commit()

        return reply
    except Exception as e: return f"Bhai, load nahi ho raha: {str(e)}"

# ================= ROUTES (Flask) =================

@app.route("/")
def index():
    if "user" in session: return redirect("/chat")
    return '''<body style="background:#0e0e0e; color:white; display:flex; flex-direction:column; align-items:center; justify-content:center; height:100vh; font-family:sans-serif;">
              <h1>PERPLEX AI</h1>
              <a href="/login" style="margin-top:20px; padding:15px 30px; background:#fff; color:#000; text-decoration:none; border-radius:50px; font-weight:bold;">Login with Google</a>
              </body>'''

@app.route("/login")
def login(): return google.authorize_redirect(url_for('callback', _external=True))

@app.route("/callback")
def callback():
    token = google.authorize_access_token()
    user_info = google.get("https://www.googleapis.com/oauth2/v2/userinfo").json()
    session["user"] = user_info["email"]
    return redirect("/chat")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

@app.route("/chat")
def chat_ui():
    if "user" not in session: return redirect("/")
    return UI_HTML

@app.route("/chats")
def get_chats():
    user = session.get("user")
    rows = db.execute("SELECT id, title FROM chats WHERE user=? ORDER BY id DESC", (user,)).fetchall()
    return jsonify(rows)

@app.route("/msgs")
def get_msgs():
    cid = request.args.get("c")
    rows = db.execute("SELECT role, content FROM messages WHERE chat_id=?", (cid,)).fetchall()
    return jsonify(rows)

@app.route("/send", methods=["POST"])
def send_msg():
    user = session.get("user")
    if not user: return jsonify({"error": "Login kar bhai"}), 401
    
    cid = request.form.get("chat")
    msg = request.form.get("msg")
    img_data = request.form.get("image")

    if not cid or cid == "null":
        cid = str(int(time.time()*1000))
        db.execute("INSERT INTO chats VALUES(?,?,?)", (cid, user, msg[:35]))
    
    db.execute("INSERT INTO messages VALUES(?,?,?)", (cid, "user", msg))
    reply = get_ai_response(msg, cid, user, img_data)
    db.execute("INSERT INTO messages VALUES(?,?,?)", (cid, "assistant", reply))
    db.commit()
    
    return jsonify({"reply": reply, "chat_id": cid})

@app.route("/delete_history", methods=["POST"])
def delete_history():
    user = session.get("user")
    db.execute("DELETE FROM messages WHERE chat_id IN (SELECT id FROM chats WHERE user=?)", (user,))
    db.execute("DELETE FROM chats WHERE user=?", (user,))
    db.commit()
    return jsonify({"success": True})

# ================= UI HTML (Dark Mode) =================
UI_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>PERPLEX AI</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        :root { --bg: #0e0e0e; --side: #171717; --accent: #3b82f6; --text: #ececec; }
        body { margin: 0; background: var(--bg); color: var(--text); font-family: sans-serif; display: flex; height: 100vh; overflow: hidden; }
        .sidebar { width: 260px; background: var(--side); display: flex; flex-direction: column; padding: 15px; border-right: 1px solid #262626; }
        .logo { font-size: 22px; font-weight: bold; color: var(--accent); margin-bottom: 20px; }
        .new-chat { background: #2f2f2f; padding: 12px; border-radius: 10px; text-align: center; cursor: pointer; border: 1px solid #333; }
        .chat-list { flex: 1; margin-top: 20px; overflow-y: auto; }
        .chat-item { padding: 10px; border-radius: 8px; cursor: pointer; font-size: 14px; margin-bottom: 5px; color: #aaa; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .chat-item:hover, .chat-item.active { background: #212121; color: white; }
        .main { flex: 1; display: flex; flex-direction: column; }
        .chat-container { flex: 1; overflow-y: auto; padding: 30px 15%; display: flex; flex-direction: column; gap: 20px; }
        .msg { max-width: 85%; padding: 12px 18px; border-radius: 15px; line-height: 1.5; }
        .user { align-self: flex-end; background: #2f2f2f; }
        .assistant { align-self: flex-start; }
        .input-area { padding: 20px 15%; }
        .input-box { background: #212121; border-radius: 30px; padding: 10px 20px; display: flex; align-items: center; border: 1px solid #333; }
        input { flex: 1; background: transparent; border: none; color: white; outline: none; font-size: 16px; }
        button { background: none; border: none; color: var(--accent); cursor: pointer; font-size: 20px; }
    </style>
</head>
<body>
    <div class="sidebar">
        <div class="logo">PERPLEX AI</div>
        <div class="new-chat" onclick="location.reload()">+ New Chat</div>
        <div class="chat-list" id="chatList"></div>
        <div style="margin-top:auto;">
            <div class="chat-item" onclick="clearAll()">🗑️ Clear History</div>
            <a href="/logout" style="text-decoration:none;"><div class="chat-item">Logout</div></a>
        </div>
    </div>
    <div class="main">
        <div class="chat-container" id="chatBox"></div>
        <div class="input-area">
            <div class="input-box">
                <input type="text" id="userInput" placeholder="Kuch pucho bhai..." onkeypress="if(event.key=='Enter')send()">
                <button onclick="send()">➤</button>
            </div>
        </div>
    </div>
    <script>
        let cid = null;
        function send() {
            const input = document.getElementById("userInput");
            const val = input.value; if(!val) return;
            const box = document.getElementById("chatBox");
            box.innerHTML += `<div class="msg user">${val}</div>`;
            input.value = "";
            const fd = new FormData(); fd.append("chat", cid); fd.append("msg", val);
            fetch("/send", {method:"POST", body:fd}).then(r=>r.json()).then(data => {
                cid = data.chat_id;
                box.innerHTML += `<div class="msg assistant">${data.reply}</div>`;
                box.scrollTop = box.scrollHeight;
                loadChats();
            });
        }
        function loadChats() {
            fetch("/chats").then(r=>r.json()).then(data => {
                const list = document.getElementById("chatList");
                list.innerHTML = "";
                data.forEach(c => {
                    list.innerHTML += `<div class="chat-item" onclick="openChat('${c[0]}')">${c[1]}</div>`;
                });
            });
        }
        function openChat(id) {
            cid = id;
            fetch("/msgs?c="+id).then(r=>r.json()).then(msgs => {
                const box = document.getElementById("chatBox");
                box.innerHTML = "";
                msgs.forEach(m => { box.innerHTML += `<div class="msg ${m[0]}">${m[1]}</div>`; });
                box.scrollTop = box.scrollHeight;
            });
        }
        function clearAll() { if(confirm("Delete history?")) fetch("/delete_history", {method:"POST"}).then(()=>location.reload()); }
        loadChats();
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
