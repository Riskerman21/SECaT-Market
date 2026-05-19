const POSITIONS_KEY = "secat_prediction_positions";

const MARKET_WINDOW_SECONDS = 45;
const BOT_TICK_MS = 1800;

let currentMarket = null;
let selectedSide = null;
let positions = [];

let marketOpen = false;
let marketSecondsLeft = 0;
let marketTimerInterval = null;
let botInterval = null;

let liveHigherPrice = 50;
let liveLowerPrice = 50;
let botTrades = [];
let marketVolume = 0;

let currentMarketMode = "normal";
let marketResolved = false;
let resolvedResultPercent = null;
let resolvedWinningSide = null;

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

function startSSEFeed() {
    if (sseSource) {
        sseSource.close();
        sseSource = null;
    }

    const dot = document.getElementById("sseDot");

    if (dot) {
        dot.className = "sentiment-sse-dot";
    }

    sseSource = new EventSource("/api/trade-feed");

    sseSource.onopen = () => {
        const d = document.getElementById("sseDot");

        if (d) {
            d.className = "sentiment-sse-dot live";
        }
    };

    sseSource.onmessage = event => {
        try {
            const trade = JSON.parse(event.data);
            updateSentimentFromSSE(trade);
            appendSSETradeToFeed(trade);
        } catch (error) {}
    };

    sseSource.onerror = () => {
        const d = document.getElementById("sseDot");

        if (d) {
            d.className = "sentiment-sse-dot";
        }
    };
}

function stopSSEFeed() {
    if (sseSource) {
        sseSource.close();
        sseSource = null;
    }

    const d = document.getElementById("sseDot");

    if (d) {
        d.className = "sentiment-sse-dot";
    }
}

function updateSentimentFromSSE(trade) {
    const card = document.getElementById("sentimentCard");
    const text = document.getElementById("sentimentText");
    const price = document.getElementById("impliedPrice");
    const bar = document.getElementById("sentimentBar");

    if (!card || !text || !price || !bar) {
        return;
    }

    const sentiment = trade.sentiment || "neutral";
    const impliedPrice = Number(trade.implied_price || 50);
    const colours = SENTIMENT_COLOURS[sentiment] || SENTIMENT_COLOURS.neutral;

    card.style.background = colours.bg;
    card.style.borderColor = colours.border;
    text.style.color = colours.text;
    text.textContent = sentiment;
    price.style.color = colours.price;
    price.textContent = impliedPrice.toFixed(1) + "¢";
    bar.style.width = impliedPrice + "%";
}

function appendSSETradeToFeed(trade) {
    if (currentMarketMode === "live") {
        return;
    }

    if (!currentMarket) {
        return;
    }

    const list = document.getElementById("botFeedList");

    if (!list) {
        return;
    }

    if (
        list.innerText === "Market has not opened yet." ||
        list.innerText === "Loading market activity..."
    ) {
        list.innerHTML = "";
    }

    const row = document.createElement("div");
    row.className = "bot-trade bot-trade-new";

    const isBuy =
        trade.sentiment === "strongly bullish" ||
        trade.sentiment === "bullish";

    const dirClass = isBuy ? "bot-buy" : "bot-sell";
    const dirLabel = isBuy ? "BUY" : "SELL";

    row.innerHTML = `
        <span>
            <strong>${trade.course}</strong>
            <span class="${dirClass}">${dirLabel}</span>
            <span style="color:#94a3b8;font-size:12px;">${trade.sentiment}</span>
        </span>
        <span>${impliedPriceLabel(trade.implied_price)}</span>
    `;

    list.prepend(row);

    while (list.children.length > 8) {
        list.removeChild(list.lastChild);
    }
}

function impliedPriceLabel(p) {
    return Number(p).toFixed(1) + "¢";
}

const CHART_ANIM_MS = 500;
let chartPoints = [];
let pendingPoint = null;
let animatingTo = null;
let rafId = null;

function lerp(a, b, t) {
    return a + (b - a) * t;
}

function easeOut(t) {
    return 1 - Math.pow(1 - t, 3);
}

function priceToY(price) {
    const clamp = Math.max(5, Math.min(95, price));
    return 220 - ((clamp - 5) / 90) * 220;
}

