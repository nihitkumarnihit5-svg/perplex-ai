import os, sqlite3, time, requests, json, base64
from flask import Flask, request, jsonify, session, redirect, url_for
from authlib.integrations.flask_client import OAuth
from datetime import datetime
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.secret_key = os.environ.get("SECRET_KEY", "nihit_final_v10")

# ================= DATABASE SETUP =================
def get_db():
    conn = sqlite3.connect("perplex.db", check_same_thread=False)
    conn.execute("CREATE TABLE IF NOT EXISTS chats(id TEXT, user TEXT, title TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS messages(chat_id TEXT, role TEXT, content TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS user_memory(user TEXT PRIMARY KEY, memory TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS usage(user TEXT, date TEXT, count INTEGER, PRIMARY KEY(user, date))")
    conn.commit()
    return conn

db = get_db()

# ================= AUTH =================
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={"scope": "email profile"}
)

# ================= AI LOGIC =================
def get_ai_response(msg, chat_id, user_email, img_b64=None):
    try:
        # Sense & Memory
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        mem = db.execute("SELECT memory FROM user_memory WHERE user=?", (user_email,)).fetchone()
        mem_data = mem[0] if mem else "No facts known."

        # History
        hist = db.execute("SELECT role, content FROM messages WHERE chat_id=? ORDER BY rowid DESC LIMIT 10", (chat_id,)).fetchall()
        messages = [{"role": h[0], "content": h[1]} for h in reversed(hist)]

        sys_prompt = f"You are Perplex AI. Current Time: {now}. User Memory: {mem_data}. If code is asked, wrap it in ```html blocks for the Canvas view."
        
        user_content = [{"type": "text", "text": msg}]
        if img_b64:
            user_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}})

        payload = {
            "model": "google/gemini-2.0-flash-001",
            "messages": [{"role": "system", "content": sys_prompt}] + messages + [{"role": "user", "content": user_content}]
        }
        
        headers = {"Authorization": f"Bearer {os.environ.get('OPENROUTER_KEY')}"}
        r = requests.post("[https://openrouter.ai/api/v1/chat/completions](https://openrouter.ai/api/v1/chat/completions)", headers=headers, json=payload, timeout=60)
        return r.json()['choices'][0]['message']['content']
    except Exception as e:
        return f"Bhai error aa gaya: {str(e)}"

# ================= ROUTES =================
@app.route("/")
def home():
    return redirect("/chat") if "user" in session else '<h1>PERPLEX AI</h1><a href="/login">Login with Google</a>'

@app.route("/login")
def login(): return google.authorize_redirect(url_for('callback', _external=True, _scheme='https'))

@app.route("/callback")
def callback():
    session["user"] = google.authorize_access_token().get('userinfo', google.get("[https://www.googleapis.com/oauth2/v2/userinfo](https://www.googleapis.com/oauth2/v2/userinfo)").json())["email"]
    return redirect("/chat")

@app.route("/chat")
def chat_ui():
    if "user" not in session: return redirect("/")
    today = datetime.now().strftime('%Y-%m-%d')
    res = db.execute("SELECT count FROM usage WHERE user=? AND date=?", (session['user'], today)).fetchone()
    count = res[0] if res else 0
    return UI_HTML.replace("{{count}}", str(count))

@app.route("/send", methods=["POST"])
def send():
    user = session.get("user")
    msg, img, cid = request.form.get("msg"), request.form.get("image"), request.form.get("chat")
    
    today = datetime.now().strftime('%Y-%m-%d')
    res = db.execute("SELECT count FROM usage WHERE user=? AND date=?", (user, today)).fetchone()
    current_usage = res[0] if res else 0
    
    if current_usage >= 50: return jsonify({"reply": "❌ Daily Limit Exceeded (50 chats)!"})
    
    if not cid or cid == "null":
        cid = str(int(time.time()))
        db.execute("INSERT INTO chats VALUES(?,?,?)", (cid, user, msg[:30]))
    
    reply = get_ai_response(msg, cid, user, img)
    
    db.execute("INSERT INTO messages VALUES(?,?,?)", (cid, "user", msg))
    db.execute("INSERT INTO messages VALUES(?,?,?)", (cid, "assistant", reply))
    db.execute("INSERT OR REPLACE INTO usage VALUES(?,?,?)", (user, today, current_usage + 1))
    db.commit()
    
    return jsonify({"reply": reply, "chat_id": cid, "new_count": current_usage + 1})

