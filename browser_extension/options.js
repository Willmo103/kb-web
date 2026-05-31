// Load saved configuration settings when the page context mounts
document.addEventListener('DOMContentLoaded', () => {
    chrome.storage.sync.get(['apiEndpoint', 'apiKey'], (data) => {
        document.getElementById('endpoint').value = data.apiEndpoint || 'http://localhost:8050/api/import/html';
        document.getElementById('apiKey').value = data.apiKey || '';
    });
});

// Capture form values and persist them to sync storage
document.getElementById('save').addEventListener('click', () => {
    const endpoint = document.getElementById('endpoint').value;
    const apiKey = document.getElementById('apiKey').value;

    chrome.storage.sync.set({
        apiEndpoint: endpoint,
        apiKey: apiKey
    }, () => {
        const status = document.getElementById('status');
        status.textContent = 'Settings saved successfully!';
        setTimeout(() => { status.textContent = ''; }, 2000);
    });
});
