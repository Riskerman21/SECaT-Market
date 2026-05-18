const BASE_WIN_REWARD = 50;
const BASE_LOSS_PENALTY = 15;
const MULTIPLIER_STEP = 0.25;
const MAX_MULTIPLIER = 5;
const LOSS_STREAK_STEP = 0.25;
const MAX_LOSS_MULTIPLIER = 4;

let currentRound = null;

let score = 0;
let roundsPlayed = 0;
let currentStreak = 0;
let gameOver = false;

let selectedCourseGroups = [];
let usedOfferingLabels = [];

let chainQuestionNum = null;
let chainAnswerNum = null;

let shuffleInterval = null;
let lookingSoundInterval = null;
let countUpSoundInterval = null;
let countUpSoundTimeout = null;
let countUpSoundStartedAt = null;

const SOUNDS = {
    looking: new Audio("/static/audio/looking-for-challenger.mp3"),
    found: new Audio("/static/audio/challenger-found.mp3"),
    countUp: new Audio("/static/audio/count-up.mp3"),
    correct: new Audio("/static/audio/correct.mp3"),
    wrong: new Audio("/static/audio/wrong.mp3")
};

Object.values(SOUNDS).forEach(sound => {
    sound.preload = "auto";
    sound.volume = 0.65;
});


function playSound(name) {
    const sound = SOUNDS[name];

    if (!sound) {
        return;
    }

    sound.currentTime = 0;

    const playPromise = sound.play();

    if (playPromise !== undefined) {
        playPromise.catch(() => {});
    }
}

function getCountUpSoundDelay(elapsed, duration = 2600) {
    const progress = Math.min(elapsed / duration, 1);

    if (progress < 0.18) {
        return 330;
    }

    if (progress < 0.38) {
        return 230;
    }

    if (progress < 0.62) {
        return 155;
    }

    if (progress < 0.84) {
        return 105;
    }

    return 75;
}

function scheduleNextCountUpSound(duration = 2600) {
    if (countUpSoundStartedAt === null) {
        return;
    }

    const elapsed = performance.now() - countUpSoundStartedAt;

    if (elapsed >= duration) {
        return;
    }

    playRapidSound("countUp");

    const nextDelay = getCountUpSoundDelay(elapsed, duration);

    countUpSoundTimeout = setTimeout(() => {
        scheduleNextCountUpSound(duration);
    }, nextDelay);
}

function startCountUpSound(duration = 2600) {
    if (countUpSoundInterval !== null) {
        clearInterval(countUpSoundInterval);
        countUpSoundInterval = null;
    }

    if (countUpSoundTimeout !== null) {
        clearTimeout(countUpSoundTimeout);
        countUpSoundTimeout = null;
    }

    countUpSoundStartedAt = performance.now();
    scheduleNextCountUpSound(duration);
}

function stopCountUpSound() {
    if (countUpSoundInterval !== null) {
        clearInterval(countUpSoundInterval);
        countUpSoundInterval = null;
    }

    if (countUpSoundTimeout !== null) {
        clearTimeout(countUpSoundTimeout);
        countUpSoundTimeout = null;
    }

    countUpSoundStartedAt = null;

    stopSound("countUp");
}

function playRapidSound(name) {
    const sound = SOUNDS[name];

    if (!sound) {
        return;
    }

    const soundClone = sound.cloneNode();
    soundClone.volume = sound.volume;

    const playPromise = soundClone.play();

    if (playPromise !== undefined) {
        playPromise.catch(() => {});
    }

    setTimeout(() => {
        soundClone.pause();
        soundClone.remove();
    }, 900);
}

function stopSound(name) {
    const sound = SOUNDS[name];

    if (!sound) {
        return;
    }

    sound.pause();
    sound.currentTime = 0;
}

function stopLoopingSounds() {
    stopCountUpSound();
}

