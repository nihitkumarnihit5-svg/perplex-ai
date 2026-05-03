from flask import Flask, request, jsonify, session, redirect, url_for
from authlib.integrations.flask_client import OAuth
from werkzeug.middleware.proxy_fix import ProxyFix
import sqlite3, time, requests, json, os, base64, re
from datetime import timedelta, datetime

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.secret_key = os.getenv("SECRET_KEY", "perplex_ultra_v5_nihit")

# ================= DATABASE SETUP =================
def init_db():
    conn = sqlite3.connect("perplex_ai.db", check_same_thread=False)
    conn.execute("CREATE TABLE IF NOT EXISTS chats(id TEXT, user TEXT, title TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS messages(chat_id TEXT, role TEXT, content TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS user_memory(user TEXT PRIMARY KEY, memory_data TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS usage(user TEXT, date TEXT, msg_count INTEGER, img_count INTEGER, PRIMARY KEY(user, date))")
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

def check_limit(user, is_img=False):
    today = datetime.now().strftime('%Y-%m-%d')
    res = db.execute("SELECT msg_count, img_count FROM usage WHERE user=? AND date=?", (user, today)).fetchone()
    if not res:
        db.execute("INSERT INTO usage VALUES(?,?,0,0)", (user, today))
        db.commit()
        return True, 0
    msg_c, img_c = res
    if is_img and img_c >= 5: return False, img_c
    if not is_img and msg_c >= 50: return False, msg_c
    return True, (img_c if is_img else msg_c)

# ================= AI LOGIC =================
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")

def get_ai_response(msg, chat_id, user_email, img_base64=None):
    try:
        mem_res = db.execute("SELECT memory_data FROM user_memory WHERE user=?", (user_email,)).fetchone()
        saved_memory = mem_res[0] if mem_res else "Nihit is the creator."

        history_rows = db.execute("SELECT role, content FROM messages WHERE chat_id=? ORDER BY rowid DESC LIMIT 6", (chat_id,)).fetchall()
        chat_history = [{"role": h[0], "content": h[1]} for h in reversed(history_rows)]

        system_prompt = f"""You are Perplex AI by Nihit kr. 
        Memory: {saved_memory}.
        CODING RULE: When providing code, ALWAYS wrap it in triple backticks like ```html ... ```. 
        Put all explanations BEFORE or AFTER the code blocks."""
        
        user_content = [{"type": "text", "text": msg}]
        if img_base64:
            user_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"}})

        payload = {
            "model": "google/gemini-2.0-flash-001",
            "messages": [{"role": "system", "content": system_prompt}] + chat_history + [{"role": "user", "content": user_content}]
        }

        r = requests.post("https://openrouter.ai/api/v1/chat/completions", 
                         headers={"Authorization": f"Bearer {OPENROUTER_KEY}"}, json=payload)
        return r.json()["choices"][0]["message"]["content"]
    except: return "Bhai, error aa gaya server mein."

# ================= ROUTES =================

@app.route("/")
def index():
    if "user" in session: return redirect("/chat")
    return '<body style="background:#000;color:#fff;display:flex;justify-content:center;align-items:center;height:100vh;font-family:sans-serif;"><div style="text-align:center;"><h1>PERPLEX AI</h1><a href="/login" style="color:#000;background:#fff;padding:12px 25px;text-decoration:none;border-radius:30px;font-weight:bold;">Get Started</a></div></body>'

@app.route("/login")
def login():
    return google.authorize_redirect(url_for('callback', _external=True, _scheme='https'))

@app.route("/callback")
def callback():
    google.authorize_access_token()
    info = google.get("https://www.googleapis.com/oauth2/v2/userinfo").json()
    session["user"] = info["email"]
    return redirect("/chat")

@app.route("/chat")
def chat_page():
    if "user" not in session: return redirect("/")
    return UI_HTML

