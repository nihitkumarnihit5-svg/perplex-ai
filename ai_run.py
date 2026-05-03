from flask import Flask, request, jsonify, session, redirect, url_for
from authlib.integrations.flask_client import OAuth
from werkzeug.middleware.proxy_fix import ProxyFix
import sqlite3, time, requests, json, os, base64
from datetime import datetime, timedelta

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.secret_key = os.environ.get("SECRET_KEY", "nihit_ultra_pro_v10")

# ================= DATABASE =================
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
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={"scope": "email profile"}
)

# ================= HELPERS =================
def get_usage(user):
    today = datetime.now().strftime('%Y-%m-%d')
    res = db.execute("SELECT msg_count, img_count FROM usage WHERE user=? AND date=?", (user, today)).fetchone()
    if not res:
        db.execute("INSERT INTO usage VALUES(?,?,0,0)", (user, today))
        db.commit()
        return 0, 0
    return res

# ================= AI LOGIC =================
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY")

def get_ai_response(msg, chat_id, user_email, img_base64=None):
    try:
        mem_res = db.execute("SELECT memory_data FROM user_memory WHERE user=?", (user_email,)).fetchone()
        memory = mem_res[0] if mem_res else "No memory yet."
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        history = db.execute("SELECT role, content FROM messages WHERE chat_id=? ORDER BY rowid DESC LIMIT 6", (chat_id,)).fetchall()
        messages = [{"role": h[0], "content": h[1]} for h in reversed(history)]

        system_prompt = f"You are Perplex AI. Sense: {current_time}. Memory: {memory}. If code is requested, use ```html blocks for canvas."
        
        user_content = [{"type": "text", "text": msg}]
        if img_base64:
            user_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"}})

        payload = {
            "model": "google/gemini-2.0-flash-001",
            "messages": [{"role": "system", "content": system_prompt}] + messages + [{"role": "user", "content": user_content}]
        }
        r = requests.post("[https://openrouter.ai/api/v1/chat/completions](https://openrouter.ai/api/v1/chat/completions)", headers={"Authorization": f"Bearer {OPENROUTER_KEY}"}, json=payload, timeout=60)
        return r.json()["choices"][0]["message"]["content"]
    except: return "Bhai error aa gaya."

# ================= ROUTES =================
@app.route("/")
def index():
    return redirect("/chat") if "user" in session else '<h1>PERPLEX AI</h1><a href="/login">Login</a>'

@app.route("/login")
def login(): return google.authorize_redirect(url_for('callback', _external=True, _scheme='https'))

@app.route("/callback")
def callback():
    token = google.authorize_access_token()
    info = google.get("[https://www.googleapis.com/oauth2/v2/userinfo](https://www.googleapis.com/oauth2/v2/userinfo)").json()
    session["user"] = info["email"]
    return redirect("/chat")

@app.route("/chat")
def chat():
    if "user" not in session: return redirect("/")
    m, i = get_usage(session['user'])
    return UI_HTML.replace("{{m}}", str(m)).replace("{{i}}", str(i))

@app.route("/send", methods=["POST"])
def send_route():
    user = session.get("user")
    msg, img, cid = request.form.get("msg"), request.form.get("image"), request.form.get("chat")
    m_count, i_count = get_usage(user)

    if img and i_count >= 5: return jsonify({"reply": "Limit Exceeded"})
    if m_count >= 50: return jsonify({"reply": "Limit Exceeded"})

    if not cid or cid == "null":
        cid = str(int(time.time()))
        db.execute("INSERT INTO chats VALUES(?,?,?)", (cid, user, msg[:20]))

    reply = get_ai_response(msg, cid, user, img)
    db.execute("INSERT INTO messages VALUES(?,?,?)", (cid, "user", msg))
    db.execute("INSERT INTO messages VALUES(?,?,?)", (cid, "assistant", reply))
    
    today = datetime.now().strftime('%Y-%m-%d')
    if img: db.execute("UPDATE usage SET img_count=img_count+1 WHERE user=? AND date=?", (user, today))
    else: db.execute("UPDATE usage SET msg_count=msg_count+1 WHERE user=? AND date=?", (user, today))
    db.commit()
    
    return jsonify({"reply": reply, "chat_id": cid})