function swapCardColours() {
    const leftCard = document.getElementById("leftCard");
    const rightCard = document.getElementById("rightCard");

    const leftWasBlue = leftCard.classList.contains("card-blue");

    leftCard.classList.remove("card-blue", "card-red");
    rightCard.classList.remove("card-blue", "card-red");

    if (leftWasBlue) {
        leftCard.classList.add("card-red");
        rightCard.classList.add("card-blue");
    } else {
        leftCard.classList.add("card-blue");
        rightCard.classList.add("card-red");
    }
}

function getCurrentMultiplier() {
    return Math.min(MAX_MULTIPLIER, 1 + currentStreak * MULTIPLIER_STEP);
}

function getLossMultiplier() {
    return Math.min(MAX_LOSS_MULTIPLIER, 1 + currentStreak * LOSS_STREAK_STEP);
}

function getCurrentReward() {
    return Math.round(BASE_WIN_REWARD * getCurrentMultiplier());
}

function getCurrentLossPenalty() {
    return Math.round(BASE_LOSS_PENALTY * getLossMultiplier());
}

function getPowerPercent() {
    return Math.min(
        100,
        ((getCurrentMultiplier() - 1) / (MAX_MULTIPLIER - 1)) * 100
    );
}

function getMeterStatus() {
    if (currentStreak === 0) {
        return "Safe Mode";
    }

    if (currentStreak < 3) {
        return "Warming Up";
    }

    if (currentStreak < 7) {
        return "Hot Streak";
    }

    if (currentStreak < 12) {
        return "Danger Zone";
    }

    return "Max Risk";
}

function updateHud() {
    document.getElementById("streakValue").innerText = currentStreak;
    document.getElementById("nextRewardValue").innerText =
        "+" + getCurrentReward() + " SC";
    document.getElementById("nextLossValue").innerText =
        "-" + getCurrentLossPenalty() + " SC";
    document.getElementById("powerFill").style.width =
        getPowerPercent() + "%";
    document.getElementById("meterStatus").innerText = getMeterStatus();

    updateWalletDisplay();
}

async function loadCourseGroups() {
    const grid = document.getElementById("courseGroupGrid");

    try {
        const response = await fetch("/api/course-groups");
        const data = await response.json();

        grid.innerHTML = "";

        data.groups.forEach(group => {
            const card = document.createElement("div");
            card.className = "group-card";
            card.dataset.groupKey = group.key;

            card.innerHTML = `
                <div class="group-title">${group.label}</div>
                <div class="group-count">${group.count} courses</div>
            `;

            card.onclick = () => {
                card.classList.toggle("selected");
                updateSelectedCourseGroups();
            };

            grid.appendChild(card);
        });
    } catch (error) {
        grid.innerText = "Could not load course lists.";
    }
}

function updateSelectedCourseGroups() {
    selectedCourseGroups = Array.from(
        document.querySelectorAll(".group-card.selected")
    ).map(card => card.dataset.groupKey);

    document.getElementById("startMessage").innerText = "";
}

function startGame() {
    updateSelectedCourseGroups();

    if (selectedCourseGroups.length === 0) {
        document.getElementById("startMessage").innerText =
            "Pick at least one course list to start.";
        return;
    }

    document.getElementById("startScreen").style.display = "none";
    document.getElementById("gameScreen").style.display = "flex";

    updateHud();
    loadRound();

    Object.values(SOUNDS).forEach(sound => {
        const originalVolume = sound.volume;
        sound.volume = 0;
        sound.play()
            .then(() => {
                sound.pause();
                sound.currentTime = 0;
                sound.volume = originalVolume;
            })
            .catch(() => {
                sound.volume = originalVolume;
            });
    });
}

function changeCourseMix() {
    stopShuffleAnimation();
    stopLoopingSounds();

    currentRound = null;
    usedOfferingLabels = [];
    chainQuestionNum = null;
    chainAnswerNum = null;
    gameOver = false;

    document.getElementById("gameScreen").style.display = "none";
    document.getElementById("cards").style.display = "none";
    document.getElementById("loading").style.display = "none";
    document.getElementById("message").innerText = "";
    document.getElementById("preloadStatus").innerText = "";
    document.getElementById("startScreen").style.display = "grid";
}

