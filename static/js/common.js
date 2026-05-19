const WALLET_KEY = "secat_coin_balance";
const STARTING_BALANCE = 500;

const ACHIEVEMENTS_KEY = "secat_achievements";
const LEADERBOARD_KEY = "secat_local_leaderboard";

const ACHIEVEMENTS = {
    first_win: {
        title: "First Win",
        description: "Win your first Higher or Lower round.",
        emoji: "🎯"
    },
    streak_3: {
        title: "Hot streak",
        description: "Reach a streak of 3.",
        emoji: "🔥"
    },
    streak_5: {
        title: "SECat GOAT",
        description: "Reach a streak of 5.",
        emoji: "🧠"
    },
    streak_10: {
        title: "SECaT Prophet",
        description: "Reach a streak of 10.",
        emoji: "🔮"
    },
    coin_collector: {
        title: "INSIDER???",
        description: "Reach 1,000 SECaT Coins.",
        emoji: "🪙"
    },
    rich_student: {
        title: "Rich Millionare",
        description: "Reach 5,000 SECaT Coins.",
        emoji: "💰"
    },
    first_bet: {
        title: "This is how it starts..",
        description: "Place your first prediction market bet.",
        emoji: "📈"
    },
    market_maker: {
        title: "Market Madness",
        description: "Place 5 prediction market bets.",
        emoji: "🏦"
    },
    live_trader: {
        title: "There it goes",
        description: "Place a bet in a live market.",
        emoji: "⚡"
    },
    big_spender: {
        title: "How did we get here",
        description: "Place a bet of 500 SC or more.",
        emoji: "🐋"
    },
    diamond_hands: {
        title: "Trust me bro",
        description: "Have 3 open bets at once.",
        emoji: "💎"
    },
    profit_hunter: {
        title: "We won, but at what price?",
        description: "Win a settled market bet.",
        emoji: "🚀"
    }
};

// ---------------------------------------------------------------------------
// Auth state
// ---------------------------------------------------------------------------

let _authUser = null;       // full user object from server, or null
let _authBalance = 0;       // cached balance for logged-in user
let _authAchievements = new Set();  // set of unlocked achievement IDs
let _authReady = false;     // true once initAuth() has resolved
let _currentAuthTab = "login";

function isLoggedIn() {
    return _authUser !== null;
}

function onAuthReady(cb) {
    if (_authReady) {
        cb();
    } else {
        document.addEventListener("authReady", cb, { once: true });
    }
}

function _setAuthUser(data) {
    _authUser = data;
    _authBalance = typeof data.balance === "number" ? data.balance : STARTING_BALANCE;
    _authAchievements = new Set(Array.isArray(data.achievements) ? data.achievements : []);
}

// ---------------------------------------------------------------------------
// Wallet
// ---------------------------------------------------------------------------

function getWalletBalance() {
    if (isLoggedIn()) {
        return _authBalance;
    }
    const stored = localStorage.getItem(WALLET_KEY);
    if (stored === null) {
        localStorage.setItem(WALLET_KEY, STARTING_BALANCE);
        return STARTING_BALANCE;
    }
    return Number(stored);
}

function setWalletBalance(amount) {
    const safeAmount = Math.max(0, Math.round(amount));
    if (isLoggedIn()) {
        const delta = safeAmount - _authBalance;
        _authBalance = safeAmount;
        updateWalletDisplay();
        checkWalletAchievements();
        _syncBalanceToServer(delta);
    } else {
        localStorage.setItem(WALLET_KEY, safeAmount);
        updateWalletDisplay();
        checkWalletAchievements();
    }
}

function addCoins(amount) {
    const current = getWalletBalance();
    setWalletBalance(current + amount);
}

function spendCoins(amount) {
    const current = getWalletBalance();
    if (amount > current) {
        return false;
    }
    setWalletBalance(current - amount);
    return true;
}

