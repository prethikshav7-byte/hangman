const alphabet = "abcdefghijklmnopqrstuvwxyz".split("");

const el = {
  userBadge: document.getElementById("user-badge"),
  themeToggle: document.getElementById("theme-toggle"),
  username: document.getElementById("username"),
  password: document.getElementById("password"),
  signupBtn: document.getElementById("signup-btn"),
  loginBtn: document.getElementById("login-btn"),
  logoutBtn: document.getElementById("logout-btn"),
  authStatus: document.getElementById("auth-status"),
  difficulty: document.getElementById("difficulty"),
  category: document.getElementById("category"),
  source: document.getElementById("source"),
  wordDisplay: document.getElementById("word-display"),
  attemptsLeft: document.getElementById("attempts-left"),
  score: document.getElementById("score"),
  correctLetters: document.getElementById("correct-letters"),
  wrongLetters: document.getElementById("wrong-letters"),
  newGameBtn: document.getElementById("new-game-btn"),
  hintBtn: document.getElementById("hint-btn"),
  aiHintBtn: document.getElementById("ai-hint-btn"),
  keyboard: document.getElementById("keyboard"),
  gameStatus: document.getElementById("game-status"),
  leaderboardList: document.getElementById("leaderboard-list"),
  roomCode: document.getElementById("room-code"),
  createRoomBtn: document.getElementById("create-room-btn"),
  joinRoomBtn: document.getElementById("join-room-btn"),
  roomWord: document.getElementById("room-word"),
  setRoomWordBtn: document.getElementById("set-room-word-btn"),
  roomStatus: document.getElementById("room-status")
};

const state = {
  guessed: [],
  correctLetters: [],
  wrongLetters: [],
  attemptsLeft: 6,
  display: [],
  gameOver: true,
  score: 0,
  room: ""
};

const socket = typeof window.io === "function" ? window.io() : null;

function playTone(freq, duration = 110) {
  const Ctx = window.AudioContext || window.webkitAudioContext;
  if (!Ctx) return;

  const ctx = new Ctx();
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();
  osc.type = "triangle";
  osc.frequency.value = freq;
  gain.gain.value = 0.03;
  osc.connect(gain);
  gain.connect(ctx.destination);
  osc.start();
  setTimeout(() => {
    osc.stop();
    ctx.close();
  }, duration);
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options
  });

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const error = new Error(data.error || "Request failed");
    error.status = res.status;
    throw error;
  }
  return data;
}

function setStatus(target, message, isError = false) {
  target.textContent = message || "";
  target.classList.toggle("error", Boolean(isError));
}

function renderWord(display) {
  el.wordDisplay.innerHTML = "";
  display.forEach((char) => {
    const tile = document.createElement("span");
    tile.className = "tile";
    tile.textContent = char === "_" ? "_" : char.toUpperCase();
    el.wordDisplay.appendChild(tile);
  });
}

function renderGuesses() {
  el.correctLetters.textContent = state.correctLetters.length ? state.correctLetters.join(", ") : "-";
  el.wrongLetters.textContent = state.wrongLetters.length ? state.wrongLetters.join(", ") : "-";
}

function renderKeyboard() {
  el.keyboard.innerHTML = "";
  alphabet.forEach((letter) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "key";
    btn.textContent = letter.toUpperCase();

    if (state.correctLetters.includes(letter)) btn.classList.add("correct");
    if (state.wrongLetters.includes(letter)) btn.classList.add("wrong");

    const used = state.guessed.includes(letter);
    btn.disabled = state.gameOver || used;
    btn.addEventListener("click", () => guessLetter(letter));
    el.keyboard.appendChild(btn);
  });
}

function applyGameData(data) {
  state.display = data.display || state.display;
  state.correctLetters = data.correct_letters || [];
  state.wrongLetters = data.wrong_letters || [];
  state.guessed = [...state.correctLetters, ...state.wrongLetters];
  state.attemptsLeft = data.attempts_left ?? state.attemptsLeft;
  state.gameOver = Boolean(data.won || data.lost);

  renderWord(state.display);
  renderGuesses();
  renderKeyboard();

  el.attemptsLeft.textContent = String(state.attemptsLeft);

  if (data.score_change && Number.isFinite(data.score_change)) {
    state.score += data.score_change;
    el.score.textContent = String(state.score);
  }

  if (data.won) {
    setStatus(el.gameStatus, "You won this round.");
    playTone(740);
  } else if (data.lost) {
    setStatus(el.gameStatus, `You lost. Word: ${data.word}`);
    playTone(220, 180);
  }
}