function resetStreak() {
    const message = document.getElementById("message");

    if (currentStreak === 0) {
        message.innerText = "Risk already reset. Starting a fresh chain...";
        loadRound();
        return;
    }

    if (!confirm("Reset your streak and start a new chain?")) {
        return;
    }

    currentStreak = 0;
    updateHud();

    message.innerText = "Risk reset. Starting a fresh chain...";
    loadRound();
}

async function fetchRound() {
    const groupsQuery = selectedCourseGroups
        .map(group => encodeURIComponent(group))
        .join(",");

    const response = await fetch("/api/round?groups=" + groupsQuery);
    const data = await response.json();

    if (!response.ok || data.error) {
        throw new Error(data.error || "Could not load round.");
    }

    return data;
}

async function fetchChallenger() {
    if (currentRound === null) {
        throw new Error("No current round.");
    }

    const groupsQuery = selectedCourseGroups
        .map(group => encodeURIComponent(group))
        .join(",");

    const usedQuery = usedOfferingLabels
        .map(label => encodeURIComponent(label))
        .join("||");

    const params = new URLSearchParams({
        course: currentRound.left.course,
        name: currentRound.left.name,
        label: currentRound.left.label,
        sem: currentRound.left.sem,
        year: currentRound.left.year,
        question_num: chainQuestionNum,
        answer_num: chainAnswerNum,
        groups: groupsQuery,
        used: usedQuery
    });

    const response = await fetch("/api/challenger?" + params.toString());
    const data = await response.json();

    if (!response.ok || data.error) {
        throw new Error(data.error || "Could not load challenger.");
    }

    return data;
}

async function loadRound() {
    stopShuffleAnimation();
    stopLoopingSounds();

    gameOver = false;
    resetAnimations();

    document.getElementById("loading").style.display = "block";
    document.getElementById("loading").innerText =
        "Loading a fresh SECaT chain...";
    document.getElementById("cards").style.display = "none";
    document.getElementById("message").innerText = "";
    document.getElementById("rightPercent").innerText = "?";
    document.getElementById("choiceButtons").style.display = "flex";
    document.getElementById("nextButton").style.display = "none";
    document.getElementById("preloadStatus").innerText = "";

    try {
        const data = await fetchRound();

        currentRound = data;
        chainQuestionNum = data.question_num;
        chainAnswerNum = data.answer_num;

        usedOfferingLabels = [
            data.left.label,
            data.right.label
        ];

        renderRound(data);

        document.getElementById("loading").style.display = "none";
        document.getElementById("cards").style.display = "grid";
    } catch (error) {
        document.getElementById("loading").innerText =
            error.message || "Something went wrong loading the round.";
    }
}

function renderRound(data) {
    const cleanAnswer = data.answer_option.replace(/^\d+\s*/, "");

    document.getElementById("questionText").innerHTML = `
        <div class="question-kicker">Rolling chain · same SECaT question</div>
        <div class="question-main">${data.question_name}</div>
        <div class="question-sub">
            Does the new course have a <strong>higher or lower</strong> percentage of
            <strong>${cleanAnswer}</strong> than the current course?
        </div>
    `;

    renderLeftCard(data.left, cleanAnswer);
    renderRightCard(data.right, cleanAnswer, true);
}

function renderLeftCard(cardData, cleanAnswer) {
    document.getElementById("leftCode").innerText = cardData.course;
    document.getElementById("leftName").innerText = cardData.name;
    document.getElementById("leftOffering").innerText =
        cardData.label.replace(cardData.course + ": ", "");
    document.getElementById("leftPercent").innerText =
        Number(cardData.percent).toFixed(2) + "%";
    document.getElementById("leftAnswer").innerText = cleanAnswer;
}

