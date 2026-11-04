import os
from datetime import datetime, timezone
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, abort, Response
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select
import csv, io

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-only-change-this')
url = os.environ.get('DATABASE_URL', 'sqlite:///jja_tech.db')
if url.startswith('postgres://'): url = url.replace('postgres://','postgresql://',1)
app.config['SQLALCHEMY_DATABASE_URI'] = url
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_pre_ping': True}
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('COOKIE_SECURE','0') == '1'
app.config['WTF_CSRF_TIME_LIMIT'] = None
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024
db = SQLAlchemy(app)
csrf = CSRFProtect(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

def now(): return datetime.now(timezone.utc)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='operator')

class Equipment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    asset_tag = db.Column(db.String(80), unique=True, nullable=False)
    kind = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='available')
    note = db.Column(db.String(300), default='')

class Loan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    teacher = db.Column(db.String(150), nullable=False)
    classroom = db.Column(db.String(60), nullable=False)
    taken_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)
    due_at = db.Column(db.DateTime(timezone=True), nullable=True)
    operator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    note = db.Column(db.String(300), default='')
    items = db.relationship('LoanItem', backref='loan', lazy=True)

class LoanItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    loan_id = db.Column(db.Integer, db.ForeignKey('loan.id'), nullable=False)
    equipment_id = db.Column(db.Integer, db.ForeignKey('equipment.id'), nullable=False)
    returned_at = db.Column(db.DateTime(timezone=True))
    returned_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    return_condition = db.Column(db.String(20))
    equipment = db.relationship('Equipment')

class Audit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    action = db.Column(db.String(40), nullable=False)
    detail = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)

@login_manager.user_loader
def load_user(uid): return db.session.get(User, int(uid))

def operator_only(fn):
    @wraps(fn)
    @login_required
    def wrapper(*a, **kw):
        if current_user.role not in ('operator','admin'): abort(403)
        return fn(*a, **kw)
    return wrapper

def admin_only(fn):
    @wraps(fn)
    @login_required
    def wrapper(*a, **kw):
        if current_user.role != 'admin': abort(403)
        return fn(*a, **kw)
    return wrapper

@app.template_filter('dt')
def dt(value):
    if not value: return '—'
    return value.strftime('%d/%m/%Y %H:%M UTC')

@app.route('/health')
def health(): return {'status':'ok'}

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        u = db.session.scalar(select(User).where(User.username == request.form.get('username','').strip()))
        if u and check_password_hash(u.password_hash, request.form.get('password','')):
            login_user(u)
            return redirect(url_for('dashboard'))
        flash('Usuário ou senha inválidos.', 'error')
    return render_template('login.html')

@app.post('/logout')
@login_required
def logout(): logout_user(); return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard():
    equipments = db.session.scalars(select(Equipment).order_by(Equipment.asset_tag)).all()
    loans = db.session.scalars(select(Loan).order_by(Loan.id.desc()).limit(60)).all()
    return render_template('dashboard.html', equipments=equipments, loans=loans,
        available=sum(e.status=='available' for e in equipments),
        borrowed=sum(e.status=='borrowed' for e in equipments),
        damaged=sum(e.status=='damaged' for e in equipments))

@app.post('/equipment')
@admin_only
def equipment_add():
    tag = request.form.get('asset_tag','').strip().upper()
    kind = request.form.get('kind','')
    if not tag or len(tag)>80 or kind not in ('Notebook','Tablet'):
        flash('Patrimônio ou tipo inválido.', 'error'); return redirect(url_for('dashboard'))
    try:
        e = Equipment(asset_tag=tag, kind=kind)
        db.session.add(e)
        db.session.add(Audit(actor_id=current_user.id, action='equipment_created',detail=tag))
        db.session.commit(); flash('Equipamento cadastrado.', 'success')
    except IntegrityError:
        db.session.rollback(); flash('Patrimônio já cadastrado.', 'error')
    return redirect(url_for('dashboard'))

