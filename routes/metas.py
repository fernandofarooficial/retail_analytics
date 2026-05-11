import calendar as pycal
from datetime import date, timedelta
from functools import wraps

from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, abort, jsonify, session)
import db

metas_bp = Blueprint('metas', __name__, url_prefix='/retail_analytics/metas')


def _admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))
        if session.get('user_type_id') != 'adm':
            abort(403)
        return f(*args, **kwargs)
    return decorated


def _entity_name(target):
    if target['entity_type'] == 'store':
        return target.get('store_name') or f'Loja {target["store_id"]}'
    elif target['entity_type'] == 'company':
        return target.get('company_name') or f'Empresa {target["company_id"]}'
    return target.get('company_group_name') or f'Grupo {target["company_group_id"]}'


# ── Hub ────────────────────────────────────────────────────────────────────────

@metas_bp.route('/')
@_admin_required
def index():
    return render_template('metas/index.html')


# ── Objetivos ──────────────────────────────────────────────────────────────────

@metas_bp.route('/objetivos', methods=['GET', 'POST'])
@_admin_required
def objetivos():
    if request.method == 'POST':
        action = request.form.get('_action')
        try:
            if action == 'criar':
                db.execute(
                    """INSERT INTO faciais.goals
                       (goal_name, goal_description, goal_unit_id, direction, base_period_id)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (
                        request.form['goal_name'].strip(),
                        request.form.get('goal_description', '').strip() or None,
                        request.form['goal_unit_id'],
                        request.form['direction'],
                        request.form['base_period_id'],
                    )
                )
                flash('Meta criada com sucesso.', 'success')

            elif action == 'editar':
                db.execute(
                    """UPDATE faciais.goals SET
                       goal_name=%s, goal_description=%s, goal_unit_id=%s,
                       direction=%s, base_period_id=%s
                       WHERE goal_id=%s""",
                    (
                        request.form['goal_name'].strip(),
                        request.form.get('goal_description', '').strip() or None,
                        request.form['goal_unit_id'],
                        request.form['direction'],
                        request.form['base_period_id'],
                        request.form['_id'],
                    )
                )
                flash('Meta atualizada com sucesso.', 'success')

            elif action == 'toggle_ativo':
                db.execute(
                    "UPDATE faciais.goals SET is_active = NOT is_active WHERE goal_id=%s",
                    (request.form['_id'],)
                )
                flash('Status da meta atualizado.', 'success')

            elif action == 'excluir':
                db.execute("DELETE FROM faciais.goals WHERE goal_id=%s", (request.form['_id'],))
                flash('Meta excluída com sucesso.', 'success')

        except Exception as e:
            err = str(e).lower()
            if 'foreign key' in err or 'violates' in err:
                flash('Não é possível excluir: existem alocações vinculadas.', 'error')
            else:
                flash(f'Erro: {e}', 'error')

        return redirect(url_for('metas.objetivos'))

    goals = db.query_all("""
        SELECT g.*, gu.goal_unit_name, gu.symbol, gp.goal_period_name,
               COUNT(gt.goal_target_id) AS num_targets
        FROM   faciais.goals g
        JOIN   faciais.goal_units   gu ON gu.goal_unit_id   = g.goal_unit_id
        JOIN   faciais.goal_periods gp ON gp.goal_period_id = g.base_period_id
        LEFT JOIN faciais.goal_targets gt ON gt.goal_id = g.goal_id
        GROUP BY g.goal_id, gu.goal_unit_name, gu.symbol, gp.goal_period_name
        ORDER  BY g.goal_name
    """)
    units   = db.query_all("SELECT * FROM faciais.goal_units   ORDER BY goal_unit_name")
    periods = db.query_all("SELECT * FROM faciais.goal_periods ORDER BY period_order")
    return render_template('metas/objetivos.html', goals=goals, units=units, periods=periods)


# ── Alocações ─────────────────────────────────────────────────────────────────

@metas_bp.route('/objetivos/<int:goal_id>/alocacoes', methods=['GET', 'POST'])
@_admin_required
def alocacoes(goal_id):
    goal = db.query_one(
        """SELECT g.*, gu.symbol FROM faciais.goals g
           JOIN faciais.goal_units gu ON gu.goal_unit_id = g.goal_unit_id
           WHERE g.goal_id = %s""",
        (goal_id,)
    )
    if not goal:
        abort(404)

    if request.method == 'POST':
        action = request.form.get('_action')
        try:
            if action == 'criar':
                entity_type = request.form['entity_type']
                store_id    = request.form.get('store_id')         or None
                company_id  = request.form.get('company_id')       or None
                group_id    = request.form.get('company_group_id') or None
                db.execute(
                    """INSERT INTO faciais.goal_targets
                       (goal_id, entity_type, store_id, company_id, company_group_id)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (goal_id, entity_type, store_id, company_id, group_id)
                )
                flash('Alocação criada com sucesso.', 'success')

            elif action == 'toggle_ativo':
                db.execute(
                    "UPDATE faciais.goal_targets SET is_active = NOT is_active WHERE goal_target_id=%s",
                    (request.form['_id'],)
                )
                flash('Status da alocação atualizado.', 'success')

            elif action == 'excluir':
                db.execute(
                    "DELETE FROM faciais.goal_targets WHERE goal_target_id=%s",
                    (request.form['_id'],)
                )
                flash('Alocação excluída com sucesso.', 'success')

        except Exception as e:
            err = str(e).lower()
            if 'unique' in err or 'duplicate' in err:
                flash('Essa meta já está alocada para essa entidade.', 'error')
            elif 'foreign key' in err or 'violates' in err:
                flash('Não é possível excluir: existem valores vinculados.', 'error')
            else:
                flash(f'Erro: {e}', 'error')

        return redirect(url_for('metas.alocacoes', goal_id=goal_id))

    targets = db.query_all("""
        SELECT gt.*,
               s.store_name, c.company_name, cg.company_group_name,
               COUNT(gv.goal_value_id) AS num_values
        FROM   faciais.goal_targets gt
        LEFT JOIN faciais.stores         s  ON s.store_id          = gt.store_id
        LEFT JOIN faciais.companies      c  ON c.company_id        = gt.company_id
        LEFT JOIN faciais.company_groups cg ON cg.company_group_id = gt.company_group_id
        LEFT JOIN faciais.goal_values    gv ON gv.goal_target_id   = gt.goal_target_id
        WHERE  gt.goal_id = %s
        GROUP  BY gt.goal_target_id, s.store_name, c.company_name, cg.company_group_name
        ORDER  BY gt.entity_type, s.store_name, c.company_name, cg.company_group_name
    """, (goal_id,))

    for t in targets:
        t['_entity_name'] = _entity_name(t)

    stores    = db.query_all("SELECT store_id, store_name FROM faciais.stores ORDER BY store_name")
    companies = db.query_all("SELECT company_id, company_name FROM faciais.companies ORDER BY company_name")
    groups    = db.query_all("SELECT company_group_id, company_group_name FROM faciais.company_groups ORDER BY company_group_name")

    return render_template('metas/alocacoes.html',
                           goal=goal, targets=targets,
                           stores=stores, companies=companies, groups=groups)