@app.route("/send", methods=["POST"])
def send():
    user = session.get("user")
    msg, img, cid = request.form.get("msg"), request.form.get("image"), request.form.get("chat")
    can_send, count = check_limit(user, bool(img))
    if not can_send: return jsonify({"reply": "Limit over bhai! 50 msg/day."})
    if not cid or cid == "null":
        cid = str(int(time.time()))
        db.execute("INSERT INTO chats VALUES(?,?,?)", (cid, user, msg[:25]))
    
    reply = get_ai_response(msg, cid, user, img)
    db.execute("INSERT INTO messages VALUES(?,?,?)", (cid, "user", msg))
    db.execute("INSERT INTO messages VALUES(?,?,?)", (cid, "assistant", reply))
    
    today = datetime.now().strftime('%Y-%m-%d')
    col = "img_count" if img else "msg_count"
    db.execute(f"UPDATE usage SET {col} = {col} + 1 WHERE user=? AND date=?", (user, today))
    db.commit()
    return jsonify({"reply": reply, "chat_id": cid, "count": count + 1})

@app.route("/chats")
def get_chats():
    rows = db.execute("SELECT id, title FROM chats WHERE user=? ORDER BY id DESC", (session['user'],)).fetchall()
    return jsonify(rows)

@app.route("/delete_all", methods=["POST"])
def delete_all():
    db.execute("DELETE FROM chats WHERE user=?", (session['user'],))
    db.commit()
    return jsonify({"status": "ok"})

