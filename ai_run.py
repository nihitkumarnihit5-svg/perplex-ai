from flask import Flask, request, jsonify, session, redirect, url_for
from authlib.integrations.flask_client import OAuth
import sqlite3, time, requests, os
from datetime import timedelta

app = Flask(__name__)
app.secret_key = "nihit_x_fire_simple_key"
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

# ================= DATABASE (Sirf Chat History ke liye) =================
def init_db():
    conn = sqlite3.connect("perplex_simple.db", check_same_thread=False)
    conn.execute("CREATE TABLE IF NOT EXISTS chats(id TEXT, user TEXT, title TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS messages(chat_id TEXT, role TEXT, content TEXT)")
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

# ================= AI ENGINE (Normal Mode) =================
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")

def get_ai_response(msg, chat_id, base64_image=None):
    try:
        # Normal Chat History (Context ke liye)
        history_rows = db.execute("SELECT role, content FROM messages WHERE chat_id=? ORDER BY rowid DESC LIMIT 8", (chat_id,)).fetchall()
        chat_history = [{"role": h[0], "content": h[1]} for h in reversed(history_rows)]

        headers = {"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"}
        
        # Simple System Prompt
        system_message = {"role": "system", "content": "You are Perplex AI, a helpful assistant created by Nihit kr. Give clear and direct answers."}
        
        user_content = [{"type": "text", "text": msg}]
        if base64_image:
            user_content.append({"type": "image_url", "image_url": {"url": base64_image}})

        payload = {
            "model": "google/gemini-2.0-flash-001",
            "messages": [system_message] + chat_history + [{"role": "user", "content": user_content}]
        }

        r = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=60)
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e: return f"Error: {str(e)}"

# ================= ROUTES =================

@app.route("/")
def index():
    if "user" in session: return redirect("/chat")
    return '<body style="background:#0e0e0e; color:white; display:flex; flex-direction:column; align-items:center; justify-content:center; height:100vh; font-family:sans-serif;"><h1>PERPLEX AI</h1><a href="/login" style="padding:12px 24px; background:#fff; color:#000; text-decoration:none; border-radius:30px; font-weight:bold;">Login with Google</a></body>'

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
    if not user: return jsonify({"error": "Unauthorized"}), 401
    
    cid = request.form.get("chat")
    msg = request.form.get("msg")
    img_data = request.form.get("image")

    if not cid or cid == "null":
        cid = str(int(time.time()*1000))
        db.execute("INSERT INTO chats VALUES(?,?,?)", (cid, user, msg[:30]))
    
    db.execute("INSERT INTO messages VALUES(?,?,?)", (cid, "user", msg))
    reply = get_ai_response(msg, cid, img_data)
    db.execute("INSERT INTO messages VALUES(?,?,?)", (cid, "assistant", reply))
    db.commit()
    
    return jsonify({"reply": reply, "chat_id": cid})

# ================= UI HTML =================
UI_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>PERPLEX AI</title>
    <style>
        body { margin: 0; background: #0e0e0e; color: #ececec; font-family: sans-serif; display: flex; height: 100vh; }
        .sidebar { width: 260px; background: #171717; padding: 15px; border-right: 1px solid #262626; display: flex; flex-direction: column; }
        .logo { font-size: 20px; font-weight: bold; color: #3b82f6; margin-bottom: 20px; }
        .chat-list { flex: 1; overflow-y: auto; }
        .chat-item { padding: 10px; border-radius: 8px; cursor: pointer; font-size: 14px; margin-bottom: 5px; color: #aaa; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .chat-item:hover { background: #212121; color: white; }
        .main { flex: 1; display: flex; flex-direction: column; }
        .box { flex: 1; overflow-y: auto; padding: 40px 15%; display: flex; flex-direction: column; gap: 20px; }
        .msg { max-width: 80%; padding: 12px; border-radius: 10px; line-height: 1.5; }
        .user { align-self: flex-end; background: #2f2f2f; }
        .assistant { align-self: flex-start; }
        .input-area { padding: 20px 15%; }
        .input-wrap { background: #212121; border-radius: 25px; padding: 10px 20px; display: flex; border: 1px solid #333; }
        input { flex: 1; background: transparent; border: none; color: white; outline: none; font-size: 16px; }
        button { background: none; border: none; color: #3b82f6; cursor: pointer; font-weight: bold; }
    </style>
</head>
<body>
    <div class="sidebar">
        <div class="logo">PERPLEX AI</div>
        <div class="chat-item" onclick="location.reload()">+ New Chat</div>
        <div class="chat-list" id="list"></div>
        <a href="/logout" style="color:#aaa; text-decoration:none; padding:10px;">Logout</a>
    </div>
    <div class="main">
        <div class="box" id="box"></div>
        <div class="input-area">
            <div class="input-wrap">
                <input type="text" id="in" placeholder="Type a message..." onkeypress="if(event.key=='Enter')send()">
                <button onclick="send()">Send</button>
            </div>
        </div>
    </div>
    <script>
        let cur = null;
        function send() {
            const i = document.getElementById("in");
            if(!i.value) return;
            document.getElementById("box").innerHTML += `<div class="msg user">${i.value}</div>`;
            const fd = new FormData(); fd.append("chat", cur); fd.append("msg", i.value);
            i.value = "";
            fetch("/send", {method:"POST", body:fd}).then(r=>r.json()).then(d => {
                cur = d.chat_id;
                document.getElementById("box").innerHTML += `<div class="msg assistant">${d.reply}</div>`;
                document.getElementById("box").scrollTop = 1000000;
                load();
            });
        }
        function load() {
            fetch("/chats").then(r=>r.json()).then(data => {
                const l = document.getElementById("list"); l.innerHTML = "";
                data.forEach(c => {
                    const d = document.createElement("div"); d.className = "chat-item"; d.innerText = c[1];
                    d.onclick = () => {
                        cur = c[0];
                        fetch("/msgs?c="+cur).then(r=>r.json()).then(ms => {
                            document.getElementById("box").innerHTML = "";
                            ms.forEach(m => { document.getElementById("box").innerHTML += `<div class="msg ${m[0]}">${m[1]}</div>`; });
                        });
                    };
                    l.appendChild(d);
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
