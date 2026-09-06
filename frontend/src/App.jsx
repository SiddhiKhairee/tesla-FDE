import { useEffect, useState } from 'react'
import './App.css'
import { fetchTickets } from './api'

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

function App() {
  return <Dashboard />
}

export default App
