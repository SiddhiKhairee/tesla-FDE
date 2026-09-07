import { useEffect, useState } from 'react'
import './App.css'
import { fetchTickets, submitReport } from './api'

const SOURCE_LABELS = {
  erp: 'ERP',
  human_report: 'Human report',
  sensor: 'Sensor',
}

function formatDiscrepancy(event) {
  if (event.anomaly_type) {
    return event.anomaly_type.replaceAll('_', ' ')
  }
  return event.field
}

function formatTimestamp(value) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function StatusBadge({ status }) {
  return <span className={`status-badge status-${status}`}>{status}</span>
}

function TicketDetail({ ticket }) {
  const { event, report } = ticket

  return (
    <div className="ticket-detail">
      <dl>
        <dt>Expected</dt>
        <dd>{String(event.expected_value)}</dd>
        <dt>Actual</dt>
        <dd>{String(event.actual_value)}</dd>
        <dt>Likely cause</dt>
        <dd>{report.likely_cause}</dd>
        <dt>Reasoning</dt>
        <dd>{report.reasoning}</dd>
        <dt>Recommended action</dt>
        <dd>{report.recommended_action}</dd>
        <dt>Confidence</dt>
        <dd>{report.confidence}</dd>
        {event.source === 'sensor' && report.predicted_failure_type && (
          <>
            <dt>Predicted failure type</dt>
            <dd>{report.predicted_failure_type}</dd>
          </>
        )}
        {typeof ticket.notified === 'boolean' && (
          <>
            <dt>Slack notified</dt>
            <dd>{ticket.notified ? 'Yes' : 'No'}</dd>
          </>
        )}
      </dl>
    </div>
  )
}

function TicketRow({ ticket, expanded, onToggle }) {
  const { event } = ticket

  return (
    <>
      <tr className="ticket-row" onClick={onToggle}>
        <td>{event.entity_id}</td>
        <td>{formatDiscrepancy(event)}</td>
        <td>{SOURCE_LABELS[event.source] ?? event.source}</td>
        <td>
          <StatusBadge status={ticket.status} />
        </td>
        <td>{formatTimestamp(event.timestamp)}</td>
        <td className="expand-indicator">{expanded ? '−' : '+'}</td>
      </tr>
      {expanded && (
        <tr className="ticket-detail-row">
          <td colSpan={6}>
            <TicketDetail ticket={ticket} />
          </td>
        </tr>
      )}
    </>
  )
}