# ================= UI CODE =================
UI_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Perplex AI Pro</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        :root { --bg: #0d0d0d; --panel: #161616; --blue: #2563eb; --border: #262626; }
        body { margin:0; background:var(--bg); color:#ececec; font-family: 'Segoe UI', sans-serif; display:flex; height:100vh; overflow:hidden; }
        
        .sidebar { width:260px; background:var(--panel); border-right:1px solid var(--border); display:flex; flex-direction:column; padding:15px; }
        .main { flex:1; display:flex; flex-direction:row; position:relative; }
        
        .chat-container { flex:1; display:flex; flex-direction:column; background:var(--bg); }
        #box { flex:1; overflow-y:auto; padding:20px 15%; display:flex; flex-direction:column; gap:15px; }
        
        /* Message Styling */
        .msg { padding:14px; border-radius:15px; max-width:85%; line-height:1.5; font-size:15px; white-space: pre-wrap; }
        .user { align-self:flex-end; background:var(--blue); color:white; border-radius:15px 15px 0 15px; }
        .assistant { align-self:flex-start; background:var(--panel); border:1px solid var(--border); border-radius:15px 15px 15px 0; }
        
        /* Canvas Styling (Split Screen) */
        .canvas { width:50%; background:#000; border-left:1px solid var(--border); display:none; flex-direction:column; animation: slideIn 0.3s; }
        @keyframes slideIn { from { transform: translateX(100%); } to { transform: translateX(0); } }
        
        .canvas-header { padding:10px 20px; background:#1a1a1a; display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid var(--border); }
        #code-editor { flex:1; background:#000; color:#4ade80; padding:20px; border:none; font-family: 'Consolas', monospace; font-size:14px; resize:none; outline:none; }
        
        /* Input Area */
        .input-wrap { padding:20px 15%; background:var(--bg); }
        .input-box { background:var(--panel); border:1px solid var(--border); border-radius:15px; padding:10px 15px; display:flex; align-items:center; gap:10px; }
        input[type="text"] { flex:1; background:transparent; border:none; color:white; outline:none; font-size:16px; }
        
        /* Buttons */
        .btn-plus { color:#888; font-size:22px; cursor:pointer; position:relative; }
        .plus-menu { position:absolute; bottom:50px; left:0; background:var(--panel); border:1px solid var(--border); border-radius:10px; display:none; flex-direction:column; width:150px; z-index:100; }
        .plus-menu div { padding:10px; font-size:14px; cursor:pointer; }
        .plus-menu div:hover { background:var(--border); }
        
        .btn-close { color:#ff4d4d; cursor:pointer; font-weight:bold; font-size:18px; }
        .run-btn { background:#22c55e; border:none; color:white; padding:5px 15px; border-radius:5px; cursor:pointer; }
    </style>
</head>
<body>

    <div class="sidebar">
        <h2 style="color:var(--blue)">PERPLEX</h2>
        <button onclick="location.reload()" style="padding:10px; border-radius:10px; border:none; background:var(--border); color:white; cursor:pointer;">+ New Chat</button>
        <input type="text" placeholder="Search chats..." id="search" oninput="doSearch()" style="margin:10px 0; background:transparent; border:1px solid var(--border); padding:8px; color:white; border-radius:5px;">
        <div id="list" style="flex:1; overflow-y:auto;"></div>
        <div onclick="clearAll()" style="color:#666; font-size:12px; cursor:pointer; text-align:center;">Clear All History</div>
    </div>

    <div class="main">
        <div class="chat-container">
            <div id="box"></div>
            <div class="input-wrap">
                <div class="input-box">
                    <div class="btn-plus" onclick="togglePlus()">+
                        <div class="plus-menu" id="plusMenu">
                            <div onclick="document.getElementById('fileIn').click()">🖼️ Upload Media</div>
                            <div onclick="toggleCanvas()">🎨 Open Canvas</div>
                        </div>
                    </div>
                    <input type="file" id="fileIn" hidden onchange="handleFile(this)">
                    <input type="text" id="userInput" placeholder="Message Perplex..." onkeypress="if(event.key=='Enter')sendMsg()">
                    <button id="sendBtn" onclick="sendMsg()" style="background:var(--blue); border:none; color:white; padding:8px 18px; border-radius:10px; cursor:pointer;">Send</button>
                </div>
            </div>
        </div>

        <div class="canvas" id="canvasArea">
            <div class="canvas-header">
                <span>Code Preview</span>
                <div style="display:flex; gap:10px;">
                    <button class="run-btn" onclick="runCode()">Run</button>
                    <span class="btn-close" onclick="toggleCanvas()">✕</span>
                </div>
            </div>
            <textarea id="code-editor" spellcheck="false"></textarea>
            <iframe id="preview-frame" style="height:40%; background:white; border:none;"></iframe>
        </div>
    </div>

    <script>
        let currentCid = null;
        let abortCtrl = null;

        async function sendMsg() {
            const input = document.getElementById("userInput");
            const text = input.value.trim();
            const btn = document.getElementById("sendBtn");
            if(!text) return;

            if(btn.innerText === "Stop") {
                abortCtrl.abort();
                btn.innerText = "Send";
                return;
            }

            const box = document.getElementById("box");
            box.innerHTML += `<div class="msg user">${text}</div>`;
            input.value = "";
            btn.innerText = "Stop";
            box.scrollTop = box.scrollHeight;

            abortCtrl = new AbortController();
            const fd = new FormData();
            fd.append("msg", text);
            fd.append("chat", currentCid);

            try {
                const r = await fetch("/send", {method:"POST", body:fd, signal: abortCtrl.signal});
                const d = await r.json();
                currentCid = d.chat_id;
                
                // Logic: Extract code from reply
                let replyText = d.reply;
                const codeMatch = replyText.match(/```(?:html|css|javascript|python)?\s*([\s\S]*?)```/);
                
                if(codeMatch) {
                    // Chat window mein sirf text dikhao (code hata kar)
                    const cleanText = replyText.replace(/```[\s\S]*?```/g, "*(Code sent to Canvas)*");
                    box.innerHTML += `<div class="msg assistant">${cleanText}</div>`;
                    
                    // Canvas mein code dalo aur open karo
                    document.getElementById("canvasArea").style.display = "flex";
                    document.getElementById("code-editor").value = codeMatch[1].trim();
                } else {
                    box.innerHTML += `<div class="msg assistant">${replyText}</div>`;
                }

                btn.innerText = "Send";
                box.scrollTop = box.scrollHeight;
                loadHistory();
            } catch(e) { btn.innerText = "Send"; }
        }

        function toggleCanvas() {
            const c = document.getElementById("canvasArea");
            c.style.display = c.style.display === "flex" ? "none" : "flex";
        }

        function togglePlus() {
            const m = document.getElementById("plusMenu");
            m.style.display = m.style.display === "flex" ? "none" : "flex";
        }

        function runCode() {
            const code = document.getElementById("code-editor").value;
            const frame = document.getElementById("preview-frame").contentWindow.document;
            frame.open(); frame.write(code); frame.close();
        }

        function loadHistory() {
            fetch("/chats").then(r=>r.json()).then(data => {
                const l = document.getElementById("list"); l.innerHTML = "";
                data.forEach(c => {
                    l.innerHTML += `<div onclick="openChat('${c[0]}')" style="padding:10px; cursor:pointer; font-size:14px;">${c[1]}</div>`;
                });
            });
        }

        function clearAll() { if(confirm("Delete all?")) fetch("/delete_all", {method:"POST"}).then(()=>location.reload()); }
        
        loadHistory();
    </script>
</body>
</html>