function buildSVGPath(pts) {
    if (pts.length === 0) {
        return {
            line:"",
            fill:""
        };
    }

    const width = 700;

    const coords = pts.map((p, i) => ({
        x:pts.length === 1 ? 0 : (i / (pts.length - 1)) * width,
        y:priceToY(p)
    }));

    let line = `M ${coords[0].x} ${coords[0].y}`;

    for (let i = 1; i < coords.length; i++) {
        const prev = coords[i - 1];
        const curr = coords[i];
        const cpX = (prev.x + curr.x) / 2;

        line += ` C ${cpX} ${prev.y} ${cpX} ${curr.y} ${curr.x} ${curr.y}`;
    }

    const last = coords[coords.length - 1];
    const first = coords[0];
    const fill = line + ` L ${last.x} 220 L ${first.x} 220 Z`;

    return {
        line,
        fill
    };
}

function drawAnimatedChart(ts) {
    rafId = requestAnimationFrame(drawAnimatedChart);

    const lineEl = document.getElementById("priceChartLine");
    const fillEl = document.getElementById("priceChartFill");

    if (!lineEl || !fillEl) {
        return;
    }

    if (pendingPoint !== null && animatingTo === null) {
        const from = chartPoints.length > 0
            ? chartPoints[chartPoints.length - 1]
            : pendingPoint;

        animatingTo = {
            from,
            to:pendingPoint,
            startTs:ts
        };

        pendingPoint = null;
    }

    let displayPts = [...chartPoints];

    if (animatingTo !== null) {
        const elapsed = ts - animatingTo.startTs;
        const progress = Math.min(elapsed / CHART_ANIM_MS, 1);
        const eased = easeOut(progress);
        const current = lerp(animatingTo.from, animatingTo.to, eased);

        displayPts = [...displayPts, current];

        if (progress >= 1) {
            chartPoints.push(animatingTo.to);

            if (chartPoints.length > 40) {
                chartPoints.shift();
            }

            animatingTo = null;
        }
    }

    if (displayPts.length < 1) {
        return;
    }

    const path = buildSVGPath(displayPts);

    lineEl.setAttribute("d", path.line);
    fillEl.setAttribute("d", path.fill);
}

function startChartLoop() {
    if (rafId) {
        cancelAnimationFrame(rafId);
    }

    rafId = requestAnimationFrame(drawAnimatedChart);
}

function stopChartLoop() {
    if (rafId) {
        cancelAnimationFrame(rafId);
        rafId = null;
    }
}

function resetPriceChart() {
    chartPoints = [Number(liveHigherPrice)];
    pendingPoint = null;
    animatingTo = null;

    startChartLoop();

    const cur = document.getElementById("chartCurrentPrice");

    if (cur) {
        cur.innerText = liveHigherPrice + "¢";
    }
}

function addPricePoint(price) {
    pendingPoint = Number(price);

    const cur = document.getElementById("chartCurrentPrice");

    if (cur) {
        cur.innerText = price + "¢";
    }
}

function loadSavedPositions() {
    const saved = localStorage.getItem(POSITIONS_KEY);

    if (saved === null) {
        positions = [];
        return;
    }

    try {
        const parsed = JSON.parse(saved);
        positions = Array.isArray(parsed) ? parsed : [];
    } catch (error) {
        positions = [];
    }
}

function savePositions() {
    localStorage.setItem(POSITIONS_KEY, JSON.stringify(positions));
}

async function loadCourses() {
    const select = document.getElementById("courseSelect");

    try {
        const response = await fetch("/api/courses");

        if (!response.ok) {
            throw new Error("Course API failed.");
        }

        const data = await response.json();

        select.innerHTML = "";

        const placeholder = document.createElement("option");
        placeholder.value = "";
        placeholder.innerText = "Choose a course";
        select.appendChild(placeholder);

        data.courses.forEach(course => {
            const option = document.createElement("option");
            option.value = course.code;
            option.innerText = course.display || `${course.code} - ${course.name || ""}`;
            select.appendChild(option);
        });
    } catch (error) {
        console.error("loadCourses failed:", error);

        select.innerHTML = "";

        const option = document.createElement("option");
        option.value = "";
        option.innerText = "Could not load courses";
        select.appendChild(option);
    }
}