function updateWalletDisplay() {
    document.querySelectorAll(".wallet-balance").forEach(element => {
        element.innerText = getWalletBalance() + " SC";
    });
}

function _syncBalanceToServer(delta) {
    fetch("/api/user/balance", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ delta })
    }).then(r => r.json()).then(data => {
        if (typeof data.balance === "number") {
            _authBalance = data.balance;
            updateWalletDisplay();
        }
    }).catch(() => {});
}

// ---------------------------------------------------------------------------
// Achievements
// ---------------------------------------------------------------------------

function getUnlockedAchievements() {
    if (isLoggedIn()) {
        const result = {};
        _authAchievements.forEach(id => {
            result[id] = { unlockedAt: "server" };
        });
        return result;
    }
    const saved = localStorage.getItem(ACHIEVEMENTS_KEY);
    if (saved === null) {
        return {};
    }
    try {
        const parsed = JSON.parse(saved);
        return typeof parsed === "object" && parsed !== null ? parsed : {};
    } catch (error) {
        return {};
    }
}

function saveUnlockedAchievements(unlocked) {
    if (!isLoggedIn()) {
        localStorage.setItem(ACHIEVEMENTS_KEY, JSON.stringify(unlocked));
    }
}

function unlockAchievement(id) {
    const achievement = ACHIEVEMENTS[id];
    if (!achievement) {
        return;
    }

    if (isLoggedIn()) {
        if (_authAchievements.has(id)) {
            return;
        }
        _authAchievements.add(id);
        showAchievementToast(achievement);
        renderAchievementsPanel();
        _syncAchievementToServer(id);
    } else {
        const unlocked = getUnlockedAchievements();
        if (unlocked[id]) {
            return;
        }
        unlocked[id] = { unlockedAt: new Date().toISOString() };
        saveUnlockedAchievements(unlocked);
        showAchievementToast(achievement);
        renderAchievementsPanel();
    }
}

function _syncAchievementToServer(id) {
    fetch("/api/user/achievement", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id })
    }).catch(() => {});
}

function showAchievementToast(achievement) {
    let toast = document.getElementById("achievementToast");

    if (toast === null) {
        toast = document.createElement("div");
        toast.id = "achievementToast";
        toast.className = "achievement-toast";
        document.body.appendChild(toast);
    }

    toast.innerHTML = `
        <div class="achievement-toast-emoji">${achievement.emoji}</div>
        <div>
            <div class="achievement-toast-title">Achievement unlocked</div>
            <div class="achievement-toast-name">${achievement.title}</div>
            <div class="achievement-toast-desc">${achievement.description}</div>
        </div>
    `;

    toast.classList.add("show");

    setTimeout(() => {
        toast.classList.remove("show");
    }, 3300);
}

function renderAchievementsPanel() {
    const panel = document.getElementById("achievementsList");

    if (panel === null) {
        return;
    }

    const unlocked = getUnlockedAchievements();
    panel.innerHTML = "";

    Object.keys(ACHIEVEMENTS).forEach(id => {
        const achievement = ACHIEVEMENTS[id];
        const isUnlocked = Boolean(unlocked[id]);

        const item = document.createElement("div");
        item.className = isUnlocked
            ? "achievement-item unlocked"
            : "achievement-item locked";

        item.innerHTML = `
            <div class="achievement-emoji">${isUnlocked ? achievement.emoji : "🔒"}</div>
            <div>
                <div class="achievement-title">${achievement.title}</div>
                <div class="achievement-desc">${achievement.description}</div>
            </div>
        `;

        panel.appendChild(item);
    });
}

function checkWalletAchievements() {
    const balance = getWalletBalance();

    if (balance >= 1000) {
        unlockAchievement("coin_collector");
    }

    if (balance >= 5000) {
        unlockAchievement("rich_student");
    }
}

function resetAchievements() {
    if (!confirm("Reset all achievements?")) {
        return;
    }

    if (isLoggedIn()) {
        _authAchievements = new Set();
        fetch("/api/user/achievements", { method: "DELETE" }).catch(() => {});
    } else {
        localStorage.removeItem(ACHIEVEMENTS_KEY);
    }

    renderAchievementsPanel();
}

