from flask import Flask, request, jsonify, session, redirect, url_for, g
from authlib.integrations.flask_client import OAuth
from werkzeug.middleware.proxy_fix import ProxyFix
import sqlite3, time, requests, json, os, base64
from datetime import timedelta, datetime

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

app.secret_key = os.environ.get("SECRET_KEY", "perplex_ultra_pro_v11")
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

DATABASE = 'perplex_ai.db'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.execute("CREATE TABLE IF NOT EXISTS chats(id TEXT, user TEXT, title TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS messages(chat_id TEXT, role TEXT, content TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS usage(user TEXT, date TEXT, msg_count INTEGER, PRIMARY KEY(user, date))")
        db.commit()
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None: db.close()

# ================= GOOGLE AUTH =================
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={"scope": "email profile"}
)

# ================= AI ENGINE (With Image Recognition) =================
def get_ai_response(msg, chat_id, user_email, img_base64=None):
    try:
        db = get_db()
        history = db.execute("SELECT role, content FROM messages WHERE chat_id=? ORDER BY rowid DESC LIMIT 6", (chat_id,)).fetchall()
        chat_history = [{"role": h[0], "content": h[1]} for h in reversed(history)]

        user_content = [{"type": "text", "text": msg}]
        if img_base64:
            user_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"}})

        payload = {
            "model": "google/gemini-2.0-flash-001",
            "messages": [{"role": "system", "content": "You are Perplex AI. If code is large, use ```html blocks to trigger Canvas."}] + chat_history + [{"role": "user", "content": user_content}]
        }

        r = requests.post("[https://openrouter.ai/api/v1/chat/completions](https://openrouter.ai/api/v1/chat/completions)", 
                         headers={"Authorization": f"Bearer {os.environ.get('OPENROUTER_KEY')}"}, 
                         json=payload, timeout=60)
        return r.json()["choices"][0]["message"]["content"]
    except: return "Bhai API error aa raha hai. Railway logs check karo."

# ================= ROUTES =================
@app.route("/")
def index():
    return redirect("/chat") if "user" in session else UI_LOGIN

@app.route("/login")
def login(): return google.authorize_redirect(url_for('callback', _external=True))

@app.route("/callback")
def callback():
    token = google.authorize_access_token()
    session["user"] = google.get("[https://www.googleapis.com/oauth2/v2/userinfo](https://www.googleapis.com/oauth2/v2/userinfo)").json()["email"]
    return redirect("/chat")

@app.route("/chat")
def chat_page():
    if "user" not in session: return redirect("/")
    today = datetime.now().strftime('%Y-%m-%d')
    res = get_db().execute("SELECT msg_count FROM usage WHERE user=? AND date=?", (session['user'], today)).fetchone()
    return UI_HTML.replace("{{msg_usage}}", str(res[0] if res else 0))

@app.route("/send", methods=["POST"])
def send_msg():
    db = get_db()
    user = session.get("user")
    data = request.form
    msg, img, cid = data.get("msg"), data.get("image"), data.get("chat")
    
    today = datetime.now().strftime('%Y-%m-%d')
    res = db.execute("SELECT msg_count FROM usage WHERE user=? AND date=?", (user, today)).fetchone()
    m_count = res[0] if res else 0

    if m_count >= 50: return jsonify({"reply": "❌ Daily Limit (50) khatam ho gayi!"})

    if not cid or cid == "null":
        cid = str(int(time.time()*1000))
        db.execute("INSERT INTO chats VALUES(?,?,?)", (cid, user, msg[:30]))
    
    reply = get_ai_response(msg, cid, user, img)
    db.execute("INSERT INTO messages VALUES(?,?,?)", (cid, "user", msg))
    db.execute("INSERT INTO messages VALUES(?,?,?)", (cid, "assistant", reply))
    db.execute("INSERT OR REPLACE INTO usage VALUES(?,?,?)", (user, today, m_count + 1))
    db.commit()
    
    return jsonify({"reply": reply, "chat_id": cid, "new_usage": m_count + 1})

@app.route("/history")
def history():
    rows = get_db().execute("SELECT id, title FROM chats WHERE user=? ORDER BY id DESC", (session['user'],)).fetchall()
    return jsonify(rows)

@app.route("/clear", methods=["POST"])
def clear():
    get_db().execute("DELETE FROM chats WHERE user=?", (session['user'],))
    get_db().commit()
    return jsonify({"success": True})

# ================= UI =================
UI_LOGIN = """<body style="background:#000;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;font-family:sans-serif;">
<div style="text-align:center;"><h1>Perplex AI</h1><a href="/login" style="background:#fff;color:#000;padding:12px 24px;text-decoration:none;border-radius:50px;font-weight:bold;">Login with Google</a></div></body>"""

