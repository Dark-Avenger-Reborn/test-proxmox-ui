import os
from flask import Flask, render_template, request, jsonify
from flask_login import LoginManager, UserMixin, login_user, current_user, logout_user
from proxmoxer import ProxmoxAPI
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(32)
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax'
)

# Proxmox
proxmox = ProxmoxAPI(
    os.environ.get('PROXMOX_SERVER'),
    user=os.environ.get('PROXMOX_USER'),
    password=os.environ.get('PROXMOX_PASSWORD'),
    verify_ssl=False,
)

# Auth
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
                    'tags': vm.get('tags', '').split(',') if 'tags' in vm else [],
                })
        return jsonify(vms=vms, user=current_user.id)
    return jsonify(error="Unauthorized"), 401

@app.route('/control_vm', methods=['POST'])
def control_vm():
    if not current_user.is_authenticated:
        return jsonify(error="Unauthorized"), 401

    data = request.get_json()
    vm_name = data.get('vm')
    action = data.get('action')

    try:
        for node in proxmox.nodes.get():
            vms = proxmox.nodes(node['node']).qemu.get()
            vm = next((v for v in vms if v['name'] == vm_name), None)
            if vm:
                node_name = node['node']
                break
        else:
            return jsonify(error=f"VM {vm_name} not found"), 404

        vmid = vm['vmid']
        if action == 'start':
            proxmox.nodes(node_name).qemu(vmid).status.start.post()
        elif action == 'stop':
            proxmox.nodes(node_name).qemu(vmid).status.stop.post()
        elif action == 'restart':
            proxmox.nodes(node_name).qemu(vmid).status.reboot.post()

        updated_vm = proxmox.nodes(node_name).qemu(vmid).status.get()
        return jsonify({
            'name': vm_name,
            'status': updated_vm['status']
        })
    except Exception as e:
        return jsonify(error=str(e)), 500

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)