async function loadMarket(mode = "normal") {
    const courseCode = document.getElementById("courseSelect").value;
    const questionNum = document.getElementById("questionSelect").value;
    const answerNum = document.getElementById("answerSelect").value;

    if (!courseCode) {
        document.getElementById("choiceMessage").innerText = "Choose a course first.";
        return;
    }

    selectedSide = null;
    resetSelectionUI();
    stopLiveMarket();

    currentMarketMode = mode;
    marketResolved = false;
    resolvedResultPercent = null;
    resolvedWinningSide = null;

    document.getElementById("loading").style.display = "block";
    document.getElementById("loading").innerText =
        mode === "live"
            ? "Building live market from cached SECaT data..."
            : "Building normal market from cached SECaT data...";

    document.getElementById("choiceMessage").innerText = "";

    try {
        const url =
            "/api/prediction-market" +
            "?course=" + encodeURIComponent(courseCode) +
            "&question_num=" + encodeURIComponent(questionNum) +
            "&answer_num=" + encodeURIComponent(answerNum);

        const response = await fetch(url);
        const data = await response.json();

        if (!response.ok || data.error) {
            document.getElementById("loading").innerText =
                data.error || "Could not build market.";
            return;
        }

        currentMarket = data;
        renderMarket(data);

        document.getElementById("loading").style.display = "none";
        document.getElementById("setupSection").style.display = "none";
        document.getElementById("marketSection").style.display = "block";
        document.getElementById("marketSection").classList.add("fade-in");

        document.getElementById("higherButton").disabled = false;
        document.getElementById("lowerButton").disabled = false;

        updateTradeSummary();
        updateWalletDisplay();
        renderLeaderboard();

        startSSEFeed();
    } catch (error) {
        console.error("loadMarket failed:", error);
        document.getElementById("loading").innerText =
            "Something went wrong building the market.";
    }
}

function backToSetup() {
    stopLiveMarket();
    stopSSEFeed();
    stopChartLoop();

    marketOpen = false;

    document.getElementById("marketSection").style.display = "none";
    document.getElementById("setupSection").style.display = "grid";
    document.getElementById("loading").style.display = "none";
    document.getElementById("choiceMessage").innerText = "";

    selectedSide = null;
    currentMarket = null;

    resetSelectionUI();
    updateWalletDisplay();
    renderPositions();
    renderLeaderboard();
}

function renderMarket(market) {
    const prediction = Number(market.initial_prediction);

    liveHigherPrice = getHigherPrice(market);
    liveLowerPrice = 100 - liveHigherPrice;

    const upcoming = market.upcoming_offering || null;
    const upcomingLabel = upcoming
        ? upcoming.label.replace(market.course + ": ", "")
        : "the next likely offering";

    document.getElementById("courseCode").innerText = market.course;
    document.getElementById("courseName").innerText = market.name;
    document.getElementById("marketBadge").innerText = upcomingLabel;

    document.getElementById("marketQuestion").innerHTML =
        `Will <strong>${market.course}</strong> in <strong>${upcomingLabel}</strong> have more than ` +
        `<strong>${prediction.toFixed(2)}%</strong> of students selecting ` +
        `<strong>${market.answer}</strong> for <strong>${market.question_name}</strong>?`;

    document.getElementById("upcomingGuessMain").innerText =
        upcoming ? upcoming.display : "No upcoming offering inferred";

    document.getElementById("upcomingGuessReason").innerText =
        upcoming
            ? upcoming.reason
            : "The app could not infer the next likely semester from historical offerings.";

    document.getElementById("predictionValue").innerText = prediction.toFixed(2) + "%";
    document.getElementById("confidenceValue").innerText = market.confidence + "/100";
    document.getElementById("historyCount").innerText =
        market.history_count || market.history.length;

    updateLivePrices();
    resetPriceChart();
    renderHistory(market);
    renderMiniChart(market);

    if (currentMarketMode === "live") {
        startLiveMarket();
    } else {
        startNormalMarket();
    }
}