function renderRightCard(cardData, cleanAnswer, hidden = true) {
    document.getElementById("rightCode").innerText = cardData.course;
    document.getElementById("rightName").innerText = cardData.name;
    document.getElementById("rightOffering").innerText =
        cardData.label.replace(cardData.course + ": ", "");
    document.getElementById("rightPercent").innerText =
        hidden ? "?" : Number(cardData.percent).toFixed(2) + "%";
    document.getElementById("rightAnswer").innerText = cleanAnswer;
}

async function makeGuess(guess) {
    if (gameOver || currentRound === null) {
        return;
    }

    gameOver = true;

    const correctAnswer = currentRound.correct_answer;
    const wasCorrect = guess === correctAnswer;

    const rightPercent = document.getElementById("rightPercent");
    const message = document.getElementById("message");
    const choiceButtons = document.getElementById("choiceButtons");
    const nextButton = document.getElementById("nextButton");

    choiceButtons.style.display = "none";
    nextButton.style.display = "none";

    message.classList.remove("correct-pop");
    message.classList.remove("wrong-shake");

    message.innerHTML = "genuis?...";
    rightPercent.classList.add("percent-reveal");

    startCountUpSound(2000);

    await animateNumberCountUp(
        rightPercent,
        currentRound.right.percent,
        2000
    );

    stopCountUpSound();

    await wait(550);

    roundsPlayed += 1;

    const winningSide = getWinningSide();

    if (winningSide === "left") {
        document.getElementById("leftCard").classList.add("winner-card");
    }

    if (winningSide === "right") {
        document.getElementById("rightCard").classList.add("winner-card");
    }

    await wait(650);

    if (wasCorrect) {
        playSound("correct");

        const reward = getCurrentReward();

        score += 1;
        addCoins(reward);
        addCoinsToLeaderboard(reward);
        unlockAchievement("first_win");

        message.innerHTML = `Correct! +${reward} SC`;
        message.classList.add("correct-pop");

        currentStreak += 1;
        updateBestStreak(currentStreak);

        if (currentStreak >= 3) {
            unlockAchievement("streak_3");
        }

        if (currentStreak >= 5) {
            unlockAchievement("streak_5");
        }

        if (currentStreak >= 10) {
            unlockAchievement("streak_10");
        }

        checkWalletAchievements();
        launchConfetti();

        document.getElementById("score").innerText =
            score + " / " + roundsPlayed;
        updateHud();

        await wait(1300);
        await advanceChainAfterCorrect();
    } else {
        playSound("wrong");

        const penalty = getCurrentLossPenalty();
        const lossMultiplier = getLossMultiplier();
        const lostStreak = currentStreak;

        addCoins(-penalty);

        message.innerHTML =
            `Wrong! It was ${correctAnswer}. -${penalty} SC<br>` +
            `Risk x${lossMultiplier.toFixed(2)} from streak ${lostStreak}.`;

        message.classList.add("wrong-shake");

        currentStreak = 0;

        document.getElementById("score").innerText =
            score + " / " + roundsPlayed;
        updateHud();

        nextButton.innerText = "Start New Chain";
        nextButton.style.display = "inline-block";
    }
}

