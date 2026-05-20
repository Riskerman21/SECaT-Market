let currentMarket = null;
let currentMarketId = null;
let selectedSide = null;
let positions = [];

let marketOpen = false;

let liveHigherPrice = 50;
let liveLowerPrice = 50;
let marketVolume = 0;

let sseSource = null;

const SENTIMENT_COLOURS = {
    "strongly bullish": {
        bg:"rgba(5,46,22,.72)",
        border:"rgba(34,197,94,.35)",
        text:"#4ade80",
        price:"#4ade80"
    },
    bullish: {
        bg:"rgba(5,46,22,.48)",
        border:"rgba(34,197,94,.22)",
        text:"#86efac",
        price:"#86efac"
    },
    neutral: {
        bg:"rgba(2,6,23,.48)",
        border:"rgba(148,163,184,.18)",
        text:"#94a3b8",
        price:"#94a3b8"
    },
    bearish: {
        bg:"rgba(69,10,10,.48)",
        border:"rgba(239,68,68,.22)",
        text:"#fca5a5",
        price:"#fca5a5"
    },
    "strongly bearish": {
        bg:"rgba(69,10,10,.72)",
        border:"rgba(239,68,68,.38)",
        text:"#ef4444",
        price:"#ef4444"
    }
};

// ---------------------------------------------------------------------------
// SSE feed
// ---------------------------------------------------------------------------

function startSSEFeed() {
    if (sseSource) {
        sseSource.close();
        sseSource = null;
    }

    const dot = document.getElementById("sseDot");
    if (dot) dot.className = "sentiment-sse-dot";

    sseSource = new EventSource("/api/trade-feed");

    sseSource.onopen = () => {
        const d = document.getElementById("sseDot");
        if (d) d.className = "sentiment-sse-dot live";
    };

    sseSource.onmessage = event => {
        try {
            const trade = JSON.parse(event.data);
            updateSentimentFromSSE(trade);
            appendSSETradeToFeed(trade);
        } catch (_) {}
    };

    sseSource.onerror = () => {
        const d = document.getElementById("sseDot");
        if (d) d.className = "sentiment-sse-dot";
    };
}

function stopSSEFeed() {
    if (sseSource) {
        sseSource.close();
        sseSource = null;
    }
    const d = document.getElementById("sseDot");
    if (d) d.className = "sentiment-sse-dot";
}

function updateSentimentFromSSE(trade) {
    const card  = document.getElementById("sentimentCard");
    const text  = document.getElementById("sentimentText");
    const price = document.getElementById("impliedPrice");
    const bar   = document.getElementById("sentimentBar");

    if (!card || !text || !price || !bar) return;

    const sentiment  = trade.sentiment || "neutral";
    const impliedPrice = Number(trade.implied_price || 50);
    const colours    = SENTIMENT_COLOURS[sentiment] || SENTIMENT_COLOURS.neutral;

    card.style.background  = colours.bg;
    card.style.borderColor = colours.border;
    text.style.color       = colours.text;
    text.textContent       = sentiment;
    price.style.color      = colours.price;
    price.textContent      = impliedPrice.toFixed(1) + "¢";
    bar.style.width        = impliedPrice + "%";
}

function appendSSETradeToFeed(trade) {
    if (!currentMarketId || trade.market_id !== currentMarketId) return;

    const list = document.getElementById("activityFeedList");
    if (!list) return;

    if (list.dataset.empty === "true") {
        list.innerHTML = "";
        list.dataset.empty = "false";
    }

    const row = document.createElement("div");
    row.className = "trade-entry trade-entry-new";

    const dirClass = trade.direction === "higher" ? "trade-buy" : "trade-sell";
    const dirLabel = trade.direction === "higher" ? "HIGHER" : "LOWER";

    row.innerHTML = `
        <span>
            <span class="${dirClass}">${dirLabel}</span>
            <span style="color:#94a3b8;font-size:12px;">${Number(trade.stake).toFixed(0)} SC</span>
        </span>
        <span>${impliedPriceLabel(trade.implied_price)}</span>
    `;

    list.prepend(row);
    while (list.children.length > 8) list.removeChild(list.lastChild);

    updateSentimentFromSSE(trade);
    liveHigherPrice = Math.round(Math.max(5, Math.min(95, trade.implied_price)));
    liveLowerPrice  = 100 - liveHigherPrice;
    updateLivePrices();
    updateTradeSummary();
    marketVolume += Number(trade.stake);
    const vol = document.getElementById("marketVolume");
    if (vol) vol.innerText = Math.round(marketVolume) + " SC";
}