@app.route("/get_chats")
def get_chats():
    rows = db.execute("SELECT id, title FROM chats WHERE user=? ORDER BY id DESC", (session['user'],)).fetchall()
    return jsonify(rows)

@app.route("/clear_chats", methods=["POST"])
def clear_chats():
    db.execute("DELETE FROM chats WHERE user=?", (session['user'],))
    db.commit()
    return jsonify({"ok": True})

# ================= UI HTML =================
UI_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Perplex AI</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        :root { --bg: #0d0d0d; --panel: #161616; --blue: #2563eb; --border: #222; }
        body { margin:0; background:var(--bg); color:#eee; font-family: sans-serif; display:flex; height:100vh; }
        .sidebar { width:260px; background:var(--panel); border-right:1px solid var(--border); display:flex; flex-direction:column; padding:15px; }
        .main { flex:1; display:flex; position:relative; overflow:hidden; }
        #chat-area { flex:1; display:flex; flex-direction:column; transition: 0.3s; }
        #box { flex:1; overflow-y:auto; padding:20px 10%; display:flex; flex-direction:column; gap:15px; }
        .msg { padding:12px; border-radius:12px; max-width:80%; line-height:1.5; }
        .user { align-self:flex-end; background:var(--blue); }
        .assistant { align-self:flex-start; background:#222; }
        .input-wrap { padding:15px 10%; border-top:1px solid var(--border); }
        .input-box { background:#1e1e1e; border-radius:25px; padding:10px 20px; display:flex; align-items:center; gap:10px; border:1px solid #333; }
        input[type="text"] { flex:1; background:transparent; border:none; color:white; outline:none; font-size:16px; }
        .canvas { width:50%; background:#000; border-left:1px solid var(--border); display:none; flex-direction:column; }
        .plus-btn { cursor:pointer; font-size:24px; color:#888; position:relative; }
        .plus-menu { position:absolute; bottom:50px; left:0; background:#222; border:1px solid #444; border-radius:8px; display:none; flex-direction:column; width:150px; z-index:100; }
        .plus-menu div { padding:10px; font-size:14px; cursor:pointer; }
        .plus-menu div:hover { background:var(--blue); }
        #stop-btn { background:#d32f2f; color:white; border:none; padding:8px 15px; border-radius:20px; cursor:pointer; display:none; }
        #send-btn { background:var(--blue); color:white; border:none; padding:8px 15px; border-radius:20px; cursor:pointer; }
    </style>
</head>
<body>
    <div class="sidebar">
        <h2 style="color:var(--blue)">PERPLEX</h2>
        <button onclick="location.reload()" style="padding:10px; border-radius:8px; border:none; cursor:pointer; background:#333; color:white;">+ New Chat</button>
        <input type="text" id="search" placeholder="Search chats..." oninput="searchChats()" style="margin-top:10px; padding:8px; background:#000; border:1px solid #333; color:white; border-radius:5px;">
        <div id="chat-list" style="flex:1; overflow-y:auto; margin-top:15px;"></div>
        <div onclick="toggleSettings()" style="cursor:pointer; padding:10px; color:#888;">⚙️ Settings</div>
    </div>

    <div class="main">
        <div id="chat-area">
            <div style="position:absolute; top:10px; left:20px; font-size:11px; color:#555;">Usage: <span id="u-msg">{{m}}</span>/50</div>
            <div id="box"></div>
            <div class="input-wrap">
                <div id="preview-box" style="display:none; padding:10px;"><img id="img-pre" style="height:50px; border-radius:5px;"></div>
                <div class="input-box">
                    <div class="plus-btn" onclick="togglePlus()">+
                        <div class="plus-menu" id="p-menu">
                            <div onclick="document.getElementById('f').click()">🖼️ Upload</div>
                            <div onclick="openCanvas()">🎨 Canvas</div>
                        </div>
                    </div>
                    <input type="file" id="f" hidden onchange="preImg(this)">
                    <input type="text" id="in" placeholder="Ask anything..." onkeypress="if(event.key=='Enter')send()">
                    <button id="send-btn" onclick="send()">Send</button>
                    <button id="stop-btn" onclick="stopAI()">Stop</button>
                </div>
            </div>
        </div>

        <div class="canvas" id="cvs">
            <div style="padding:10px; background:#111; display:flex; justify-content:space-between;">
                <span>Canvas Preview</span>
                <button onclick="runCode()" style="background:#22c55e; color:white; border:none; padding:5px 10px; cursor:pointer;">Run</button>
                <span onclick="closeCanvas()" style="cursor:pointer; color:red;">✕</span>
            </div>
            <textarea id="code" style="flex:1; background:#000; color:#0f0; padding:15px; border:none; font-family:monospace; outline:none;"></textarea>
            <iframe id="run" style="height:40%; background:white; border:none;"></iframe>
        </div>
    </div>

    <div id="sett" style="display:none; position:fixed; bottom:60px; left:20px; background:#222; padding:15px; border-radius:10px; border:1px solid #444; z-index:1000;">
        <div onclick="clearAll()" style="color:red; cursor:pointer;">🗑️ Clear All Chats</div>
        <div onclick="alert(document.cookie)" style="margin-top:10px; cursor:pointer;">🍪 Cookies Pref</div>
    </div>

    <script>
        let cid = null;
        let selectedImg = null;
        let aborter = null;

        async function send() {
            const input = document.getElementById("in");
            if(!input.value && !selectedImg) return;
            
            document.getElementById("box").innerHTML += `<div class="msg user">${input.value}</div>`;
            const val = input.value; input.value = "";
            document.getElementById("send-btn").style.display = "none";
            document.getElementById("stop-btn").style.display = "block";

            aborter = new AbortController();
            const fd = new FormData();
            fd.append("msg", val); fd.append("chat", cid);
            if(selectedImg) fd.append("image", selectedImg);

            try {
                const r = await fetch("/send", {method:"POST", body:fd, signal: aborter.signal});
                const d = await r.json();
                cid = d.chat_id;
                
                let reply = d.reply;
                const codeMatch = reply.match(/```html([\\s\\S]*?)```/);
                if(codeMatch) {
                    openCanvas();
                    document.getElementById("code").value = codeMatch[1].trim();
                    reply = reply.replace(/```html[\\s\\S]*?```/g, "*(Code opened in Canvas)*");
                }
                
                document.getElementById("box").innerHTML += `<div class="msg assistant">${reply}</div>`;
                document.getElementById("u-msg").innerText = parseInt(document.getElementById("u-msg").innerText) + 1;
            } catch(e) {}
            
            document.getElementById("send-btn").style.display = "block";
            document.getElementById("stop-btn").style.display = "none";
            selectedImg = null; document.getElementById("preview-box").style.display = "none";
            loadChats();
        }

        function stopAI() { if(aborter) aborter.abort(); }
        function preImg(input) {
            const reader = new FileReader();
            reader.onload = (e) => {
                selectedImg = e.target.result.split(',')[1];
                document.getElementById("img-pre").src = e.target.result;
                document.getElementById("preview-box").style.display = "block";
            };
            reader.readAsDataURL(input.files[0]);
        }
        function openCanvas() { document.getElementById("cvs").style.display="flex"; document.getElementById("chat-area").style.flex="0.5"; }
        function closeCanvas() { document.getElementById("cvs").style.display="none"; document.getElementById("chat-area").style.flex="1"; }
        function runCode() {
            const frame = document.getElementById("run").contentWindow.document;
            frame.open(); frame.write(document.getElementById("code").value); frame.close();
        }
        function togglePlus() { const m = document.getElementById("p-menu"); m.style.display = m.style.display === "flex" ? "none" : "flex"; }
        function toggleSettings() { const s = document.getElementById("sett"); s.style.display = s.style.display === "block" ? "none" : "block"; }
        function searchChats() {
            const q = document.getElementById("search").value.toLowerCase();
            document.querySelectorAll(".c-item").forEach(i => i.style.display = i.innerText.toLowerCase().includes(q) ? "block" : "none");
        }
        function loadChats() {
            fetch("/get_chats").then(r=>r.json()).then(data => {
                const l = document.getElementById("chat-list"); l.innerHTML = "";
                data.forEach(c => l.innerHTML += `<div class="c-item" style="padding:8px; cursor:pointer; border-bottom:1px solid #222;">${c[1]}</div>`);
            });
        }
        function clearAll() { if(confirm("Delete all?")) fetch("/clear_chats",{method:"POST"}).then(()=>location.reload()); }
        loadChats();
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