function getHigherPrice(market) {
    const history = market.history;

    if (!history || history.length < 2) {
        return 50;
    }

    const newest = Number(history[0].percent);
    const oldest = Number(history[history.length - 1].percent);
    const trend = newest - oldest;

    let price = 50 + trend * 1.2;
    const confidenceBoost = (Number(market.confidence) - 50) / 10;

    price += trend >= 0 ? confidenceBoost : -confidenceBoost;

    return Math.max(5, Math.min(95, Math.round(price)));
}

function startNormalMarket() {
    stopLiveMarket();

    marketOpen = true;
    marketResolved = false;
    marketSecondsLeft = 0;
    botTrades = [];
    marketVolume = 0;

    document.getElementById("botFeedList").innerText = "Loading market activity...";
    document.getElementById("higherButton").disabled = false;
    document.getElementById("lowerButton").disabled = false;

    updateLivePrices();
    updateNormalMarketUI();
    fetchBotActivity();
}

function updateNormalMarketUI() {
    const status = document.getElementById("liveStatus");
    const timer = document.getElementById("marketTimer");
    const volume = document.getElementById("marketVolume");

    if (status !== null) {
        status.innerText = "Normal Market";
        status.className = "live-status";
    }

    if (timer !== null) {
        timer.innerText = "∞";
    }

    if (volume !== null) {
        volume.innerText = Math.round(marketVolume) + " SC";
    }
}

function startLiveMarket() {
    stopLiveMarket();

    marketOpen = true;
    marketResolved = false;
    marketSecondsLeft = MARKET_WINDOW_SECONDS;
    botTrades = [];
    marketVolume = 0;

    document.getElementById("botFeedList").innerText = "Waiting for bot trades...";

    updateLivePrices();
    updateLiveMarketUI();

    marketTimerInterval = setInterval(() => {
        marketSecondsLeft -= 1;
        updateLiveMarketUI();

        if (marketSecondsLeft <= 0) {
            closeLiveMarket();
        }
    }, 1000);

    fetchBotActivity();
    botInterval = setInterval(fetchBotActivity, BOT_TICK_MS);
}

function stopLiveMarket() {
    if (marketTimerInterval !== null) {
        clearInterval(marketTimerInterval);
        marketTimerInterval = null;
    }

    if (botInterval !== null) {
        clearInterval(botInterval);
        botInterval = null;
    }
}

function closeLiveMarket() {
    marketOpen = false;
    stopLiveMarket();

    resolveLiveMarket();
    updateLiveMarketUI();

    document.getElementById("higherButton").disabled = true;
    document.getElementById("lowerButton").disabled = true;
    document.getElementById("placeTradeButton").disabled = true;
}

function resolveLiveMarket() {
    if (currentMarket === null || marketResolved) {
        return;
    }

    const latestHistory =
        currentMarket.history && currentMarket.history.length > 0
            ? currentMarket.history[0]
            : null;

    if (latestHistory === null) {
        return;
    }

    resolvedResultPercent = Number(latestHistory.percent);
    const prediction = Number(currentMarket.initial_prediction);

    if (resolvedResultPercent > prediction) {
        resolvedWinningSide = "higher";
    } else if (resolvedResultPercent < prediction) {
        resolvedWinningSide = "lower";
    } else {
        resolvedWinningSide = "push";
    }

    marketResolved = true;
    settlePositionsForCurrentMarket();

    const botFeed = document.getElementById("botFeedList");

    if (botFeed !== null) {
        const resultText =
            resolvedWinningSide === "push"
                ? "PUSH / SAME"
                : resolvedWinningSide.toUpperCase();

        const resultRow = document.createElement("div");
        resultRow.className = "bot-trade";
        resultRow.innerHTML = `
            <span><strong>Market Closed</strong> <span class="bot-buy">RESULT</span> ${resultText}</span>
            <span>${resolvedResultPercent.toFixed(2)}%</span>
        `;

        botFeed.prepend(resultRow);
    }

    alert(
        "Live market closed.\n\n" +
        "Latest historical result used for demo: " + resolvedResultPercent.toFixed(2) + "%\n" +
        "Winning side: " + resolvedWinningSide.toUpperCase()
    );
}