function impliedPriceLabel(p) {
    return Number(p).toFixed(1) + "¢";
}

function initSentiment(price) {
    const s = price >= 70 ? "strongly bullish"
            : price >= 55 ? "bullish"
            : price >= 45 ? "neutral"
            : price >= 30 ? "bearish"
            : "strongly bearish";
    updateSentimentFromSSE({ implied_price: price, sentiment: s });
}

// ---------------------------------------------------------------------------
// Price chart
// ---------------------------------------------------------------------------

const CHART_ANIM_MS = 500;
let chartPoints = [];
let pendingPoint = null;
let animatingTo  = null;
let rafId        = null;

function lerp(a, b, t) { return a + (b - a) * t; }
function easeOut(t) { return 1 - Math.pow(1 - t, 3); }

function priceToY(price) {
    const clamp = Math.max(5, Math.min(95, price));
    return 220 - ((clamp - 5) / 90) * 220;
}

function buildSVGPath(pts) {
    if (pts.length === 0) return { line:"", fill:"" };

    const width  = 700;
    const coords = pts.map((p, i) => ({
        x: pts.length === 1 ? 0 : (i / (pts.length - 1)) * width,
        y: priceToY(p)
    }));

    let line = `M ${coords[0].x} ${coords[0].y}`;
    for (let i = 1; i < coords.length; i++) {
        const prev = coords[i - 1];
        const curr = coords[i];
        const cpX  = (prev.x + curr.x) / 2;
        line += ` C ${cpX} ${prev.y} ${cpX} ${curr.y} ${curr.x} ${curr.y}`;
    }

    const last  = coords[coords.length - 1];
    const first = coords[0];
    const fill  = line + ` L ${last.x} 220 L ${first.x} 220 Z`;

    return { line, fill };
}

function drawAnimatedChart(ts) {
    rafId = requestAnimationFrame(drawAnimatedChart);

    const lineEl = document.getElementById("priceChartLine");
    const fillEl = document.getElementById("priceChartFill");
    if (!lineEl || !fillEl) return;

    if (pendingPoint !== null && animatingTo === null) {
        const from = chartPoints.length > 0
            ? chartPoints[chartPoints.length - 1]
            : pendingPoint;
        animatingTo  = { from, to: pendingPoint, startTs: ts };
        pendingPoint = null;
    }

    let displayPts = [...chartPoints];

    if (animatingTo !== null) {
        const elapsed  = ts - animatingTo.startTs;
        const progress = Math.min(elapsed / CHART_ANIM_MS, 1);
        const eased    = easeOut(progress);
        const current  = lerp(animatingTo.from, animatingTo.to, eased);

        displayPts = [...displayPts, current];

        if (progress >= 1) {
            chartPoints.push(animatingTo.to);
            if (chartPoints.length > 40) chartPoints.shift();
            animatingTo = null;
        }
    }

    if (displayPts.length < 1) return;

    const path = buildSVGPath(displayPts);
    lineEl.setAttribute("d", path.line);
    fillEl.setAttribute("d", path.fill);
}

function startChartLoop() {
    if (rafId) cancelAnimationFrame(rafId);
    rafId = requestAnimationFrame(drawAnimatedChart);
}

function stopChartLoop() {
    if (rafId) {
        cancelAnimationFrame(rafId);
        rafId = null;
    }
}

function resetPriceChart() {
    chartPoints  = [Number(liveHigherPrice)];
    pendingPoint = null;
    animatingTo  = null;
    startChartLoop();

    const cur = document.getElementById("chartCurrentPrice");
    if (cur) cur.innerText = liveHigherPrice + "¢";
}