function getShuffleCourseCodes() {
    const selectedCards = Array.from(document.querySelectorAll(".group-card.selected"));

    const selectedText = selectedCards
        .map(card => card.innerText.toLowerCase())
        .join(" ");

    let courseCodes = [];

    if (selectedText.includes("computer")) {
        courseCodes = courseCodes.concat([
            "CSSE1001",
            "CSSE2002",
            "CSSE2310",
            "COMP3301",
            "COMP3506",
            "DECO2500",
            "COMS3200"
        ]);
    }

    if (selectedText.includes("engineering")) {
        courseCodes = courseCodes.concat([
            "ENGG1001",
            "ENGG1100",
            "ENGG1300",
            "ENGG1500",
            "ENGG1700"
        ]);
    }

    if (selectedText.includes("electrical")) {
        courseCodes = courseCodes.concat([
            "ELEC2300",
            "ELEC2400",
            "ELEC3100",
            "ELEC3310",
            "ELEC4302"
        ]);
    }

    if (selectedText.includes("mechanical")) {
        courseCodes = courseCodes.concat([
            "MECH2410",
            "MECH2210",
            "MECH3100",
            "MECH3410",
            "MECH2700"
        ]);
    }

    if (selectedText.includes("psychology")) {
        courseCodes = courseCodes.concat([
            "PSYC1020",
            "PSYC1030",
            "PSYC1040",
            "PSYC2010",
            "PSYC3020",
            "PSYC3082"
        ]);
    }

    if (selectedText.includes("information")) {
        courseCodes = courseCodes.concat([
            "INFS1200",
            "INFS2200",
            "INFS3200",
            "INFS3202",
            "INFS3208",
            "INFS4203"
        ]);
    }

    if (courseCodes.length === 0) {
        courseCodes = [
            "CSSE2310",
            "COMP3301",
            "DECO2500",
            "ELEC4302",
            "MECH2410",
            "PSYC1020",
            "INFS3200",
            "ENGG1300"
        ];
    }

    return [...new Set(courseCodes)];
}

function startShuffleAnimation() {
    const overlay = document.getElementById("shuffleOverlay");
    const courseText = document.getElementById("shuffleCourse");

    if (overlay === null || courseText === null) {
        return;
    }

    const courseCodes = getShuffleCourseCodes();

    overlay.classList.add("show");

    let index = 0;
    courseText.innerText = courseCodes[0];

    if (shuffleInterval !== null) {
        clearInterval(shuffleInterval);
    }

    if (lookingSoundInterval !== null) {
        clearInterval(lookingSoundInterval);
    }

    playRapidSound("looking");

    shuffleInterval = setInterval(() => {
        courseText.innerText = courseCodes[index % courseCodes.length];
        index += 1;
    }, 120);

    lookingSoundInterval = setInterval(() => {
        playRapidSound("looking");
    }, 120);
}

function stopShuffleAnimation() {
    const overlay = document.getElementById("shuffleOverlay");

    if (shuffleInterval !== null) {
        clearInterval(shuffleInterval);
        shuffleInterval = null;
    }

    if (lookingSoundInterval !== null) {
        clearInterval(lookingSoundInterval);
        lookingSoundInterval = null;
    }

    if (overlay !== null) {
        overlay.classList.remove("show");
    }
}

async function advanceChainAfterCorrect() {
    const message = document.getElementById("message");
    const cleanAnswer = currentRound.answer_option.replace(/^\d+\s*/, "");

    document.getElementById("preloadStatus").innerText =
        "Rolling course forward...";

    const leftCard = document.getElementById("leftCard");
    const rightCard = document.getElementById("rightCard");

    leftCard.classList.add("chain-slide-old-out");
    rightCard.classList.add("chain-slide-to-left");

    await wait(1150);

    currentRound.left = currentRound.right;

    resetAnimations();

    renderLeftCard(currentRound.left, cleanAnswer);
    swapCardColours();

    document.getElementById("rightPercent").innerText = "?";
    document.getElementById("rightCode").innerText = "";
    document.getElementById("rightName").innerText = "";
    document.getElementById("rightOffering").innerText = "";
    document.getElementById("rightAnswer").innerText = "";
    document.getElementById("message").innerHTML = "";
    document.getElementById("preloadStatus").innerText =
        "Shuffling through possible challengers...";

    await wait(1050);

    document.getElementById("message").innerHTML =
        "Finding the next challenger...";
    document.getElementById("preloadStatus").innerText =
        "Finding next challenger with the same question...";

    startShuffleAnimation();

    try {
        const challenger = await fetchChallenger();

        stopShuffleAnimation();
        playSound("found");

        const newRight = {
            course: challenger.offering.course,
            name: challenger.offering.name,
            label: challenger.offering.label,
            display: challenger.offering.display,
            sem: challenger.offering.sem,
            year: challenger.offering.year,
            count: challenger.data.count,
            percent: challenger.data.percent
        };

        currentRound.right = newRight;
        currentRound.question_name = challenger.data.question_name;
        currentRound.answer_option = challenger.data.answer_option;

        usedOfferingLabels.push(newRight.label);

        if (currentRound.right.percent > currentRound.left.percent) {
            currentRound.correct_answer = "higher";
        } else if (currentRound.right.percent < currentRound.left.percent) {
            currentRound.correct_answer = "lower";
        } else {
            currentRound.correct_answer = "same";
        }

        renderRightCard(currentRound.right, cleanAnswer, true);

        rightCard.classList.add("chain-slide-in");

        document.getElementById("choiceButtons").style.display = "flex";
        document.getElementById("nextButton").style.display = "none";
        document.getElementById("message").innerHTML = "";
        document.getElementById("preloadStatus").innerText =
            "Next challenger ready.";

        gameOver = false;

        await wait(1050);
        resetAnimations();
    } catch (error) {
        stopShuffleAnimation();
        stopLoopingSounds();

        message.innerHTML =
            "Could not find another challenger. Start a new chain.";
        document.getElementById("nextButton").innerText =
            "Start New Chain";
        document.getElementById("nextButton").style.display =
            "inline-block";
        document.getElementById("preloadStatus").innerText = "";
    }
}