async function loadCategories() {
  try {
    const data = await api("/api/categories");
    el.category.innerHTML = "";
    data.categories.forEach((cat) => {
      const option = document.createElement("option");
      option.value = cat;
      option.textContent = cat[0].toUpperCase() + cat.slice(1);
      el.category.appendChild(option);
    });
    el.category.value = "general";
  } catch {
    setStatus(el.gameStatus, "Could not load categories.", true);
  }
}

async function loadMe() {
  try {
    const data = await api("/api/me");
    if (!data.authenticated) {
      el.userBadge.textContent = "Guest";
      state.score = 0;
      el.score.textContent = "0";
      return;
    }

    el.userBadge.textContent = data.username;
    state.score = data.score;
    el.score.textContent = String(data.score);
  } catch {
    setStatus(el.authStatus, "Auth check failed.", true);
  }
}

async function signup() {
  const username = el.username.value.trim();
  const password = el.password.value.trim();

  try {
    const data = await api("/api/signup", {
      method: "POST",
      body: JSON.stringify({ username, password })
    });
    setStatus(el.authStatus, `Welcome ${data.username}.`);
    await loadMe();
    await loadLeaderboard();
  } catch (error) {
    setStatus(el.authStatus, error.message, true);
  }
}

async function login() {
  const username = el.username.value.trim();
  const password = el.password.value.trim();

  try {
    const data = await api("/api/login", {
      method: "POST",
      body: JSON.stringify({ username, password })
    });
    setStatus(el.authStatus, `Logged in as ${data.username}.`);
    await loadMe();
    await loadLeaderboard();
  } catch (error) {
    setStatus(el.authStatus, error.message, true);
  }
}

async function logout() {
  try {
    await api("/api/logout", { method: "POST" });
    setStatus(el.authStatus, "Logged out.");
    await loadMe();
    await loadLeaderboard();
  } catch (error) {
    setStatus(el.authStatus, error.message, true);
  }
}

async function startGame() {
  try {
    setStatus(el.gameStatus, "Starting game...");
    const data = await api("/api/new-game", {
      method: "POST",
      body: JSON.stringify({
        difficulty: el.difficulty.value,
        category: el.category.value,
        source: el.source.value
      })
    });

    applyGameData(data);
    setStatus(el.gameStatus, "Game ready. Pick a letter.");
  } catch (error) {
    setStatus(el.gameStatus, error.message, true);
  }
}

async function guessLetter(letter) {
  if (state.guessed.includes(letter) || state.gameOver) return;

  try {
    const data = await api("/api/guess", {
      method: "POST",
      body: JSON.stringify({ letter })
    });
    applyGameData(data);
  } catch (error) {
    setStatus(el.gameStatus, error.message, true);
  }
}

async function useHint() {
  try {
    const data = await api("/api/hint", { method: "POST" });
    applyGameData(data);
    setStatus(el.gameStatus, `Hint revealed letter: ${data.hint_letter.toUpperCase()}`);
  } catch (error) {
    setStatus(el.gameStatus, error.message, true);
  }
}

async function askAiHint() {
  try {
    const data = await api("/api/ai-hint");
    setStatus(el.gameStatus, data.hint);
  } catch (error) {
    setStatus(el.gameStatus, error.message, true);
  }
}

async function loadLeaderboard() {
  try {
    const rows = await api("/api/leaderboard");
    el.leaderboardList.innerHTML = "";

    rows.forEach((row) => {
      const li = document.createElement("li");
      li.textContent = `${row.name} - ${row.score}`;
      el.leaderboardList.appendChild(li);
    });

    if (!rows.length) {
      const li = document.createElement("li");
      li.textContent = "No players yet";
      el.leaderboardList.appendChild(li);
    }
  } catch {
    el.leaderboardList.innerHTML = "<li>Leaderboard unavailable</li>";
  }
}

