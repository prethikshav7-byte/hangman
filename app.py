from __future__ import annotations

import random
import string
from pathlib import Path

from flask import Flask, jsonify, render_template, request, session
from flask_login import (
    LoginManager,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_socketio import SocketIO, emit, join_room
from werkzeug.security import check_password_hash, generate_password_hash

from models import User, db, init_db

BASE_DIR = Path(__file__).resolve().parent
MAX_WRONG = 6
AI_WORDS = {
    "easy": ["cloud", "river", "stone", "bread", "light"],
    "medium": ["quantum", "network", "orchard", "harvest", "gallery"],
    "hard": ["synchrony", "astronomy", "framework", "pineapple", "algorithm"],
}


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(BASE_DIR / "templates"),
        static_folder=str(BASE_DIR / "static"),
    )

    app.config["SECRET_KEY"] = "hangman_secret_key"
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{BASE_DIR / 'database.db'}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    return app


app = create_app()
init_db(app)

socketio = SocketIO(app, async_mode="threading")
login_manager = LoginManager(app)


@app.after_request
def add_security_headers(response):
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self'; "
        "img-src 'self' data:; "
        "connect-src 'self' ws: wss:; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    return response


@login_manager.user_loader
def load_user(user_id: str):
    return db.session.get(User, int(user_id))


def load_words() -> list[str]:
    words_path = BASE_DIR / "words.txt"
    if not words_path.exists():
        raise FileNotFoundError(f"Could not find word list at {words_path}")

    with words_path.open("r", encoding="utf-8") as f:
        loaded_words = [w.strip().lower() for w in f.read().splitlines() if w.strip()]

    cleaned = [w for w in loaded_words if w.isalpha()]
    if not cleaned:
        raise ValueError("words.txt is empty or has no alphabetic words.")

    return sorted(set(cleaned))


WORDS = load_words()
CATEGORIES = {
    "general": WORDS,
    "animals": [
        "tiger",
        "rabbit",
        "dolphin",
        "giraffe",
        "penguin",
        "sparrow",
        "leopard",
        "octopus",
    ],
    "fruits": [
        "apple",
        "banana",
        "orange",
        "papaya",
        "mango",
        "pineapple",
        "watermelon",
        "strawberry",
    ],
    "technology": [
        "python",
        "backend",
        "frontend",
        "database",
        "socket",
        "compiler",
        "variable",
        "algorithm",
    ],
}

MP_ROOMS: dict[str, dict[str, object]] = {}


def filter_by_difficulty(words: list[str], difficulty: str) -> list[str]:
    if difficulty == "easy":
        return [w for w in words if len(w) <= 5]
    if difficulty == "medium":
        return [w for w in words if 5 < len(w) <= 8]
    return [w for w in words if len(w) > 8]


def pick_word(difficulty: str, category: str, use_ai: bool = False) -> str:
    if use_ai:
        return random.choice(AI_WORDS.get(difficulty, AI_WORDS["medium"]))

    base_words = CATEGORIES.get(category, CATEGORIES["general"])
    filtered = filter_by_difficulty(base_words, difficulty)

    if not filtered:
        filtered = filter_by_difficulty(CATEGORIES["general"], difficulty)
    if not filtered:
        filtered = CATEGORIES["general"]

    return random.choice(filtered)


def game_state(include_word: bool = False) -> dict[str, object]:
    word = session.get("word", "")
    correct = set(session.get("correct_letters", []))
    wrong = set(session.get("wrong_letters", []))
    attempts_left = MAX_WRONG - len(wrong)
    display = [ch if ch in correct else "_" for ch in word]
    won = word != "" and "_" not in display
    lost = word != "" and attempts_left <= 0

    return {
        "display": display,
        "correct_letters": sorted(correct),
        "wrong_letters": sorted(wrong),
        "attempts_left": attempts_left,
        "won": won,
        "lost": lost,
        "word": word if include_word or won or lost else None,
        "difficulty": session.get("difficulty", "medium"),
        "category": session.get("category", "general"),
        "hints_used": session.get("hints_used", 0),
    }


def update_user_score(points: int) -> None:
    if not current_user.is_authenticated:
        return
    current_user.score += points
    db.session.commit()


