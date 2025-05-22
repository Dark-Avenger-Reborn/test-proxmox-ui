// Login function
function login() {
    const username = document.getElementById('username').value;
    const password = document.getElementById('password').value;

    fetch('/login', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ username, password })
    })
    .then(res => {
        if (!res.ok) throw new Error("Login failed");
        return res.json();
    })
    .then(() => {
        document.getElementById('login-container').classList.add('hidden');
        document.getElementById('dashboard').classList.remove('hidden');
        document.querySelector('.background').style.filter = 'none';
        loadDashboard();
    })
    .catch(() => {
        document.getElementById('login-error').textContent = 'Invalid credentials.';
    });
}

// Logout
function logout() {
    fetch('/logout', { method: 'POST' }).then(() => location.reload());
}

// Theme from localStorage
if (localStorage.getItem('theme') === 'light') {
    document.body.classList.add('light');
}

// Toggle dark/light theme
function toggleTheme() {
    document.body.classList.toggle('light');
    localStorage.setItem('theme', document.body.classList.contains('light') ? 'light' : 'dark');
}

// On page load
window.addEventListener('DOMContentLoaded', () => {
    fetch('/vms').then(res => {
        if (res.ok) {
            document.getElementById('login-container').classList.add('hidden');
            document.getElementById('dashboard').classList.remove('hidden');
            document.querySelector('.background').style.filter = 'none';
            loadDashboard();
        }
    });
});

// Load dashboard and VM tree
function loadDashboard() {
    fetch('/vms')
        .then(res => res.json())
        .then(data => {
            document.getElementById('welcome').textContent = `Welcome, ${data.user}`;
            buildVMTree(data.vms);
            startPolling();
        });
}

// Build nested VM tree by tags
function buildVMTree(vms) {
    const tree = {};
    vms.forEach(vm => {
        let node = tree;
        vm.tags.forEach(tag => {
            if (!node[tag]) node[tag] = {};
            node = node[tag];
        });
        node[vm.name] = vm;
    });

    const container = document.getElementById('vm-tree');
    container.innerHTML = renderTree(tree);
}

// Render tree as collapsible list
function renderTree(obj, path = []) {
    let html = '<ul>';
    for (let key in obj) {
        const node = obj[key];
        const nodeId = path.concat(key).join('-');

        if (node.name) {
            html += `<li><button onclick="showVM('${node.name}')">${key}</button></li>`;
        } else {
            html += `
                <li>
                    <span class="folder" onclick="toggleFolder('${nodeId}')">▶ ${key}</span>
                    <div id="folder-${nodeId}" class="collapsed">
                        ${renderTree(node, path.concat(key))}
                    </div>
                </li>
            `;
        }
    }
    return html + '</ul>';
}

function toggleFolder(id) {
    const el = document.getElementById('folder-' + id);
    el.classList.toggle('collapsed');
}

function showVM(name) {
    fetch('/vms')
        .then(res => res.json())
        .then(data => {
            const vm = data.vms.find(v => v.name === name);
            const panel = document.getElementById('vm-panel');

            panel.innerHTML = `
                <h3>${vm.name}</h3>
                <p>Status: <span id="vm-status">${vm.status}</span></p>
                <button onclick="controlVM('${vm.name}', 'start')">Start</button>
                <button onclick="controlVM('${vm.name}', 'stop')">Stop</button>
                <button onclick="controlVM('${vm.name}', 'restart')">Restart</button>
                <br><br>
                <a href="https://${window.location.hostname}/novnc/${vm.name}" target="_blank">Open noVNC</a>
            `;
        });
}

function controlVM(vm, action) {
    fetch('/control_vm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ vm, action })
    })
    .then(res => res.json())
    .then(data => {
        if (data.error) {
            alert(`Error: ${data.error}`);
        } else {
            updateVM(data);
        }
    });
}

function updateVM(vm) {
    const panel = document.getElementById('vm-panel');
    const header = panel.querySelector('h3');
    const status = document.getElementById('vm-status');

    if (status && header && header.textContent === vm.name) {
        status.textContent = vm.status;
    }
}

// Polling every 5 seconds
function startPolling() {
    setInterval(() => {
        const panel = document.getElementById('vm-panel');
        const header = panel.querySelector('h3');

        if (header) {
            const vmName = header.textContent;
            fetch('/vms')
                .then(res => res.json())
                .then(data => {
                    const vm = data.vms.find(v => v.name === vmName);
                    if (vm) updateVM(vm);
                });
        }
    }, 5000);
}
