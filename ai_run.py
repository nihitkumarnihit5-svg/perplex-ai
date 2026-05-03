from flask import Flask, request, jsonify, session, redirect, url_for
from authlib.integrations.flask_client import OAuth
from werkzeug.middleware.proxy_fix import ProxyFix
import sqlite3, time, requests, json, os
from datetime import timedelta

app = Flask(__name__)

# Railway/Production ke liye HTTPS fix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

app.secret_key = os.getenv("SECRET_KEY", "nihit_x_fire_ultra_pro_secure_key")
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

# ================= DATABASE (Sense + Memory) =================
def init_db():
    conn = sqlite3.connect("perplex_ai.db", check_same_thread=False)
    # Chat records
    conn.execute("CREATE TABLE IF NOT EXISTS chats(id TEXT, user TEXT, title TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS messages(chat_id TEXT, role TEXT, content TEXT)")
    # Personal Memory (Sirf wahi jo user yaad rakhne ko kahe)
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

# ================= AI ENGINE (The Sense Logic) =================
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")

def get_ai_response(msg, chat_id, user_email):
    try:
        # 1. Fetch Personal Memory (Only for specific identity)
        mem_res = db.execute("SELECT memory_data FROM user_memory WHERE user=?", (user_email,)).fetchone()
        personal_info = mem_res[0] if mem_res else "No personal details saved yet."

        # 2. Fetch Current Chat Context (Sense: focus on THIS conversation)
        history_rows = db.execute("SELECT role, content FROM messages WHERE chat_id=? ORDER BY rowid DESC LIMIT 8", (chat_id,)).fetchall()
        chat_history = [{"role": h[0], "content": h[1]} for h in reversed(history_rows)]

        # 3. Targeted System Prompt
        system_prompt = f"""
        Identity: You are 'Perplex AI', created by Nihit kr.
        Style: Speak in friendly Hinglish (Bhai, Bro, Theek hai).
        Sense: Focus deeply on the current chat history. Do not mix info from other chats.
        Personal Memory: {personal_info}
        
        Instruction: If the user gives personal info (like name, age, or preference) and says 'remember' or 'yaad rakhna', acknowledge it.
        """

        headers = {"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"}
        
        payload = {
            "model": "google/gemini-2.0-flash-001",
            "messages": [{"role": "system", "content": system_prompt}] + chat_history + [{"role": "user", "content": msg}],
            "temperature": 0.7
        }

        r = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=60)
        reply = r.json()["choices"][0]["message"]["content"]

        # 4. Smart Memory Save: Check if user wants to save something
        save_keywords = ["yaad rakhna", "remember", "mera naam", "i am", "my name"]
        if any(key in msg.lower() for key in save_keywords):
            current_mem = personal_info if personal_info != "No personal details saved yet." else ""
            new_entry = f"{msg}"
            updated_mem = f"{current_mem} | {new_entry}"[-500:] # Limit memory size
            db.execute("INSERT OR REPLACE INTO user_memory VALUES(?,?)", (user_email, updated_mem))
            db.commit()

        return reply
    except Exception as e: return f"Bhai, thoda error aa gaya: {str(e)}"

# ================= ROUTES (Fixed Login) =================

@app.route("/")
def index():
    if "user" in session: return redirect("/chat")
    return '''<body style="background:#0e0e0e; color:white; display:flex; flex-direction:column; align-items:center; justify-content:center; height:100vh; font-family:sans-serif;">
              <h1 style="font-size:42px; margin-bottom:10px;">PERPLEX AI</h1>
              <p style="color:#888; margin-bottom:30px;">Your Private Smart Assistant</p>
              <a href="/login" style="padding:15px 40px; background:#fff; color:#000; text-decoration:none; border-radius:50px; font-weight:bold; transition:0.3s;">Login with Google</a>
              </body>'''

@app.route("/login")
def login():
    # Production mein HTTPS scheme force karna zaroori hai redirect ke liye
    r_uri = url_for('callback', _external=True, _scheme='https')
    return google.authorize_redirect(r_uri)

@app.route("/callback")
def callback():
    try:
        token = google.authorize_access_token()
        user_info = google.get("https://www.googleapis.com/oauth2/v2/userinfo").json()
        session["user"] = user_info["email"]
        return redirect("/chat")
    except Exception as e:
        return f"Login Failed: {str(e)}"

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
    if not user: return jsonify({"error": "Login First"}), 401
    
    cid, msg = request.form.get("chat"), request.form.get("msg")
    if not cid or cid == "null":
        cid = str(int(time.time()*1000))
        db.execute("INSERT INTO chats VALUES(?,?,?)", (cid, user, msg[:30]))
    
    db.execute("INSERT INTO messages VALUES(?,?,?)", (cid, "user", msg))
    reply = get_ai_response(msg, cid, user)
    db.execute("INSERT INTO messages VALUES(?,?,?)", (cid, "assistant", reply))
    db.commit()
    
    return jsonify({"reply": reply, "chat_id": cid})