function Dashboard() {
  const [tickets, setTickets] = useState(null)
  const [error, setError] = useState(null)
  const [expandedId, setExpandedId] = useState(null)

  const runFetch = () => {
    fetchTickets()
      .then(setTickets)
      .catch((err) => setError(err.message))
  }

  const load = () => {
    setError(null)
    setTickets(null)
    runFetch()
  }

  useEffect(() => {
    runFetch()
  }, [])

  return (
    <section className="dashboard">
      <header className="dashboard-header">
        <h1>Detected Issues</h1>
        <button type="button" onClick={load}>
          Refresh
        </button>
      </header>

      {tickets === null && error === null && <p className="state-message">Loading tickets…</p>}

      {error !== null && (
        <div className="state-message state-error">
          <p>Couldn't load tickets: {error}</p>
          <button type="button" onClick={load}>
            Retry
          </button>
        </div>
      )}

      {tickets !== null && tickets.length === 0 && (
        <p className="state-message">No issues detected yet.</p>
      )}

      {tickets !== null && tickets.length > 0 && (
        <table className="ticket-table">
          <thead>
            <tr>
              <th>Entity</th>
              <th>Discrepancy</th>
              <th>Source</th>
              <th>Status</th>
              <th>Timestamp</th>
              <th aria-label="expand" />
            </tr>
          </thead>
          <tbody>
            {tickets.map((ticket) => (
              <TicketRow
                key={ticket.id}
                ticket={ticket}
                expanded={expandedId === ticket.id}
                onToggle={() => setExpandedId(expandedId === ticket.id ? null : ticket.id)}
              />
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

// datetime-local's value has no timezone — sent to the backend as-is, same
// as it displays here. equipment_failure events never parse this string
// (see diagnosis.py's _gather_context), so an opaque local-time string is
// fine.
function nowForDatetimeLocal() {
  const pad = (n) => String(n).padStart(2, '0')
  const d = new Date()
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const EMPTY_FORM = { machine: '', issue: '', timestamp: nowForDatetimeLocal(), notes: '' }

function ReportForm() {
  const [form, setForm] = useState(EMPTY_FORM)
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  const updateField = (field) => (e) => setForm({ ...form, [field]: e.target.value })

  const submit = (e) => {
    e?.preventDefault()
    setSubmitting(true)
    setError(null)
    setResult(null)
    submitReport({
      machine: form.machine.trim(),
      issue: form.issue.trim(),
      timestamp: form.timestamp,
      notes: form.notes.trim() || null,
    })
      .then((ticket) => setResult(ticket))
      .catch((err) => setError(err.message))
      .finally(() => setSubmitting(false))
  }

  const reportAnother = () => {
    setResult(null)
    setForm({ ...EMPTY_FORM, timestamp: nowForDatetimeLocal() })
  }

  if (result) {
    return (
      <section className="dashboard">
        <header className="dashboard-header">
          <h1>Report Submitted</h1>
          <button type="button" onClick={reportAnother}>
            Report another issue
          </button>
        </header>
        <p className="state-message">
          Ticket created for <strong>{result.event.entity_id}</strong> — the diagnosis engine's
          findings:
        </p>
        <TicketDetail ticket={result} />
      </section>
    )
  }

  return (
    <section className="dashboard">
      <header className="dashboard-header">
        <h1>Report an Issue</h1>
      </header>

      <form className="report-form" onSubmit={submit}>
        <label htmlFor="machine">Machine</label>
        <input
          id="machine"
          type="text"
          required
          value={form.machine}
          onChange={updateField('machine')}
          placeholder="e.g. Cell Winder 3"
        />

        <label htmlFor="issue">Issue</label>
        <textarea
          id="issue"
          required
          rows={3}
          value={form.issue}
          onChange={updateField('issue')}
          placeholder="What did you see? Be specific — sounds, symptoms, when it started."
        />

        <label htmlFor="timestamp">When it happened</label>
        <input
          id="timestamp"
          type="datetime-local"
          required
          value={form.timestamp}
          onChange={updateField('timestamp')}
        />

        <label htmlFor="notes">Notes (optional)</label>
        <textarea
          id="notes"
          rows={2}
          value={form.notes}
          onChange={updateField('notes')}
          placeholder="Anything else worth mentioning"
        />

        <button type="submit" disabled={submitting}>
          {submitting ? 'Submitting…' : 'Submit report'}
        </button>

        {submitting && (
          <p className="state-message">
            Running real diagnosis and Slack notification — this can take a few seconds…
          </p>
        )}

        {error !== null && (
          <div className="state-message state-error">
            <p>Couldn't submit report: {error}</p>
            <button type="button" onClick={submit}>
              Retry
            </button>
          </div>
        )}
      </form>
    </section>
  )
}

function App() {
  const [view, setView] = useState('dashboard')

  return (
    <>
      <nav className="tab-nav">
        <button
          type="button"
          className={view === 'dashboard' ? 'active' : ''}
          onClick={() => setView('dashboard')}
        >
          Dashboard
        </button>
        <button
          type="button"
          className={view === 'report' ? 'active' : ''}
          onClick={() => setView('report')}
        >
          Report Issue
        </button>
      </nav>
      {view === 'dashboard' ? <Dashboard /> : <ReportForm />}
    </>
  )
}

export default App