// ---------------------------------------------------------------------------
// Leaderboard / stats
// ---------------------------------------------------------------------------

function getLeaderboard() {
    if (isLoggedIn() && _authUser) {
        return {
            bestStreak:          _authUser.best_streak           || 0,
            totalCoinsEarned:    _authUser.total_coins_earned     || 0,
            biggestMarketProfit: _authUser.biggest_market_profit  || 0,
            totalBetsPlaced:     _authUser.total_bets_placed      || 0,
        };
    }

    const saved = localStorage.getItem(LEADERBOARD_KEY);
    if (saved === null) {
        return { bestStreak:0, totalCoinsEarned:0, biggestMarketProfit:0, totalBetsPlaced:0 };
    }

    try {
        const parsed = JSON.parse(saved);
        return {
            bestStreak:          Number(parsed.bestStreak          || 0),
            totalCoinsEarned:    Number(parsed.totalCoinsEarned    || 0),
            biggestMarketProfit: Number(parsed.biggestMarketProfit || 0),
            totalBetsPlaced:     Number(parsed.totalBetsPlaced     || 0)
        };
    } catch (error) {
        return { bestStreak:0, totalCoinsEarned:0, biggestMarketProfit:0, totalBetsPlaced:0 };
    }
}

function _saveGuestLeaderboard(leaderboard) {
    localStorage.setItem(LEADERBOARD_KEY, JSON.stringify(leaderboard));
    renderLeaderboard();
}

function _syncStatToServer(field, value) {
    fetch("/api/user/stat", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ field, value })
    }).catch(() => {});
}

function renderLeaderboard() {
    const leaderboard = getLeaderboard();

    const bestStreakElement      = document.getElementById("bestStreakValue");
    const totalCoinsElement      = document.getElementById("totalCoinsEarnedValue");
    const biggestProfitElement   = document.getElementById("biggestMarketProfitValue");
    const totalBetsElement       = document.getElementById("totalBetsPlacedValue");

    if (bestStreakElement !== null) {
        bestStreakElement.innerText = leaderboard.bestStreak;
    }

    if (totalCoinsElement !== null) {
        totalCoinsElement.innerText = Math.round(leaderboard.totalCoinsEarned) + " SC";
    }

    if (biggestProfitElement !== null) {
        biggestProfitElement.innerText = Math.round(leaderboard.biggestMarketProfit) + " SC";
    }

    if (totalBetsElement !== null) {
        totalBetsElement.innerText = leaderboard.totalBetsPlaced;
    }
}

function updateBestStreak(streak) {
    if (isLoggedIn()) {
        if (streak > (_authUser.best_streak || 0)) {
            _authUser.best_streak = streak;
            _syncStatToServer("best_streak", streak);
            renderLeaderboard();
        }
    } else {
        const lb = getLeaderboard();
        if (streak > lb.bestStreak) {
            lb.bestStreak = streak;
            _saveGuestLeaderboard(lb);
        }
    }
}

function addCoinsToLeaderboard(amount) {
    if (amount <= 0) {
        return;
    }

    if (isLoggedIn()) {
        _authUser.total_coins_earned = (_authUser.total_coins_earned || 0) + amount;
        _syncStatToServer("total_coins_earned", amount);
        renderLeaderboard();
    } else {
        const lb = getLeaderboard();
        lb.totalCoinsEarned += amount;
        _saveGuestLeaderboard(lb);
    }
}

function addBetToLeaderboard() {
    if (isLoggedIn()) {
        _authUser.total_bets_placed = (_authUser.total_bets_placed || 0) + 1;
        _syncStatToServer("total_bets_placed", 1);
        renderLeaderboard();
    } else {
        const lb = getLeaderboard();
        lb.totalBetsPlaced += 1;
        _saveGuestLeaderboard(lb);
    }
}

