from flask import Flask, request, jsonify, session, redirect, url_for
from authlib.integrations.flask_client import OAuth
from werkzeug.middleware.proxy_fix import ProxyFix
import sqlite3, time, requests, json, os, base64
from datetime import timedelta, datetime

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.secret_key = os.getenv("SECRET_KEY", "nihit_x_fire_ultra_pro_v4")

# ================= DATABASE (Limits + Memory + Media) =================
def init_db():
    conn = sqlite3.connect("perplex_ai.db", check_same_thread=False)
    conn.execute("CREATE TABLE IF NOT EXISTS chats(id TEXT, user TEXT, title TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS messages(chat_id TEXT, role TEXT, content TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS user_memory(user TEXT PRIMARY KEY, memory_data TEXT)")
    # Usage tracking
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

# ================= AI ENGINE (With Image Vision) =================
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")

def get_ai_response(msg, chat_id, user_email, img_base64=None):
    try:
        mem_res = db.execute("SELECT memory_data FROM user_memory WHERE user=?", (user_email,)).fetchone()
        saved_memory = mem_res[0] if mem_res else "Unknown"

        history_rows = db.execute("SELECT role, content FROM messages WHERE chat_id=? ORDER BY rowid DESC LIMIT 6", (chat_id,)).fetchall()
        chat_history = [{"role": h[0], "content": h[1]} for h in reversed(history_rows)]

        system_prompt = f"Identity: Perplex AI by Nihit kr. Memory: {saved_memory}. If code is asked, start with <!DOCTYPE html>. If image is provided, describe it accurately."
        
        user_content = [{"type": "text", "text": msg}]
        if img_base64:
            user_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"}})

        payload = {
            "model": "google/gemini-2.0-flash-001",
            "messages": [{"role": "system", "content": system_prompt}] + chat_history + [{"role": "user", "content": user_content}]
        }

        r = requests.post("https://openrouter.ai/api/v1/chat/completions", headers={"Authorization": f"Bearer {OPENROUTER_KEY}"}, json=payload)
        return r.json()["choices"][0]["message"]["content"]
    except: return "Bhai, server busy hai."

# ================= ROUTES =================

@app.route("/")
def index():
    if "user" in session: return redirect("/chat")
    return '<body style="background:#000;color:#fff;display:flex;justify-content:center;align-items:center;height:100vh;"><a href="/login" style="color:#000;background:#fff;padding:15px;text-decoration:none;border-radius:10px;">Login with Google</a></body>'

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
    msg = request.form.get("msg")
    img = request.form.get("image") # Base64
    cid = request.form.get("chat")

    can_send, count = check_limit(user, is_img=True if img else False)
    if not can_send: return jsonify({"reply": "Daily Limit Exceeded! (50 Msgs / 5 Images)"})

    if not cid or cid == "null":
        cid = str(int(time.time()))
        db.execute("INSERT INTO chats VALUES(?,?,?)", (cid, user, msg[:20]))

    reply = get_ai_response(msg, cid, user, img)
    
    db.execute("INSERT INTO messages VALUES(?,?,?)", (cid, "user", msg))
    db.execute("INSERT INTO messages VALUES(?,?,?)", (cid, "assistant", reply))
    
    # Update Usage
    today = datetime.now().strftime('%Y-%m-%d')
    if img:
        db.execute("UPDATE usage SET img_count = img_count + 1 WHERE user=? AND date=?", (user, today))
    else:
        db.execute("UPDATE usage SET msg_count = msg_count + 1 WHERE user=? AND date=?", (user, today))
    db.commit()

    return jsonify({"reply": reply, "chat_id": cid, "count": count + 1})

@app.route("/chats")
def get_chats():
    rows = db.execute("SELECT id, title FROM chats WHERE user=? ORDER BY id DESC", (session['user'],)).fetchall()
    return jsonify(rows)

@app.route("/delete_all", methods=["POST"])
def delete_all():
    db.execute("DELETE FROM chats WHERE user=?", (session['user'],))
    db.execute("DELETE FROM messages WHERE chat_id NOT IN (SELECT id FROM chats)")
    db.commit()
    return jsonify({"status": "ok"})