function addPricePoint(price) {
    pendingPoint = Number(price);
    const cur = document.getElementById("chartCurrentPrice");
    if (cur) cur.innerText = price + "¢";
}

// ---------------------------------------------------------------------------
// Market browser
// ---------------------------------------------------------------------------

let allMarkets = [];

async function loadMarkets() {
    const grid = document.getElementById("marketGrid");
    if (!grid) return;

    grid.innerHTML = '<div class="market-loading">Loading markets…</div>';

    try {
        const resp = await fetch("/api/markets");
        if (!resp.ok) throw new Error("API failed");
        const data = await resp.json();
        allMarkets = data.markets || [];

        if (allMarkets.length === 0) {
            grid.innerHTML = '<div class="market-empty">No markets available yet.</div>';
            return;
        }

        applyFiltersAndSort();
    } catch (_) {
        grid.innerHTML = '<div class="market-empty">Could not load markets.</div>';
    }
}

function applyFiltersAndSort() {
    const query  = (document.getElementById("marketSearch")?.value || "").toLowerCase().trim();
    const status = document.querySelector(".filter-pill.active")?.dataset.status || "all";
    const sort   = document.getElementById("marketSort")?.value || "newest";

    let markets = allMarkets.filter(m => {
        if (status !== "all" && m.status !== status) return false;
        if (!query) return true;
        return m.course_code.toLowerCase().includes(query) ||
               (m.question_name || "").toLowerCase().includes(query);
    });

    if (sort === "course_az") {
        markets = markets.slice().sort((a, b) => a.course_code.localeCompare(b.course_code));
    } else if (sort === "price_high") {
        markets = markets.slice().sort((a, b) => b.current_price - a.current_price);
    } else if (sort === "price_low") {
        markets = markets.slice().sort((a, b) => a.current_price - b.current_price);
    }
    // "newest" keeps the API order (DESC created_at)

    renderMarkets(markets);
}

function setStatusFilter(btn) {
    document.querySelectorAll(".filter-pill").forEach(p => p.classList.remove("active"));
    btn.classList.add("active");
    applyFiltersAndSort();
}

function renderMarkets(markets) {
    const grid  = document.getElementById("marketGrid");
    const count = document.getElementById("marketCount");
    if (!grid) return;

    const total = allMarkets.length;
    if (count) {
        count.textContent = markets.length === total
            ? `${total} market${total !== 1 ? "s" : ""}`
            : `${markets.length} of ${total} markets`;
    }

    if (markets.length === 0) {
        grid.innerHTML = '<div class="market-empty">No markets match your search.</div>';
        return;
    }

    grid.innerHTML = "";

    markets.forEach(market => {
        const card = document.createElement("div");
        card.className = "market-card";
        if (market.status !== "open") card.classList.add("market-resolved");

        const price      = Math.round(Math.max(5, Math.min(95, market.current_price)));
        const priceClass = price >= 50 ? "price-higher" : "price-lower";
        const statusText = market.status === "open" ? "Open" : "Resolved";

        card.innerHTML = `
            <div class="market-card-course">${market.course_code}</div>
            <div class="market-card-question">${market.question_name || "Market question"}</div>
            <div class="market-card-footer">
                <span class="${priceClass}">${price}¢</span>
                <span class="market-card-status">${statusText}</span>
            </div>
            <div class="market-card-upcoming">Sem ${market.upcoming_sem} · ${market.upcoming_year}</div>
        `;

        if (market.status === "open") {
            card.onclick = () => openMarket(market.id);
            card.style.cursor = "pointer";
        }

        grid.appendChild(card);
    });
}

async function openMarket(marketId) {
    try {
        const resp = await fetch(`/api/markets/${marketId}`);
        if (!resp.ok) return;
        const row = await resp.json();

        currentMarket   = row;
        currentMarketId = marketId;
        selectedSide    = null;
        marketVolume    = 0;
        marketOpen      = row.status === "open";

        liveHigherPrice = Math.round(Math.max(5, Math.min(95, row.current_price)));
        liveLowerPrice  = 100 - liveHigherPrice;

        document.getElementById("browserSection").style.display = "none";
        document.getElementById("marketSection").style.display  = "block";
        document.getElementById("marketSection").classList.add("fade-in");

        renderMarketFromRow(row);
        renderGuestOverlay();
        resetSelectionUI();
        resetPriceChart();
        updateLivePrices();
        updateTradeSummary();
        updateWalletDisplay();
        renderLeaderboard();
        initSentiment(liveHigherPrice);

        await loadMarketActivity();
        startSSEFeed();

        await loadSavedPositions();
        renderPositions();
    } catch (err) {
        console.error("openMarket failed:", err);
    }
}