def ai_hint_for_word(word: str, revealed_letters: set[str]) -> str:
    hidden = [c for c in word if c not in revealed_letters]
    vowels = sum(1 for c in word if c in "aeiou")

    if len(hidden) >= len(word) - 1:
        return f"The word has {len(word)} letters and starts with '{word[0].upper()}'."
    if len(hidden) > 2:
        return f"The word has {vowels} vowel(s)."
    return f"The word ends with '{word[-1].upper()}'."


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/get-word/<difficulty>")
def get_word(difficulty: str):
    return jsonify({"word": pick_word(difficulty, "general")})


@app.route("/api/categories")
def categories():
    return jsonify({"categories": sorted(CATEGORIES.keys())})


@app.route("/api/me")
def me():
    if not current_user.is_authenticated:
        return jsonify({"authenticated": False})

    return jsonify(
        {
            "authenticated": True,
            "id": current_user.id,
            "username": current_user.username,
            "score": current_user.score,
        }
    )


@app.route("/api/signup", methods=["POST"])
def signup():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip().lower()
    password = (data.get("password") or "").strip()

    if len(username) < 3:
        return jsonify({"error": "Username must be at least 3 characters."}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters."}), 400

    if User.query.filter_by(username=username).first():
        return jsonify({"error": "Username already exists."}), 409

    user = User(username=username, password_hash=generate_password_hash(password))
    db.session.add(user)
    db.session.commit()

    login_user(user)
    return jsonify({"message": "User created", "username": user.username, "score": user.score})


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip().lower()
    password = (data.get("password") or "").strip()

    user = User.query.filter_by(username=username).first()
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({"error": "Invalid username or password."}), 401

    login_user(user)
    return jsonify({"message": "Logged in", "username": user.username, "score": user.score})


@app.route("/api/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return jsonify({"message": "Logged out"})


@app.route("/api/new-game", methods=["POST"])
def new_game():
    data = request.get_json(silent=True) or {}
    difficulty = (data.get("difficulty") or "medium").lower()
    category = (data.get("category") or "general").lower()
    source = (data.get("source") or "local").lower()

    if difficulty not in {"easy", "medium", "hard"}:
        difficulty = "medium"

    word = pick_word(difficulty, category, use_ai=(source == "ai"))

    session["word"] = word
    session["correct_letters"] = []
    session["wrong_letters"] = []
    session["difficulty"] = difficulty
    session["category"] = category
    session["hints_used"] = 0
    session["scored"] = False

    state = game_state()
    state["word_length"] = len(word)
    state["max_wrong"] = MAX_WRONG
    return jsonify(state)


@app.route("/api/guess", methods=["POST"])
def guess():
    data = request.get_json(silent=True) or {}
    letter = (data.get("letter") or "").lower().strip()

    if len(letter) != 1 or letter not in string.ascii_lowercase:
        return jsonify({"error": "Send a single letter (a-z)."}), 400

    word = session.get("word", "")
    if not word:
        return jsonify({"error": "Start a game first."}), 400

    correct = set(session.get("correct_letters", []))
    wrong = set(session.get("wrong_letters", []))

    if letter in correct or letter in wrong:
        return jsonify({"error": "Duplicate guess.", "duplicate": True}), 409

    if letter in word:
        correct.add(letter)
    else:
        wrong.add(letter)

    session["correct_letters"] = sorted(correct)
    session["wrong_letters"] = sorted(wrong)

    state = game_state()
    score_change = 0

    if (state["won"] or state["lost"]) and not session.get("scored", False):
        if state["won"]:
            hints_used = int(session.get("hints_used", 0))
            score_change = max(2, 10 - (2 * hints_used))
        else:
            score_change = -5

        update_user_score(score_change)
        session["scored"] = True

    state["score_change"] = score_change
    return jsonify(state)


@app.route("/api/hint", methods=["POST"])
def hint():
    word = session.get("word", "")
    if not word:
        return jsonify({"error": "Start a game first."}), 400

    state = game_state()
    if state["won"] or state["lost"]:
        return jsonify({"error": "Game is already finished."}), 400

    correct = set(session.get("correct_letters", []))
    unrevealed = [ch for ch in sorted(set(word)) if ch not in correct]

    if not unrevealed:
        return jsonify({"error": "No hint available."}), 400

    revealed = random.choice(unrevealed)
    correct.add(revealed)
    session["correct_letters"] = sorted(correct)
    session["hints_used"] = int(session.get("hints_used", 0)) + 1

    update_user_score(-2)

    state = game_state()
    state["hint_letter"] = revealed
    state["score_change"] = -2 if current_user.is_authenticated else 0
    return jsonify(state)


@app.route("/api/ai-word")
def ai_word():
    difficulty = (request.args.get("difficulty") or "medium").lower()
    return jsonify({"word": pick_word(difficulty, "general", use_ai=True)})


@app.route("/api/ai-hint")
def ai_hint():
    word = session.get("word", "")
    if not word:
        return jsonify({"error": "Start a game first."}), 400

    revealed = set(session.get("correct_letters", []))
    return jsonify({"hint": ai_hint_for_word(word, revealed)})


@app.route("/api/update-score", methods=["POST"])
@login_required
def update_score():
    data = request.get_json(silent=True) or {}
    points = int(data.get("points", 0))
    points = max(-100, min(100, points))

    update_user_score(points)
    return jsonify({"message": "Score updated", "score": current_user.score})


@app.route("/api/leaderboard")
def leaderboard():
    users = User.query.order_by(User.score.desc(), User.username.asc()).limit(10).all()
    return jsonify([{"name": u.username, "score": u.score} for u in users])


def room_state(room_code: str, include_word: bool = False) -> dict[str, object]:
    room = MP_ROOMS[room_code]
    word = room.get("word", "")
    correct = set(room.get("correct", set()))
    wrong = set(room.get("wrong", set()))
    attempts_left = MAX_WRONG - len(wrong)
    display = [c if c in correct else "_" for c in word] if word else []
    won = bool(word) and "_" not in display
    lost = bool(word) and attempts_left <= 0

    return {
        "room": room_code,
        "display": display,
        "correct_letters": sorted(correct),
        "wrong_letters": sorted(wrong),
        "attempts_left": attempts_left,
        "won": won,
        "lost": lost,
        "word": word if include_word or won or lost else None,
    }


@socketio.on("create_room")
def create_room_socket(data):
    room = ((data or {}).get("room") or "").strip().upper()
    if not room:
        room = "".join(random.choices("ABCDEFGHJKLMNPQRSTUVWXYZ23456789", k=5))

    MP_ROOMS[room] = {"word": "", "correct": set(), "wrong": set(), "host": request.sid}
    join_room(room)
    emit("room_created", {"room": room})


@socketio.on("join_room")
def join_room_socket(data):
    room = ((data or {}).get("room") or "").strip().upper()
    if room not in MP_ROOMS:
        emit("room_error", {"error": "Room not found."})
        return

    join_room(room)
    emit("room_joined", {"room": room})
    emit("room_state", room_state(room), to=room)


@socketio.on("set_room_word")
def set_room_word_socket(data):
    payload = data or {}
    room = (payload.get("room") or "").strip().upper()
    word = (payload.get("word") or "").strip().lower()

    if room not in MP_ROOMS:
        emit("room_error", {"error": "Room not found."})
        return

    if not word.isalpha() or len(word) < 3:
        emit("room_error", {"error": "Word must be alphabetic and >= 3 chars."})
        return

    MP_ROOMS[room]["word"] = word
    MP_ROOMS[room]["correct"] = set()
    MP_ROOMS[room]["wrong"] = set()
    emit("room_state", room_state(room), to=room)


@socketio.on("room_guess")
def room_guess_socket(data):
    payload = data or {}
    room = (payload.get("room") or "").strip().upper()
    letter = (payload.get("letter") or "").strip().lower()

    if room not in MP_ROOMS:
        emit("room_error", {"error": "Room not found."})
        return

    if len(letter) != 1 or letter not in string.ascii_lowercase:
        emit("room_error", {"error": "Guess must be one letter."})
        return

    room_data = MP_ROOMS[room]
    word = room_data.get("word", "")
    if not word:
        emit("room_error", {"error": "Set room word first."})
        return

    correct = set(room_data.get("correct", set()))
    wrong = set(room_data.get("wrong", set()))

    if letter in correct or letter in wrong:
        emit("room_error", {"error": "Duplicate guess."})
        return

    if letter in word:
        correct.add(letter)
    else:
        wrong.add(letter)

    room_data["correct"] = correct
    room_data["wrong"] = wrong

    emit("room_state", room_state(room), to=room)


if __name__ == "__main__":
    socketio.run(app, debug=True, allow_unsafe_werkzeug=True)