function settlePositionsForCurrentMarket() {
    if (currentMarket === null || resolvedWinningSide === null) {
        return;
    }

    let totalPayout = 0;

    positions = positions.map(position => {
        const sameMarket =
            position.course === currentMarket.course &&
            Number(position.questionNum) === Number(currentMarket.question_num) &&
            Number(position.answerNum) === Number(currentMarket.answer_num) &&
            position.status === "open";

        if (!sameMarket) {
            return position;
        }

        if (resolvedWinningSide === "push") {
            totalPayout += Number(position.stake);

            return {
                ...position,
                status:"refunded",
                resolvedAt:new Date().toISOString(),
                resolvedResultPercent:resolvedResultPercent,
                payout:Number(position.stake),
                profit:0
            };
        }

        if (position.side === resolvedWinningSide) {
            const payout = Number(position.shares);
            const profit = payout - Number(position.stake);

            updateBiggestMarketProfit(profit);
            totalPayout += payout;

            return {
                ...position,
                status:"won",
                resolvedAt:new Date().toISOString(),
                resolvedResultPercent:resolvedResultPercent,
                payout:payout,
                profit:profit
            };
        }

        return {
            ...position,
            status:"lost",
            resolvedAt:new Date().toISOString(),
            resolvedResultPercent:resolvedResultPercent,
            payout:0,
            profit:-Number(position.stake)
        };
    });

    if (totalPayout > 0) {
        setWalletBalance(getWalletBalance() + totalPayout);
    }

    const hasWinningPosition = positions.some(position => position.status === "won");

    if (hasWinningPosition) {
        unlockAchievement("profit_hunter");
    }

    checkWalletAchievements();
    savePositions();
    renderPositions();
    updateWalletDisplay();
    renderLeaderboard();
}

function updateLiveMarketUI() {
    const status = document.getElementById("liveStatus");
    const timer = document.getElementById("marketTimer");
    const volume = document.getElementById("marketVolume");

    if (status !== null) {
        status.innerText = marketOpen ? "Trading Open" : "Trading Closed";
        status.className = marketOpen
            ? "live-status"
            : "live-status market-closed-warning";
    }

    if (timer !== null) {
        timer.innerText = Math.max(0, marketSecondsLeft);
    }

    if (volume !== null) {
        volume.innerText = Math.round(marketVolume) + " SC";
    }
}

async function fetchBotActivity() {
    if (currentMarket === null) {
        return;
    }

    try {
        const params = new URLSearchParams({
            course: currentMarket.course,
            question_num: currentMarket.question_num,
            answer_num: currentMarket.answer_num,
            market_key: currentMarket.market_key || "",
            base_price: currentMarket.initial_prediction
        });

        const response = await fetch("/api/bot-activity?" + params.toString());

        if (!response.ok) {
            return;
        }

        const data = await response.json();

        if (!data.bot_trades || data.bot_trades.length === 0) {
            return;
        }

        const newHigherPrice = Math.round(Math.max(5, Math.min(95, data.current_price)));
        const priceChanged = newHigherPrice !== liveHigherPrice;

        liveHigherPrice = newHigherPrice;
        liveLowerPrice = 100 - liveHigherPrice;

        data.bot_trades.forEach(trade => {
            marketVolume += trade.size;
            botTrades.unshift({
                bot:trade.bot,
                personality:trade.personality,
                side:trade.direction.toLowerCase(),
                size:trade.size,
                belief:trade.belief,
                higherPrice:liveHigherPrice,
                lowerPrice:liveLowerPrice,
                time:new Date().toLocaleTimeString()
            });
        });

        botTrades = botTrades.slice(0, 8);
        renderBotFeed();

        if (priceChanged) {
            updateLivePrices();
            updateTradeSummary();
        }

        if (currentMarketMode === "live") {
            updateLiveMarketUI();
        } else {
            updateNormalMarketUI();
        }
    } catch (error) {}
}

function updateLivePrices() {
    document.getElementById("higherPrice").innerText = liveHigherPrice + "¢";
    document.getElementById("lowerPrice").innerText = liveLowerPrice + "¢";

    addPricePoint(liveHigherPrice);
}