UI_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Perplex AI | Nihit</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        :root { --bg: #0d0d0d; --sidebar: #161616; --accent: #2563eb; --border: #222; }
        body { margin:0; background:var(--bg); color:#eee; font-family: sans-serif; display:flex; height:100vh; }
        .sidebar { width:260px; background:var(--sidebar); border-right:1px solid var(--border); display:flex; flex-direction:column; padding:15px; }
        .main { flex:1; display:flex; position:relative; overflow:hidden; }
        .chat-area { flex:1; display:flex; flex-direction:column; }
        #box { flex:1; overflow-y:auto; padding:20px 15%; display:flex; flex-direction:column; gap:20px; }
        .msg { padding:12px; border-radius:12px; max-width:85%; line-height:1.6; }
        .user { align-self:flex-end; background:var(--accent); }
        .assistant { align-self:flex-start; background:transparent; border:1px solid #333; }
        .input-wrap { padding:20px 15%; border-top:1px solid var(--border); }
        .bar { background:#1e1e1e; border-radius:30px; padding:8px 15px; display:flex; align-items:center; gap:10px; border:1px solid #333; }
        input[type="text"] { flex:1; background:transparent; border:none; color:white; outline:none; font-size:16px; }
        #canvas { width:50%; background:#000; border-left:1px solid var(--border); display:none; flex-direction:column; }
        .plus-btn { cursor:pointer; font-size:20px; color:#888; position:relative; width:30px; }
        .plus-menu { position:absolute; bottom:50px; left:0; background:#222; border:1px solid #444; border-radius:10px; display:none; flex-direction:column; width:150px; z-index:100; overflow:hidden; }
        .plus-menu div { padding:12px; cursor:pointer; font-size:14px; }
        .plus-menu div:hover { background:#333; }
        #sendBtn, #stopBtn { border:none; padding:8px 15px; border-radius:20px; cursor:pointer; font-weight:bold; }
        #sendBtn { background:white; color:black; }
        #stopBtn { background:#ef4444; color:white; display:none; }
        .mic-btn { cursor:pointer; font-size:18px; color:#888; }
        .mic-active { color: #ef4444; animation: pulse 1s infinite; }
        @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.5; } 100% { opacity: 1; } }
    </style>
</head>
<body>
    <div class="sidebar">
        <h2 style="color:var(--accent); margin:0 0 15px 0;">PERPLEX AI</h2>
        <button onclick="location.reload()" style="background:#222; color:white; padding:10px; border:none; border-radius:8px; cursor:pointer; font-weight:bold;">+ New Chat</button>
        <input type="text" id="srch" placeholder="Search chats..." oninput="filter()" style="margin:10px 0; padding:8px; background:#000; border:1px solid #333; color:white; border-radius:5px;">
        <div id="hist" style="flex:1; overflow-y:auto;"></div>
        <div style="font-size:12px; color:#555; margin-bottom:10px;">Usage: <span id="u-tag">{{msg_usage}}</span>/50</div>
        <div onclick="toggleSett()" style="cursor:pointer; color:#888; display:flex; align-items:center; gap:8px;">⚙️ Settings</div>
    </div>

    <div class="main">
        <div class="chat-area" id="chatArea">
            <div id="box"></div>
            <div class="input-wrap">
                <div id="p-box" style="display:none; margin-bottom:10px;"><img id="p-img" style="height:60px; border-radius:8px; border:1px solid #444;"></div>
                <div class="bar">
                    <div class="plus-btn" onclick="togglePlus()">+
                        <div class="plus-menu" id="p-menu">
                            <div onclick="document.getElementById('f').click()">🖼️ Upload Photo</div>
                            <div onclick="openCvs()">🎨 Open Canvas</div>
                        </div>
                    </div>
                    <input type="file" id="f" hidden onchange="pre(this)">
                    <input type="text" id="in" placeholder="Ask Nihit's AI..." onkeypress="if(event.key=='Enter')send()">
                    <div class="mic-btn" id="mic" onclick="toggleMic()">🎤</div>
                    <button id="sendBtn" onclick="send()">Send</button>
                    <button id="stopBtn" onclick="stop()">Stop</button>
                </div>
            </div>
        </div>
        <div id="canvas">
            <div style="padding:10px; background:#111; display:flex; justify-content:space-between; border-bottom:1px solid #222;">
                <span>Canvas</span>
                <div><button onclick="run()">Run</button> <button onclick="openCvs(false)">✕</button></div>
            </div>
            <textarea id="code" style="flex:1; background:#000; color:#0f0; padding:15px; border:none; font-family:monospace; outline:none; resize:none;"></textarea>
            <iframe id="out" style="height:45%; background:white; border:none; width:100%;"></iframe>
        </div>
    </div>

    <div id="sett" style="display:none; position:fixed; bottom:60px; left:20px; background:#222; padding:15px; border-radius:10px; border:1px solid #444; z-index:1000; width:150px;">
        <div onclick="clearAll()" style="color:#ef4444; cursor:pointer; font-weight:bold;">🗑️ Clear All</div>
        <div onclick="alert(document.cookie)" style="margin-top:10px; cursor:pointer; color:#888;">🍪 Cookies</div>
    </div>

    <script>
        let cid = null, img = null, controller = null;
        const mic = document.getElementById('mic');
        const recognition = window.SpeechRecognition || window.webkitSpeechRecognition ? new (window.SpeechRecognition || window.webkitSpeechRecognition)() : null;

        if(recognition) {
            recognition.onresult = (e) => { document.getElementById("in").value = e.results[0][0].transcript; toggleMic(); };
        }

        function toggleMic() {
            if(!recognition) return alert("Mic not supported in this browser.");
            mic.classList.toggle('mic-active');
            mic.classList.contains('mic-active') ? recognition.start() : recognition.stop();
        }

        async function send() {
            const i = document.getElementById("in");
            if(!i.value && !img) return;
            const b = document.getElementById("box");
            b.innerHTML += `<div class="msg user">${i.value}</div>`;
            const val = i.value; i.value = "";
            b.scrollTop = b.scrollHeight;

            document.getElementById("sendBtn").style.display = "none";
            document.getElementById("stopBtn").style.display = "block";
            controller = new AbortController();

            const fd = new FormData();
            fd.append("msg", val); fd.append("chat", cid);
            if(img) fd.append("image", img);

            try {
                const r = await fetch("/send", {method:"POST", body:fd, signal: controller.signal});
                const d = await r.json();
                cid = d.chat_id;
                let reply = d.reply;
                if(reply.includes("```html")) {
                    openCvs(true);
                    const match = reply.match(/```html([\\s\\S]*?)```/);
                    if(match) document.getElementById("code").value = match[1].trim();
                    reply = reply.replace(/```html[\\s\\S]*?```/g, "*(Code displayed in Canvas)*");
                }
                b.innerHTML += `<div class="msg assistant">${reply}</div>`;
                document.getElementById("u-tag").innerText = d.new_usage || "{{msg_usage}}";
            } catch(e) { if(e.name !== 'AbortError') b.innerHTML += `<div class="msg assistant">Error: Request Failed</div>`; }

            document.getElementById("sendBtn").style.display = "block";
            document.getElementById("stopBtn").style.display = "none";
            img = null; document.getElementById("p-box").style.display="none";
            b.scrollTop = b.scrollHeight;
            loadHist();
        }

        function stop() { if(controller) controller.abort(); }
        function pre(i) {
            const r = new FileReader();
            r.onload = (e) => {
                img = e.target.result.split(',')[1];
                document.getElementById("p-img").src = e.target.result;
                document.getElementById("p-box").style.display = "block";
            };
            r.readAsDataURL(i.files[0]);
        }
        function openCvs(s=true) { document.getElementById("canvas").style.display = s?"flex":"none"; document.getElementById("chatArea").style.flex = s?"0.5":"1"; }
        function run() { const f = document.getElementById("out").contentWindow.document; f.open(); f.write(document.getElementById("code").value); f.close(); }
        function togglePlus() { const m = document.getElementById("p-menu"); m.style.display = m.style.display==="flex"?"none":"flex"; }
        function toggleSett() { const s = document.getElementById("sett"); s.style.display = s.style.display==="block"?"none":"block"; }
        function filter() { const q = document.getElementById("srch").value.toLowerCase(); document.querySelectorAll(".h-i").forEach(i => i.style.display = i.innerText.toLowerCase().includes(q)?"block":"none"); }
        function loadHist() { fetch("/history").then(r=>r.json()).then(data => { const h = document.getElementById("hist"); h.innerHTML = ""; data.forEach(c => h.innerHTML += `<div class="h-i" style="padding:10px; cursor:pointer; font-size:14px;" onclick="location.href='/chat?c=${c[0]}'"># ${c[1]}</div>`); }); }
        function clearAll() { if(confirm("Confirm? All chats will be deleted.")) fetch("/clear", {method:"POST"}).then(()=>location.reload()); }
        loadHist();
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
