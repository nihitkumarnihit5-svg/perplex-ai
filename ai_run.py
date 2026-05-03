from flask import Flask, request, jsonify, session, redirect, url_for
from authlib.integrations.flask_client import OAuth
from werkzeug.middleware.proxy_fix import ProxyFix
import sqlite3, time, requests, json, os, base64, re
from datetime import datetime

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
# Railway ke liye secret key robust honi chahiye
app.secret_key = os.environ.get("SECRET_KEY", "nihit_ultra_stable_v6")

# ================= DATABASE SETUP =================
def init_db():
    try:
        conn = sqlite3.connect("perplex_ai.db", check_same_thread=False)
        conn.execute("CREATE TABLE IF NOT EXISTS chats(id TEXT, user TEXT, title TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS messages(chat_id TEXT, role TEXT, content TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS user_memory(user TEXT PRIMARY KEY, memory_data TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS usage(user TEXT, date TEXT, msg_count INTEGER, img_count INTEGER, PRIMARY KEY(user, date))")
        conn.commit()
        return conn
    except Exception as e:
        print(f"DB Error: {e}")
        return None

db = init_db()

# ================= GOOGLE AUTH =================
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={"scope": "email profile"}
)

# ================= LIMIT CHECKER =================
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
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY")

def get_ai_response(msg, chat_id, user_email, img_base64=None):
    try:
        # History fetch
        history_rows = db.execute("SELECT role, content FROM messages WHERE chat_id=? ORDER BY rowid DESC LIMIT 6", (chat_id,)).fetchall()
        chat_history = [{"role": h[0], "content": h[1]} for h in reversed(history_rows)]

        system_prompt = "You are Perplex AI by Nihit kr. CODING RULE: Wrap code in triple backticks. Keep chat and code separate."
        
        user_content = [{"type": "text", "text": msg}]
        if img_base64:
            user_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"}})

        payload = {
            "model": "google/gemini-2.0-flash-001",
            "messages": [{"role": "system", "content": system_prompt}] + chat_history + [{"role": "user", "content": user_content}]
        }

        r = requests.post("https://openrouter.ai/api/v1/chat/completions", 
                         headers={"Authorization": f"Bearer {OPENROUTER_KEY}"}, json=payload, timeout=30)
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e: 
        print(f"AI Error: {e}")
        return "Bhai, AI ne jawab nahi diya. Check API Key."

# ================= ROUTES =================

@app.route("/")
def index():
    if "user" in session: return redirect("/chat")
    return '<body style="background:#000;color:#fff;display:flex;justify-content:center;align-items:center;height:100vh;font-family:sans-serif;"><div><h1>PERPLEX AI</h1><a href="/login" style="color:#000;background:#fff;padding:12px 25px;text-decoration:none;border-radius:30px;font-weight:bold;">Login with Google</a></div></body>'

@app.route("/login")
def login():
    return google.authorize_redirect(url_for('callback', _external=True, _scheme='https'))

@app.route("/callback")
def callback():
    try:
        token = google.authorize_access_token()
        resp = google.get("https://www.googleapis.com/oauth2/v2/userinfo")
        info = resp.json()
        session["user"] = info["email"]
        return redirect("/chat")
    except Exception as e:
        return f"Login Failed: {e}"

@app.route("/chat")
def chat_page():
    if "user" not in session: return redirect("/")
    return UI_HTML

@app.route("/send", methods=["POST"])
def send():
    user = session.get("user")
    if not user: return jsonify({"reply": "Login first!"})
    
    msg = request.form.get("msg")
    img = request.form.get("image")
    cid = request.form.get("chat")

    can_send, count = check_limit(user, bool(img))
    if not can_send: return jsonify({"reply": "Limit Exceeded (50/day)"})

    if not cid or cid == "null" or cid == "undefined":
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
    if "user" not in session: return jsonify([])
    rows = db.execute("SELECT id, title FROM chats WHERE user=? ORDER BY id DESC", (session['user'],)).fetchall()
    return jsonify(rows)