function animateNumberCountUp(element, targetValue, duration = 2600) {
    return new Promise(resolve => {
        const startTime = performance.now();
        const target = Number(targetValue);

        function update(currentTime) {
            const elapsed = currentTime - startTime;
            const progress = Math.min(elapsed / duration, 1);

            const easedProgress = Math.pow(progress, 2.15);

            const currentValue = target * easedProgress;
            element.innerText = currentValue.toFixed(2) + "%";

            if (progress < 1) {
                requestAnimationFrame(update);
            } else {
                element.innerText = target.toFixed(2) + "%";
                resolve();
            }
        }

        requestAnimationFrame(update);
    });
}

function getWinningSide() {
    const left = currentRound.left.percent;
    const right = currentRound.right.percent;

    if (left > right) {
        return "left";
    }

    if (right > left) {
        return "right";
    }

    return "same";
}

function resetAnimations() {
    document.getElementById("leftCard").classList.remove("winner-card");
    document.getElementById("rightCard").classList.remove("winner-card");
    document.getElementById("rightPercent").classList.remove("percent-reveal");
    document.getElementById("message").classList.remove("correct-pop");
    document.getElementById("message").classList.remove("wrong-shake");
    document.getElementById("leftCard").classList.remove("chain-slide-old-out");
    document.getElementById("rightCard").classList.remove("chain-slide-to-left");
    document.getElementById("rightCard").classList.remove("chain-slide-in");
}

function launchConfetti() {
    const emojis = ["🎉", "✨", "⭐", "🔥", "💯", "🎊", "🚀"];

    for (let i = 0; i < 42; i++) {
        const piece = document.createElement("div");

        piece.className = "confetti-piece";
        piece.innerText = emojis[Math.floor(Math.random() * emojis.length)];
        piece.style.left = Math.random() * 100 + "vw";
        piece.style.animationDelay = Math.random() * 0.25 + "s";
        piece.style.fontSize = (18 + Math.random() * 20) + "px";

        document.body.appendChild(piece);

        setTimeout(() => {
            piece.remove();
        }, 1700);
    }
}

function toggleAchievementsMenu() {
    document.getElementById("achievementsDrawer").classList.toggle("show");
    document.getElementById("achievementsOverlay").classList.toggle("show");
    renderAchievementsPanel();
    renderLeaderboard();
}

function closeAchievementsMenu() {
    document.getElementById("achievementsDrawer").classList.remove("show");
    document.getElementById("achievementsOverlay").classList.remove("show");
}

updateHud();
loadCourseGroups();
initialiseCommonUi();