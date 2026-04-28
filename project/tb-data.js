// TalentBridge Mock Data

const COMPANY_NAMES = [
  'Acme Technologies','Beacon Analytics','Crestline Capital','Dawnlight Media',
  'Ember Systems','Forge Consulting','Granite Financial','Harbor Health',
  'Ironwood Ventures','Jade Cloud','Kestrel AI','Luminary Software',
  'Meridian Data','Nexus Labs','Opal Robotics','Pinnacle Research',
  'Quartz Digital','Reef Technologies','Solaris Energy','Terrain Analytics',
  'Umbra Security','Vault Finance','Wren Logistics','Xenon Software',
  'Yonder Media','Zenith Platforms','Alcove Design','Blueprint Systems',
  'Cobalt Networks','Delta Analytics','Equinox Health','Fathom Data',
  'Glacier Tech','Horizon Capital','Indigo Labs','Junction AI',
  'Keystone Finance','Lattice Systems','Matrix Cloud','Northern Trust',
  'Offset Digital','Prism Analytics','Quantum Ventures','Ridge Software',
  'Summit Consulting','Tidal Platforms','Uplift Health','Vertex Labs',
  'Watershed Media','Zenon Technologies'
];

const INDUSTRIES = [
  'Technology','Data & AI','Finance','Media','Systems','Consulting','Financial Services',
  'Healthcare','Venture Capital','Cloud','Artificial Intelligence','Software',
  'Data Analytics','Research','Robotics','Research','Digital','Technology','Energy',
  'Analytics','Cybersecurity','Finance','Logistics','Software','Media','Platforms',
  'Design','Systems','Networks','Analytics','Health','Data','Technology','Capital',
  'AI','Artificial Intelligence','Finance','Systems','Cloud','Finance',
  'Digital','Analytics','Ventures','Software','Consulting','Platforms','Health','Labs',
  'Media','Technology'
];

const SCRAPE_STATUSES = ['success','success','success','success','pending','failed','success','success','pending','success'];

const JOB_TITLES = [
  'Senior Software Engineer','Product Manager','Data Scientist','ML Engineer',
  'Frontend Engineer','Backend Engineer','Full Stack Engineer','DevOps Engineer',
  'Platform Engineer','Staff Engineer','Engineering Manager','Principal Engineer',
  'Data Engineer','Analytics Engineer','Research Scientist','Applied Scientist',
  'Product Designer','UX Researcher','Technical Program Manager','Solutions Architect',
  'Site Reliability Engineer','Security Engineer','Growth Engineer','Mobile Engineer',
  'iOS Engineer','Android Engineer','Infrastructure Engineer','Systems Engineer',
  'Business Analyst','Strategy Manager','Operations Manager','Finance Manager',
  'Content Strategist','Marketing Manager','Account Executive','Sales Engineer'
];

const AI_REASONS = [
  'Strong match on distributed systems and Python; team uses similar tech stack.',
  'Role requires 5+ years ML experience; your CV shows 6 years with relevant frameworks.',
  'Product domain aligns with your consumer fintech background.',
  'React and TypeScript listed as primary stack; matches your frontend skills.',
  'Leadership expectations exceed your current experience level.',
  'Requires healthcare industry knowledge not evidenced in your CV.',
  'System design and Kubernetes experience strongly aligned.',
  'Strong data infrastructure overlap; Spark and dbt mentioned explicitly.',
  'Strategy consulting background matches the role context well.',
  'Robotics-specific domain knowledge not present in your profile.',
  'Cloud architecture experience directly relevant; AWS certifications noted.',
  'Partial match — Python skills align but NLP specialization is missing.',
  'Excellent overlap: TypeScript, React, GraphQL all present in your CV.',
  'Research publication record aligns with their stated preference.',
  'Operations scope broader than your current experience warrants.',
  'Security clearance required; not applicable from your profile.',
  'Growth-stage company context matches your past startup experience.',
  'Mobile development not present in your CV.',
  'Technical writing portfolio would strengthen this application.',
  'Revenue target expectations are very senior; may be a reach.',
];

function seedRand(seed) {
  let s = seed;
  return () => { s = (s * 16807 + 0) % 2147483647; return (s - 1) / 2147483646; };
}

function generateJobs(companyId) {
  const r = seedRand(companyId * 997 + 13);
  const count = Math.floor(r() * 12) + 2;
  const jobs = [];
  const usedTitles = new Set();
  for (let i = 0; i < count; i++) {
    let titleIdx = Math.floor(r() * JOB_TITLES.length);
    while (usedTitles.has(titleIdx)) titleIdx = (titleIdx + 1) % JOB_TITLES.length;
    usedTitles.add(titleIdx);
    const score = Math.round(r() * 95 + 5);
    const isExpired = r() < 0.22;
    const reasonIdx = Math.floor(r() * AI_REASONS.length);
    const decisionRoll = r();
    let decision = null;
    if (!isExpired && decisionRoll < 0.15) decision = 'Interested';
    else if (!isExpired && decisionRoll < 0.25) decision = 'Applied';
    else if (!isExpired && decisionRoll < 0.38) decision = 'Skipped';
    const skipReasons = ['Salary too low','Location mismatch','Not a good culture fit','Too senior','Too junior','Prefer remote'];
    jobs.push({
      id: companyId * 100 + i,
      companyId,
      title: JOB_TITLES[titleIdx],
      score,
      aiReasoning: AI_REASONS[reasonIdx],
      status: isExpired ? 'Expired' : 'Active',
      decision,
      decisionReason: decision === 'Skipped' ? skipReasons[Math.floor(r() * skipReasons.length)] : null,
      postedDate: new Date(Date.now() - Math.floor(r() * 30) * 86400000).toISOString(),
      url: '#',
    });
  }
  return jobs;
}

function generateCompanies() {
  return COMPANY_NAMES.map((name, i) => {
    const r = seedRand(i * 31 + 7);
    const jobs = generateJobs(i);
    const activeJobs = jobs.filter(j => j.status === 'Active');
    const matchedJobs = activeJobs.filter(j => j.score >= 50);
    const hoursAgo = Math.floor(r() * 48);
    const lastScraped = new Date(Date.now() - hoursAgo * 3600000).toISOString();
    return {
      id: i,
      name,
      industry: INDUSTRIES[i],
      website: `https://careers.${name.toLowerCase().replace(/[^a-z]/g,'')}.com`,
      lastScraped,
      scrapeStatus: SCRAPE_STATUSES[i % SCRAPE_STATUSES.length],
      jobs,
      activeJobCount: activeJobs.length,
      matchedJobCount: matchedJobs.length,
    };
  });
}

const TB_COMPANIES = generateCompanies();

const TB_ALL_JOBS = TB_COMPANIES.flatMap(c => c.jobs);

const TB_DECIDED_JOBS = TB_ALL_JOBS.filter(j => j.decision !== null).map(j => ({
  ...j,
  companyName: TB_COMPANIES.find(c => c.id === j.companyId)?.name || '',
}));

const TB_CV = {
  filename: 'alex_chen_cv_2026.pdf',
  lastUpdated: '2026-04-10T14:22:00',
  keywords: [
    'Python','TypeScript','React','Node.js','PostgreSQL','AWS','Kubernetes',
    'Docker','GraphQL','REST APIs','System Design','Distributed Systems',
    'Machine Learning','Data Pipelines','dbt','Spark','Redis','Kafka',
    'Agile','Product Strategy','Technical Leadership','CI/CD','Terraform',
    'Microservices','Event-Driven Architecture'
  ],
};