# ================= UI WITH CANVAS & LIMITS =================
UI_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Perplex AI Pro</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { margin:0; background:#0b0b0b; color:#eee; font-family:sans-serif; display:flex; height:100vh; overflow:hidden; }
        .sidebar { width:260px; background:#111; border-right:1px solid #222; display:flex; flex-direction:column; padding:15px; transition: 0.3s; }
        .search-chat { background:#222; border:none; color:white; padding:10px; border-radius:8px; margin:10px 0; outline:none; }
        .main { flex:1; display:flex; flex-direction:row; }
        .chat-section { flex:1; display:flex; flex-direction:column; border-right:1px solid #222; }
        .canvas-section { flex:1; display:none; flex-direction:column; background:#000; }
        #box { flex:1; overflow-y:auto; padding:20px; }
        .msg { padding:12px; border-radius:10px; margin-bottom:10px; max-width:85%; }
        .user { align-self:flex-end; background:#2563eb; }
        .assistant { align-self:flex-start; background:#1e1e1e; }
        .input-area { padding:20px; display:flex; gap:10px; align-items:center; }
        .plus-btn { font-size:24px; cursor:pointer; color:#888; }
        .limit-tag { position:fixed; top:10px; left:270px; font-size:12px; color:#555; }
        .settings-panel { position:fixed; right:20px; top:60px; background:#1e1e1e; padding:15px; border-radius:10px; display:none; z-index:100; border:1px solid #333; }
        #canvas-frame { width:100%; height:80%; border:none; background:white; }
    </style>
</head>
<body>
    <div class="limit-tag">Daily Usage: <span id="usage-count">0</span>/50</div>
    
    <div class="sidebar">
        <div style="display:flex; justify-content:space-between;">
            <b>PERPLEX AI</b>
            <span onclick="toggleSettings()" style="cursor:pointer;">⚙️</span>
        </div>
        <button onclick="location.reload()" style="margin-top:15px; padding:10px; border-radius:8px; border:none; cursor:pointer;">+ New Chat</button>
        <input type="text" class="search-chat" placeholder="Search chats..." oninput="searchChats(this.value)">
        <div id="list" style="flex:1; overflow-y:auto;"></div>
    </div>

    <div class="main">
        <div class="chat-section">
            <div id="box"></div>
            <div class="input-area">
                <div class="plus-btn" onclick="document.getElementById('file-in').click()">+</div>
                <input type="file" id="file-in" hidden onchange="uploadFile(this)">
                <input type="text" id="msg-in" placeholder="Ask anything..." style="flex:1; padding:12px; border-radius:10px; border:none; background:#1e1e1e; color:white;" onkeypress="if(event.key=='Enter')send()">
                <button id="send-btn" onclick="send()" style="background:#2563eb; color:white; border:none; padding:10px 20px; border-radius:10px; cursor:pointer;">Send</button>
            </div>
        </div>
        
        <div class="canvas-section" id="canvas">
            <div style="padding:10px; background:#111; display:flex; justify-content:space-between;">
                <span>Canvas (Code Preview)</span>
                <button onclick="runCode()" style="background:#22c55e; border:none; color:white; padding:5px 10px; border-radius:5px; cursor:pointer;">Run Code</button>
            </div>
            <textarea id="code-editor" style="flex:1; background:#000; color:#0f0; padding:15px; border:none; font-family:monospace; outline:none;"></textarea>
            <iframe id="canvas-frame"></iframe>
        </div>
    </div>

    <div class="settings-panel" id="settings">
        <p onclick="clearAll()" style="color:red; cursor:pointer;">🗑️ Clear All Chats</p>
        <p onclick="alert(document.cookie)" style="cursor:pointer;">🍪 View Cookies</p>
        <p onclick="toggleSettings()" style="cursor:pointer; color:#888;">Close</p>
    </div>

    <script>
        let currentCid = null;
        let controller = null;

        async function send() {
            const input = document.getElementById("msg-in");
            const val = input.value; if(!val) return;
            const btn = document.getElementById("send-btn");
            
            // Stop Response logic
            if(btn.innerText === "Stop") {
                controller.abort();
                btn.innerText = "Send";
                return;
            }

            btn.innerText = "Stop";
            controller = new AbortController();
            
            const box = document.getElementById("box");
            box.innerHTML += `<div class="msg user">${val}</div>`;
            input.value = "";

            const fd = new FormData();
            fd.append("msg", val);
            fd.append("chat", currentCid);

            try {
                const r = await fetch("/send", {method:"POST", body:fd, signal: controller.signal});
                const d = await r.json();
                
                currentCid = d.chat_id;
                document.getElementById("usage-count").innerText = d.count || 0;

                let reply = d.reply;
                if(reply.includes("<!DOCTYPE")) {
                    document.getElementById("canvas").style.display = "flex";
                    document.getElementById("code-editor").value = reply;
                }

                box.innerHTML += `<div class="msg assistant">${reply.replace(/\\n/g, "<br>")}</div>`;
                box.scrollTop = box.scrollHeight;
                btn.innerText = "Send";
                load();
            } catch(e) { btn.innerText = "Send"; }
        }

        function uploadFile(el) {
            const file = el.files[0];
            const reader = new FileReader();
            reader.onloadend = () => {
                const box = document.getElementById("box");
                box.innerHTML += `<div class="msg user"><i>Image Uploaded (Recognizing...)</i></div>`;
                const fd = new FormData();
                fd.append("msg", "Analyze this image");
                fd.append("image", reader.result.split(',')[1]);
                fd.append("chat", currentCid);
                fetch("/send", {method:"POST", body:fd}).then(r=>r.json()).then(d => {
                    box.innerHTML += `<div class="msg assistant">${d.reply}</div>`;
                    document.getElementById("usage-count").innerText = d.count || 0;
                });
            };
            reader.readAsDataURL(file);
        }

        function runCode() {
            const code = document.getElementById("code-editor").value;
            const frame = document.getElementById("canvas-frame").contentWindow.document;
            frame.open(); frame.write(code); frame.close();
        }

        function searchChats(q) {
            const items = document.querySelectorAll(".chat-link");
            items.forEach(i => {
                i.style.display = i.innerText.toLowerCase().includes(q.toLowerCase()) ? "block" : "none";
            });
        }

        function toggleSettings() {
            const s = document.getElementById("settings");
            s.style.display = s.style.display === "block" ? "none" : "block";
        }

        function clearAll() {
            if(confirm("Saare chats delete karun?")) {
                fetch("/delete_all", {method:"POST"}).then(() => location.reload());
            }
        }

        function load() {
            fetch("/chats").then(r=>r.json()).then(data => {
                const l = document.getElementById("list"); l.innerHTML = "";
                data.forEach(c => {
                    l.innerHTML += `<div class="chat-link" style="padding:10px; cursor:pointer;" onclick="openChat('${c[0]}')">${c[1]}</div>`;
                });
            });
        }
        load();
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