// ---------------------------------------------------------------------------
// Market rendering
// ---------------------------------------------------------------------------

function renderMarketFromRow(row) {
    const prediction   = Number(row.initial_prediction);
    const upcomingLabel = `Semester ${row.upcoming_sem}, ${row.upcoming_year}`;

    document.getElementById("courseCode").innerText    = row.course_code;
    document.getElementById("courseName").innerText    = row.name || row.course_code;
    document.getElementById("marketBadge").innerText   = upcomingLabel;

    document.getElementById("marketQuestion").innerHTML =
        `Will <strong>${row.course_code}</strong> in <strong>${upcomingLabel}</strong> have more than ` +
        `<strong>${prediction.toFixed(2)}%</strong> of students selecting ` +
        `<strong>${row.answer || "Strongly Agree"}</strong> for ` +
        `<strong>${row.question_name || "Q8: Overall Rating"}</strong>?`;

    document.getElementById("upcomingGuessMain").innerText   = upcomingLabel;
    document.getElementById("upcomingGuessReason").innerText =
        `Upcoming offering: Sem ${row.upcoming_sem}, ${row.upcoming_year}`;

    document.getElementById("predictionValue").innerText =
        prediction.toFixed(2) + "%";
    document.getElementById("confidenceValue").innerText =
        (row.confidence || 50) + "/100";
    document.getElementById("historyCount").innerText =
        row.history_count != null ? row.history_count
        : (row.history ? row.history.length : "--");

    const status = document.getElementById("liveStatus");
    const timer  = document.getElementById("marketTimer");
    const volume = document.getElementById("marketVolume");
    if (status) status.innerText = row.status === "open" ? "Open" : "Resolved";
    if (timer)  timer.innerText  = "∞";
    if (volume) volume.innerText = "0 SC";

    if (row.history && row.history.length > 0) {
        renderHistory(row);
        renderMiniChart(row);
    } else {
        const historyList = document.getElementById("historyList");
        if (historyList) historyList.innerHTML = '<div class="empty">No historical data available.</div>';
        const miniChart = document.getElementById("miniChart");
        if (miniChart) miniChart.innerHTML = "";
    }

    document.getElementById("higherButton").disabled = !marketOpen;
    document.getElementById("lowerButton").disabled  = !marketOpen;
}

function renderGuestOverlay() {
    const overlay = document.getElementById("guestTradeOverlay");
    const form    = document.getElementById("tradeForm");
    if (!overlay || !form) return;

    if (isLoggedIn()) {
        overlay.style.display = "none";
        form.style.display    = "block";
    } else {
        overlay.style.display = "block";
        form.style.display    = "none";
    }
}

function renderHistory(market) {
    const historyList = document.getElementById("historyList");
    if (!historyList) return;
    historyList.innerHTML = "";

    const history = market.history || [];
    if (history.length === 0) {
        historyList.innerHTML = '<div class="empty">No history available.</div>';
        return;
    }

    history.forEach(item => {
        const row = document.createElement("div");
        row.className = "history-row";
        row.innerHTML = `
            <div>${item.offering}</div>
            <div class="history-percent">${Number(item.percent).toFixed(2)}%</div>
            <div>${item.count}/${item.answered}</div>
        `;
        historyList.appendChild(row);
    });
}

