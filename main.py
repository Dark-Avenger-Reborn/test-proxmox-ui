import os
from flask import Flask, render_template, request, jsonify, abort
from flask_login import LoginManager, UserMixin, login_user, current_user, logout_user
from flask_socketio import SocketIO, emit, disconnect
from proxmoxer import ProxmoxAPI
from dotenv import load_dotenv

load_dotenv()

# Setup
app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(32)

# Session cookie security
app.config.update(
    SESSION_COOKIE_SECURE=True,       # Only over HTTPS (you’re behind Cloudflare)
    SESSION_COOKIE_HTTPONLY=True,     # Prevent JS access to cookies
    SESSION_COOKIE_SAMESITE='Lax'     # Helps prevent CSRF
)

# Proxmox connection
proxmox = ProxmoxAPI(
    os.environ.get('PROXMOX_SERVER'),
    user=os.environ.get('PROXMOX_USER'),
    password=os.environ.get('PROXMOX_PASSWORD'),
    verify_ssl=False,
)

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)

# Socket.IO setup
socketio = SocketIO(app, manage_session=False)

# Dummy user store
users = {
    'admin': {'password': 'admin'},
    'red1': {'password': 'test'},
    'blue1': {'password': 'test'}
}

# User class
class User(UserMixin):
    def __init__(self, username):
        self.id = username

@login_manager.user_loader
def load_user(user_id):
    if user_id in users:
        return User(user_id)

# Routes and Socket.IO events

@app.route('/')
def index():
    return render_template('index.html')

# Login API
@app.route('/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')

    if username in users and users[username]['password'] == password:
        login_user(User(username))
        return jsonify(success=True)
    return jsonify(success=False), 401

# Logout API
@app.route('/logout', methods=['POST'])
def logout():
    logout_user()
    return jsonify(success=True)

# VM list API
@app.route('/vms')
def get_vms():
    if current_user.is_authenticated:
        # Fetch VMs from Proxmox
        vms = []
        nodes = proxmox.nodes.get()  # Get list of all nodes (hosts)
        
        for node in nodes:
            node_vms = proxmox.nodes(node['node']).qemu.get()  # Get QEMU VMs from the node
            for vm in node_vms:
                vms.append({
                    'name': vm['name'],
                    'status': vm['status'],
                    'tags': vm.get('tags', []),  # Assuming you're managing tags within Proxmox
                })
        
        return jsonify(vms=vms, user=current_user.id)
    return jsonify(error="Unauthorized"), 401

# Socket.IO: control VMs
@socketio.on('control_vm')
def handle_vm_control(data):
    if not current_user.is_authenticated:
        emit('auth_error', {'error': 'Unauthorized'})
        print(f"[SECURITY] Unauthorized WebSocket access: {request.sid}")
        disconnect()
        return

    vm_name = data.get('vm')
    action = data.get('action')
    node_name = data.get('node')  # Assuming we have node name info from Proxmox

    try:
        # Fetch VM information by name
        node_vms = proxmox.nodes(node_name).qemu.get()  # Get QEMU VMs from the node
        vm = next((v for v in node_vms if v['name'] == vm_name), None)

        if not vm:
            emit('vm_update', {'error': f'VM {vm_name} not found on node {node_name}'})
            return
        
        # Perform the requested action
        if action == 'start':
            proxmox.nodes(node_name).qemu(vm['vmid']).status.start.post()
        elif action == 'stop':
            proxmox.nodes(node_name).qemu(vm['vmid']).status.stop.post()
        elif action == 'restart':
            proxmox.nodes(node_name).qemu(vm['vmid']).status.reboot.post()
        
        # After action, update the VM status and emit the changes to the frontend
        updated_vm = proxmox.nodes(node_name).qemu(vm['vmid']).status.get()
        emit('vm_update', updated_vm, broadcast=True)

    except Exception as e:
        emit('vm_update', {'error': str(e)})

if __name__ == '__main__':
    socketio.run(app, debug=False, host='0.0.0.0', port=5000)
