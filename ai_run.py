from flask import Flask, request, jsonify, session, redirect, url_for
from authlib.integrations.flask_client import OAuth
from werkzeug.middleware.proxy_fix import ProxyFix
import sqlite3, time, requests, json, os, base64, re
from datetime import datetime

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.secret_key = os.environ.get("SECRET_KEY", "perplex_sense_memory_v8")

# ================= DATABASE (Memory + Sense Storage) =================
def init_db():
    conn = sqlite3.connect("perplex_ai.db", check_same_thread=False)
    conn.execute("CREATE TABLE IF NOT EXISTS chats(id TEXT, user TEXT, title TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS messages(chat_id TEXT, role TEXT, content TEXT)")
    # Memory Table: User ki preference save karne ke liye
    conn.execute("CREATE TABLE IF NOT EXISTS user_memory(user TEXT PRIMARY KEY, memory_data TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS usage(user TEXT, date TEXT, msg_count INTEGER, img_count INTEGER, PRIMARY KEY(user, date))")
    conn.commit()
    return conn

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

# ================= SENSE & MEMORY LOGIC =================
def get_user_memory(user_email):
    res = db.execute("SELECT memory_data FROM user_memory WHERE user=?", (user_email,)).fetchone()
    return res[0] if res else "No specific memory yet. Learn about the user naturally."

def update_memory(user_email, new_info):
    db.execute("INSERT OR REPLACE INTO user_memory VALUES(?, ?)", (user_email, new_info))
    db.commit()

# ================= AI ENGINE (With Sense & Memory) =================
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY")

def get_ai_response(msg, chat_id, user_email, img_base64=None):
    try:
        user_mem = get_user_memory(user_email)
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # History fetch
        history_rows = db.execute("SELECT role, content FROM messages WHERE chat_id=? ORDER BY rowid DESC LIMIT 6", (chat_id,)).fetchall()
        chat_history = [{"role": h[0], "content": h[1]} for h in reversed(history_rows)]

        # System Prompt with SENSE and MEMORY
        system_prompt = f"""You are Perplex AI, created by Nihit kr.
        [SENSE]: Current Date/Time: {current_time}. Location: Railway Cloud.
        [MEMORY]: Facts about user: {user_mem}.
        INSTRUCTION: If user shares personal info, remember it. Use Triple Backticks for code. 
        If the user asks 'Who are you?', mention you are Nihit's AI with Memory and Sense."""
        
        user_content = [{"type": "text", "text": msg}]
        if img_base64:
            user_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"}})

        payload = {
            "model": "google/gemini-2.0-flash-001",
            "messages": [{"role": "system", "content": system_prompt}] + chat_history + [{"role": "user", "content": user_content}]
        }
        r = requests.post("https://openrouter.ai/api/v1/chat/completions", headers={"Authorization": f"Bearer {OPENROUTER_KEY}"}, json=payload, timeout=40)
        ai_msg = r.json()["choices"][0]["message"]["content"]
        
        # Memory Update Logic (Simple Keyword check)
        if any(word in msg.lower() for word in ["my name is", "i love", "i am a", "mera naam"]):
            update_memory(user_email, user_mem + " | " + msg)

        return ai_msg
    except: return "Bhai, Sense/Memory engine me error hai."

# ================= ROUTES =================

@app.route("/")
def index():
    if "user" in session: return redirect("/chat")
    return '<body style="background:#000;color:#fff;display:flex;justify-content:center;align-items:center;height:100vh;font-family:sans-serif;"><div><h1>PERPLEX AI</h1><a href="/login" style="color:#000;background:#fff;padding:12px 25px;text-decoration:none;border-radius:30px;font-weight:bold;">Enter</a></div></body>'

@app.route("/login")
def login(): return google.authorize_redirect(url_for('callback', _external=True, _scheme='https'))

@app.route("/callback")
def callback():
    token = google.authorize_access_token()
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
    if not cid or cid == "null":
        cid = str(int(time.time()))
        db.execute("INSERT INTO chats VALUES(?,?,?)", (cid, user, msg[:25]))

    reply = get_ai_response(msg, cid, user, img)
    db.execute("INSERT INTO messages VALUES(?,?,?)", (cid, "user", msg))
    db.execute("INSERT INTO messages VALUES(?,?,?)", (cid, "assistant", reply))
    db.commit()
    return jsonify({"reply": reply, "chat_id": cid})

@app.route("/chats")
def get_chats():
    rows = db.execute("SELECT id, title FROM chats WHERE user=? ORDER BY id DESC", (session['user'],)).fetchall()
    return jsonify(rows)

