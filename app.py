from flask import Flask, request, jsonify, send_from_directory
import sqlite3
import os
from datetime import datetime

app = Flask(__name__, static_folder='static')

DB_PATH = os.environ.get('DB_PATH', 'attendance.db')

# ─────────────────────────────────────────
#  DB SETUP
# ─────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS employees (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL UNIQUE,
                department  TEXT DEFAULT '',
                join_date   TEXT
            );
            CREATE TABLE IF NOT EXISTS attendance (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                date        TEXT NOT NULL,
                check_in    TEXT,
                check_out   TEXT,
                status      TEXT DEFAULT "미퇴근",
                UNIQUE(employee_id, date),
                FOREIGN KEY(employee_id) REFERENCES employees(id)
            );
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            );
            INSERT OR IGNORE INTO settings VALUES ("work_start", "09:00");
            INSERT OR IGNORE INTO settings VALUES ("work_end",   "18:00");
            INSERT OR IGNORE INTO settings VALUES ("admin_pw",   "admin1234");
        ''')

init_db()

# ─────────────────────────────────────────
#  FRONTEND
# ─────────────────────────────────────────
@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

# ─────────────────────────────────────────
#  SETTINGS
# ─────────────────────────────────────────
@app.route('/api/settings', methods=['GET'])
def get_settings():
    with get_db() as conn:
        rows = conn.execute('SELECT key, value FROM settings').fetchall()
        return jsonify({r['key']: r['value'] for r in rows})

@app.route('/api/settings', methods=['PUT'])
def update_settings():
    data = request.json
    with get_db() as conn:
        for k, v in data.items():
            conn.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)', (k, v))
    return jsonify({'ok': True})

# ─────────────────────────────────────────
#  ADMIN LOGIN
# ─────────────────────────────────────────
@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    data = request.json or {}
    with get_db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key='admin_pw'").fetchone()
        if row and row['value'] == data.get('password'):
            return jsonify({'ok': True})
    return jsonify({'ok': False, 'error': '비밀번호가 올바르지 않습니다'}), 401

# ─────────────────────────────────────────
#  EMPLOYEES
# ─────────────────────────────────────────
@app.route('/api/employees', methods=['GET'])
def get_employees():
    with get_db() as conn:
        rows = conn.execute('SELECT * FROM employees ORDER BY name').fetchall()
        return jsonify([dict(r) for r in rows])

@app.route('/api/employees', methods=['POST'])
def add_employee():
    data = request.json or {}
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': '이름을 입력해주세요'}), 400
    with get_db() as conn:
        try:
            conn.execute(
                'INSERT INTO employees (name, department, join_date) VALUES (?,?,?)',
                (name, data.get('department', ''), datetime.now().strftime('%Y-%m-%d'))
            )
            return jsonify({'ok': True})
        except sqlite3.IntegrityError:
            return jsonify({'error': '이미 등록된 이름입니다'}), 400

@app.route('/api/employees/<int:emp_id>', methods=['DELETE'])
def delete_employee(emp_id):
    with get_db() as conn:
        conn.execute('DELETE FROM attendance WHERE employee_id=?', (emp_id,))
        conn.execute('DELETE FROM employees WHERE id=?', (emp_id,))
    return jsonify({'ok': True})

# ─────────────────────────────────────────
#  ATTENDANCE
# ─────────────────────────────────────────
@app.route('/api/attendance', methods=['GET'])
def get_attendance():
    date  = request.args.get('date')
    month = request.args.get('month')   # YYYY-MM
    emp_id = request.args.get('employee_id')

    query, params = 'SELECT * FROM attendance WHERE 1=1', []
    if date:   query += ' AND date=?';           params.append(date)
    if month:  query += ' AND date LIKE ?';      params.append(month + '%')
    if emp_id: query += ' AND employee_id=?';    params.append(emp_id)
    query += ' ORDER BY date'

    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()
        return jsonify([dict(r) for r in rows])

@app.route('/api/attendance/checkin', methods=['POST'])
def checkin():
    data   = request.json or {}
    emp_id = data.get('employee_id')
    date   = data.get('date')
    time   = data.get('time')
    with get_db() as conn:
        try:
            conn.execute(
                'INSERT INTO attendance (employee_id, date, check_in, status) VALUES (?,?,?,?)',
                (emp_id, date, time, '미퇴근')
            )
            return jsonify({'ok': True})
        except sqlite3.IntegrityError:
            return jsonify({'error': '이미 출근 처리되었습니다'}), 400

@app.route('/api/attendance/checkout', methods=['POST'])
def checkout():
    data   = request.json or {}
    emp_id = data.get('employee_id')
    date   = data.get('date')
    time   = data.get('time')
    with get_db() as conn:
        rec = conn.execute(
            'SELECT * FROM attendance WHERE employee_id=? AND date=?', (emp_id, date)
        ).fetchone()
        if not rec:
            return jsonify({'error': '출근 기록이 없습니다'}), 400

        ws = conn.execute("SELECT value FROM settings WHERE key='work_start'").fetchone()['value']
        we = conn.execute("SELECT value FROM settings WHERE key='work_end'").fetchone()['value']

        check_in = rec['check_in']
        if check_in > ws:     status = '지각'
        elif time < we:       status = '조퇴'
        else:                 status = '정상'

        conn.execute(
            'UPDATE attendance SET check_out=?, status=? WHERE employee_id=? AND date=?',
            (time, status, emp_id, date)
        )
    return jsonify({'ok': True, 'status': status})

@app.route('/api/attendance/update', methods=['PUT'])
def update_attendance():
    data   = request.json or {}
    emp_id = data.get('employee_id')
    date   = data.get('date')
    with get_db() as conn:
        existing = conn.execute(
            'SELECT id FROM attendance WHERE employee_id=? AND date=?', (emp_id, date)
        ).fetchone()
        if existing:
            conn.execute(
                'UPDATE attendance SET check_in=?, check_out=?, status=? WHERE employee_id=? AND date=?',
                (data.get('check_in'), data.get('check_out'), data.get('status'), emp_id, date)
            )
        else:
            conn.execute(
                'INSERT INTO attendance (employee_id, date, check_in, check_out, status) VALUES (?,?,?,?,?)',
                (emp_id, date, data.get('check_in'), data.get('check_out'), data.get('status'))
            )
    return jsonify({'ok': True})

# ─────────────────────────────────────────
#  RUN
# ─────────────────────────────────────────
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