function updateBiggestMarketProfit(profit) {
    if (isLoggedIn()) {
        if (profit > (_authUser.biggest_market_profit || 0)) {
            _authUser.biggest_market_profit = profit;
            _syncStatToServer("biggest_market_profit", profit);
            renderLeaderboard();
        }
    } else {
        const lb = getLeaderboard();
        if (profit > lb.biggestMarketProfit) {
            lb.biggestMarketProfit = profit;
            _saveGuestLeaderboard(lb);
        }
    }
}

function resetLeaderboard() {
    if (!confirm("Reset your player statistics?")) {
        return;
    }

    if (isLoggedIn()) {
        _authUser.best_streak           = 0;
        _authUser.total_coins_earned    = 0;
        _authUser.biggest_market_profit = 0;
        _authUser.total_bets_placed     = 0;
        fetch("/api/user/stats", { method: "DELETE" }).catch(() => {});
    } else {
        localStorage.removeItem(LEADERBOARD_KEY);
    }

    renderLeaderboard();
}

// ---------------------------------------------------------------------------
// Auth modal
// ---------------------------------------------------------------------------

function _createAuthModal() {
    const existing = document.getElementById("authModal");
    if (existing) {
        return;
    }

    const modal = document.createElement("div");
    modal.id = "authModal";
    modal.className = "auth-modal-overlay";
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.setAttribute("aria-label", "Sign in or create account");
    modal.addEventListener("click", function(e) {
        if (e.target === modal) {
            closeAuthModal();
        }
    });

    modal.innerHTML = `
        <div class="auth-modal-card">
            <div class="auth-modal-header">
                <div class="brand">SECaT <span>Arcade</span></div>
                <button class="auth-modal-close" onclick="closeAuthModal()" aria-label="Close">✕</button>
            </div>
            <div class="auth-tabs">
                <button class="auth-tab active" id="loginTab" onclick="switchAuthTab('login')">Sign In</button>
                <button class="auth-tab" id="registerTab" onclick="switchAuthTab('register')">Create Account</button>
            </div>
            <p class="auth-modal-desc">Save your wallet, achievements, and stats permanently across sessions.</p>
            <div id="authError" class="auth-error" role="alert"></div>
            <div class="auth-form">
                <div class="auth-field">
                    <label for="authUsername">Username</label>
                    <input id="authUsername" type="text" placeholder="Choose a username" autocomplete="username" maxlength="30">
                </div>
                <div class="auth-field">
                    <label for="authPassword">Password</label>
                    <input id="authPassword" type="password" placeholder="Password" autocomplete="current-password">
                </div>
                <button class="primary-btn auth-submit-btn" id="authSubmitBtn" onclick="submitAuth()">Sign In</button>
            </div>
            <button class="auth-guest-btn" onclick="closeAuthModal()">Continue as Guest →</button>
            <p class="auth-disclaimer">
                A session cookie is set on sign-in. It is strictly necessary for authentication
                and does not require a consent banner under GDPR/ePrivacy.
                Guest progress is saved only in this browser via localStorage.
            </p>
        </div>
    `;

    document.body.appendChild(modal);

    document.addEventListener("keydown", function(e) {
        const m = document.getElementById("authModal");
        if (!m || !m.classList.contains("open")) {
            return;
        }
        if (e.key === "Escape") {
            closeAuthModal();
        }
        if (e.key === "Enter") {
            submitAuth();
        }
    });
}

function openAuthModal() {
    const modal = document.getElementById("authModal");
    if (!modal) {
        return;
    }
    _showAuthError("");
    modal.classList.add("open");
    setTimeout(() => {
        const input = document.getElementById("authUsername");
        if (input) {
            input.focus();
        }
    }, 50);
}

function closeAuthModal() {
    const modal = document.getElementById("authModal");
    if (modal) {
        modal.classList.remove("open");
    }
}