function renderMiniChart(market) {
    const chart = document.getElementById("miniChart");
    if (!chart) return;
    chart.innerHTML = "";

    const history = [...(market.history || [])].reverse();
    history.forEach(item => {
        const percent = Number(item.percent);
        const wrap  = document.createElement("div");
        wrap.className = "bar-wrap";

        const bar = document.createElement("div");
        bar.className    = "bar";
        bar.style.height = Math.max(4, percent) + "%";
        bar.title        = percent.toFixed(2) + "%";

        const label = document.createElement("div");
        label.className  = "bar-label";
        label.innerText  = `S${item.sem} ${item.year}`;

        wrap.appendChild(bar);
        wrap.appendChild(label);
        chart.appendChild(wrap);
    });
}

// ---------------------------------------------------------------------------
// Trade panel
// ---------------------------------------------------------------------------

function selectSide(side) {
    if (currentMarket === null || !marketOpen) return;

    selectedSide = side;
    resetSelectionUI();

    if (side === "higher") {
        document.getElementById("higherCard").classList.add("selected");
        document.getElementById("higherButton").classList.add("selected-higher");
        document.getElementById("selectedSideValue").innerText = "Higher";
    } else {
        document.getElementById("lowerCard").classList.add("selected");
        document.getElementById("lowerButton").classList.add("selected-lower");
        document.getElementById("selectedSideValue").innerText = "Lower";
    }

    document.getElementById("placeTradeButton").disabled = false;
    updateTradeSummary();
}

function resetSelectionUI() {
    document.getElementById("higherCard").classList.remove("selected");
    document.getElementById("lowerCard").classList.remove("selected");
    document.getElementById("higherButton").classList.remove("selected-higher");
    document.getElementById("lowerButton").classList.remove("selected-lower");
    document.getElementById("selectedSideValue").innerText  = "--";
    document.getElementById("placeTradeButton").disabled    = true;
    document.getElementById("selectedPrice").innerText      = "--";
    document.getElementById("estimatedShares").innerText    = "--";
    document.getElementById("potentialPayout").innerText    = "--";
    document.getElementById("potentialProfit").innerText    = "--";
}

function updateTradeSummary() {
    if (currentMarket === null || selectedSide === null) return;

    const stake              = Number(document.getElementById("stakeInput").value || 0);
    const selectedPriceCents = selectedSide === "higher" ? liveHigherPrice : liveLowerPrice;
    const selectedPrice      = selectedPriceCents / 100;

    if (stake <= 0 || selectedPrice <= 0) return;

    const shares = stake / selectedPrice;
    const payout = shares;
    const profit = payout - stake;

    document.getElementById("selectedPrice").innerText    = selectedPriceCents + "¢";
    document.getElementById("estimatedShares").innerText  = shares.toFixed(2);
    document.getElementById("potentialPayout").innerText  = payout.toFixed(2) + " SC";
    document.getElementById("potentialProfit").innerText  = profit.toFixed(2) + " SC";
}

function updateLivePrices() {
    document.getElementById("higherPrice").innerText = liveHigherPrice + "¢";
    document.getElementById("lowerPrice").innerText  = liveLowerPrice  + "¢";
    addPricePoint(liveHigherPrice);
}

// ---------------------------------------------------------------------------
// Market activity feed
// ---------------------------------------------------------------------------

async function loadMarketActivity() {
    const list = document.getElementById("activityFeedList");
    if (!list || currentMarketId === null) return;

    try {
        const resp = await fetch(`/api/markets/${currentMarketId}/positions`);
        if (!resp.ok) throw new Error();
        const data   = await resp.json();
        const trades = (data.positions || []).slice(0, 8);

        if (trades.length === 0) {
            list.innerText      = "No trades yet — be the first!";
            list.dataset.empty  = "true";
            return;
        }

        list.innerHTML     = "";
        list.dataset.empty = "false";

        trades.forEach(pos => {
            const row      = document.createElement("div");
            row.className  = "trade-entry";
            const dirClass = pos.side === "higher" ? "trade-buy" : "trade-sell";
            const ts       = pos.created_at ? new Date(pos.created_at).toLocaleTimeString() : "";
            row.innerHTML  = `
                <span>
                    <span class="${dirClass}">${pos.side.toUpperCase()}</span>
                    <span style="color:#94a3b8;font-size:12px;">${Number(pos.stake).toFixed(0)} SC</span>
                </span>
                <span>${Number(pos.price_cents).toFixed(0)}¢ · ${ts}</span>
            `;
            list.appendChild(row);
        });

        marketVolume = trades.reduce((sum, p) => sum + Number(p.stake), 0);
        const vol = document.getElementById("marketVolume");
        if (vol) vol.innerText = Math.round(marketVolume) + " SC";
    } catch (_) {
        list.innerText     = "No trades yet — be the first!";
        list.dataset.empty = "true";
    }
}

