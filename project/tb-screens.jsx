// TalentBridge — All 5 screens

// ── Shared helpers ──────────────────────────────────────────────
const fmt = {
  time: (iso) => {
    const d = new Date(iso);
    const diff = Date.now() - d.getTime();
    const h = Math.floor(diff / 3600000);
    if (h < 1) return 'Just now';
    if (h < 24) return `${h}h ago`;
    const days = Math.floor(h / 24);
    return `${days}d ago`;
  },
  date: (iso) => new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }),
  score: (n) => `${n}%`
};

function ScoreBadge({ score, size = 'sm' }) {
  const color = score >= 70 ? 'var(--green)' : score >= 50 ? 'var(--amber)' : 'var(--muted-fg)';
  const bg = score >= 70 ? 'var(--green-bg)' : score >= 50 ? 'var(--amber-bg)' : 'var(--surface-2)';
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3, padding: size === 'sm' ? '2px 7px' : '3px 10px',
      borderRadius: 99, fontSize: size === 'sm' ? 11 : 12, fontWeight: 600, color, background: bg,
      fontFamily: 'var(--mono)', letterSpacing: '0.01em' }}>
      {fmt.score(score)}
    </span>);

}

function StatusBadge({ status }) {
  const map = {
    success: { label: 'Success', bg: 'var(--green-bg)', color: 'var(--green)' },
    pending: { label: 'Pending', bg: 'var(--amber-bg)', color: 'var(--amber)' },
    failed: { label: 'Failed', bg: 'var(--red-bg)', color: 'var(--red)' },
    Active: { label: 'Active', bg: 'var(--blue-bg)', color: 'var(--blue)' },
    Expired: { label: 'Expired', bg: 'var(--surface-2)', color: 'var(--muted-fg)' },
    Interested: { label: 'Interested', bg: 'var(--teal-bg)', color: 'var(--teal)' },
    Applied: { label: 'Applied', bg: 'var(--green-bg)', color: 'var(--green)' },
    Skipped: { label: 'Skipped', bg: 'var(--surface-2)', color: 'var(--muted-fg)' }
  };
  const s = map[status] || { label: status, bg: 'var(--surface-2)', color: 'var(--muted-fg)' };
  return (
    <span style={{ display: 'inline-block', padding: '2px 8px', borderRadius: 99, fontSize: 11,
      fontWeight: 600, background: s.bg, color: s.color, whiteSpace: 'nowrap' }}>
      {s.label}
    </span>);

}

function ScrapeIcon({ status }) {
  if (status === 'success') return <span style={{ color: 'var(--green)', fontSize: 13 }}>●</span>;
  if (status === 'pending') return <span style={{ color: 'var(--amber)', fontSize: 13 }}>●</span>;
  return <span style={{ color: 'var(--red)', fontSize: 13 }}>●</span>;
}

function FilterTabs({ options, value, onChange }) {
  return (
    <div style={{ display: 'flex', gap: 2, borderBottom: '1px solid var(--border)', marginBottom: 20 }}>
      {options.map((o) =>
      <button key={o.value} onClick={() => onChange(o.value)} style={{
        padding: '8px 14px', border: 'none', background: 'transparent', cursor: 'pointer',
        fontSize: 13, fontWeight: value === o.value ? 600 : 400,
        color: value === o.value ? 'var(--fg)' : 'var(--muted-fg)',
        borderBottom: value === o.value ? '2px solid var(--accent)' : '2px solid transparent',
        marginBottom: -1, transition: 'all 0.15s'
      }}>
          {o.label}
          {o.count != null &&
        <span style={{ marginLeft: 6, padding: '1px 6px', borderRadius: 99, fontSize: 10,
          fontWeight: 600, background: value === o.value ? 'var(--accent-bg)' : 'var(--surface-2)',
          color: value === o.value ? 'var(--accent)' : 'var(--muted-fg)' }}>
              {o.count}
            </span>
        }
        </button>
      )}
    </div>);

}