# ── Valores ───────────────────────────────────────────────────────────────────

@metas_bp.route('/objetivos/<int:goal_id>/alocacoes/<int:target_id>/valores', methods=['GET', 'POST'])
@_admin_required
def valores(goal_id, target_id):
    goal = db.query_one(
        """SELECT g.*, gu.symbol FROM faciais.goals g
           JOIN faciais.goal_units gu ON gu.goal_unit_id = g.goal_unit_id
           WHERE g.goal_id = %s""",
        (goal_id,)
    )
    target = db.query_one(
        """SELECT gt.*,
                  s.store_name, c.company_name, cg.company_group_name
           FROM   faciais.goal_targets gt
           LEFT JOIN faciais.stores         s  ON s.store_id          = gt.store_id
           LEFT JOIN faciais.companies      c  ON c.company_id        = gt.company_id
           LEFT JOIN faciais.company_groups cg ON cg.company_group_id = gt.company_group_id
           WHERE  gt.goal_target_id = %s AND gt.goal_id = %s""",
        (target_id, goal_id)
    )
    if not goal or not target:
        abort(404)

    target['_entity_name'] = _entity_name(target)

    if request.method == 'POST':
        action = request.form.get('_action')
        try:
            if action == 'criar':
                db.execute(
                    """INSERT INTO faciais.goal_values
                       (goal_target_id, goal_period_id, reference_date, target_value)
                       VALUES (%s, %s, %s, %s)""",
                    (
                        target_id,
                        request.form['goal_period_id'],
                        request.form['reference_date'],
                        request.form.get('target_value') or None,
                    )
                )
                flash('Valor de meta criado com sucesso.', 'success')

            elif action == 'editar':
                db.execute(
                    """UPDATE faciais.goal_values SET
                       goal_period_id=%s, reference_date=%s, target_value=%s
                       WHERE goal_value_id=%s""",
                    (
                        request.form['goal_period_id'],
                        request.form['reference_date'],
                        request.form.get('target_value') or None,
                        request.form['_id'],
                    )
                )
                flash('Valor atualizado com sucesso.', 'success')

            elif action == 'excluir':
                db.execute(
                    "DELETE FROM faciais.goal_values WHERE goal_value_id=%s",
                    (request.form['_id'],)
                )
                flash('Valor excluído com sucesso.', 'success')

        except Exception as e:
            err = str(e).lower()
            if 'unique' in err or 'duplicate' in err:
                flash('Já existe um valor para essa alocação, período e data.', 'error')
            else:
                flash(f'Erro: {e}', 'error')

        return redirect(url_for('metas.valores', goal_id=goal_id, target_id=target_id))

    values = db.query_all("""
        SELECT gv.*, gp.goal_period_name, gp.period_order,
               (SELECT COUNT(*) FROM faciais.goal_breakdowns gb
                WHERE  gb.parent_goal_value_id = gv.goal_value_id) AS num_children,
               (SELECT COUNT(*) FROM faciais.goal_breakdowns gb
                WHERE  gb.child_goal_value_id  = gv.goal_value_id) AS num_parents
        FROM   faciais.goal_values gv
        JOIN   faciais.goal_periods gp ON gp.goal_period_id = gv.goal_period_id
        WHERE  gv.goal_target_id = %s
        ORDER  BY gp.period_order DESC, gv.reference_date
    """, (target_id,))

    periods = db.query_all("SELECT * FROM faciais.goal_periods ORDER BY period_order")
    return render_template('metas/valores.html',
                           goal=goal, target=target, values=values, periods=periods)