# ================= UI WITH SENSE/MEMORY INDICATORS =================
UI_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Perplex AI (Sense + Memory)</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        :root { --bg: #0d0d0d; --panel: #161616; --blue: #2563eb; --border: #222; }
        body { margin:0; background:var(--bg); color:#eee; font-family:'Inter', sans-serif; display:flex; height:100vh; overflow:hidden; }
        .sidebar { width:260px; background:var(--panel); border-right:1px solid var(--border); display:flex; flex-direction:column; padding:15px; }
        .main { flex:1; display:flex; position:relative; }
        .chat-area { flex:1; display:flex; flex-direction:column; }
        #box { flex:1; overflow-y:auto; padding:20px 12%; display:flex; flex-direction:column; gap:15px; }
        .msg { padding:14px; border-radius:15px; max-width:85%; font-size:15px; line-height:1.5; }
        .user { align-self:flex-end; background:var(--blue); }
        .assistant { align-self:flex-start; background:var(--panel); border:1px solid var(--border); }
        .input-wrap { padding:20px 12%; }
        .input-box { background:var(--panel); border:1px solid var(--border); border-radius:20px; padding:10px 15px; display:flex; align-items:center; gap:12px; }
        input[type="text"] { flex:1; background:transparent; border:none; color:white; outline:none; font-size:16px; }
        .plus-btn { font-size:24px; cursor:pointer; color:#555; }
        .sense-tag { position:fixed; top:10px; left:275px; font-size:11px; color:#4ade80; background:rgba(74,222,128,0.1); padding:4px 10px; border-radius:10px; }
        .canvas { width:50%; display:none; background:#000; border-left:1px solid var(--border); flex-direction:column; }
    </style>
</head>
<body>
    <div class="sense-tag">● SENSE ACTIVE | MEMORY ENABLED</div>
    <div class="sidebar">
        <h3 style="color:var(--blue);">PERPLEX V8</h3>
        <button onclick="location.reload()" style="padding:10px; border-radius:10px; border:none; background:#222; color:white; cursor:pointer;">+ New Chat</button>
        <div id="list" style="margin-top:20px; flex:1; overflow-y:auto;"></div>
        <div style="font-size:12px; color:#555;">Nihit Kr. Edition</div>
    </div>

    <div class="main">
        <div class="chat-area">
            <div id="box"></div>
            <div class="input-wrap">
                <div class="input-box">
                    <div class="plus-btn" onclick="toggleCanvas()">+</div>
                    <input type="text" id="u-in" placeholder="Ask anything (I remember...)" onkeypress="if(event.key=='Enter')send()">
                    <button id="s-btn" onclick="send()" style="background:var(--blue); color:white; border:none; padding:8px 18px; border-radius:12px; cursor:pointer;">Send</button>
                </div>
            </div>
        </div>
        <div class="canvas" id="canvas">
            <div style="padding:10px; background:#111; display:flex; justify-content:space-between;">
                <span>Code Canvas</span>
                <span onclick="toggleCanvas()" style="cursor:pointer; color:red;">✕</span>
            </div>
            <textarea id="code-ed" style="flex:1; background:#000; color:#0f0; padding:20px; border:none; outline:none; font-family:monospace;"></textarea>
            <iframe id="pre" style="height:40%; background:white; border:none;"></iframe>
            <button onclick="runCode()" style="background:#22c55e; color:white; border:none; padding:10px; cursor:pointer;">Run Code</button>
        </div>
    </div>

    <script>
        let cid = null;
        let ctrl = null;

        async function send() {
            const i = document.getElementById("u-in");
            const b = document.getElementById("s-btn");
            if(!i.value || b.innerText === "Stop") { if(ctrl) ctrl.abort(); b.innerText="Send"; return; }

            const val = i.value;
            const box = document.getElementById("box");
            box.innerHTML += `<div class="msg user">${val}</div>`;
            i.value = ""; b.innerText = "Stop";
            box.scrollTop = box.scrollHeight;

            ctrl = new AbortController();
            const fd = new FormData();
            fd.append("msg", val); fd.append("chat", cid);

            try {
                const r = await fetch("/send", {method:"POST", body:fd, signal: ctrl.signal});
                const d = await r.json();
                cid = d.chat_id;
                
                let reply = d.reply;
                const code = reply.match(/```[\\s\\S]*?```/);
                if(code) {
                    document.getElementById("canvas").style.display = "flex";
                    document.getElementById("code-ed").value = code[0].replace(/```html|```/g, "");
                    reply = reply.replace(/```[\\s\\S]*?```/g, "*(Code in Canvas)*");
                }

                box.innerHTML += `<div class="msg assistant">${reply}</div>`;
                b.innerText = "Send";
                box.scrollTop = box.scrollHeight;
            } catch(e) { b.innerText = "Send"; }
        }

        function toggleCanvas() { 
            const c = document.getElementById("canvas");
            c.style.display = c.style.display === "flex" ? "none" : "flex"; 
        }
        function runCode() {
            const code = document.getElementById("code-ed").value;
            const f = document.getElementById("pre").contentWindow.document;
            f.open(); f.write(code); f.close();
        }
        fetch("/chats").then(r=>r.json()).then(data => {
            const l = document.getElementById("list");
            data.forEach(c => l.innerHTML += `<div style="padding:10px; cursor:pointer; font-size:14px; border-bottom:1px solid #222;">${c[1]}</div>`);
        });
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