function switchAuthTab(tab) {
    _currentAuthTab = tab;
    const loginTab    = document.getElementById("loginTab");
    const registerTab = document.getElementById("registerTab");
    const submitBtn   = document.getElementById("authSubmitBtn");
    const pwInput     = document.getElementById("authPassword");

    if (loginTab)    loginTab.className    = tab === "login"    ? "auth-tab active" : "auth-tab";
    if (registerTab) registerTab.className = tab === "register" ? "auth-tab active" : "auth-tab";
    if (submitBtn)   submitBtn.textContent = tab === "login"    ? "Sign In" : "Create Account";
    if (pwInput)     pwInput.autocomplete  = tab === "login"    ? "current-password" : "new-password";

    _showAuthError("");
}

function _showAuthError(msg) {
    const el = document.getElementById("authError");
    if (el) {
        el.textContent = msg;
    }
}

async function submitAuth() {
    const username = (document.getElementById("authUsername").value || "").trim();
    const password =  document.getElementById("authPassword").value || "";

    if (!username) {
        _showAuthError("Enter a username.");
        return;
    }
    if (!password) {
        _showAuthError("Enter a password.");
        return;
    }

    const btn = document.getElementById("authSubmitBtn");
    if (btn) {
        btn.disabled = true;
        btn.textContent = "Please wait…";
    }
    _showAuthError("");

    try {
        if (_currentAuthTab === "login") {
            await _doLogin(username, password);
        } else {
            await _doRegister(username, password);
        }
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = _currentAuthTab === "login" ? "Sign In" : "Create Account";
        }
    }
}

async function _doLogin(username, password) {
    const resp = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password })
    });
    const data = await resp.json();
    if (!resp.ok) {
        _showAuthError(data.error || "Login failed.");
        return;
    }
    _setAuthUser(data);
    closeAuthModal();
    initialiseCommonUi();
    renderAuthUI();
}

async function _doRegister(username, password) {
    const resp = await fetch("/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password })
    });
    const data = await resp.json();
    if (!resp.ok) {
        _showAuthError(data.error || "Registration failed.");
        return;
    }
    _setAuthUser(data);
    closeAuthModal();
    initialiseCommonUi();
    renderAuthUI();
}

async function logOut() {
    await fetch("/api/auth/logout", { method: "POST" }).catch(() => {});
    _authUser         = null;
    _authBalance      = 0;
    _authAchievements = new Set();
    initialiseCommonUi();
    renderAuthUI();
}

function renderAuthUI() {
    const navBars = document.querySelectorAll(".nav-bar, .top-bar");

    navBars.forEach(nav => {
        let slot = nav.querySelector(".auth-slot");
        if (!slot) {
            slot = document.createElement("div");
            slot.className = "auth-slot";
            nav.appendChild(slot);
        }

        if (isLoggedIn()) {
            slot.innerHTML = `
                <span class="auth-username">👤 ${_authUser.username}</span>
                <button class="auth-btn-small" onclick="logOut()">Sign Out</button>
            `;
        } else {
            slot.innerHTML = `
                <button class="auth-btn-small" onclick="openAuthModal()">Sign In</button>
            `;
        }
    });
}

// ---------------------------------------------------------------------------
// Common init
// ---------------------------------------------------------------------------

function initialiseCommonUi() {
    updateWalletDisplay();
    renderAchievementsPanel();
    checkWalletAchievements();
    renderLeaderboard();
}

async function initAuth() {
    _createAuthModal();

    try {
        const resp = await fetch("/api/auth/me");
        const data = await resp.json();
        if (data.user) {
            _setAuthUser(data.user);
        }
    } catch (e) {
        // Network error — continue as guest
    }

    renderAuthUI();
    initialiseCommonUi();
    _authReady = true;
    document.dispatchEvent(new Event("authReady"));
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function wait(milliseconds) {
    return new Promise(resolve => {
        setTimeout(resolve, milliseconds);
    });
}

initAuth();