# ── Desdobramento ──────────────────────────────────────────────────────────────

@metas_bp.route('/valores/<int:value_id>/desdobrar', methods=['GET', 'POST'])
@_admin_required
def desdobrar(value_id):
    parent = db.query_one("""
        SELECT gv.*, gp.goal_period_name, gp.period_order, gp.goal_period_id AS parent_period_id,
               gt.goal_id, gt.goal_target_id, gt.entity_type,
               g.goal_name, gu.symbol,
               s.store_name, c.company_name, cg.company_group_name
        FROM   faciais.goal_values  gv
        JOIN   faciais.goal_periods  gp ON gp.goal_period_id  = gv.goal_period_id
        JOIN   faciais.goal_targets  gt ON gt.goal_target_id  = gv.goal_target_id
        JOIN   faciais.goals         g  ON g.goal_id          = gt.goal_id
        JOIN   faciais.goal_units    gu ON gu.goal_unit_id    = g.goal_unit_id
        LEFT JOIN faciais.stores         s  ON s.store_id          = gt.store_id
        LEFT JOIN faciais.companies      c  ON c.company_id        = gt.company_id
        LEFT JOIN faciais.company_groups cg ON cg.company_group_id = gt.company_group_id
        WHERE  gv.goal_value_id = %s
    """, (value_id,))
    if not parent:
        abort(404)

    parent['_entity_name'] = _entity_name(parent)

    child_periods = db.query_all("""
        SELECT * FROM faciais.goal_periods
        WHERE period_order < %s
        ORDER BY period_order DESC
    """, (parent['period_order'],))

    row = db.query_one(
        "SELECT COUNT(*) AS cnt FROM faciais.goal_breakdowns WHERE parent_goal_value_id=%s",
        (value_id,)
    )
    num_children = row['cnt'] if row else 0

    if request.method == 'POST':
        child_period_id = request.form.get('child_period_id', '').strip()
        dates  = request.form.getlist('ref_date[]')
        tvals  = request.form.getlist('target_value[]')

        if not child_period_id or not dates:
            flash('Selecione um período filho e carregue a distribuição antes de salvar.', 'error')
            return redirect(url_for('metas.desdobrar', value_id=value_id))

        try:
            for ref_date, tval in zip(dates, tvals):
                tval_num = float(tval.strip()) if tval.strip() else None
                existing = db.query_one(
                    """SELECT goal_value_id FROM faciais.goal_values
                       WHERE goal_target_id=%s AND goal_period_id=%s AND reference_date=%s""",
                    (parent['goal_target_id'], child_period_id, ref_date)
                )
                if existing:
                    child_id = existing['goal_value_id']
                    db.execute(
                        "UPDATE faciais.goal_values SET target_value=%s WHERE goal_value_id=%s",
                        (tval_num, child_id)
                    )
                else:
                    row = db.query_one(
                        """INSERT INTO faciais.goal_values
                           (goal_target_id, goal_period_id, reference_date, target_value)
                           VALUES (%s,%s,%s,%s) RETURNING goal_value_id""",
                        (parent['goal_target_id'], child_period_id, ref_date, tval_num)
                    )
                    child_id = row['goal_value_id']

                db.execute(
                    """INSERT INTO faciais.goal_breakdowns
                       (parent_goal_value_id, child_goal_value_id)
                       VALUES (%s,%s)
                       ON CONFLICT (parent_goal_value_id, child_goal_value_id) DO NOTHING""",
                    (value_id, child_id)
                )

            flash('Desdobramento salvo com sucesso.', 'success')
        except Exception as e:
            flash(f'Erro no desdobramento: {e}', 'error')

        return redirect(url_for('metas.valores',
                                goal_id=parent['goal_id'],
                                target_id=parent['goal_target_id']))

    return render_template('metas/desdobrar.html',
                           parent=parent,
                           child_periods=child_periods,
                           num_children=num_children,
                           value_id=value_id)