// ── Screen 1: Company Overview ───────────────────────────────────
function CompanyOverview({ onSelectCompany, activeGroup }) {
  const [search, setSearch] = React.useState('');
  const [statusFilter, setStatusFilter] = React.useState('all');
  const companies = TB_COMPANIES;

  const filtered = companies.filter((c) => {
    const matchSearch = c.name.toLowerCase().includes(search.toLowerCase()) ||
    c.industry.toLowerCase().includes(search.toLowerCase());
    const matchStatus = statusFilter === 'all' || c.scrapeStatus === statusFilter;
    const matchGroup = !activeGroup || activeGroup.companyIds.includes(c.id);
    return matchSearch && matchStatus && matchGroup;
  });

  const base = activeGroup ? companies.filter((c) => activeGroup.companyIds.includes(c.id)) : companies;
  const totals = { companies: base.length, active: base.reduce((a, c) => a + c.activeJobCount, 0), matched: base.reduce((a, c) => a + c.matchedJobCount, 0) };

  return (
    <div className="screen-content" style={{ width: "1200px" }}>
      <div className="screen-header">
        <div>
          <h1 className="screen-title">{activeGroup ? activeGroup.name : 'Companies'}</h1>
          <p className="screen-sub">{totals.companies} companies · {totals.active} active jobs · {totals.matched} matched</p>
        </div>
      </div>
      <div style={{ display: 'flex', gap: 10, marginBottom: 20, alignItems: 'center' }}>
        <div style={{ position: 'relative', flex: 1, maxWidth: 320 }}>
          <svg style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', opacity: 0.4 }} width="14" height="14" viewBox="0 0 16 16" fill="none"><circle cx="7" cy="7" r="5.5" stroke="currentColor" strokeWidth="1.5" /><path d="M11 11l3 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search companies…"
          style={{ width: '100%', paddingLeft: 32, paddingRight: 12, height: 34, border: '1px solid var(--border)',
            borderRadius: 6, fontSize: 13, background: 'var(--surface)', color: 'var(--fg)',
            outline: 'none', boxSizing: 'border-box' }} />
        </div>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}
        style={{ height: 34, border: '1px solid var(--border)', borderRadius: 6, fontSize: 13,
          background: 'var(--surface)', color: 'var(--fg)', padding: '0 10px', cursor: 'pointer' }}>
          <option value="all">All statuses</option>
          <option value="success">Success</option>
          <option value="pending">Pending</option>
          <option value="failed">Failed</option>
        </select>
        <span style={{ fontSize: 12, color: 'var(--muted-fg)', marginLeft: 4 }}>{filtered.length} shown</span>
      </div>
      <div className="company-grid">
        {filtered.map((c) =>
        <div key={c.id} className="company-card" onClick={() => onSelectCompany(c)}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <div className="company-logo">{c.name.slice(0, 2).toUpperCase()}</div>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--fg)', lineHeight: 1.3 }}>{c.name}</div>
                  <div style={{ fontSize: 11, color: 'var(--muted-fg)', marginTop: 1 }}>{c.industry}</div>
                </div>
              </div>
              <StatusBadge status={c.scrapeStatus} />
            </div>
            <div style={{ display: 'flex', gap: 16, marginTop: 8 }}>
              <div className="card-stat">
                <span className="card-stat-val">{c.activeJobCount}</span>
                <span className="card-stat-label">active</span>
              </div>
              <div className="card-stat">
                <span className="card-stat-val" style={{ color: c.matchedJobCount > 0 ? 'var(--green)' : 'var(--muted-fg)' }}>{c.matchedJobCount}</span>
                <span className="card-stat-label">matched</span>
              </div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginTop: 10, paddingTop: 10, borderTop: '1px solid var(--border)' }}>
              <ScrapeIcon status={c.scrapeStatus} />
              <span style={{ fontSize: 11, color: 'var(--muted-fg)', fontFamily: 'var(--mono)' }}>
                {fmt.time(c.lastScraped)}
              </span>
            </div>
          </div>
        )}
      </div>
      {filtered.length === 0 &&
      <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--muted-fg)', fontSize: 14 }}>
          No companies match your search.
        </div>
      }
    </div>);

}

// ── Screen 2: Per-Company View ───────────────────────────────────
const SKIP_REASONS_LIST = ['Salary too low', 'Location mismatch', 'Not a good culture fit', 'Too senior', 'Too junior', 'Prefer remote', 'Stack mismatch', 'Other'];

