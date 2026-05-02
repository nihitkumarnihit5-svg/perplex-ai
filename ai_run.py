from flask import Flask, request, jsonify, session, redirect, url_for
import sqlite3, time, requests, json, base64, os
from datetime import timedelta, datetime

app = Flask(__name__)
app.secret_key = "nihit_kr_anur_canvas_key"

# ================= DATABASE =================
def init_db():
    conn = sqlite3.connect("chat.db", check_same_thread=False)
    conn.execute("CREATE TABLE IF NOT EXISTS chats(id TEXT, user TEXT, title TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS messages(chat_id TEXT, role TEXT, content TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS usage_limits(user TEXT, date TEXT, msg_count INTEGER, img_count INTEGER, PRIMARY KEY(user, date))")
    conn.commit()
    return conn

db = init_db()

# ================= AI ENGINE (VISION SUPPORT) =================
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")

def get_ai_response(msg, base64_image=None):
    try:
        headers = {"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"}
        content_list = [{"type": "text", "text": msg}]
        
        if base64_image:
            if "base64," in base64_image:
                base64_data = base64_image.split("base64,")[1]
                mime_type = base64_image.split(":")[1].split(";")[0]
            else:
                base64_data = base64_image
                mime_type = "image/jpeg"
            content_list.append({"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_data}"}})

        payload = {
            "model": "google/gemini-2.0-flash-001",
            "messages": [
                {
                    "role": "system", 
                    "content": "Your name is Perplex AI. Created by Nihit kr. When someone asks who made you, always answer Nihit kr. You can see images and write code perfectly."
                },
                {"role": "user", "content": content_list}
            ]
        }
        
        r = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=60)
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"Error: {str(e)}"

# ================= ROUTES =================
@app.route("/")
def index():
    return UI_HTML

@app.route("/chats")
def get_chats():
    # Login hatne ki wajah se default 'guest' user use ho raha hai
    rows = db.execute("SELECT id, title FROM chats WHERE user=? ORDER BY id DESC", ("guest",)).fetchall()
    return jsonify(rows)

@app.route("/msgs")
def get_msgs():
    cid = request.args.get("c")
    rows = db.execute("SELECT role, content FROM messages WHERE chat_id=?", (cid,)).fetchall()
    return jsonify(rows)

@app.route("/send", methods=["POST"])
def send_msg():
    user = "guest"
    today = datetime.now().strftime('%Y-%m-%d')
    cid = request.form.get("chat")
    msg = request.form.get("msg")
    img_data = request.form.get("image")

    res = db.execute("SELECT msg_count, img_count FROM usage_limits WHERE user=? AND date=?", (user, today)).fetchone()
    m_count, i_count = (res[0], res[1]) if res else (0, 0)

    if m_count >= 100: return jsonify({"error": "Daily limit reached (100/100)"})

    if not cid or cid == "null" or cid == "":
        cid = str(int(time.time()*1000))
        db.execute("INSERT INTO chats VALUES(?,?,?)", (cid, user, msg[:30]))

    db.execute("INSERT INTO messages VALUES(?,?,?)", (cid, "user", msg))
    reply = get_ai_response(msg, img_data)
    db.execute("INSERT INTO messages VALUES(?,?,?)", (cid, "ai", reply))
    
    db.execute("INSERT OR REPLACE INTO usage_limits VALUES(?,?,?,?)", (user, today, m_count+1, i_count + (1 if img_data else 0)))
    db.commit()
    
    return jsonify({"reply": reply, "chat_id": cid, "usage": m_count+1})