@metas_bp.route('/valores/<int:value_id>/desdobrar/sugestao')
@_admin_required
def desdobrar_sugestao(value_id):
    parent = db.query_one("""
        SELECT gv.*, gp.period_order, gp.goal_period_id AS parent_period_id,
               gt.entity_type, gt.store_id
        FROM   faciais.goal_values gv
        JOIN   faciais.goal_periods gp ON gp.goal_period_id = gv.goal_period_id
        JOIN   faciais.goal_targets gt ON gt.goal_target_id = gv.goal_target_id
        WHERE  gv.goal_value_id = %s
    """, (value_id,))
    if not parent:
        return jsonify([]), 404

    child_period_id = request.args.get('child_period_id', '')
    if not child_period_id:
        return jsonify([])

    return jsonify(_suggest_breakdown(parent, child_period_id))


def _suggest_breakdown(parent, child_period_id):
    ref_date   = parent['reference_date']
    parent_pid = parent['parent_period_id']
    target_val = float(parent['target_value']) if parent['target_value'] else 0.0
    year, month = ref_date.year, ref_date.month

    if parent_pid == 'annual':
        start, end = date(year, 1, 1), date(year, 12, 31)
    elif parent_pid == 'ytd':
        start, end = date(year, 1, 1), ref_date
    elif parent_pid == 'quadrimester':
        q = (month - 1) // 4
        start = date(year, q * 4 + 1, 1)
        em = min(q * 4 + 4, 12)
        end = date(year, em, pycal.monthrange(year, em)[1])
    elif parent_pid == 'quarterly':
        q = (month - 1) // 3
        start = date(year, q * 3 + 1, 1)
        em = min(q * 3 + 3, 12)
        end = date(year, em, pycal.monthrange(year, em)[1])
    elif parent_pid == 'monthly':
        start = date(year, month, 1)
        end   = date(year, month, pycal.monthrange(year, month)[1])
    elif parent_pid == 'weekly':
        start = ref_date - timedelta(days=ref_date.weekday())
        end   = start + timedelta(days=6)
    else:
        return []

    def _next_month(d):
        return date(d.year + (d.month // 12), d.month % 12 + 1, 1)

    slots = []

    if child_period_id == 'monthly':
        months = []
        cur = date(start.year, start.month, 1)
        while cur <= end:
            months.append(cur)
            cur = _next_month(cur)
        sug = round(target_val / len(months), 4) if months else 0
        for m in months:
            slots.append({'ref_date': m.isoformat(), 'label': m.strftime('%b/%Y'), 'suggested_value': str(sug)})

    elif child_period_id == 'weekly':
        cur = start - timedelta(days=start.weekday())
        weeks = []
        while cur <= end:
            weeks.append(cur)
            cur += timedelta(weeks=1)
        sug = round(target_val / len(weeks), 4) if weeks else 0
        for w in weeks:
            iso = w.isocalendar()
            slots.append({
                'ref_date': w.isoformat(),
                'label': f'Sem {iso[1]}/{iso[0]} ({w.strftime("%d/%m")})',
                'suggested_value': str(sug),
            })

    elif child_period_id == 'daily':
        # Distribui proporcionalmente ao peso do dia no calendário
        entity_type = parent.get('entity_type')
        store_id    = parent.get('store_id')

        if entity_type == 'store' and store_id:
            cal_days = db.query_all("""
                SELECT calendar_date, day_weight, day_label
                FROM   faciais.vw_store_calendar
                WHERE  store_id = %s
                  AND  calendar_date BETWEEN %s AND %s
                  AND  day_weight > 0
                ORDER  BY calendar_date
            """, (store_id, start, end))
        else:
            cal_days = db.query_all("""
                SELECT c.calendar_date,
                       dt.weight AS day_weight,
                       c.holiday_name AS day_label
                FROM   faciais.calendar c
                JOIN   faciais.day_types dt ON dt.day_type_id = c.day_type_id
                WHERE  c.calendar_date BETWEEN %s AND %s
                  AND  dt.weight > 0
                ORDER  BY c.calendar_date
            """, (start, end))

        if not cal_days:
            # Fallback: todos os dias igualmente (calendário não populado)
            cur = start
            all_days = []
            while cur <= end:
                all_days.append(cur)
                cur += timedelta(days=1)
            sug = round(target_val / len(all_days), 4) if all_days else 0
            for d in all_days:
                slots.append({
                    'ref_date': d.isoformat(),
                    'label': d.strftime('%d/%m/%Y') + ' ⚠ sem calendário',
                    'suggested_value': str(sug),
                })
        else:
            total_weight = sum(float(d['day_weight']) for d in cal_days)
            for d in cal_days:
                weight   = float(d['day_weight'])
                sug      = round(target_val * weight / total_weight, 4) if total_weight else 0
                cal_date = d['calendar_date']
                label    = cal_date.strftime('%d/%m/%Y')
                if d.get('day_label'):
                    label += f' — {d["day_label"]}'
                elif weight < 1.0:
                    label += f' (peso {weight})'
                slots.append({
                    'ref_date': cal_date.isoformat(),
                    'label': label,
                    'suggested_value': str(sug),
                })

    elif child_period_id == 'quarterly':
        seen, quarters = set(), []
        cur = date(start.year, start.month, 1)
        while cur <= end:
            q = (cur.month - 1) // 3
            qs = date(cur.year, q * 3 + 1, 1)
            if qs not in seen:
                seen.add(qs)
                quarters.append((qs, f'T{q + 1}/{cur.year}'))
            cur = _next_month(cur)
        sug = round(target_val / len(quarters), 4) if quarters else 0
        for qs, label in quarters:
            slots.append({'ref_date': qs.isoformat(), 'label': label, 'suggested_value': str(sug)})

    elif child_period_id == 'quadrimester':
        seen, quads = set(), []
        cur = date(start.year, start.month, 1)
        while cur <= end:
            q = (cur.month - 1) // 4
            qs = date(cur.year, q * 4 + 1, 1)
            if qs not in seen:
                seen.add(qs)
                quads.append((qs, f'Q{q + 1}/{cur.year}'))
            cur = _next_month(cur)
        sug = round(target_val / len(quads), 4) if quads else 0
        for qs, label in quads:
            slots.append({'ref_date': qs.isoformat(), 'label': label, 'suggested_value': str(sug)})

    return slots


# ── Calendário ─────────────────────────────────────────────────────────────────

@metas_bp.route('/calendario', methods=['GET', 'POST'])
@_admin_required
def calendario():
    today = date.today()
    year  = int(request.args.get('year',  today.year))
    month = int(request.args.get('month', today.month))

    if request.method == 'POST':
        action = request.form.get('_action')
        try:
            if action == 'popular':
                pop_year  = int(request.form['pop_year'])
                overwrite = request.form.get('overwrite') == '1'
                _populate_calendar(pop_year, overwrite)
                flash(f'Calendário {pop_year} populado com sucesso.', 'success')
                return redirect(url_for('metas.calendario', year=pop_year, month=1))

            elif action == 'editar_dia':
                cal_date = request.form['calendar_date']
                day_type = request.form['day_type_id']
                hol_name = request.form.get('holiday_name', '').strip() or None
                db.execute(
                    "UPDATE faciais.calendar SET day_type_id=%s, holiday_name=%s WHERE calendar_date=%s",
                    (day_type, hol_name, cal_date)
                )
                flash('Dia atualizado com sucesso.', 'success')

        except Exception as e:
            flash(f'Erro: {e}', 'error')

        return redirect(url_for('metas.calendario', year=year, month=month))

    days = db.query_all("""
        SELECT c.*, dt.day_type_name, dt.weight
        FROM   faciais.calendar c
        JOIN   faciais.day_types dt ON dt.day_type_id = c.day_type_id
        WHERE  c.year = %s AND c.month = %s
        ORDER  BY c.calendar_date
    """, (year, month))

    day_types = db.query_all("SELECT * FROM faciais.day_types ORDER BY day_type_id")

    if days:
        first_dow = days[0]['day_of_week']
        cal_grid  = [None] * first_dow + list(days)
        while len(cal_grid) % 7 != 0:
            cal_grid.append(None)
    else:
        cal_grid = []

    stats = {}
    for d in days:
        stats[d['day_type_id']] = stats.get(d['day_type_id'], 0) + 1
    working_weight = sum(float(d['weight']) for d in days if float(d['weight']) > 0)

    prev_year,  prev_month = (year - 1, 12) if month == 1  else (year, month - 1)
    next_year,  next_month = (year + 1, 1)  if month == 12 else (year, month + 1)

    month_names = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho',
                   'Julho','Agosto','Setembro','Outubro','Novembro','Dezembro']

    return render_template('metas/calendario.html',
                           days=days, day_types=day_types, cal_grid=cal_grid,
                           stats=stats, working_weight=working_weight,
                           year=year, month=month, month_name=month_names[month - 1],
                           prev_year=prev_year, prev_month=prev_month,
                           next_year=next_year, next_month=next_month)


def _populate_calendar(year, overwrite=False):
    cur = date(year, 1, 1)
    end = date(year, 12, 31)
    while cur <= end:
        dow    = cur.weekday()          # 0=Mon..6=Sun
        db_dow = (dow + 1) % 7         # 0=Sun..6=Sat
        day_type = 'sunday' if dow == 6 else ('saturday' if dow == 5 else 'workday')
        week_num = cur.isocalendar()[1]
        quarter  = (cur.month - 1) // 3 + 1

        if overwrite:
            db.execute(
                """INSERT INTO faciais.calendar
                   (calendar_date, year, month, day, week_number, day_of_week, quarter, day_type_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (calendar_date) DO UPDATE SET
                   day_type_id=EXCLUDED.day_type_id, holiday_name=NULL""",
                (cur, year, cur.month, cur.day, week_num, db_dow, quarter, day_type)
            )
        else:
            db.execute(
                """INSERT INTO faciais.calendar
                   (calendar_date, year, month, day, week_number, day_of_week, quarter, day_type_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (calendar_date) DO NOTHING""",
                (cur, year, cur.month, cur.day, week_num, db_dow, quarter, day_type)
            )
        cur += timedelta(days=1)


# ── Exceções por Loja ──────────────────────────────────────────────────────────

@metas_bp.route('/excecoes', methods=['GET', 'POST'])
@_admin_required
def excecoes():
    stores    = db.query_all("SELECT store_id, store_name FROM faciais.stores ORDER BY store_name")
    day_types = db.query_all("SELECT * FROM faciais.day_types ORDER BY day_type_id")

    if request.method == 'POST':
        action       = request.form.get('_action')
        store_filter = request.form.get('store_filter', '')
        try:
            if action == 'criar':
                db.execute(
                    """INSERT INTO faciais.store_calendar_exceptions
                       (store_id, calendar_date, day_type_id, exception_name)
                       VALUES (%s,%s,%s,%s)""",
                    (
                        request.form['store_id'],
                        request.form['calendar_date'],
                        request.form['day_type_id'],
                        request.form.get('exception_name', '').strip() or None,
                    )
                )
                flash('Exceção criada com sucesso.', 'success')

            elif action == 'editar':
                db.execute(
                    """UPDATE faciais.store_calendar_exceptions SET
                       day_type_id=%s, exception_name=%s WHERE exception_id=%s""",
                    (
                        request.form['day_type_id'],
                        request.form.get('exception_name', '').strip() or None,
                        request.form['_id'],
                    )
                )
                flash('Exceção atualizada com sucesso.', 'success')

            elif action == 'excluir':
                db.execute(
                    "DELETE FROM faciais.store_calendar_exceptions WHERE exception_id=%s",
                    (request.form['_id'],)
                )
                flash('Exceção excluída com sucesso.', 'success')

        except Exception as e:
            err = str(e).lower()
            if 'unique' in err or 'duplicate' in err:
                flash('Já existe uma exceção para essa loja nessa data.', 'error')
            elif 'foreign key' in err or 'violates' in err:
                flash('Data não encontrada no calendário base. Popule o calendário primeiro.', 'error')
            else:
                flash(f'Erro: {e}', 'error')

        return redirect(url_for('metas.excecoes', store_id=store_filter))

    store_id = request.args.get('store_id', '')
    if store_id:
        excecoes_list = db.query_all("""
            SELECT sce.*, s.store_name, dt.day_type_name
            FROM   faciais.store_calendar_exceptions sce
            JOIN   faciais.stores    s  ON s.store_id    = sce.store_id
            JOIN   faciais.day_types dt ON dt.day_type_id = sce.day_type_id
            WHERE  sce.store_id = %s
            ORDER  BY sce.calendar_date DESC
        """, (int(store_id),))
    else:
        excecoes_list = db.query_all("""
            SELECT sce.*, s.store_name, dt.day_type_name
            FROM   faciais.store_calendar_exceptions sce
            JOIN   faciais.stores    s  ON s.store_id    = sce.store_id
            JOIN   faciais.day_types dt ON dt.day_type_id = sce.day_type_id
            ORDER  BY s.store_name, sce.calendar_date DESC
        """)

    return render_template('metas/excecoes.html',
                           excecoes=excecoes_list,
                           stores=stores,
                           day_types=day_types,
                           store_id=store_id)


# ── Perfis de Calendário ───────────────────────────────────────────────────────

@metas_bp.route('/perfis-calendario', methods=['GET', 'POST'])
@_admin_required
def perfis_calendario():
    day_types = db.query_all("SELECT * FROM faciais.day_types ORDER BY day_type_id")

    if request.method == 'POST':
        action = request.form.get('_action')
        try:
            if action == 'criar':
                db.execute(
                    """INSERT INTO faciais.business_calendar_profiles
                       (profile_name, description, saturday_day_type, sunday_day_type)
                       VALUES (%s, %s, %s, %s)""",
                    (
                        request.form['profile_name'].strip(),
                        request.form.get('description', '').strip() or None,
                        request.form['saturday_day_type'],
                        request.form['sunday_day_type'],
                    )
                )
                flash('Perfil criado com sucesso.', 'success')

            elif action == 'editar':
                db.execute(
                    """UPDATE faciais.business_calendar_profiles SET
                       profile_name=%s, description=%s,
                       saturday_day_type=%s, sunday_day_type=%s
                       WHERE profile_id=%s""",
                    (
                        request.form['profile_name'].strip(),
                        request.form.get('description', '').strip() or None,
                        request.form['saturday_day_type'],
                        request.form['sunday_day_type'],
                        request.form['_id'],
                    )
                )
                flash('Perfil atualizado com sucesso.', 'success')

            elif action == 'toggle_ativo':
                db.execute(
                    "UPDATE faciais.business_calendar_profiles SET is_active = NOT is_active WHERE profile_id=%s",
                    (request.form['_id'],)
                )
                flash('Status do perfil atualizado.', 'success')

            elif action == 'excluir':
                db.execute(
                    "DELETE FROM faciais.business_calendar_profiles WHERE profile_id=%s",
                    (request.form['_id'],)
                )
                flash('Perfil excluído com sucesso.', 'success')

        except Exception as e:
            err = str(e).lower()
            if 'foreign key' in err or 'violates' in err:
                flash('Não é possível excluir: existem lojas vinculadas a este perfil.', 'error')
            else:
                flash(f'Erro: {e}', 'error')

        return redirect(url_for('metas.perfis_calendario'))

    perfis = db.query_all("""
        SELECT bcp.*,
               dts.day_type_name AS saturday_type_name,
               dtd.day_type_name AS sunday_type_name,
               COUNT(s.store_id) AS num_stores
        FROM   faciais.business_calendar_profiles bcp
        LEFT JOIN faciais.day_types dts ON dts.day_type_id = bcp.saturday_day_type
        LEFT JOIN faciais.day_types dtd ON dtd.day_type_id = bcp.sunday_day_type
        LEFT JOIN faciais.stores    s   ON s.calendar_profile_id = bcp.profile_id
        GROUP BY bcp.profile_id, dts.day_type_name, dtd.day_type_name
        ORDER BY bcp.profile_name
    """)
    return render_template('metas/perfis_calendario.html', perfis=perfis, day_types=day_types)


# ── Feriados Regionais ─────────────────────────────────────────────────────────

@metas_bp.route('/feriados-regionais', methods=['GET', 'POST'])
@_admin_required
def feriados_regionais():
    day_types = db.query_all(
        "SELECT * FROM faciais.day_types WHERE day_type_id != 'workday' ORDER BY day_type_id"
    )

    if request.method == 'POST':
        action = request.form.get('_action')
        year_filter = request.form.get('year_filter', '')
        uf_filter   = request.form.get('uf_filter', '')
        try:
            if action == 'criar':
                scope = request.form['scope']
                city  = request.form.get('city', '').strip() or None
                db.execute(
                    """INSERT INTO faciais.geo_holidays
                       (calendar_date, holiday_name, scope, uf, city, day_type_id)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (
                        request.form['calendar_date'],
                        request.form['holiday_name'].strip(),
                        scope,
                        request.form['uf'].strip().upper(),
                        city if scope == 'city' else None,
                        request.form['day_type_id'],
                    )
                )
                flash('Feriado regional criado com sucesso.', 'success')

            elif action == 'editar':
                scope = request.form['scope']
                city  = request.form.get('city', '').strip() or None
                db.execute(
                    """UPDATE faciais.geo_holidays SET
                       holiday_name=%s, scope=%s, uf=%s, city=%s, day_type_id=%s
                       WHERE geo_holiday_id=%s""",
                    (
                        request.form['holiday_name'].strip(),
                        scope,
                        request.form['uf'].strip().upper(),
                        city if scope == 'city' else None,
                        request.form['day_type_id'],
                        request.form['_id'],
                    )
                )
                flash('Feriado regional atualizado com sucesso.', 'success')

            elif action == 'excluir':
                db.execute(
                    "DELETE FROM faciais.geo_holidays WHERE geo_holiday_id=%s",
                    (request.form['_id'],)
                )
                flash('Feriado regional excluído com sucesso.', 'success')

        except Exception as e:
            err = str(e).lower()
            if 'foreign key' in err or 'not present' in err:
                flash('Data não encontrada no calendário base. Popule o calendário primeiro.', 'error')
            elif 'unique' in err or 'duplicate' in err:
                flash('Já existe um feriado regional para essa data e localidade.', 'error')
            else:
                flash(f'Erro: {e}', 'error')

        qs = {}
        if year_filter:
            qs['year'] = year_filter
        if uf_filter:
            qs['uf'] = uf_filter
        return redirect(url_for('metas.feriados_regionais', **qs))

    year_filter = request.args.get('year', '')
    uf_filter   = request.args.get('uf', '').upper()

    query = """
        SELECT gh.*, dt.day_type_name
        FROM   faciais.geo_holidays gh
        JOIN   faciais.day_types dt ON dt.day_type_id = gh.day_type_id
        WHERE  1=1
    """
    params = []
    if year_filter:
        query += " AND EXTRACT(YEAR FROM gh.calendar_date) = %s"
        params.append(int(year_filter))
    if uf_filter:
        query += " AND gh.uf = %s"
        params.append(uf_filter)
    query += " ORDER BY gh.calendar_date, gh.uf, gh.city"

    feriados = db.query_all(query, params if params else None)

    years = db.query_all("""
        SELECT DISTINCT EXTRACT(YEAR FROM calendar_date)::int AS yr
        FROM   faciais.geo_holidays
        ORDER  BY yr DESC
    """)

    return render_template('metas/feriados_regionais.html',
                           feriados=feriados,
                           day_types=day_types,
                           years=years,
                           year_filter=year_filter,
                           uf_filter=uf_filter)