# ================= UI =================
UI_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Perplex AI Pro</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        :root { --bg: #0a0a0a; --panel: #141414; --blue: #2563eb; --border: #222; }
        body { margin:0; background:var(--bg); color:#eee; font-family: 'Inter', sans-serif; display:flex; height:100vh; overflow:hidden; }
        .sidebar { width:260px; background:var(--panel); border-right:1px solid var(--border); display:flex; flex-direction:column; padding:20px; }
        .main { flex:1; display:flex; position:relative; }
        .chat-area { flex:1; display:flex; flex-direction:column; }
        #box { flex:1; overflow-y:auto; padding:30px 15%; display:flex; flex-direction:column; gap:20px; }
        .msg { padding:14px 18px; border-radius:18px; max-width:80%; line-height:1.6; font-size:15px; }
        .user { align-self:flex-end; background:var(--blue); color:white; border-radius:18px 18px 0 18px; }
        .assistant { align-self:flex-start; background:var(--panel); border:1px solid var(--border); border-radius:18px 18px 18px 0; }
        .canvas { width:50%; background:#000; border-left:1px solid var(--border); display:none; flex-direction:column; }
        .input-wrap { padding:20px 15%; }
        .input-box { background:var(--panel); border:1px solid var(--border); border-radius:15px; padding:12px; display:flex; align-items:center; gap:12px; }
        input[type="text"] { flex:1; background:transparent; border:none; color:white; outline:none; font-size:16px; }
        .plus-btn { color:#888; cursor:pointer; font-size:24px; }
        .run-btn { background:#22c55e; color:white; border:none; padding:6px 12px; border-radius:6px; cursor:pointer; }
        .close-canvas { color:#ff4b4b; cursor:pointer; font-weight:bold; padding:5px; }
    </style>
</head>
<body>
    <div class="sidebar">
        <h2 style="margin:0 0 20px 0; color:var(--blue);">PERPLEX AI</h2>
        <button onclick="location.reload()" style="padding:10px; border:none; border-radius:8px; background:var(--border); color:white; cursor:pointer;">+ New Chat</button>
        <input type="text" id="search" placeholder="Search..." oninput="searchChats()" style="margin-top:15px; background:transparent; border:1px solid var(--border); padding:8px; color:white; border-radius:6px;">
        <div id="list" style="margin-top:20px; flex:1; overflow-y:auto;"></div>
    </div>

    <div class="main">
        <div class="chat-area">
            <div id="box"></div>
            <div class="input-wrap">
                <div class="input-box">
                    <span class="plus-btn" onclick="toggleCanvas()">🎨</span>
                    <input type="text" id="userInput" placeholder="Ask me anything..." onkeypress="if(event.key=='Enter')send()">
                    <button id="sendBtn" onclick="send()" style="background:var(--blue); color:white; border:none; padding:8px 16px; border-radius:8px; cursor:pointer;">Send</button>
                </div>
            </div>
        </div>

        <div class="canvas" id="canvasArea">
            <div style="padding:10px; background:#111; display:flex; justify-content:space-between; border-bottom:1px solid var(--border);">
                <b>Canvas</b>
                <div>
                    <button class="run-btn" onclick="runCode()">Run</button>
                    <span class="close-canvas" onclick="toggleCanvas()">✕</span>
                </div>
            </div>
            <textarea id="codeEditor" style="flex:1; background:#000; color:#4ade80; padding:15px; border:none; font-family:monospace; resize:none; outline:none;"></textarea>
            <iframe id="preview" style="height:40%; background:white; border:none;"></iframe>
        </div>
    </div>

    <script>
        let currentCid = null;
        let abortCtrl = null;

        async function send() {
            const input = document.getElementById("userInput");
            const btn = document.getElementById("sendBtn");
            const val = input.value.trim();
            if(!val) return;

            if(btn.innerText === "Stop") {
                abortCtrl.abort();
                btn.innerText = "Send";
                return;
            }

            const box = document.getElementById("box");
            box.innerHTML += `<div class="msg user">${val}</div>`;
            input.value = "";
            btn.innerText = "Stop";
            box.scrollTop = box.scrollHeight;

            abortCtrl = new AbortController();
            const fd = new FormData();
            fd.append("msg", val);
            fd.append("chat", currentCid);

            try {
                const r = await fetch("/send", {method:"POST", body:fd, signal: abortCtrl.signal});
                const d = await r.json();
                currentCid = d.chat_id;

                let reply = d.reply;
                const codeMatch = reply.match(/```(?:html|css|js)?\s*([\s\S]*?)```/);
                
                if(codeMatch) {
                    document.getElementById("canvasArea").style.display = "flex";
                    document.getElementById("codeEditor").value = codeMatch[1].trim();
                    reply = reply.replace(/```[\s\S]*?```/g, "*(Code sent to Canvas)*");
                }

                box.innerHTML += `<div class="msg assistant">${reply}</div>`;
                btn.innerText = "Send";
                box.scrollTop = box.scrollHeight;
                loadHistory();
            } catch(e) { btn.innerText = "Send"; }
        }

        function toggleCanvas() {
            const c = document.getElementById("canvasArea");
            c.style.display = c.style.display === "flex" ? "none" : "flex";
        }

        function runCode() {
            const code = document.getElementById("codeEditor").value;
            const frame = document.getElementById("preview").contentWindow.document;
            frame.open(); frame.write(code); frame.close();
        }

        function loadHistory() {
            fetch("/chats").then(r=>r.json()).then(data => {
                const l = document.getElementById("list"); l.innerHTML = "";
                data.forEach(c => {
                    l.innerHTML += `<div onclick="openChat('${c[0]}')" style="padding:8px; cursor:pointer; font-size:14px; border-bottom:1px solid #222;">${c[1]}</div>`;
                });
            });
        }
        
        loadHistory();
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    # Railway ke liye host '0.0.0.0' zaroori hai
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