# ================= UI HTML =================
# (Bhai, UI_HTML code wahi rahega jo aapne diya tha, bas session checks nikal gaye hain)
UI_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Perplex AI</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        :root { --bg: #131314; --side: #1e1f20; --active: #333537; --text: #e3e3e3; --blue: #8ab4f8; --red: #ff6b6b; --border: #333; }
        body{margin:0; display:flex; height:100vh; background:var(--bg); color:var(--text); font-family:sans-serif; overflow:hidden;}
        .sidebar{width:260px; background:var(--side); padding:15px; display:flex; flex-direction:column; border-right:1px solid var(--border); transition: 0.3s;}
        .new-btn{background:#2a2b2d; padding:12px; border-radius:30px; text-align:center; cursor:pointer; margin-bottom:15px; font-weight:bold; border:1px solid #444;}
        .chat-list{flex:1; overflow-y:auto; scrollbar-width:none;}
        .chat-item{padding:10px 15px; margin:4px 0; border-radius:20px; cursor:pointer; font-size:14px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;}
        .chat-item:hover, .chat-item.active{background:var(--active);}
        .main-section{ flex:1; display:flex; flex-direction:column; background:var(--bg); position: relative; }
        .msgs{flex:1; overflow-y:auto; padding:20px 15%; display:flex; flex-direction:column; gap:25px; scroll-behavior: smooth;}
        .msg{max-width:90%; line-height:1.6; font-size:16px; word-wrap: break-word;}
        .user{align-self:flex-end; background:#2a2b2d; padding:12px 20px; border-radius:22px;}
        .ai{align-self:flex-start; white-space:pre-wrap;}
        .input-container{padding:15px 15%; display:flex; flex-direction:column; align-items:center; gap:8px; border-top: 1px solid var(--border);}
        .input-bar{width:100%; max-width:850px; background:#1e1f20; border-radius:35px; padding:8px 20px; display:flex; align-items:center; border:1px solid #444;}
        input#userInput{flex:1; background:transparent; border:none; color:white; padding:12px; outline:none; font-size:16px;}
        .icon-btn{background:transparent; border:none; color:#aaa; cursor:pointer; font-size:20px; padding:5px; margin:0 5px;}
        .usage-bar{padding:8px 20px; font-size:12px; color:#777; display:flex; justify-content:space-between; position: absolute; top: 0; width: 100%; box-sizing: border-box;}
    </style>
</head>
<body>
<div class="sidebar">
    <div class="new-btn" onclick="startFresh()">+ New Chat</div>
    <div class="chat-list" id="chatList"></div>
</div>
<div class="main-section">
    <div class="usage-bar"><span id="usageStat">Usage: 0/100</span><span>Perplex AI | Nihit kr</span></div>
    <div class="msgs" id="chatBox">
        <div id="welcome" style="text-align:center; margin-top:20vh; opacity:0.5;">
            <h1 style="font-size: 40px;">Hello, I'm Perplex</h1>
            <p>I can help you with code, images, and more.</p>
        </div>
    </div>
    <div class="input-container">
        <div class="input-bar">
            <button class="icon-btn" onclick="document.getElementById('fileInput').click()">+</button>
            <input id="userInput" placeholder="Type a message..." onkeypress="if(event.key=='Enter')send()">
            <button class="icon-btn" id="sendBtn" onclick="send()" style="color:var(--blue);">➤</button>
        </div>
    </div>
</div>
<input type="file" id="fileInput" hidden accept="image/*" onchange="previewFile(this)">
<script>
    let activeChatId = "";
    let currentBase64 = null;
    
    function previewFile(input) { 
        if(input.files && input.files[0]) { 
            const reader = new FileReader(); 
            reader.onload = (e) => { currentBase64 = e.target.result; alert("Image attached!"); }; 
            reader.readAsDataURL(input.files[0]); 
        } 
    }

    function send() {
        const input = document.getElementById("userInput");
        const val = input.value.trim();
        if(!val && !currentBase64) return;
        const box = document.getElementById("chatBox");
        if(document.getElementById("welcome")) box.innerHTML = "";
        
        box.innerHTML += `<div class="msg user">${val}</div>`;
        input.value = "";
        box.scrollTop = box.scrollHeight;

        const fd = new FormData();
        fd.append("chat", activeChatId);
        fd.append("msg", val);
        if(currentBase64) fd.append("image", currentBase64);

        fetch("/send", {method:"POST", body:fd}).then(r=>r.json()).then(data => {
            if(data.error) { alert(data.error); return; }
            activeChatId = data.chat_id;
            box.innerHTML += `<div class="msg ai">${data.reply}</div>`;
            box.scrollTop = box.scrollHeight;
            document.getElementById("usageStat").innerText = `Usage: ${data.usage}/100`;
            currentBase64 = null;
            loadChatList();
        });
    }

    function loadChatList() {
        fetch("/chats").then(r=>r.json()).then(data => {
            const list = document.getElementById("chatList");
            list.innerHTML = "";
            data.forEach(c => {
                const item = document.createElement("div");
                item.className = `chat-item ${c[0]==activeChatId?'active':''}`;
                item.innerText = c[1];
                item.onclick = () => openChat(c[0]);
                list.appendChild(item);
            });
        });
    }

    function openChat(id) {
        activeChatId = id;
        fetch("/msgs?c="+id).then(r=>r.json()).then(msgs => {
            const box = document.getElementById("chatBox");
            box.innerHTML = "";
            msgs.forEach(m => { box.innerHTML += `<div class="msg ${m[0]}">${m[1]}</div>`; });
            box.scrollTop = box.scrollHeight;
        });
    }

    function startFresh() {
        activeChatId = "";
        document.getElementById("chatBox").innerHTML = '<div id="welcome" style="text-align:center; margin-top:20vh; opacity:0.5;"><h1>Perplex AI</h1><p>Created by Nihit kr</p></div>';
    }

    loadChatList();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
