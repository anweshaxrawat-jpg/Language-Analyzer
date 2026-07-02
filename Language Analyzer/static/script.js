const textInput = document.getElementById("textInput");
const languageBtn = document.getElementById("languageBtn");
const piiBtn = document.getElementById("piiBtn");
const summaryBtn = document.getElementById("summaryBtn");
const result = document.getElementById("result");
const loading = document.getElementById("loading");
const counter = document.getElementById("count");
const copyBtn = document.getElementById("copyBtn");

const allButtons = [languageBtn, piiBtn, summaryBtn];

textInput.addEventListener("input", () => {
    counter.textContent = textInput.value.length;
});

copyBtn.addEventListener("click", () => {
    navigator.clipboard.writeText(result.innerText);

    copyBtn.innerText = "✅ Copied!";

    setTimeout(() => {
        copyBtn.innerText = "📋 Copy";
    }, 1500);
});

// Escapes user/API-derived text before it's inserted via innerHTML,
// so text like "<img src=x onerror=...>" is rendered as plain text
// instead of being executed as HTML.
function escapeHTML(str) {
    const div = document.createElement("div");
    div.textContent = str ?? "";
    return div.innerHTML;
}

async function callAPI(route) {

    const text = textInput.value.trim();

    if (!text) {
        showError("Please enter some text.");
        return;
    }

    const text = textInput.value.trim();

if (!text) {
    showError("Please enter some text.");
    return;
} 
    loading.hidden = false;
    result.innerHTML = "";
    allButtons.forEach(b => b.disabled = true);

    try {

        const response = await fetch(route, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ text })
        });

        const data = await response.json();

        if (!response.ok) {
            showError(data.error || "Something went wrong.");
            return;
        }

        if (route === "/api/language") {
            showLanguage(data);
        }

        if (route === "/api/pii") {
            showPII(data);
        }

        if (route === "/api/summarize") {
            showSummary(data);
        }

    }

    catch (err) {

        showError("Unable to connect to server.");

    }

    finally {

        loading.hidden = true;
        allButtons.forEach(b => b.disabled = false);

    }

}

languageBtn.onclick = () => callAPI("/api/language");
piiBtn.onclick = () => callAPI("/api/pii");
summaryBtn.onclick = () => callAPI("/api/summarize");


function showLanguage(data) {

    result.innerHTML = `
        <div class="result-title">🌍 Language Detection</div>

        <div class="result-item">
            <strong>Language:</strong> ${escapeHTML(data.language)}
        </div>

        <div class="result-item">
            <strong>ISO Code:</strong> ${escapeHTML(data.iso6391)}
        </div>

        <div class="result-item success">
            <strong>Confidence:</strong> ${escapeHTML(String(data.confidence))}%
        </div>
    `;

}


function showPII(data) {

    let entities = "";

    if (data.entities.length === 0) {

        entities = "<p>No personal information detected.</p>";

    }

    else {

        data.entities.forEach(entity => {

            entities += `
                <li>
                    ${escapeHTML(entity.text)}
                    (${escapeHTML(entity.category)})
                </li>
            `;

        });

        entities = `<ul>${entities}</ul>`;
    }

    result.innerHTML = `
        <div class="result-title">
            🔒 PII Redaction
        </div>

        <p><strong>Redacted Text</strong></p>

        <p>${escapeHTML(data.redactedText)}</p>

        <br>

        <p><strong>Detected Entities</strong></p>

        ${entities}
    `;

}


function showSummary(data) {

    result.innerHTML = `
        <div class="result-title">
            📝 AI Summary
        </div>

        <p>
            ${escapeHTML(data.summary)}
        </p>
    `;

}


function showError(message) {

    result.innerHTML = `
        <div class="result-title error">
            ❌ Error
        </div>

        <p>${escapeHTML(message)}</p>
    `;

}