// ---------------------------------------------------------------------------
// Positions
// ---------------------------------------------------------------------------

async function placeTrade() {
    if (currentMarketId === null) return;
    if (selectedSide === null) return;

    if (!isLoggedIn()) {
        openAuthModal();
        return;
    }

    if (!marketOpen) {
        alert("Trading window is closed.");
        return;
    }

    const stake = Number(document.getElementById("stakeInput").value || 0);
    if (stake <= 0) {
        alert("Enter a stake greater than zero.");
        return;
    }

    if (stake > getWalletBalance()) {
        alert("Not enough SECaT Coins. Play Higher or Lower to earn more.");
        return;
    }

    try {
        const response = await fetch(`/api/markets/${currentMarketId}/trade`, {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify({ direction: selectedSide, stake }),
        });

        if (response.status === 401) {
            openAuthModal();
            return;
        }

        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            alert(err.error || "Trade failed.");
            return;
        }

        const data = await response.json();

        if (typeof data.new_balance === "number") {
            _authBalance = data.new_balance;
            updateWalletDisplay();
        }

        const newHigherPrice = Math.round(Math.max(5, Math.min(95, data.new_price)));
        liveHigherPrice = newHigherPrice;
        liveLowerPrice  = 100 - liveHigherPrice;

        const priceCents = selectedSide === "higher" ? liveHigherPrice : liveLowerPrice;
        const pos        = data.position || {};

        positions.push({
            id:          Date.now().toString() + "_" + Math.random().toString(16).slice(2),
            createdAt:   new Date().toISOString(),
            course:      currentMarket.course_code,
            courseName:  currentMarket.course_code,
            question:    currentMarket.question_name,
            questionNum: currentMarket.question_num,
            answer:      currentMarket.answer,
            answerNum:   currentMarket.answer_num,
            prediction:  currentMarket.initial_prediction,
            upcoming:    `Sem ${currentMarket.upcoming_sem} ${currentMarket.upcoming_year}`,
            side:        selectedSide,
            stake:       pos.stake       ?? stake,
            priceCents:  pos.price_cents ?? priceCents,
            shares:      pos.shares      ?? (stake / (priceCents / 100)),
            status:      "open",
            market_id:   currentMarketId,
        });
    } catch (_) {
        alert("Network error placing trade.");
        return;
    }

    marketVolume += stake;
    updateLivePrices();
    addBetToLeaderboard();
    unlockAchievement("first_bet");

    if (positions.length >= 5) unlockAchievement("market_maker");
    if (stake >= 500)          unlockAchievement("big_spender");

    const openPositions = positions.filter(p => p.status === "open");
    if (openPositions.length >= 3) unlockAchievement("diamond_hands");

    checkWalletAchievements();
    renderPositions();
    updateWalletDisplay();
    renderLeaderboard();

    const priceCents = selectedSide === "higher" ? liveHigherPrice : liveLowerPrice;
    alert(`Bet placed: ${selectedSide.toUpperCase()} ${stake.toFixed(0)} SC at ${priceCents}¢.`);

    selectedSide = null;
    resetSelectionUI();
}

async function loadSavedPositions() {
    if (!isLoggedIn()) {
        positions = [];
        return;
    }

    try {
        const resp = await fetch("/api/user/positions");
        if (resp.ok) {
            const data = await resp.json();
            if (Array.isArray(data.positions)) {
                positions = data.positions.map(p => ({
                    id:          p.id,
                    createdAt:   p.created_at,
                    course:      p.course_code,
                    courseName:  p.course_code,
                    question:    p.question_name,
                    questionNum: p.question_num,
                    answer:      p.answer,
                    answerNum:   p.answer_num,
                    prediction:  p.initial_prediction,
                    upcoming:    `Sem ${p.upcoming_sem} ${p.upcoming_year}`,
                    side:        p.side,
                    stake:       p.stake,
                    priceCents:  p.price_cents,
                    shares:      p.shares,
                    status:      p.status,
                    payout:      p.payout,
                    profit:      p.profit,
                    resolvedResultPercent: p.resolution_result,
                    market_id:   p.market_id,
                }));
                return;
            }
        }
    } catch (_) {}

    positions = [];
}