function CompanyView({ company, onBack }) {
  const [jobs, setJobs] = React.useState(company.jobs);
  const [filter, setFilter] = React.useState('all');
  const [editingJob, setEditingJob] = React.useState(null);
  const [pendingDecision, setPendingDecision] = React.useState('');
  const [pendingReason, setPendingReason] = React.useState('');

  const activeJobs = jobs.filter((j) => j.status === 'Active');
  const matchedJobs = activeJobs.filter((j) => j.score >= 50);
  const expiredJobs = jobs.filter((j) => j.status === 'Expired');

  const filterOptions = [
  { value: 'all', label: 'All', count: jobs.length },
  { value: 'matched', label: 'Matched', count: matchedJobs.length },
  { value: 'unmatched', label: 'Unmatched', count: activeJobs.length - matchedJobs.length },
  { value: 'expired', label: 'Expired', count: expiredJobs.length }];


  const visible = jobs.filter((j) => {
    if (filter === 'all') return true;
    if (filter === 'matched') return j.status === 'Active' && j.score >= 50;
    if (filter === 'unmatched') return j.status === 'Active' && j.score < 50;
    if (filter === 'expired') return j.status === 'Expired';
    return true;
  }).sort((a, b) => {
    if (a.status === 'Expired' && b.status !== 'Expired') return 1;
    if (a.status !== 'Expired' && b.status === 'Expired') return -1;
    return b.score - a.score;
  });

  function saveDecision(jobId) {
    setJobs((prev) => prev.map((j) => j.id === jobId ? { ...j, decision: pendingDecision || null, decisionReason: pendingDecision === 'Skipped' ? pendingReason : null } : j));
    setEditingJob(null);
    setPendingDecision('');
    setPendingReason('');
  }

  function startEdit(job) {
    setEditingJob(job.id);
    setPendingDecision(job.decision || '');
    setPendingReason(job.decisionReason || '');
  }

  return (
    <div className="screen-content">
      <div className="screen-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <button onClick={onBack} className="back-btn">
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M10 3L5 8l5 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
            Companies
          </button>
          <span style={{ color: 'var(--border)' }}>/</span>
          <h1 className="screen-title" style={{ margin: 0 }}>{company.name}</h1>
        </div>
        <a href={company.website} target="_blank" rel="noreferrer" className="btn-outline">
          <svg width="12" height="12" viewBox="0 0 16 16" fill="none"><path d="M6 3H3a1 1 0 00-1 1v9a1 1 0 001 1h9a1 1 0 001-1v-3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /><path d="M9 2h5v5M14 2L8 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
          Visit Career Portal
        </a>
      </div>

      <div style={{ display: 'flex', gap: 20, marginBottom: 20 }}>
        {[['Active Jobs', activeJobs.length, 'var(--blue)'], ['Matched (≥50%)', matchedJobs.length, 'var(--green)'], ['Expired', expiredJobs.length, 'var(--muted-fg)']].map(([label, val, color]) =>
        <div key={label} style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '12px 18px' }}>
            <div style={{ fontSize: 22, fontWeight: 700, color, fontFamily: 'var(--mono)' }}>{val}</div>
            <div style={{ fontSize: 12, color: 'var(--muted-fg)', marginTop: 2 }}>{label}</div>
          </div>
        )}
      </div>

      <FilterTabs options={filterOptions} value={filter} onChange={setFilter} />

      <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
        {visible.map((job) =>
        <div key={job.id} className={`job-row ${job.status === 'Expired' ? 'job-expired' : ''}`}>
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, flex: 1, minWidth: 0 }}>
              <ScoreBadge score={job.score} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 3 }}>
                  <span style={{ fontSize: 14, fontWeight: 500, color: job.status === 'Expired' ? 'var(--muted-fg)' : 'var(--fg)' }}>{job.title}</span>
                  <StatusBadge status={job.status} />
                  {job.decision && <StatusBadge status={job.decision} />}
                </div>
                <p style={{ fontSize: 12, color: 'var(--muted-fg)', margin: 0, lineHeight: 1.5 }}>{job.aiReasoning}</p>
                {job.decision === 'Skipped' && job.decisionReason &&
              <p style={{ fontSize: 11, color: 'var(--muted-fg)', margin: '3px 0 0', fontStyle: 'italic' }}>Reason: {job.decisionReason}</p>
              }
              </div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
              {editingJob === job.id ?
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 6, padding: 6 }}>
                  <select value={pendingDecision} onChange={(e) => setPendingDecision(e.target.value)}
              style={{ fontSize: 12, border: '1px solid var(--border)', borderRadius: 4, padding: '3px 6px', background: 'var(--surface)', color: 'var(--fg)' }}>
                    <option value="">No decision</option>
                    <option value="Interested">Interested</option>
                    <option value="Applied">Applied</option>
                    <option value="Skipped">Skipped</option>
                  </select>
                  {pendingDecision === 'Skipped' &&
              <select value={pendingReason} onChange={(e) => setPendingReason(e.target.value)}
              style={{ fontSize: 12, border: '1px solid var(--border)', borderRadius: 4, padding: '3px 6px', background: 'var(--surface)', color: 'var(--fg)' }}>
                      <option value="">Select reason…</option>
                      {SKIP_REASONS_LIST.map((r) => <option key={r} value={r}>{r}</option>)}
                    </select>
              }
                  <button onClick={() => saveDecision(job.id)} style={{ fontSize: 11, padding: '3px 8px', background: 'var(--accent)', color: 'white', border: 'none', borderRadius: 4, cursor: 'pointer', fontWeight: 600 }}>Save</button>
                  <button onClick={() => setEditingJob(null)} style={{ fontSize: 11, padding: '3px 8px', background: 'transparent', color: 'var(--muted-fg)', border: '1px solid var(--border)', borderRadius: 4, cursor: 'pointer' }}>✕</button>
                </div> :

            <button onClick={() => startEdit(job)} className="btn-ghost" style={{ fontSize: 11 }}>
                  {job.decision ? 'Override' : 'Set decision'}
                </button>
            }
              <a href={job.url} className="btn-ghost" style={{ fontSize: 11, textDecoration: 'none' }}>View Job ↗</a>
            </div>
          </div>
        )}
      </div>
    </div>);

}