function renderBotFeed() {
    const list = document.getElementById("botFeedList");

    if (list === null) {
        return;
    }

    if (botTrades.length === 0) {
        list.innerText = "Waiting for bot trades...";
        return;
    }

    list.innerHTML = "";

    botTrades.forEach(trade => {
        const row = document.createElement("div");
        row.className = "bot-trade";

        const sideClass = trade.side === "higher" ? "bot-buy" : "bot-sell";

        row.innerHTML = `
            <span>
                <strong>${trade.bot}</strong>
                <span class="${sideClass}">${trade.side.toUpperCase()}</span>
                <span style="color:#94a3b8;font-size:12px;">${trade.personality}</span>
            </span>
            <span>${trade.size} shares · H ${trade.higherPrice}¢</span>
        `;

        list.appendChild(row);
    });
}

function renderHistory(market) {
    const historyList = document.getElementById("historyList");
    historyList.innerHTML = "";

    market.history.forEach(item => {
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
    chart.innerHTML = "";

    const history = [...market.history].reverse();

    history.forEach(item => {
        const percent = Number(item.percent);
        const wrap = document.createElement("div");
        wrap.className = "bar-wrap";

        const bar = document.createElement("div");
        bar.className = "bar";
        bar.style.height = Math.max(4, percent) + "%";
        bar.title = percent.toFixed(2) + "%";

        const label = document.createElement("div");
        label.className = "bar-label";
        label.innerText = `S${item.sem} ${item.year}`;

        wrap.appendChild(bar);
        wrap.appendChild(label);
        chart.appendChild(wrap);
    });
}

function selectSide(side) {
    if (currentMarket === null || !marketOpen) {
        return;
    }

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
    document.getElementById("selectedSideValue").innerText = "--";
    document.getElementById("placeTradeButton").disabled = true;
    document.getElementById("selectedPrice").innerText = "--";
    document.getElementById("estimatedShares").innerText = "--";
    document.getElementById("potentialPayout").innerText = "--";
    document.getElementById("potentialProfit").innerText = "--";
}

function updateTradeSummary() {
    if (currentMarket === null || selectedSide === null) {
        return;
    }

    const stake = Number(document.getElementById("stakeInput").value || 0);
    const selectedPriceCents =
        selectedSide === "higher" ? liveHigherPrice : liveLowerPrice;
    const selectedPrice = selectedPriceCents / 100;

    if (stake <= 0 || selectedPrice <= 0) {
        return;
    }

    const shares = stake / selectedPrice;
    const payout = shares;
    const profit = payout - stake;

    document.getElementById("selectedPrice").innerText = selectedPriceCents + "¢";
    document.getElementById("estimatedShares").innerText = shares.toFixed(2);
    document.getElementById("potentialPayout").innerText = payout.toFixed(2) + " SC";
    document.getElementById("potentialProfit").innerText = profit.toFixed(2) + " SC";
}

async function placeTrade() {
    if (currentMarket === null || selectedSide === null) {
        return;
    }

    if (!marketOpen) {
        alert("Trading window is closed. Build another market to trade again.");
        return;
    }

    const stake = Number(document.getElementById("stakeInput").value || 0);
    const currentBalance = getWalletBalance();

    if (stake <= 0) {
        alert("Enter a stake greater than zero.");
        return;
    }

    if (stake > currentBalance) {
        alert("Not enough SECaT Coins. Play Higher or Lower to earn more.");
        return;
    }

    const priceCents = selectedSide === "higher" ? liveHigherPrice : liveLowerPrice;
    const price = priceCents / 100;
    const shares = stake / price;

    const spent = spendCoins(stake);

    if (!spent) {
        alert("Not enough SECaT Coins.");
        return;
    }

    try {
        const response = await fetch("/api/trade", {
            method:"POST",
            headers:{
                "Content-Type":"application/json"
            },
            body:JSON.stringify({
                market_key:currentMarket.market_key || "",
                base_price:currentMarket.initial_prediction,
                direction:selectedSide.toUpperCase(),
                size:Math.round(stake)
            })
        });

        if (response.ok) {
            const data = await response.json();
            const newHigherPrice = Math.round(Math.max(5, Math.min(95, data.new_price)));

            liveHigherPrice = newHigherPrice;
            liveLowerPrice = 100 - liveHigherPrice;

            if (data.bot_trades && data.bot_trades.length > 0) {
                data.bot_trades.forEach(trade => {
                    marketVolume += trade.size;
                    botTrades.unshift({
                        bot:trade.bot,
                        personality:trade.personality,
                        side:trade.direction.toLowerCase(),
                        size:trade.size,
                        belief:trade.belief,
                        higherPrice:liveHigherPrice,
                        lowerPrice:liveLowerPrice,
                        time:new Date().toLocaleTimeString()
                    });
                });

                botTrades = botTrades.slice(0, 8);
                renderBotFeed();
            }
        }
    } catch (error) {}

    marketVolume += stake;

    if (currentMarketMode === "live") {
        updateLiveMarketUI();
    } else {
        updateNormalMarketUI();
    }

    updateLivePrices();

    const position = {
        id:Date.now().toString() + "_" + Math.random().toString(16).slice(2),
        createdAt:new Date().toISOString(),
        course:currentMarket.course,
        courseName:currentMarket.name,
        question:currentMarket.question_name,
        questionNum:currentMarket.question_num,
        answer:currentMarket.answer,
        answerNum:currentMarket.answer_num,
        prediction:currentMarket.initial_prediction,
        confidence:currentMarket.confidence,
        upcoming:currentMarket.upcoming_offering
            ? currentMarket.upcoming_offering.label
            : "Upcoming offering",
        side:selectedSide,
        stake:stake,
        priceCents:priceCents,
        shares:shares,
        marketMode:currentMarketMode,
        currentLivePriceHigher:liveHigherPrice,
        currentLivePriceLower:liveLowerPrice,
        status:"open"
    };

    positions.push(position);
    savePositions();

    addBetToLeaderboard();

    unlockAchievement("first_bet");

    if (positions.length >= 5) {
        unlockAchievement("market_maker");
    }

    if (currentMarketMode === "live") {
        unlockAchievement("live_trader");
    }

    if (stake >= 500) {
        unlockAchievement("big_spender");
    }

    const openPositions = positions.filter(position => position.status === "open");

    if (openPositions.length >= 3) {
        unlockAchievement("diamond_hands");
    }

    checkWalletAchievements();
    renderPositions();
    updateWalletDisplay();
    renderLeaderboard();

    alert(`Bet saved: ${selectedSide.toUpperCase()} ${stake.toFixed(0)} SC at ${priceCents}¢.`);

    selectedSide = null;
    resetSelectionUI();
}

function renderPositions() {
    const list = document.getElementById("positionsList");
    const openBetsValue = document.getElementById("openBetsValue");
    const totalStakedValue = document.getElementById("totalStakedValue");

    const openPositions = positions.filter(position => position.status === "open");
    const totalStaked = openPositions.reduce(
        (sum, position) => sum + Number(position.stake || 0),
        0
    );

    if (openBetsValue !== null) {
        openBetsValue.innerText = openPositions.length;
    }

    if (totalStakedValue !== null) {
        totalStakedValue.innerText = totalStaked.toFixed(0) + " SC";
    }

    if (positions.length === 0) {
        list.className = "empty";
        list.innerText = "No bets yet.";
        return;
    }

    list.className = "";
    list.innerHTML = "";

    positions.slice().reverse().forEach(position => {
        const item = document.createElement("div");
        item.className = "position-item";

        const sideClass = position.side === "higher" ? "higher" : "lower";
        const sideText = position.side.toUpperCase();
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
            ${position.resolvedResultPercent !== undefined ? `<br>Resolved result: ${Number(position.resolvedResultPercent).toFixed(2)}%` : ""}
            ${position.payout !== undefined ? `<br>Payout: ${Number(position.payout).toFixed(2)} SC` : ""}
            ${position.profit !== undefined ? `<br>Profit: ${Number(position.profit).toFixed(2)} SC` : ""}
            <br><span style="color:#94a3b8;">${createdDate}</span>
        `;

        list.appendChild(item);
    });
}

function resetPortfolio() {
    if (!confirm("Reset all saved bets? This will not refund SECaT Coins.")) {
        return;
    }

    positions = [];
    savePositions();
    selectedSide = null;
    renderPositions();
    resetSelectionUI();
}

function resetWalletForTesting() {
    if (!confirm("Reset wallet to 500 SC?")) {
        return;
    }

    setWalletBalance(STARTING_BALANCE);
}

onAuthReady(function () {
    loadCourses();
    loadSavedPositions();
    renderPositions();
});