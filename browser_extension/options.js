// Load saved configuration settings when the page context mounts
document.addEventListener('DOMContentLoaded', () => {
    chrome.storage.sync.get(['apiEndpoint', 'apiKey'], (data) => {
        document.getElementById('endpoint').value = data.apiEndpoint || 'http://localhost:8050/api/import/html';
        document.getElementById('apiKey').value = data.apiKey || '';
    });
});

// Capture form values and persist them to sync storage
document.getElementById('save').addEventListener('click', () => {
    const endpoint = document.getElementById('endpoint').value.trim();
    const apiKey = document.getElementById('apiKey').value.trim();

    chrome.storage.sync.set({
        apiEndpoint: endpoint,
        apiKey: apiKey
    }, () => {
        const status = document.getElementById('status');
        status.style.color = '#859900';
        status.textContent = 'Settings saved successfully!';
        setTimeout(() => { status.textContent = ''; }, 2000);
    });
});

// Verify server connectivity and API key credentials
document.getElementById('testConn').addEventListener('click', async () => {
    const rawEndpoint = (document.getElementById('endpoint').value || 'http://localhost:8050/api/import/html').trim();
    const apiKey = (document.getElementById('apiKey').value || '').trim();
    const status = document.getElementById('status');
    status.style.color = '#586e75';
    status.textContent = 'Testing connection...';

    try {
        const parsed = new URL(rawEndpoint);
        const testUrl = `${parsed.origin}/api/cli/obsidian/config`;
        const resp = await fetch(testUrl, {
            method: 'GET',
            headers: { 'X-API-Key': apiKey }
        });
        if (resp.ok) {
            status.style.color = '#859900';
            status.textContent = 'Connected & authenticated successfully!';
        } else {
            status.style.color = '#dc322f';
            status.textContent = `Auth/Server error: HTTP ${resp.status}`;
        }
    } catch (err) {
        status.style.color = '#dc322f';
        status.textContent = `Connection failed: ${err.message}`;
    }
});