function createRoom() {
  if (!socket) {
    setStatus(el.roomStatus, "Multiplayer client is disabled in secure mode.", true);
    return;
  }
  socket.emit("create_room", { room: el.roomCode.value.trim() });
}

function joinRoom() {
  if (!socket) {
    setStatus(el.roomStatus, "Multiplayer client is disabled in secure mode.", true);
    return;
  }
  socket.emit("join_room", { room: el.roomCode.value.trim() });
}

function setRoomWord() {
  if (!socket) {
    setStatus(el.roomStatus, "Multiplayer client is disabled in secure mode.", true);
    return;
  }
  if (!state.room) {
    setStatus(el.roomStatus, "Create or join a room first.", true);
    return;
  }

  socket.emit("set_room_word", {
    room: state.room,
    word: el.roomWord.value.trim()
  });
}

function guessRoomLetter(letter) {
  if (!socket || !state.room) return;
  socket.emit("room_guess", { room: state.room, letter });
}

function bindSocketEvents() {
  if (!socket) {
    setStatus(el.roomStatus, "Multiplayer unavailable without local Socket.IO client.", true);
    return;
  }

  socket.on("room_created", (data) => {
    state.room = data.room;
    el.roomCode.value = data.room;
    setStatus(el.roomStatus, `Room created: ${data.room}`);
  });

  socket.on("room_joined", (data) => {
    state.room = data.room;
    setStatus(el.roomStatus, `Joined room: ${data.room}`);
  });

  socket.on("room_error", (data) => {
    setStatus(el.roomStatus, data.error || "Room error", true);
  });

  socket.on("room_state", (data) => {
    state.display = data.display || [];
    state.correctLetters = data.correct_letters || [];
    state.wrongLetters = data.wrong_letters || [];
    state.guessed = [...state.correctLetters, ...state.wrongLetters];
    state.attemptsLeft = data.attempts_left ?? 0;
    state.gameOver = Boolean(data.won || data.lost);

    renderWord(state.display);
    renderGuesses();
    el.attemptsLeft.textContent = String(state.attemptsLeft);

    el.keyboard.querySelectorAll("button").forEach((btn) => {
      const letter = btn.textContent.toLowerCase();
      btn.onclick = () => guessRoomLetter(letter);
      btn.disabled = state.gameOver || state.guessed.includes(letter);
      btn.classList.toggle("correct", state.correctLetters.includes(letter));
      btn.classList.toggle("wrong", state.wrongLetters.includes(letter));
    });

    if (data.won) setStatus(el.roomStatus, "Room game won.");
    if (data.lost) setStatus(el.roomStatus, `Room game over. Word: ${data.word}`);
  });
}

function initTheme() {
  const saved = localStorage.getItem("theme");
  if (saved === "dark") document.body.classList.add("dark");
}

function toggleTheme() {
  document.body.classList.toggle("dark");
  const mode = document.body.classList.contains("dark") ? "dark" : "light";
  localStorage.setItem("theme", mode);
}

function bindEvents() {
  el.signupBtn.addEventListener("click", signup);
  el.loginBtn.addEventListener("click", login);
  el.logoutBtn.addEventListener("click", logout);
  el.newGameBtn.addEventListener("click", startGame);
  el.hintBtn.addEventListener("click", useHint);
  el.aiHintBtn.addEventListener("click", askAiHint);
  el.createRoomBtn.addEventListener("click", createRoom);
  el.joinRoomBtn.addEventListener("click", joinRoom);
  el.setRoomWordBtn.addEventListener("click", setRoomWord);
  el.themeToggle.addEventListener("click", toggleTheme);

  document.addEventListener("keydown", (e) => {
    const letter = e.key.toLowerCase();
    if (!/^[a-z]$/.test(letter)) return;
    if (state.room) {
      guessRoomLetter(letter);
    } else {
      guessLetter(letter);
    }
  });
}

async function bootstrap() {
  initTheme();
  bindEvents();
  bindSocketEvents();
  renderKeyboard();
  await loadCategories();
  await loadMe();
  await loadLeaderboard();
  await startGame();
}

bootstrap();