// ── Screen 3: CV Manager ─────────────────────────────────────────
function CVManager() {
  const [cv, setCv] = React.useState(TB_CV);
  const [dragging, setDragging] = React.useState(false);
  const [uploading, setUploading] = React.useState(false);
  const [uploaded, setUploaded] = React.useState(false);
  const fileRef = React.useRef();

  function handleFile(file) {
    if (!file) return;
    setUploading(true);
    setTimeout(() => {
      setCv({ ...TB_CV, filename: file.name, lastUpdated: new Date().toISOString() });
      setUploading(false);
      setUploaded(true);
      setTimeout(() => setUploaded(false), 2000);
    }, 1200);
  }

  return (
    <div className="screen-content">
      <div className="screen-header">
        <div>
          <h1 className="screen-title">CV Manager</h1>
          <p className="screen-sub">Your CV is used to compute match scores for all job listings.</p>
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, maxWidth: 860 }}>
        <div>
          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--muted-fg)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }}>Current CV</div>
          <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, padding: 20 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
              <div style={{ width: 40, height: 48, background: 'var(--accent-bg)', borderRadius: 6, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <svg width="18" height="20" viewBox="0 0 18 20" fill="none"><rect x="1" y="1" width="12" height="18" rx="2" stroke="var(--accent)" strokeWidth="1.5" /><path d="M4 6h6M4 9h6M4 12h4" stroke="var(--accent)" strokeWidth="1.3" strokeLinecap="round" /><path d="M13 1l4 4" stroke="var(--accent)" strokeWidth="1.5" /></svg>
              </div>
              <div>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--fg)' }}>{cv.filename}</div>
                <div style={{ fontSize: 11, color: 'var(--muted-fg)', marginTop: 2, fontFamily: 'var(--mono)' }}>
                  Last updated {fmt.date(cv.lastUpdated)}
                </div>
              </div>
              {uploaded && <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--green)', fontWeight: 600 }}>✓ Updated</span>}
            </div>
            <div
              className={`upload-zone ${dragging ? 'dragging' : ''}`}
              onDragOver={(e) => {e.preventDefault();setDragging(true);}}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {e.preventDefault();setDragging(false);handleFile(e.dataTransfer.files[0]);}}
              onClick={() => fileRef.current?.click()}>
              
              <input ref={fileRef} type="file" accept=".pdf,.txt,.docx" style={{ display: 'none' }} onChange={(e) => handleFile(e.target.files[0])} />
              {uploading ?
              <div style={{ color: 'var(--accent)', fontSize: 13 }}>Processing CV…</div> :

              <>
                  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" style={{ marginBottom: 8, opacity: 0.5 }}><path d="M10 13V5M7 8l3-3 3 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /><path d="M3 14v1a2 2 0 002 2h10a2 2 0 002-2v-1" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>
                  <div style={{ fontSize: 13, color: 'var(--muted-fg)' }}>Drop PDF / TXT here, or <span style={{ color: 'var(--accent)', cursor: 'pointer' }}>browse</span></div>
                  <div style={{ fontSize: 11, color: 'var(--muted-fg)', marginTop: 4 }}>Replaces current CV</div>
                </>
              }
            </div>
          </div>
        </div>
        <div>
          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--muted-fg)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }}>Extracted Keywords <span style={{ fontSize: 10, fontWeight: 400 }}>({cv.keywords.length})</span></div>
          <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, padding: 20 }}>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {cv.keywords.map((kw) =>
              <span key={kw} style={{ padding: '4px 10px', borderRadius: 99, fontSize: 12, fontWeight: 500,
                background: 'var(--accent-bg)', color: 'var(--accent)', fontFamily: 'var(--mono)' }}>
                  {kw}
                </span>
              )}
            </div>
            <div style={{ marginTop: 16, paddingTop: 16, borderTop: '1px solid var(--border)', fontSize: 12, color: 'var(--muted-fg)' }}>
              Keywords are extracted automatically and used to score all job listings. Re-upload your CV to refresh.
            </div>
          </div>
        </div>
      </div>
    </div>);

}

