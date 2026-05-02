from flask import Flask, request, jsonify, session, redirect, url_for
from authlib.integrations.flask_client import OAuth
import sqlite3, time, requests, json, os, base64
from datetime import timedelta, datetime

app = Flask(__name__)
app.secret_key = "nihit_x_fire_ultra_pro_max_key"
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

# ================= DATABASE (Memory & History) =================
def init_db():
    conn = sqlite3.connect("perplex_ai.db", check_same_thread=False)
    # Chat records
    conn.execute("CREATE TABLE IF NOT EXISTS chats(id TEXT, user TEXT, title TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS messages(chat_id TEXT, role TEXT, content TEXT)")
    # Memory for personalization
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

# ================= AI ENGINE (With Sense & Memory) =================
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")

def get_ai_response(msg, chat_id, user_email, base64_image=None):
    try:
        # 1. Memory Retrieval
        mem_res = db.execute("SELECT memory_data FROM user_memory WHERE user=?", (user_email,)).fetchone()
        user_context = mem_res[0] if mem_res else "No previous memory."

        # 2. History for Context
        history_rows = db.execute("SELECT role, content FROM messages WHERE chat_id=? ORDER BY rowid DESC LIMIT 6", (chat_id,)).fetchall()
        chat_history = [{"role": h[0], "content": h[1]} for h in reversed(history_rows)]

        # 3. System Prompt (The 'Sense' Logic)
        system_prompt = f"""
        Identity: You are 'Perplex AI', a powerful assistant created by Nihit kr.
        Tone: Friendly, cool, and talks in Hinglish (Hindi + English). Use words like 'bhai', 'theek hai', 'bro'.
        Memory: {user_context}
        
        Capabilities:
        - If the user asks for code, act as a Senior Full-Stack Developer. Provide clean, modular, and well-commented code.
        - If the user says 'yaad rakhna' or 'remember', acknowledge it and focus on that detail.
        - NEVER mention 'Powered by Gemini'.
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

        # 4. Auto-Memory Update
        if any(x in msg.lower() for x in ["yaad rakhna", "remember", "mera naam", "i like"]):
            new_mem = f"{user_context} | {msg}"
            db.execute("INSERT OR REPLACE INTO user_memory VALUES(?,?)", (user_email, new_mem[-1000:])) # Keep last 1000 chars
            db.commit()

        return reply
    except Exception as e: return f"Bhai, server mein kuch locha ho gaya: {str(e)}"

# ================= ROUTES =================

@app.route("/")
def index():
    if "user" in session: return redirect("/chat")
    return '''<body style="background:#0e0e0e; color:white; display:flex; flex-direction:column; align-items:center; justify-content:center; height:100vh; font-family:sans-serif;">
              <h1 style="font-size:40px; letter-spacing:-1px;">PERPLEX AI</h1>
              <p style="color:#888;">Modern Intelligence for Nihit</p>
              <a href="/login" style="margin-top:20px; padding:15px 30px; background:#fff; color:#000; text-decoration:none; border-radius:50px; font-weight:bold;">Get Started</a>
              </body>'''

@app.route("/login")
def login():
    return google.authorize_redirect(url_for('callback', _external=True))

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
    if not user: return jsonify({"error": "Login required"}), 401
    
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

# ================= UI HTML (Advanced Look) =================
UI_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PERPLEX AI</title>
    <style>
        :root { --bg: #0e0e0e; --side: #171717; --item-hover: #212121; --accent: #3b82f6; --text: #ececec; }
        body { margin: 0; background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; display: flex; height: 100vh; overflow: hidden; }
        
        .sidebar { width: 280px; background: var(--side); display: flex; flex-direction: column; padding: 15px; border-right: 1px solid #262626; }
        .logo { font-size: 20px; font-weight: 800; padding: 10px; color: var(--accent); margin-bottom: 20px; }
        .new-chat { background: #2f2f2f; padding: 12px; border-radius: 12px; text-align: center; cursor: pointer; font-weight: 600; transition: 0.2s; border: 1px solid #3d3d3d; }
        .new-chat:hover { background: #3d3d3d; }
        .chat-list { flex: 1; margin-top: 20px; overflow-y: auto; }
        .chat-item { padding: 12px; border-radius: 10px; cursor: pointer; font-size: 14px; margin-bottom: 5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: #b4b4b4; }
        .chat-item:hover, .chat-item.active { background: var(--item-hover); color: white; }
        .footer-menu { border-top: 1px solid #262626; padding-top: 10px; }
        .menu-btn { padding: 12px; border-radius: 10px; cursor: pointer; font-size: 14px; display: flex; align-items: center; gap: 10px; color: #b4b4b4; text-decoration:none;}
        .menu-btn:hover { background: var(--item-hover); color: white; }

        .main { flex: 1; display: flex; flex-direction: column; position: relative; }
        .chat-container { flex: 1; overflow-y: auto; padding: 40px 15%; display: flex; flex-direction: column; gap: 30px; }
        .msg { max-width: 85%; font-size: 16px; line-height: 1.6; animation: fadeIn 0.3s ease; }
        .user { align-self: flex-end; background: #2f2f2f; padding: 12px 20px; border-radius: 20px 20px 0 20px; }
        .assistant { align-self: flex-start; }
        
        .input-area { padding: 20px 15%; background: var(--bg); }
        .input-wrapper { background: #212121; border-radius: 24px; padding: 10px 15px; display: flex; align-items: center; border: 1px solid #333; box-shadow: 0 4px 20px rgba(0,0,0,0.3); }
        input { flex: 1; background: transparent; border: none; color: white; padding: 10px; font-size: 16px; outline: none; }
        .action-btn { background: transparent; border: none; color: #888; cursor: pointer; font-size: 20px; padding: 5px; transition: 0.2s; }
        .action-btn:hover { color: var(--accent); }
        
        .preview-box { display: none; padding: 10px; background: #212121; border-radius: 10px; width: fit-content; margin-bottom: 10px; position: relative; }
        .preview-box img { height: 60px; border-radius: 5px; }
        .close-pre { position: absolute; top: -5px; right: -5px; background: red; color: white; border-radius: 50%; width: 20px; height: 20px; font-size: 12px; cursor: pointer; display: flex; align-items: center; justify-content: center; }

        pre { background: #000; padding: 15px; border-radius: 10px; overflow-x: auto; border: 1px solid #333; }
        code { font-family: 'Courier New', Courier, monospace; color: #61afef; }

        @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
    </style>
</head>
<body>
    <div class="sidebar">
        <div class="logo">PERPLEX AI</div>
        <div class="new-chat" onclick="startNew()">+ New Chat</div>
        <div class="chat-list" id="chatList"></div>
        <div class="footer-menu">
            <div class="menu-btn" onclick="clearAll()">🗑️ Clear All History</div>
            <a href="/logout" class="menu-btn">🚪 Logout</a>
        </div>
    </div>
    <div class="main">
        <div class="chat-container" id="chatBox">
            <div style="text-align:center; margin-top:15vh; color:#555;">
                <h2>Welcome to Perplex AI</h2>
                <p>Coding, Images, and Smart Memory. Kya haal hai bhai?</p>
            </div>
        </div>
        <div class="input-area">
            <div class="preview-box" id="preBox">
                <span class="close-pre" onclick="removeImg()">✕</span>
                <img id="imgView">
            </div>
            <div class="input-wrapper">
                <button class="action-btn" onclick="document.getElementById('fInput').click()">📎</button>
                <input type="text" id="userInput" placeholder="Ask anything..." onkeypress="if(event.key=='Enter')send()">
                <button class="action-btn" onclick="send()" style="color:var(--accent);">➤</button>
            </div>
        </div>
    </div>
    <input type="file" id="fInput" hidden accept="image/*" onchange="handleFile(this)">

    <script>
        let currentChatId = null;
        let selectedImg = null;

        function handleFile(input) {
            const reader = new FileReader();
            reader.onload = (e) => {
                selectedImg = e.target.result;
                document.getElementById('imgView').src = selectedImg;
                document.getElementById('preBox').style.display = 'block';
            };
            reader.readAsDataURL(input.files[0]);
        }

        function removeImg() { selectedImg = null; document.getElementById('preBox').style.display = 'none'; }

        function send() {
            const input = document.getElementById("userInput");
            const val = input.value.trim();
            if(!val && !selectedImg) return;

            const box = document.getElementById("chatBox");
            if(box.querySelector('h2')) box.innerHTML = '';
            
            box.innerHTML += `<div class="msg user">${val}</div>`;
            input.value = "";
            box.scrollTop = box.scrollHeight;

            const fd = new FormData();
            fd.append("chat", currentChatId);
            fd.append("msg", val);
            if(selectedImg) fd.append("image", selectedImg);

            fetch("/send", {method:"POST", body:fd}).then(r=>r.json()).then(data => {
                currentChatId = data.chat_id;
                box.innerHTML += `<div class="msg assistant">${data.reply.replace(/\\n/g, '<br>')}</div>`;
                box.scrollTop = box.scrollHeight;
                removeImg();
                loadChats();
            });
        }

        function loadChats() {
            fetch("/chats").then(r=>r.json()).then(data => {
                const list = document.getElementById("chatList");
                list.innerHTML = "";
                data.forEach(c => {
                    const d = document.createElement("div");
                    d.className = `chat-item ${c[0]==currentChatId?'active':''}`;
                    d.innerText = c[1];
                    d.onclick = () => openChat(c[0]);
                    list.appendChild(d);
                });
            });
        }

        function openChat(id) {
            currentChatId = id;
            fetch("/msgs?c="+id).then(r=>r.json()).then(msgs => {
                const box = document.getElementById("chatBox");
                box.innerHTML = "";
                msgs.forEach(m => {
                    box.innerHTML += `<div class="msg ${m[0]}">${m[1]}</div>`;
                });
                box.scrollTop = box.scrollHeight;
                loadChats();
            });
        }

        function startNew() { currentChatId = null; document.getElementById("chatBox").innerHTML = '<h2>New Conversation</h2>'; }
        
        function clearAll() {
            if(confirm("Saare chats delete karun?")) {
                fetch("/delete_history", {method:"POST"}).then(() => location.reload());
            }
        }

        loadChats();
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
