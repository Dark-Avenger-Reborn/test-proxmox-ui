import os
from flask import Flask, render_template, request, jsonify
from flask_login import LoginManager, UserMixin, login_user, current_user, logout_user
from proxmoxer import ProxmoxAPI
from dotenv import load_dotenv
from flask_sock import Sock
import websockets
import asyncio

# Load environment variables
load_dotenv()

# Initialize the Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(32)
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax'
)

# Proxmox API connection
proxmox = ProxmoxAPI(
    os.environ.get('PROXMOX_SERVER'),
    user=os.environ.get('PROXMOX_USER'),
    password=os.environ.get('PROXMOX_PASSWORD'),
    verify_ssl=False,
)

# Auth Setup
login_manager = LoginManager()
login_manager.init_app(app)

users = {
    'admin': {'password': 'admin'},
    'red1': {'password': 'test'},
    'blue1': {'password': 'test'}
}

class User(UserMixin):
    def __init__(self, username):
        self.id = username

@login_manager.user_loader
def load_user(user_id):
    if user_id in users:
        return User(user_id)

# WebSocket proxy setup
sock = Sock(app)

@sock.route('/vncws/<node>/<int:vmid>')
def vnc_websocket(ws, node, vmid):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        # Request VNC ticket and port from Proxmox
        resp = proxmox.nodes(node).qemu(vmid).vncproxy.post()
        port = resp['port']
        ticket = resp['ticket']

        # Build WebSocket target URL (internal)
        target_ws_url = f"wss://{os.environ['PROXMOX_SERVER']}:8006/api2/json/nodes/{node}/qemu/{vmid}/vncwebsocket?port={port}&vncticket={ticket}"

        async def proxy():
            async with websockets.connect(
                target_ws_url,
                ssl=True,
                extra_headers={'Authorization': f"PVEAPIToken={os.environ['PROXMOX_USER']}={ticket}"}
            ) as remote_ws:

                async def forward_to_proxmox():
                    while True:
                        msg = await ws.receive()
                        await remote_ws.send(msg)

                async def forward_to_client():
                    while True:
                        msg = await remote_ws.recv()
                        ws.send(msg)

                await asyncio.gather(forward_to_proxmox(), forward_to_client())

        loop.run_until_complete(proxy())
    except Exception as e:
        print(f"WebSocket error: {e}")
        ws.close()

@app.route('/novnc/<vmid>')
def novnc(vm_id):
    if not current_user.is_authenticated:
        return jsonify(error="Unauthorized"), 401

    try:
        # Find VM's node
        target_node = None
        for node in proxmox.nodes.get():
            node_name = node['node']
            for vm in proxmox.nodes(node_name).qemu.get():
                if str(vm['vmid']) == str(vm_id):
                    target_node = node_name
                    break
            if target_node:
                break

        if not target_node:
            return "VM not found", 404

        # We will handle the WebSocket proxying internally
        websocket_url = f"wss://{request.host}/vncws/{target_node}/{vm_id}"

        return render_template('novnc.html', websocket_url=websocket_url)

    except Exception as e:
        return f"Error: {str(e)}", 500



# Route to display VMs
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')

    if username in users and users[username]['password'] == password:
        login_user(User(username))
        return jsonify(success=True)
    return jsonify(success=False), 401

@app.route('/logout', methods=['POST'])
def logout():
    logout_user()
    return jsonify(success=True)

# Get VM details
@app.route('/vms')
def get_vms():
    if current_user.is_authenticated:
        vms = []
        nodes = proxmox.nodes.get()
        for node in nodes:
            for vm in proxmox.nodes(node['node']).qemu.get():
                vms.append({
                    'name': vm['name'],
                    'status': vm['status'],
                    'tags': vm.get('tags', '').split(';') if 'tags' in vm else [],
                    'vmid': vm['vmid'],
                    'node': node['node']
                })
        return jsonify(vms=vms, user=current_user.id)
    return jsonify(error="Unauthorized"), 401

# Route to handle VM control actions
@app.route('/control_vm', methods=['POST'])
def control_vm():
    if not current_user.is_authenticated:
        return jsonify(error="Unauthorized"), 401

    data = request.get_json()
    vm_name = data.get('vm')
    action = data.get('action')

    try:
        target_vm = None
        for node in proxmox.nodes.get():
            node_name = node['node']
            vms = proxmox.nodes(node_name).qemu.get()
            for vm in vms:
                if vm.get('name') == vm_name:
                    target_vm = {
                        'node': node_name,
                        'vmid': vm['vmid'],
                        'name': vm['name']
                    }
                    break
            if target_vm:
                break

        if not target_vm:
            return jsonify(error=f"VM '{vm_name}' not found"), 404

        node_name = target_vm['node']
        vmid = target_vm['vmid']

        if action == 'start':
            proxmox.nodes(node_name).qemu(vmid).status.start.post()
        elif action == 'stop':
            proxmox.nodes(node_name).qemu(vmid).status.stop.post()
        elif action == 'restart':
            proxmox.nodes(node_name).qemu(vmid).status.reboot.post()
        else:
            return jsonify(error="Invalid action"), 400

        updated_status = proxmox.nodes(node_name).qemu(vmid).status.current.get()

        return jsonify({
            'name': vm_name,
            'status': updated_status['status']
        })

    except Exception as e:
        return jsonify(error=str(e)), 500

# Start Flask app
if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)
