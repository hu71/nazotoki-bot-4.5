import os
from flask import Flask, request, abort, render_template, redirect, url_for
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage, ImageSendMessage
import requests

app = Flask(__name__)

# --- LINE設定 ---
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "00KCkQLhlaDFzo5+UTu+/C4A49iLmHu7bbpsfW8iamonjEJ1s88/wdm7Yrou+FazbxY7719UNGh96EUMa8QbsG Bf9K5rDWhJpq8XTxakXRuTM6HiJDSmERbIWfyfRMfscXJPcRyTL6YyGNZxqkYSAQdB04t89/1O/w1cDnyilFU=")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "6c12aedc292307f95ccd67e959973761")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# --- 問題データ（仮のストーリー、画像ID、ヒント） ---
PUZZLES = [
    {"story": "第1問：物語が始まる…", "image_id": "1GhjyvsaWP23x_wdz7n-nSqq5cziFcf1U", "hint_word": "apple", "hint": "赤くて甘い果物だよ"},
    {"story": "第2問：謎は深まる…", "image_id": "xxxxxx", "hint_word": "banana", "hint": "黄色くて長い果物だよ"},
    {"story": "第3問：不穏な気配…", "image_id": "xxxxxx", "hint_word": "cat", "hint": "よく鳴くペットだよ"},
    {"story": "第4問：核心に迫る…", "image_id": "xxxxxx", "hint_word": "dog", "hint": "散歩が大好きな動物だよ"},
    {"story": "第5問：最後の謎…", "image_id": "xxxxxx", "hint_word": "egg", "hint": "鳥が産む丸いものだよ"},
]

GOOD_ENDING = "おめでとう！GOODエンディングです！"
BAD_ENDING = "正解だけどBADエンディング…"
EPILOGUE = "終章：物語の幕が下りる…"
BONUS_PUZZLE = {"image_id": "xxxxxx"}

# --- 状態管理 ---
progress = {}        # user_id -> 現在の問題番号
last_image_id = {}   # user_id -> 画像のLINE message_id
user_images = {}     # user_id -> 画像ファイル名

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    user_id = event.source.user_id
    text = event.message.text.strip().lower()

    # startで開始
    if text == "start":
        progress[user_id] = 0
        send_puzzle(user_id)
        return

    # 現在の問題に対するヒント
    idx = progress.get(user_id, None)
    if idx is not None and idx < len(PUZZLES):
        if text == PUZZLES[idx]["hint_word"]:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"ヒント：{PUZZLES[idx]['hint']}"))
            return

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    user_id = event.source.user_id
    message_id = event.message.id

    # 画像を保存
    img_content = line_bot_api.get_message_content(message_id)
    file_path = f"static/{user_id}_{message_id}.jpg"
    with open(file_path, "wb") as f:
        for chunk in img_content.iter_content():
            f.write(chunk)

    last_image_id[user_id] = message_id
    user_images[user_id] = file_path

    # 判定中メッセージ
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="判定中です…"))

def send_puzzle(user_id):
    idx = progress[user_id]
    story = PUZZLES[idx]["story"]
    image_id = PUZZLES[idx]["image_id"]

    messages = [
        TextSendMessage(text=story),
        ImageSendMessage(
            original_content_url=f"https://drive.google.com/uc?id={image_id}",
            preview_image_url=f"https://drive.google.com/uc?id={image_id}"
        ),
        TextSendMessage(text="答えとなるものの写真を送ってね")
    ]
    line_bot_api.push_message(user_id, messages)

@app.route("/judge")
def judge():
    data = []
    for uid, file_path in user_images.items():
        name = f"User {uid[:6]}..."
        current_q = progress.get(uid, 0) + 1
        data.append({"user_id": uid, "name": name, "img_url": "/" + file_path, "q": current_q})
    return render_template("judge.html", users=data)

@app.route("/send/<user_id>/<result>")
def send_result(user_id, result):
    idx = progress.get(user_id, None)
    if idx is None:
        return redirect(url_for("judge"))

    if idx < 4:
        # 1〜4問目
        if result == "correct":
            line_bot_api.push_message(user_id, TextSendMessage(text="大正解！"))
            progress[user_id] += 1
            send_puzzle(user_id)
        else:
            line_bot_api.push_message(user_id, [TextSendMessage(text="残念。もう一度考えてみよう！"), TextSendMessage(text="〜と送ったら何かあるかも")])

    elif idx == 4:
        # 5問目
        if result == "good":
            line_bot_api.push_message(user_id, [TextSendMessage(text="大正解！"), TextSendMessage(text=GOOD_ENDING)])
            progress[user_id] += 1
            send_epilogue(user_id)
        elif result == "bad":
            line_bot_api.push_message(user_id, [TextSendMessage(text="正解！"), TextSendMessage(text=BAD_ENDING)])
            progress[user_id] += 1
            send_epilogue(user_id)
        else:
            line_bot_api.push_message(user_id, [TextSendMessage(text="残念。もう一度考えてみよう！"), TextSendMessage(text="〜と送ったら何かあるかも")])

    else:
        # おまけ問題
        if result == "correct":
            line_bot_api.push_message(user_id, [TextSendMessage(text="大正解！"), TextSendMessage(text="クリア特典があるよ。探偵事務所にお越しください。")])
        else:
            line_bot_api.push_message(user_id, [TextSendMessage(text="残念。もう一度考えてみよう！"), TextSendMessage(text="〜と送ったら何かあるかも")])

    return redirect(url_for("judge"))

def send_epilogue(user_id):
    messages = [
        TextSendMessage(text=EPILOGUE),
        ImageSendMessage(
            original_content_url=f"https://drive.google.com/uc?id={BONUS_PUZZLE['image_id']}",
            preview_image_url=f"https://drive.google.com/uc?id={BONUS_PUZZLE['image_id']}"
        ),
        TextSendMessage(text="答えとなる画像を送ってね")
    ]
    line_bot_api.push_message(user_id, messages)

if __name__ == "__main__":
    os.makedirs("static", exist_ok=True)
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