@app.post('/loan')
@operator_only
def loan_create():
    teacher=request.form.get('teacher','').strip()
    classroom=request.form.get('classroom','').strip()
    tags=list(dict.fromkeys(t.strip().upper() for t in request.form.get('tags','').replace(',', '\n').splitlines() if t.strip()))
    if not teacher or not classroom or len(teacher)>150 or len(classroom)>60 or not tags or len(tags)>150:
        flash('Informe professor, turma e até 150 patrimônios.', 'error'); return redirect(url_for('dashboard'))
    try:
        items=db.session.scalars(select(Equipment).where(Equipment.asset_tag.in_(tags)).order_by(Equipment.id).with_for_update()).all()
        if len(items)!=len(tags) or any(e.status!='available' for e in items):
            db.session.rollback(); flash('Há patrimônios inexistentes ou indisponíveis.', 'error'); return redirect(url_for('dashboard'))
        due_text=request.form.get('due_at','').strip()
        due=datetime.fromisoformat(due_text).replace(tzinfo=timezone.utc) if due_text else None
        loan=Loan(teacher=teacher,classroom=classroom,operator_id=current_user.id,due_at=due,note=request.form.get('note','')[:300])
        db.session.add(loan); db.session.flush()
        for e in items:
            e.status='borrowed'; db.session.add(LoanItem(loan_id=loan.id,equipment_id=e.id))
        db.session.add(Audit(actor_id=current_user.id,action='loan_created',detail=f'Empréstimo #{loan.id}: {", ".join(tags)}'))
        db.session.commit(); flash(f'Empréstimo #{loan.id} registrado: {len(items)} equipamento(s).','success')
    except ValueError:
        db.session.rollback(); flash('Previsão de devolução inválida.','error')
    except Exception:
        db.session.rollback(); app.logger.exception('Loan error'); flash('Não foi possível registrar a retirada.','error')
    return redirect(url_for('dashboard'))

@app.post('/return/<int:loan_id>')
@operator_only
def loan_return(loan_id):
    selected=request.form.getlist('item_ids')
    condition=request.form.get('condition','good')
    if condition not in ('good','damaged') or not selected or len(set(selected))!=len(selected) or not all(i.isdecimal() for i in selected):
        flash('Selecione os itens e a condição.','error'); return redirect(url_for('dashboard'))
    try:
        ids=[int(x) for x in selected]
        items=db.session.scalars(select(LoanItem).where(LoanItem.loan_id==loan_id,LoanItem.id.in_(ids)).order_by(LoanItem.id).with_for_update()).all()
        if len(items)!=len(ids) or any(i.returned_at for i in items):
            db.session.rollback(); flash('Itens inválidos ou já devolvidos.','error'); return redirect(url_for('dashboard'))
        eqs=db.session.scalars(select(Equipment).where(Equipment.id.in_([i.equipment_id for i in items])).order_by(Equipment.id).with_for_update()).all()
        for item in items:
            item.returned_at=now(); item.returned_by=current_user.id; item.return_condition=condition
        for eq in eqs: eq.status='available' if condition=='good' else 'damaged'
        db.session.add(Audit(actor_id=current_user.id,action='items_returned',detail=f'Empréstimo #{loan_id}: {len(items)} itens; condição={condition}'))
        db.session.commit(); flash('Devolução registrada.','success')
    except Exception:
        db.session.rollback(); app.logger.exception('Return error'); flash('Não foi possível registrar a devolução.','error')
    return redirect(url_for('dashboard'))

@app.get('/export.csv')
@login_required
def export():
    output=io.StringIO(); writer=csv.writer(output)
    writer.writerow(['Emprestimo','Professor','Turma','Patrimonio','Tipo','Retirada UTC','Devolucao UTC','Condicao'])
    for item in db.session.scalars(select(LoanItem).order_by(LoanItem.id)).all():
        writer.writerow([item.loan_id,item.loan.teacher,item.loan.classroom,item.equipment.asset_tag,item.equipment.kind,item.loan.taken_at,item.returned_at or '',item.return_condition or ''])
    return Response('\ufeff'+output.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=jja_tech_historico.csv'})

@app.cli.command('init-db')
def init_db():
    db.create_all()
    username=os.environ.get('ADMIN_USERNAME','admin').strip()
    password=os.environ.get('ADMIN_PASSWORD','')
    if not password or len(password)<12: raise RuntimeError('Defina ADMIN_PASSWORD com pelo menos 12 caracteres.')
    if not db.session.scalar(select(User).where(User.username==username)):
        db.session.add(User(username=username,password_hash=generate_password_hash(password),role='admin'))
        db.session.commit(); print('Administrador criado.')
    else: print('Banco pronto. Administrador já existe; senha não alterada.')

if __name__=='__main__': app.run(debug=os.environ.get('FLASK_DEBUG')=='1')
