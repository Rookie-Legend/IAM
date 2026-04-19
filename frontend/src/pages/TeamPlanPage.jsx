import { useCallback, useEffect, useMemo, useState } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faCalendarDays,
  faChartGantt,
  faChevronLeft,
  faChevronRight,
  faPen,
  faPlus,
  faSpinner,
  faTrash,
} from '@fortawesome/free-solid-svg-icons';
import { apiUrl } from '../stores/configStore';
import './TeamPlanPage.css';

const ADMIN_ROLES = ['Security Admin', 'System Administrator', 'HR Manager', 'admin'];
const STATUSES = ['planned', 'active', 'blocked', 'done'];
const PRIORITIES = ['low', 'medium', 'high'];
const ITEM_TYPES = ['task', 'milestone', 'release', 'meeting'];
const DAY_NAMES = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

function toDateKey(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function parseKey(key) {
  const [year, month, day] = key.split('-').map(Number);
  return new Date(year, month - 1, day);
}

function addDays(date, amount) {
  const next = new Date(date);
  next.setDate(next.getDate() + amount);
  return next;
}

function emptyForm(user, isAdmin, department) {
  const today = toDateKey(new Date());
  return {
    title: '',
    description: '',
    department: isAdmin ? (department === 'all' ? user.department : department) : user.department,
    owner: user.full_name || user.username || '',
    start: today,
    end: today,
    status: 'planned',
    priority: 'medium',
    type: 'task',
  };
}

function labelize(value) {
  return value.replace(/_/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase());
}

function itemTouchesDay(item, dayKey) {
  return item.start <= dayKey && item.end >= dayKey;
}

function itemInMonth(item, firstDay, lastDay) {
  const start = parseKey(item.start);
  const end = parseKey(item.end);
  return end >= firstDay && start <= lastDay;
}

function daysBetween(start, end) {
  const days = [];
  for (let date = new Date(start); date <= end; date = addDays(date, 1)) {
    days.push(new Date(date));
  }
  return days;
}

export default function TeamPlanPage({ user, token }) {
  const isAdmin = ADMIN_ROLES.includes(user.role);
  const authHeaders = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);
  const [view, setView] = useState('calendar');
  const [monthDate, setMonthDate] = useState(() => new Date());
  const [departments, setDepartments] = useState([]);
  const [selectedDepartment, setSelectedDepartment] = useState(isAdmin ? 'all' : user.department);
  const [items, setItems] = useState([]);
  const [form, setForm] = useState(() => emptyForm(user, isAdmin, selectedDepartment));
  const [editingId, setEditingId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const firstDay = useMemo(
    () => new Date(monthDate.getFullYear(), monthDate.getMonth(), 1),
    [monthDate]
  );
  const lastDay = useMemo(
    () => new Date(monthDate.getFullYear(), monthDate.getMonth() + 1, 0),
    [monthDate]
  );

  const monthDays = useMemo(() => daysBetween(firstDay, lastDay), [firstDay, lastDay]);

  const calendarDays = useMemo(() => {
    const gridStart = addDays(firstDay, -firstDay.getDay());
    return Array.from({ length: 42 }, (_, index) => addDays(gridStart, index));
  }, [firstDay]);

  const visibleItems = useMemo(
    () => items.filter((item) => itemInMonth(item, firstDay, lastDay)),
    [items, firstDay, lastDay]
  );

  const fetchDepartments = useCallback(async () => {
    try {
      const res = await fetch(apiUrl('/api/planning/departments'), { headers: authHeaders });
      if (res.ok) {
        const data = await res.json();
        setDepartments(data);
      }
    } catch {
      setError('Could not load departments.');
    }
  }, [authHeaders]);

  const fetchItems = useCallback(async () => {
    setLoading(true);
    setError('');
    const query = isAdmin && selectedDepartment !== 'all'
      ? `?department=${encodeURIComponent(selectedDepartment)}`
      : '';
    try {
      const res = await fetch(apiUrl(`/api/planning/items${query}`), { headers: authHeaders });
      if (!res.ok) throw new Error('Could not load plan items.');
      setItems(await res.json());
    } catch (err) {
      setError(err.message || 'Could not load plan items.');
    } finally {
      setLoading(false);
    }
  }, [authHeaders, isAdmin, selectedDepartment]);

  useEffect(() => {
    fetchDepartments();
  }, [fetchDepartments]);

  useEffect(() => {
    fetchItems();
  }, [fetchItems]);

  useEffect(() => {
    if (!editingId) {
      setForm((current) => ({
        ...current,
        department: isAdmin
          ? (selectedDepartment === 'all' ? user.department : selectedDepartment)
          : user.department,
      }));
    }
  }, [editingId, isAdmin, selectedDepartment, user.department]);

  const changeMonth = (amount) => {
    setMonthDate((current) => new Date(current.getFullYear(), current.getMonth() + amount, 1));
  };

  const resetForm = () => {
    setEditingId(null);
    setForm(emptyForm(user, isAdmin, selectedDepartment));
  };

  const selectItem = (item) => {
    setEditingId(item.id);
    setForm({
      title: item.title,
      description: item.description || '',
      department: item.department,
      owner: item.owner || user.full_name || user.username || '',
      start: item.start,
      end: item.end,
      status: item.status,
      priority: item.priority,
      type: item.type,
    });
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError('');

    try {
      const endpoint = editingId ? `/api/planning/items/${editingId}` : '/api/planning/items';
      const res = await fetch(apiUrl(endpoint), {
        method: editingId ? 'PUT' : 'POST',
        headers: { ...authHeaders, 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || 'Could not save plan item.');
      }
      await fetchItems();
      resetForm();
    } catch (err) {
      setError(err.message || 'Could not save plan item.');
    } finally {
      setSaving(false);
    }
  };

  const deleteItem = async () => {
    if (!editingId) return;
    setSaving(true);
    setError('');
    try {
      const res = await fetch(apiUrl(`/api/planning/items/${editingId}`), {
        method: 'DELETE',
        headers: authHeaders,
      });
      if (!res.ok) throw new Error('Could not delete plan item.');
      await fetchItems();
      resetForm();
    } catch (err) {
      setError(err.message || 'Could not delete plan item.');
    } finally {
      setSaving(false);
    }
  };

  const deletePlanningItem = async (item) => {
    if (!item || saving) return;
    if (!window.confirm(`Delete "${item.title}" from the team plan?`)) return;
    setSaving(true);
    setError('');
    try {
      const res = await fetch(apiUrl(`/api/planning/items/${item.id}`), {
        method: 'DELETE',
        headers: authHeaders,
      });
      if (!res.ok) throw new Error('Could not delete plan item.');
      await fetchItems();
      if (editingId === item.id) resetForm();
    } catch (err) {
      setError(err.message || 'Could not delete plan item.');
    } finally {
      setSaving(false);
    }
  };

  const monthTitle = `${MONTH_NAMES[monthDate.getMonth()]} ${monthDate.getFullYear()}`;
  const todayKey = toDateKey(new Date());

  return (
    <section className="team-plan-page">
      <header className="team-plan-header">
        <div>
          <p className="team-plan-kicker">{isAdmin ? 'Organization plan' : `${user.department} plan`}</p>
          <h1>Team Calendar</h1>
        </div>

        <div className="team-plan-actions">
          {isAdmin && (
            <select
              value={selectedDepartment}
              onChange={(event) => setSelectedDepartment(event.target.value)}
              aria-label="Filter department"
            >
              <option value="all">All departments</option>
              {departments.map((department) => (
                <option key={department} value={department}>{department}</option>
              ))}
            </select>
          )}
          <div className="team-plan-view-toggle" aria-label="Planning view">
            <button
              type="button"
              className={view === 'calendar' ? 'is-active' : ''}
              onClick={() => setView('calendar')}
            >
              <FontAwesomeIcon icon={faCalendarDays} />
              Calendar
            </button>
            <button
              type="button"
              className={view === 'gantt' ? 'is-active' : ''}
              onClick={() => setView('gantt')}
            >
              <FontAwesomeIcon icon={faChartGantt} />
              Gantt
            </button>
          </div>
          <button type="button" className="team-plan-primary" onClick={resetForm}>
            <FontAwesomeIcon icon={faPlus} />
            New item
          </button>
        </div>
      </header>

      <div className="team-plan-monthbar">
        <button type="button" onClick={() => changeMonth(-1)} aria-label="Previous month">
          <FontAwesomeIcon icon={faChevronLeft} />
        </button>
        <strong>{monthTitle}</strong>
        <button type="button" onClick={() => changeMonth(1)} aria-label="Next month">
          <FontAwesomeIcon icon={faChevronRight} />
        </button>
      </div>

      {error && <div className="team-plan-error">{error}</div>}

      <div className="team-plan-workspace">
        <div className="team-plan-main">
          {loading ? (
            <div className="team-plan-loading">
              <FontAwesomeIcon icon={faSpinner} spin />
              Loading plan
            </div>
          ) : view === 'calendar' ? (
            <div className="team-calendar">
              {DAY_NAMES.map((day) => (
                <div key={day} className="team-calendar-dayname">{day}</div>
              ))}
              {calendarDays.map((day) => {
                const dayKey = toDateKey(day);
                const dayItems = items.filter((item) => itemTouchesDay(item, dayKey));
                return (
                  <div
                    key={dayKey}
                    className={[
                      'team-calendar-day',
                      day.getMonth() !== monthDate.getMonth() ? 'is-muted' : '',
                      dayKey === todayKey ? 'is-today' : '',
                    ].filter(Boolean).join(' ')}
                  >
                    <span className="team-calendar-date">{day.getDate()}</span>
                    <div className="team-calendar-items">
                      {dayItems.slice(0, 4).map((item) => (
                        <button
                          key={item.id}
                          type="button"
                          className={`plan-chip status-${item.status} priority-${item.priority}`}
                          onClick={() => selectItem(item)}
                          title={`${item.title} - ${item.department}`}
                        >
                          {item.title}
                        </button>
                      ))}
                      {dayItems.length > 4 && (
                        <span className="team-calendar-more">+{dayItems.length - 4} more</span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="team-gantt">
              <div className="team-gantt-header">
                <span>Work item</span>
                <div
                  className="team-gantt-days"
                  style={{
                    '--gantt-days': monthDays.length,
                    gridTemplateColumns: `repeat(${monthDays.length}, minmax(2.2rem, 1fr))`,
                  }}
                >
                  {monthDays.map((day) => (
                    <span key={toDateKey(day)}>{day.getDate()}</span>
                  ))}
                </div>
              </div>
              {visibleItems.length === 0 ? (
                <div className="team-plan-empty">No planning items in this month.</div>
              ) : visibleItems.map((item) => {
                const startIndex = Math.max(0, Math.floor((parseKey(item.start) - firstDay) / 86400000));
                const endIndex = Math.min(monthDays.length - 1, Math.floor((parseKey(item.end) - firstDay) / 86400000));
                return (
                  <div className="team-gantt-row" key={item.id}>
                    <div className="team-gantt-label">
                      <button type="button" className="team-gantt-label-main" onClick={() => selectItem(item)}>
                        <strong>{item.title}</strong>
                        <span>{item.department} / {labelize(item.status)}</span>
                      </button>
                      <button
                        type="button"
                        className="team-gantt-delete"
                        onClick={() => deletePlanningItem(item)}
                        disabled={saving}
                        title={`Delete ${item.title}`}
                        aria-label={`Delete ${item.title}`}
                      >
                        <FontAwesomeIcon icon={faTrash} />
                      </button>
                    </div>
                    <div
                      className="team-gantt-track"
                      style={{
                        '--gantt-days': monthDays.length,
                        gridTemplateColumns: `repeat(${monthDays.length}, minmax(2.2rem, 1fr))`,
                      }}
                    >
                      <button
                        type="button"
                        className={`team-gantt-bar status-${item.status} priority-${item.priority}`}
                        style={{ gridColumn: `${startIndex + 1} / ${endIndex + 2}` }}
                        onClick={() => selectItem(item)}
                      >
                        {item.type === 'milestone' ? labelize(item.type) : item.title}
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <form className="team-plan-form" onSubmit={handleSubmit}>
          <div className="team-plan-form-title">
            <div>
              <span>{editingId ? 'Edit item' : 'Create item'}</span>
              <strong>{form.department || user.department}</strong>
            </div>
            {editingId && <FontAwesomeIcon icon={faPen} />}
          </div>

          <label>
            Title
            <input
              value={form.title}
              onChange={(event) => setForm({ ...form, title: event.target.value })}
              placeholder="VPN rollout"
              required
            />
          </label>

          <label>
            Notes
            <textarea
              value={form.description}
              onChange={(event) => setForm({ ...form, description: event.target.value })}
              placeholder="Scope, risks, and owners"
              rows={4}
            />
          </label>

          <div className="team-plan-form-grid">
            <label>
              Department
              <select
                value={form.department}
                disabled={!isAdmin}
                onChange={(event) => setForm({ ...form, department: event.target.value })}
              >
                {(departments.length ? departments : [user.department]).map((department) => (
                  <option key={department} value={department}>{department}</option>
                ))}
              </select>
            </label>
            <label>
              Owner
              <input
                value={form.owner}
                onChange={(event) => setForm({ ...form, owner: event.target.value })}
                placeholder={user.full_name || user.username}
              />
            </label>
            <label>
              Start
              <input
                type="date"
                value={form.start}
                onChange={(event) => setForm({ ...form, start: event.target.value })}
                required
              />
            </label>
            <label>
              End
              <input
                type="date"
                value={form.end}
                onChange={(event) => setForm({ ...form, end: event.target.value })}
                required
              />
            </label>
            <label>
              Status
              <select
                value={form.status}
                onChange={(event) => setForm({ ...form, status: event.target.value })}
              >
                {STATUSES.map((status) => (
                  <option key={status} value={status}>{labelize(status)}</option>
                ))}
              </select>
            </label>
            <label>
              Priority
              <select
                value={form.priority}
                onChange={(event) => setForm({ ...form, priority: event.target.value })}
              >
                {PRIORITIES.map((priority) => (
                  <option key={priority} value={priority}>{labelize(priority)}</option>
                ))}
              </select>
            </label>
            <label>
              Type
              <select
                value={form.type}
                onChange={(event) => setForm({ ...form, type: event.target.value })}
              >
                {ITEM_TYPES.map((type) => (
                  <option key={type} value={type}>{labelize(type)}</option>
                ))}
              </select>
            </label>
          </div>

          <div className="team-plan-form-actions">
            <button type="submit" className="team-plan-primary" disabled={saving}>
              {saving ? <FontAwesomeIcon icon={faSpinner} spin /> : null}
              {editingId ? 'Save changes' : 'Create item'}
            </button>
            {editingId && (
              <button type="button" className="team-plan-danger" onClick={deleteItem} disabled={saving}>
                <FontAwesomeIcon icon={faTrash} />
                Delete
              </button>
            )}
            <button type="button" className="team-plan-secondary" onClick={resetForm} disabled={saving}>
              Clear
            </button>
          </div>
        </form>
      </div>
    </section>
  );
}
