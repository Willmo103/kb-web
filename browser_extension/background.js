// Listen for the extensions toolbar button action click
chrome.action.onClicked.addListener(async (tab) => {
    // 1. Guard against system/blank URLs
    if (!tab.url || !tab.url.startsWith("http")) {
        showBadge("ERR", "#EF4444"); // Red error badge
        return;
    }

    // Indicate synchronization activity
    showBadge("SYNC", "#4F46E5"); // Indigo syncing badge

    try {
        // 2. Inject scripting into active tab context to extract DOM HTML
        const injection = await chrome.scripting.executeScript({
            target: { tabId: tab.id },
            func: () => document.documentElement.outerHTML
        });

        if (!injection || !injection[0]) {
            showBadge("ERR", "#EF4444");
            return;
        }

        const htmlContent = injection[0].result;

        // 3. Fetch endpoint/keys configurations from options storage
        const settings = await chrome.storage.sync.get(["apiEndpoint", "apiKey"]);
        const endpoint = settings.apiEndpoint || "http://localhost:8050/api/import/html";
        const apiKey = settings.apiKey || "";

        const payload = {
            url: tab.url,
            html_content: htmlContent,
            title: tab.title
        };

        // 4. POST HTML payload to the knowledge base API
        const response = await fetch(endpoint, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-API-Key": apiKey
            },
            body: JSON.stringify(payload)
        });

        // 5. Update user-facing badge feedback
        if (response.ok) {
            showBadge("OK", "#10B981"); // Green success badge
        } else {
            console.error("HTTP error response returned: Status", response.status);
            showBadge("ERR", "#EF4444");
        }
    } catch (error) {
        console.error("Failed page sync operation:", error);
        showBadge("ERR", "#EF4444");
    }
});

/**
 * Utility helper displaying temporary text badges over the extension icon.
 * Clears status automatically after a 2-second timeout window.
 */
function showBadge(text, color) {
    chrome.action.setBadgeText({ text: text });
    chrome.action.setBadgeBackgroundColor({ color: color });
    setTimeout(() => {
        chrome.action.setBadgeText({ text: "" });
    }, 2000);
}