function renderPositions() {
    const list             = document.getElementById("positionsList");
    const openBetsValue    = document.getElementById("openBetsValue");
    const totalStakedValue = document.getElementById("totalStakedValue");

    const openPositions = positions.filter(p => p.status === "open");
    const totalStaked   = openPositions.reduce(
        (sum, p) => sum + Number(p.stake || 0), 0
    );

    if (openBetsValue)    openBetsValue.innerText    = openPositions.length;
    if (totalStakedValue) totalStakedValue.innerText = totalStaked.toFixed(0) + " SC";

    if (positions.length === 0) {
        list.className  = "empty";
        list.innerText  = "No bets yet.";
        return;
    }

    list.className = "";
    list.innerHTML = "";

    positions.slice().reverse().forEach(position => {
        const item = document.createElement("div");
        item.className = "position-item";

        const sideClass  = position.side === "higher" ? "higher" : "lower";
        const sideText   = position.side.toUpperCase();
        const statusText = position.status ? position.status.toUpperCase() : "OPEN";
        const createdDate = position.createdAt
            ? new Date(position.createdAt).toLocaleString()
            : "Saved bet";

        item.innerHTML = `
            <div class="position-header">
                <strong>${position.course}</strong>
                <span class="position-side ${sideClass}">${sideText}</span>
            </div>
            <span>${sideText} than ${Number(position.prediction).toFixed(2)}%</span><br>
            <span>${position.question}</span><br>
            <span>${position.upcoming}</span><br>
            Stake: ${Number(position.stake).toFixed(0)} SC
            · Price: ${position.priceCents}¢
            · Shares: ${Number(position.shares).toFixed(2)}<br>
            Status: <strong>${statusText}</strong>
            ${position.resolvedResultPercent !== undefined && position.resolvedResultPercent !== null
                ? `<br>Resolved result: ${Number(position.resolvedResultPercent).toFixed(2)}%`
                : ""}
            ${position.payout !== undefined && position.payout !== null
                ? `<br>Payout: ${Number(position.payout).toFixed(2)} SC`
                : ""}
            ${position.profit !== undefined && position.profit !== null
                ? `<br>Profit: ${Number(position.profit).toFixed(2)} SC`
                : ""}
            <br><span style="color:#94a3b8;">${createdDate}</span>
        `;
        list.appendChild(item);
    });
}

// ---------------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------------

function backToSetup() {
    stopSSEFeed();
    stopChartLoop();

    marketOpen      = false;
    selectedSide    = null;
    currentMarket   = null;
    currentMarketId = null;

    document.getElementById("marketSection").style.display  = "none";
    document.getElementById("browserSection").style.display = "block";

    resetSelectionUI();
    updateWalletDisplay();
    renderPositions();
    renderLeaderboard();
}

// ---------------------------------------------------------------------------
// Resets
// ---------------------------------------------------------------------------

function resetPortfolio() {
    if (!confirm("Reset all saved bets? This will not refund SECaT Coins.")) return;

    positions    = [];
    selectedSide = null;
    renderPositions();
    resetSelectionUI();
}

function resetWalletForTesting() {
    if (!confirm("Reset wallet to 500 SC?")) return;
    setWalletBalance(STARTING_BALANCE);
}

// ---------------------------------------------------------------------------
// Auth hook — re-render guest overlay whenever auth state changes
// ---------------------------------------------------------------------------

(function () {
    const _orig = window.initialiseCommonUi;
    window.initialiseCommonUi = function () {
        _orig.call(this);
        if (currentMarket !== null) renderGuestOverlay();
    };
}());

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

onAuthReady(async function () {
    await loadMarkets();
    await loadSavedPositions();
    renderPositions();
});