// ── Screen 4: Application Tracker ───────────────────────────────
function ApplicationTracker() {
  const [filter, setFilter] = React.useState('all');
  const [sortBy, setSortBy] = React.useState('score');

  const jobs = TB_DECIDED_JOBS;
  const counts = {
    all: jobs.length,
    Interested: jobs.filter((j) => j.decision === 'Interested').length,
    Applied: jobs.filter((j) => j.decision === 'Applied').length,
    Skipped: jobs.filter((j) => j.decision === 'Skipped').length
  };

  const filterOptions = [
  { value: 'all', label: 'All', count: counts.all },
  { value: 'Interested', label: 'Interested', count: counts.Interested },
  { value: 'Applied', label: 'Applied', count: counts.Applied },
  { value: 'Skipped', label: 'Skipped', count: counts.Skipped }];


  const visible = jobs.filter((j) => filter === 'all' || j.decision === filter).
  sort((a, b) => sortBy === 'score' ? b.score - a.score : sortBy === 'date' ? new Date(b.postedDate) - new Date(a.postedDate) : sortBy === 'applied' ? new Date(b.postedDate) - new Date(a.postedDate) : a.companyName.localeCompare(b.companyName));

  return (
    <div className="screen-content" style={{ width: "1200px" }}>
      <div className="screen-header">
        <div>
          <h1 className="screen-title">Application Tracker</h1>
          <p className="screen-sub">{counts.Applied} applied · {counts.Interested} interested · {counts.Skipped} skipped</p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 12, color: 'var(--muted-fg)' }}>Sort by</span>
          <select value={sortBy} onChange={(e) => setSortBy(e.target.value)}
          style={{ fontSize: 12, border: '1px solid var(--border)', borderRadius: 6, padding: '5px 10px', background: 'var(--surface)', color: 'var(--fg)', cursor: 'pointer' }}>
            <option value="score">Match score</option>
            <option value="company">Company</option>
            <option value="date">Date scraped</option>
            <option value="applied">Applied date</option>
          </select>
        </div>
      </div>

      <FilterTabs options={filterOptions} value={filter} onChange={setFilter} />

      <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ background: 'var(--surface-2)', borderBottom: '1px solid var(--border)' }}>
              {['Job Title', 'Company', 'Score', 'Decision', 'Reason'].map((h) =>
              <th key={h} style={{ padding: '10px 14px', textAlign: 'left', fontSize: 11, fontWeight: 600,
                color: 'var(--muted-fg)', textTransform: 'uppercase', letterSpacing: '0.05em', whiteSpace: 'nowrap' }}>{h}</th>
              )}
            </tr>
          </thead>
          <tbody>
            {visible.map((job, i) =>
            <tr key={job.id} style={{ borderBottom: i < visible.length - 1 ? '1px solid var(--border)' : 'none',
              background: i % 2 === 0 ? 'var(--surface)' : 'transparent' }}>
                <td style={{ padding: '11px 14px', fontWeight: 500, color: 'var(--fg)' }}>
                  <a href={job.url} style={{ color: 'inherit', textDecoration: 'none' }} className="table-link">{job.title}</a>
                </td>
                <td style={{ padding: '11px 14px', color: 'var(--muted-fg)' }}>{job.companyName}</td>
                <td style={{ padding: '11px 14px' }}><ScoreBadge score={job.score} /></td>
                <td style={{ padding: '11px 14px' }}><StatusBadge status={job.decision} /></td>
                <td style={{ padding: '11px 14px', color: 'var(--muted-fg)', fontSize: 12, fontStyle: job.decisionReason ? 'normal' : 'italic' }}>
                  {job.decisionReason || (job.decision !== 'Skipped' ? '—' : 'No reason')}
                </td>
              </tr>
            )}
          </tbody>
        </table>
        {visible.length === 0 &&
        <div style={{ padding: '40px', textAlign: 'center', color: 'var(--muted-fg)', fontSize: 14 }}>
            No jobs in this category.
          </div>
        }
      </div>
    </div>);

}