@app.route("/get_history")
def get_history():
    rows = db.execute("SELECT id, title FROM chats WHERE user=? ORDER BY id DESC", (session['user'],)).fetchall()
    return jsonify(rows)

@app.route("/clear", methods=["POST"])
def clear():
    db.execute("DELETE FROM chats WHERE user=?", (session['user'],))
    db.commit()
    return jsonify({"status": "ok"})

# ================= HTML UI =================
UI_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Perplex AI</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { margin:0; background:#0d0d0d; color:#eee; font-family: sans-serif; display:flex; height:100vh; overflow:hidden; }
        .sidebar { width:260px; background:#161616; border-right:1px solid #222; display:flex; flex-direction:column; padding:15px; }
        .main { flex:1; display:flex; position:relative; }
        #chat-window { flex:1; display:flex; flex-direction:column; border-right:1px solid #222; transition: 0.3s; }
        #box { flex:1; overflow-y:auto; padding:20px 10%; display:flex; flex-direction:column; gap:15px; }
        .msg { padding:12px; border-radius:12px; max-width:85%; font-size:15px; line-height:1.5; }
        .user { align-self:flex-end; background:#2563eb; }
        .assistant { align-self:flex-start; background:#222; border:1px solid #333; }
        .input-area { padding:20px 10%; border-top:1px solid #222; }
        .input-bar { background:#1e1e1e; border-radius:25px; padding:8px 20px; display:flex; align-items:center; gap:12px; border:1px solid #333; }
        input[type="text"] { flex:1; background:transparent; border:none; color:white; outline:none; font-size:16px; }
        .plus-btn { cursor:pointer; font-size:24px; color:#888; position:relative; }
        .plus-menu { position:absolute; bottom:55px; left:0; background:#222; border:1px solid #444; border-radius:8px; display:none; flex-direction:column; width:160px; z-index:100; }
        .plus-menu div { padding:12px; font-size:14px; cursor:pointer; border-bottom:1px solid #333; }
        .plus-menu div:hover { background:#2563eb; }
        #canvas { width:50%; background:#000; border-left:1px solid #222; display:none; flex-direction:column; }
        button { cursor:pointer; border:none; border-radius:20px; padding:8px 18px; font-weight:bold; }
        #send-btn { background:#2563eb; color:white; }
        #stop-btn { background:#d32f2f; color:white; display:none; }
    </style>
</head>
<body>
    <div class="sidebar">
        <h2 style="color:#2563eb; margin:0 0 15px 0;">PERPLEX</h2>
        <button onclick="location.reload()" style="background:#333; color:white; margin-bottom:10px;">+ New Chat</button>
        <input type="text" id="search" placeholder="Search chats..." oninput="filterChats()" style="padding:10px; background:#000; border:1px solid #333; color:white; border-radius:8px; outline:none;">
        <div id="history" style="flex:1; overflow-y:auto; margin-top:15px;"></div>
        <div onclick="toggleSettings()" style="cursor:pointer; color:#777; padding:10px; font-size:14px;">⚙️ Settings</div>
    </div>

    <div class="main">
        <div id="chat-window">
            <div style="position:absolute; top:10px; left:20px; font-size:12px; color:#555;">Usage: <span id="usage-tag">{{count}}</span>/50</div>
            <div id="box"></div>
            <div class="input-area">
                <div id="img-preview" style="display:none; margin-bottom:10px;"><img id="pre-view" style="height:60px; border-radius:8px;"></div>
                <div class="input-bar">
                    <div class="plus-btn" onclick="togglePlus()">+
                        <div class="plus-menu" id="plus-menu">
                            <div onclick="document.getElementById('file-in').click()">🖼️ Upload Photo</div>
                            <div onclick="toggleCanvas(true)">🎨 Open Canvas</div>
                        </div>
                    </div>
                    <input type="file" id="file-in" hidden onchange="handleFile(this)">
                    <input type="text" id="msg-in" placeholder="Ask Nihit's AI..." onkeypress="if(event.key=='Enter')sendMsg()">
                    <button id="send-btn" onclick="sendMsg()">Send</button>
                    <button id="stop-btn" onclick="stopAI()">Stop</button>
                </div>
            </div>
        </div>

        <div id="canvas">
            <div style="padding:10px; background:#111; display:flex; justify-content:space-between; align-items:center;">
                <span style="font-size:13px; color:#888;">Code Canvas</span>
                <div>
                    <button onclick="runCode()" style="background:#22c55e; color:white; padding:4px 10px; font-size:12px;">Run</button>
                    <button onclick="toggleCanvas(false)" style="background:transparent; color:red; font-size:18px;">✕</button>
                </div>
            </div>
            <textarea id="code-editor" style="flex:1; background:#000; color:#4ade80; padding:15px; border:none; font-family:monospace; outline:none; resize:none;"></textarea>
            <iframe id="output" style="height:45%; background:white; border:none;"></iframe>
        </div>
    </div>

    <div id="settings" style="display:none; position:fixed; bottom:60px; left:20px; background:#222; padding:15px; border-radius:10px; border:1px solid #444; z-index:1000;">
        <div onclick="clearChats()" style="color:#ff4d4d; cursor:pointer; font-weight:bold;">🗑️ Clear All History</div>
        <div onclick="alert(document.cookie)" style="margin-top:12px; cursor:pointer; color:#aaa;">🍪 Cookie Preferences</div>
    </div>

    <script>
        let currentCid = null, selectedImg = null, aborter = null;

        async function sendMsg() {
            const input = document.getElementById("msg-in");
            if(!input.value && !selectedImg) return;

            const box = document.getElementById("box");
            box.innerHTML += `<div class="msg user">${input.value}</div>`;
            const val = input.value; input.value = "";
            box.scrollTop = box.scrollHeight;

            document.getElementById("send-btn").style.display = "none";
            document.getElementById("stop-btn").style.display = "block";

            aborter = new AbortController();
            const fd = new FormData();
            fd.append("msg", val); fd.append("chat", currentCid);
            if(selectedImg) fd.append("image", selectedImg);

            try {
                const r = await fetch("/send", {method:"POST", body:fd, signal: aborter.signal});
                const d = await r.json();
                currentCid = d.chat_id;
                
                let reply = d.reply;
                if(reply.includes("```html")) {
                    const code = reply.match(/```html([\\s\\S]*?)```/)[1].trim();
                    toggleCanvas(true);
                    document.getElementById("code-editor").value = code;
                    reply = reply.replace(/```html[\\s\\S]*?```/g, "*(Code sent to Canvas)*");
                }

                box.innerHTML += `<div class="msg assistant">${reply}</div>`;
                document.getElementById("usage-tag").innerText = d.new_count || "{{count}}";
            } catch(e) { if(e.name !== 'AbortError') box.innerHTML += `<div class="msg assistant">Connection Lost.</div>`; }

            document.getElementById("send-btn").style.display = "block";
            document.getElementById("stop-btn").style.display = "none";
            selectedImg = null; document.getElementById("img-preview").style.display = "none";
            box.scrollTop = box.scrollHeight;
            loadHistory();
        }

        function stopAI() { if(aborter) aborter.abort(); }
        
        function handleFile(input) {
            const reader = new FileReader();
            reader.onload = (e) => {
                selectedImg = e.target.result.split(',')[1];
                document.getElementById("pre-view").src = e.target.result;
                document.getElementById("img-preview").style.display = "block";
            };
            reader.readAsDataURL(input.files[0]);
            togglePlus();
        }

        function toggleCanvas(show) {
            document.getElementById("canvas").style.display = show ? "flex" : "none";
            document.getElementById("chat-window").style.flex = show ? "0.5" : "1";
        }
        function runCode() {
            const frame = document.getElementById("output").contentWindow.document;
            frame.open(); frame.write(document.getElementById("code-editor").value); frame.close();
        }
        function togglePlus() { const m = document.getElementById("plus-menu"); m.style.display = m.style.display === "flex" ? "none" : "flex"; }
        function toggleSettings() { const s = document.getElementById("settings"); s.style.display = s.style.display === "block" ? "none" : "block"; }
        function filterChats() {
            const q = document.getElementById("search").value.toLowerCase();
            document.querySelectorAll(".h-item").forEach(i => i.style.display = i.innerText.toLowerCase().includes(q) ? "block" : "none");
        }
        function loadHistory() {
            fetch("/get_history").then(r=>r.json()).then(data => {
                const h = document.getElementById("history"); h.innerHTML = "";
                data.forEach(c => h.innerHTML += `<div class="h-item" style="padding:10px; cursor:pointer; border-bottom:1px solid #222;">${c[1]}</div>`);
            });
        }
        function clearChats() { if(confirm("Saari chats uda doon?")) fetch("/clear", {method:"POST"}).then(()=>location.reload()); }
        loadHistory();
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
