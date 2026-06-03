const screenEl = document.getElementById("terminal-screen");
const promptEl = document.getElementById("terminal-prompt");
const inputEl = document.getElementById("terminal-input");
const formEl = document.getElementById("terminal-form");
const resetButton = document.getElementById("reset-button");

const PALETTE_STORAGE_KEY = "taxonomica-terminal-palette";
const PALETTES = [
    "classic-green",
    "desert",
    "meadow",
    "reef",
    "deep-sea",
    "arctic",
    "volcano",
    "autumn-forest",
];
const URL_PATTERN = /https?:\/\/[^\s<>"']+/g;

function selectPalette() {
    let storedPalette = null;
    try {
        storedPalette = sessionStorage.getItem(PALETTE_STORAGE_KEY);
    } catch {
        storedPalette = null;
    }

    if (PALETTES.includes(storedPalette)) {
        document.documentElement.dataset.palette = storedPalette;
        return;
    }

    const palette = PALETTES[Math.floor(Math.random() * PALETTES.length)];
    try {
        sessionStorage.setItem(PALETTE_STORAGE_KEY, palette);
    } catch {
        // A blocked sessionStorage should not keep the terminal from loading.
    }
    document.documentElement.dataset.palette = palette;
}

function renderTerminalText(text) {
    const fragment = document.createDocumentFragment();
    let currentIndex = 0;

    for (const match of text.matchAll(URL_PATTERN)) {
        const url = match[0];
        const urlIndex = match.index;
        if (urlIndex > currentIndex) {
            fragment.append(document.createTextNode(text.slice(currentIndex, urlIndex)));
        }

        const link = document.createElement("a");
        link.href = url;
        link.textContent = url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        fragment.append(link);
        currentIndex = urlIndex + url.length;
    }

    if (currentIndex < text.length) {
        fragment.append(document.createTextNode(text.slice(currentIndex)));
    }

    screenEl.replaceChildren(fragment);
}

function renderTerminal(data) {
    renderTerminalText(data.screen || "");
    promptEl.textContent = data.prompt || ">";
    inputEl.value = "";
    window.requestAnimationFrame(() => {
        screenEl.scrollTop = screenEl.scrollHeight;
        inputEl.focus();
    });
}

function renderError(message) {
    renderTerminalText([
        "Taxonomica web terminal error:",
        "",
        message,
        "",
        "Try reloading the page or pressing Reset.",
    ].join("\n"));
    promptEl.textContent = ">";
    inputEl.focus();
}

async function fetchJson(url, options = {}) {
    const response = await fetch(url, options);
    if (!response.ok) {
        throw new Error(`${response.status} ${response.statusText}`);
    }
    return response.json();
}

async function loadSession() {
    inputEl.disabled = true;
    try {
        renderTerminal(await fetchJson("/api/session"));
    } catch (error) {
        renderError(error.message);
    } finally {
        inputEl.disabled = false;
    }
}

async function submitCommand(command) {
    inputEl.disabled = true;
    try {
        const data = await fetchJson("/api/command", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ command }),
        });
        renderTerminal(data);
    } catch (error) {
        renderError(error.message);
    } finally {
        inputEl.disabled = false;
    }
}

async function resetSession() {
    inputEl.disabled = true;
    try {
        renderTerminal(await fetchJson("/api/reset", { method: "POST" }));
    } catch (error) {
        renderError(error.message);
    } finally {
        inputEl.disabled = false;
    }
}

formEl.addEventListener("submit", (event) => {
    event.preventDefault();
    submitCommand(inputEl.value);
});

resetButton.addEventListener("click", () => {
    resetSession();
});

document.addEventListener("click", (event) => {
    if (event.target.closest("a")) {
        return;
    }
    inputEl.focus();
});

selectPalette();
loadSession();