// ── Week helpers (exported for sidebar use) ──────────────────────
function getISOWeek(date) {
  const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  const day = d.getUTCDay() || 7;
  d.setUTCDate(d.getUTCDate() + 4 - day);
  const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  return { week: Math.ceil(((d - yearStart) / 86400000 + 1) / 7), year: d.getUTCFullYear() };
}

function getWeekBounds(year, week) {
  const simple = new Date(Date.UTC(year, 0, 1 + (week - 1) * 7));
  const dow = simple.getUTCDay();
  const monday = new Date(simple);
  monday.setUTCDate(simple.getUTCDate() - (dow <= 4 ? dow - 1 : dow - 8));
  const sunday = new Date(monday);
  sunday.setUTCDate(monday.getUTCDate() + 6);
  return { monday, sunday };
}

function fmtShort(d) {
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function buildWeeks(count = 16) {
  const now = new Date();
  const { week: curWeek, year: curYear } = getISOWeek(now);
  const result = [];
  for (let i = 0; i < count; i++) {
    let w = curWeek - i,y = curYear;
    if (w <= 0) {y--;w += 52;}
    const { monday, sunday } = getWeekBounds(y, w);
    result.push({ week: w, year: y, monday, sunday, isCurrent: i === 0 });
  }
  return result;
}

function generateWeekReport(week, year) {
  function r(s) {let v = s;return () => {v = v * 16807 % 2147483647;return (v - 1) / 2147483646;};}
  const rand = r(week * 997 + year * 31);
  const newCount = Math.floor(rand() * 18) + 3;
  const matchedCount = Math.floor(rand() * newCount * 0.6) + 1;
  const appliedCount = Math.floor(rand() * 4);
  const skippedCount = Math.floor(rand() * 5);
  const jobs = TB_ALL_JOBS.slice(0, newCount).map((j) => ({
    ...j, companyName: TB_COMPANIES.find((c) => c.id === j.companyId)?.name || '',
    score: Math.floor(rand() * 90) + 10
  }));
  return { newJobs: jobs, matchedJobs: jobs.slice(0, matchedCount), appliedJobs: jobs.slice(0, appliedCount), skippedJobs: jobs.slice(0, skippedCount) };
}

// ── Screen 5: Weekly Report ──────────────────────────────────────
function WeeklyReport({ selectedWeek, weeks }) {
  const sel = weeks[selectedWeek];
  const report = React.useMemo(() => {
    if (selectedWeek === 0) {
      const cutoff = Date.now() - 7 * 86400000;
      const newJobs = TB_ALL_JOBS.filter((j) => j.status === 'Active' && new Date(j.postedDate).getTime() > cutoff).slice(0, 12).
      map((j) => ({ ...j, companyName: TB_COMPANIES.find((c) => c.id === j.companyId)?.name || '' }));
      const matchedJobs = TB_ALL_JOBS.filter((j) => j.status === 'Active' && j.score >= 50).slice(0, 8).
      map((j) => ({ ...j, companyName: TB_COMPANIES.find((c) => c.id === j.companyId)?.name || '' }));
      return { newJobs, matchedJobs, appliedJobs: TB_DECIDED_JOBS.filter((j) => j.decision === 'Applied'), skippedJobs: TB_DECIDED_JOBS.filter((j) => j.decision === 'Skipped').slice(0, 8) };
    }
    return generateWeekReport(sel.week, sel.year);
  }, [selectedWeek]);

  const dateRange = `${fmtShort(sel.monday)} \u2013 ${fmtShort(sel.sunday)}, ${sel.year}`;

  return (
    <div className="screen-content">
      <div className="screen-header">
        <div>
          <h1 className="screen-title">
            Weekly Report
            {sel.isCurrent && <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--green)', background: 'var(--green-bg)', padding: '2px 8px', borderRadius: 99, marginLeft: 10, verticalAlign: 'middle' }}>current</span>}
          </h1>
          <p className="screen-sub">CW{String(sel.week).padStart(2, '0')} {sel.year} · {dateRange}</p>
        </div>
        <button className="btn-outline">
          <svg width="13" height="13" viewBox="0 0 16 16" fill="none"><path d="M2 8a6 6 0 1112 0A6 6 0 012 8z" stroke="currentColor" strokeWidth="1.4" /><path d="M8 5v4l2.5 2.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" /></svg>
          Send Now
        </button>
      </div>
      <div style={{ maxWidth: 660 }}>
        <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, overflow: 'hidden' }}>
          <div style={{ background: 'var(--fg)', padding: '32px 36px' }}>
            <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'rgba(255,255,255,0.4)', marginBottom: 8 }}>Weekly Digest</div>
            <div style={{ fontSize: 22, fontWeight: 700, color: 'white' }}>TalentBridge Report</div>
            <div style={{ fontSize: 13, color: 'rgba(255,255,255,0.55)', marginTop: 4 }}>CW{String(sel.week).padStart(2, '0')} · {dateRange}</div>
          </div>
          <div style={{ padding: '28px 36px' }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 12, marginBottom: 28, paddingBottom: 24, borderBottom: '1px solid var(--border)' }}>
              {[['New Jobs', report.newJobs.length, 'var(--blue)'], ['Matched', report.matchedJobs.length, 'var(--green)'], ['Applied', report.appliedJobs.length, 'var(--teal)'], ['Skipped', report.skippedJobs.length, 'var(--muted-fg)']].map(([l, v, c]) =>
              <div key={l} style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: 28, fontWeight: 700, color: c, fontFamily: 'var(--mono)' }}>{v}</div>
                  <div style={{ fontSize: 11, color: 'var(--muted-fg)', marginTop: 2 }}>{l}</div>
                </div>
              )}
            </div>
            {[
            { title: '\uD83C\uDD95 New Jobs This Week', jobs: report.newJobs },
            { title: '\u2B50 Matched Jobs (\u226550%)', jobs: report.matchedJobs },
            { title: '\u2705 Applied', jobs: report.appliedJobs },
            { title: '\u23ED Skipped', jobs: report.skippedJobs, showReason: true }].
            map((section) => section.jobs.length > 0 &&
            <div key={section.title} style={{ marginBottom: 24 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--muted-fg)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }}>{section.title}</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                  {section.jobs.map((job) =>
                <div key={job.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 10px', borderRadius: 6, transition: 'background 0.15s' }}
                onMouseEnter={(e) => e.currentTarget.style.background = 'var(--surface-2)'}
                onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}>
                      <ScoreBadge score={job.score} size="sm" />
                      <a href={job.url} style={{ flex: 1, fontSize: 13, fontWeight: 500, color: 'var(--accent)', textDecoration: 'none' }}>{job.title}</a>
                      <span style={{ fontSize: 12, color: 'var(--muted-fg)' }}>{job.companyName}</span>
                      {section.showReason && job.decisionReason && <span style={{ fontSize: 11, color: 'var(--muted-fg)', fontStyle: 'italic' }}>{job.decisionReason}</span>}
                    </div>
                )}
                </div>
              </div>
            )}
          </div>
          <div style={{ padding: '16px 36px', background: 'var(--surface-2)', borderTop: '1px solid var(--border)', textAlign: 'center', fontSize: 11, color: 'var(--muted-fg)' }}>
            Generated by TalentBridge · Running locally on your machine
          </div>
        </div>
      </div>
    </div>);

}

// Export to window
Object.assign(window, { CompanyOverview, CompanyView, CVManager, ApplicationTracker, WeeklyReport, ScoreBadge, StatusBadge, buildWeeks, fmtShort, generateWeekReport });