@app.route("/delete", methods=["POST"])
def delete_all():
    user = session.get("user")
    db.execute("DELETE FROM messages WHERE chat_id IN (SELECT id FROM chats WHERE user=?)", (user,))
    db.execute("DELETE FROM chats WHERE user=?", (user,))
    db.commit()
    return jsonify({"ok": True})

# ================= UI DESIGN =================
UI_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>PERPLEX AI</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        :root { --bg: #0e0e0e; --side: #171717; --acc: #3b82f6; }
        body { margin: 0; background: var(--bg); color: #ececec; font-family: -apple-system, sans-serif; display: flex; height: 100vh; }
        .sidebar { width: 260px; background: var(--side); display: flex; flex-direction: column; padding: 15px; border-right: 1px solid #262626; }
        .logo { font-size: 18px; font-weight: bold; color: var(--acc); margin-bottom: 20px; }
        .btn { background: #2f2f2f; padding: 12px; border-radius: 10px; text-align: center; cursor: pointer; font-size: 14px; margin-bottom: 10px; border: 1px solid #333; }
        .chat-list { flex: 1; overflow-y: auto; }
        .chat-item { padding: 10px; border-radius: 8px; cursor: pointer; font-size: 14px; color: #aaa; margin-bottom: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .chat-item:hover, .active { background: #212121; color: #fff; }
        .main { flex: 1; display: flex; flex-direction: column; position: relative; }
        .box { flex: 1; overflow-y: auto; padding: 30px 10%; display: flex; flex-direction: column; gap: 20px; }
        .msg { max-width: 85%; padding: 12px; border-radius: 15px; line-height: 1.5; font-size: 15px; }
        .user { align-self: flex-end; background: #2f2f2f; color: #fff; }
        .assistant { align-self: flex-start; color: #ececec; }
        .input-area { padding: 20px 10%; background: var(--bg); }
        .input-wrap { background: #212121; border-radius: 25px; padding: 8px 18px; display: flex; border: 1px solid #333; }
        input { flex: 1; background: transparent; border: none; color: #fff; outline: none; font-size: 16px; }
    </style>
</head>
<body>
    <div class="sidebar">
        <div class="logo">PERPLEX AI</div>
        <div class="btn" onclick="location.reload()">+ New Chat</div>
        <div class="chat-list" id="list"></div>
        <div class="btn" style="background:none; color:red;" onclick="clearHistory()">Clear History</div>
        <a href="/logout" style="text-decoration:none; color:#aaa; font-size:13px; text-align:center;">Logout</a>
    </div>
    <div class="main">
        <div class="box" id="box"></div>
        <div class="input-area">
            <div class="input-wrap">
                <input type="text" id="in" placeholder="Ask anything..." onkeypress="if(event.key=='Enter')send()">
                <button onclick="send()" style="background:none; border:none; color:var(--acc); font-size:20px; cursor:pointer;">➤</button>
            </div>
        </div>
    </div>
    <script>
        let cid = null;
        function send() {
            const i = document.getElementById("in"); if(!i.value) return;
            const b = document.getElementById("box");
            b.innerHTML += `<div class="msg user">${i.value}</div>`;
            const fd = new FormData(); fd.append("chat", cid); fd.append("msg", i.value);
            i.value = ""; b.scrollTop = b.scrollHeight;
            fetch("/send", {method:"POST", body:fd}).then(r=>r.json()).then(d => {
                cid = d.chat_id;
                b.innerHTML += `<div class="msg assistant">${d.reply.replace(/\\n/g, '<br>')}</div>`;
                b.scrollTop = b.scrollHeight;
                load();
            });
        }
        function load() {
            fetch("/chats").then(r=>r.json()).then(data => {
                const l = document.getElementById("list"); l.innerHTML = "";
                data.forEach(c => {
                    const item = document.createElement("div");
                    item.className = "chat-item" + (c[0]==cid?" active":"");
                    item.innerText = c[1];
                    item.onclick = () => {
                        cid = c[0];
                        fetch("/msgs?c="+cid).then(r=>r.json()).then(ms => {
                            b = document.getElementById("box"); b.innerHTML = "";
                            ms.forEach(m => { b.innerHTML += `<div class="msg ${m[0]}">${m[1]}</div>`; });
                            b.scrollTop = b.scrollHeight;
                        });
                    };
                    l.appendChild(item);
                });
            });
        }
        function clearHistory() { if(confirm("Delete all?")) fetch("/delete", {method:"POST"}).then(()=>location.reload()); }
        load();
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
