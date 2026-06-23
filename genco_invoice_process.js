const XLSX = require('xlsx');
const fs = require('fs');
const path = require('path');
const http = require('http');

const DATA_DIR = path.join(__dirname, 'data');
const INVOICES_FILE = path.join(DATA_DIR, 'genco_invoices.json');
const EXPECTED_BILLS_FILE = path.join(DATA_DIR, 'expected_genco_bills.json');
const JOURNAL_FILE = path.join(DATA_DIR, 'journal_entries.json');

if (!fs.existsSync(DATA_DIR)) fs.mkdirSync(DATA_DIR, { recursive: true });

function loadJSON(file) {
  if (!fs.existsSync(file)) return [];
  return JSON.parse(fs.readFileSync(file, 'utf8'));
}

function saveJSON(file, data) {
  fs.writeFileSync(file, JSON.stringify(data, null, 2), 'utf8');
}

const GENCOS = [
  'Egbin Power Plc',
  'Sapele Power Plc',
  'Afam Power Plc',
  'Ughelli Power Plc (Transcorp)',
  'Shiroro Hydro Power Plc',
  'Kainji/Jebba Hydro Power Plc',
  'Geregu Power Plc',
  'Olorunsogo Power Plc',
  'Omotosho Power Plc',
  'Azura-Edo IPP',
  'Odukpani Power Plc',
  'Calabar GenCo',
  'Gbarain GenCo',
  'Olorunsogo NIPP',
  'Omotosho NIPP',
  'Geregu NIPP',
  'Ihovbor NIPP',
  'Afam VI (Shell)',
  'Rivers IPP',
  'Trans Amadi',
  'ASCO (Geometric)',
  'Paras Energy'
];

function generateInvoiceId() {
  const invoices = loadJSON(INVOICES_FILE);
  const num = invoices.length + 1;
  return `INV-GENCO-${String(num).padStart(5, '0')}`;
}

function receiveInvoice(data) {
  const invoices = loadJSON(INVOICES_FILE);
  const invoice = {
    invoiceId: generateInvoiceId(),
    gencoName: data.gencoName,
    invoiceNumber: data.invoiceNumber,
    invoiceDate: data.invoiceDate,
    billingPeriod: data.billingPeriod,
    receiptDate: new Date().toISOString(),
    receiptTime: new Date().toLocaleTimeString('en-NG', { hour12: false }),
    deliveryMethod: data.deliveryMethod, // 'email' or 'physical'
    deliveryDetails: data.deliveryDetails || '',
    energyMWh: parseFloat(data.energyMWh) || 0,
    capacityMW: parseFloat(data.capacityMW) || 0,
    energyCharge: parseFloat(data.energyCharge) || 0,
    capacityCharge: parseFloat(data.capacityCharge) || 0,
    startupCost: parseFloat(data.startupCost) || 0,
    otherCharges: parseFloat(data.otherCharges) || 0,
    totalAmount: parseFloat(data.totalAmount) || 0,
    currency: data.currency || 'NGN',
    attachmentPath: data.attachmentPath || '',
    status: 'received',
    reviewNotes: '',
    reviewedBy: '',
    reviewedAt: '',
    comparisonResult: null,
    journalEntryId: null,
    createdAt: new Date().toISOString()
  };
  invoices.push(invoice);
  saveJSON(INVOICES_FILE, invoices);
  return invoice;
}

function reviewInvoice(invoiceId, reviewData) {
  const invoices = loadJSON(INVOICES_FILE);
  const idx = invoices.findIndex(i => i.invoiceId === invoiceId);
  if (idx === -1) throw new Error('Invoice not found');

  invoices[idx].status = reviewData.approved ? 'reviewed' : 'rejected';
  invoices[idx].reviewNotes = reviewData.notes || '';
  invoices[idx].reviewedBy = reviewData.reviewedBy || '';
  invoices[idx].reviewedAt = new Date().toISOString();

  if (reviewData.correctedTotal) {
    invoices[idx].totalAmount = parseFloat(reviewData.correctedTotal);
  }

  saveJSON(INVOICES_FILE, invoices);
  return invoices[idx];
}

function compareWithExpected(invoiceId) {
  const invoices = loadJSON(INVOICES_FILE);
  const expected = loadJSON(EXPECTED_BILLS_FILE);
  const idx = invoices.findIndex(i => i.invoiceId === invoiceId);
  if (idx === -1) throw new Error('Invoice not found');

  const inv = invoices[idx];
  const match = expected.find(
    e => e.gencoName === inv.gencoName && e.billingPeriod === inv.billingPeriod
  );

  let result;
  if (!match) {
    result = {
      matched: false,
      reason: 'No expected bill found for this GenCo and billing period',
      expectedAmount: null,
      invoicedAmount: inv.totalAmount,
      variance: null,
      variancePercent: null
    };
  } else {
    const variance = inv.totalAmount - match.expectedAmount;
    const variancePercent = match.expectedAmount !== 0
      ? ((variance / match.expectedAmount) * 100).toFixed(2)
      : 0;
    const threshold = 2; // 2% tolerance

    result = {
      matched: Math.abs(variancePercent) <= threshold,
      reason: Math.abs(variancePercent) <= threshold
        ? 'Within acceptable variance threshold'
        : `Variance of ${variancePercent}% exceeds ${threshold}% threshold`,
      expectedAmount: match.expectedAmount,
      invoicedAmount: inv.totalAmount,
      variance: variance,
      variancePercent: parseFloat(variancePercent),
      expectedEnergyMWh: match.energyMWh,
      invoicedEnergyMWh: inv.energyMWh,
      expectedCapacityMW: match.capacityMW,
      invoicedCapacityMW: inv.capacityMW
    };
  }

  invoices[idx].comparisonResult = result;
  invoices[idx].status = result.matched ? 'compared-ok' : 'compared-variance';
  saveJSON(INVOICES_FILE, invoices);
  return { invoice: invoices[idx], comparison: result };
}

function postToJournal(invoiceId, postData) {
  const invoices = loadJSON(INVOICES_FILE);
  const journal = loadJSON(JOURNAL_FILE);
  const idx = invoices.findIndex(i => i.invoiceId === invoiceId);
  if (idx === -1) throw new Error('Invoice not found');

  const inv = invoices[idx];
  const entryId = `JE-${Date.now()}`;

  const journalEntry = {
    entryId,
    invoiceId: inv.invoiceId,
    gencoName: inv.gencoName,
    billingPeriod: inv.billingPeriod,
    postingDate: new Date().toISOString(),
    postedBy: postData.postedBy || '',
    narration: postData.narration || `GenCo invoice ${inv.invoiceNumber} for ${inv.billingPeriod}`,
    lines: [
      {
        account: 'Energy Purchase - GenCo',
        accountCode: '5100',
        debit: inv.energyCharge,
        credit: 0,
        description: `Energy charge: ${inv.energyMWh} MWh`
      },
      {
        account: 'Capacity Purchase - GenCo',
        accountCode: '5200',
        debit: inv.capacityCharge,
        credit: 0,
        description: `Capacity charge: ${inv.capacityMW} MW`
      },
      ...(inv.startupCost > 0 ? [{
        account: 'Startup Cost - GenCo',
        accountCode: '5300',
        debit: inv.startupCost,
        credit: 0,
        description: 'Startup cost'
      }] : []),
      ...(inv.otherCharges > 0 ? [{
        account: 'Other Charges - GenCo',
        accountCode: '5400',
        debit: inv.otherCharges,
        credit: 0,
        description: 'Other charges'
      }] : []),
      {
        account: 'Accounts Payable - GenCo',
        accountCode: '2100',
        debit: 0,
        credit: inv.totalAmount,
        description: `Payable to ${inv.gencoName}`
      }
    ],
    totalDebit: inv.energyCharge + inv.capacityCharge + inv.startupCost + inv.otherCharges,
    totalCredit: inv.totalAmount,
    balanced: Math.abs(
      (inv.energyCharge + inv.capacityCharge + inv.startupCost + inv.otherCharges) - inv.totalAmount
    ) < 0.01,
    status: 'posted'
  };

  journal.push(journalEntry);
  saveJSON(JOURNAL_FILE, journal);

  invoices[idx].journalEntryId = entryId;
  invoices[idx].status = 'posted';
  saveJSON(INVOICES_FILE, invoices);

  return journalEntry;
}

function importExpectedBills(filePath) {
  const wb = XLSX.readFile(filePath);
  const ws = wb.Sheets[wb.SheetNames[0]];
  const rows = XLSX.utils.sheet_to_json(ws);
  const bills = rows.map(r => ({
    gencoName: r['GenCo Name'] || r['gencoName'] || '',
    billingPeriod: r['Billing Period'] || r['billingPeriod'] || '',
    expectedAmount: parseFloat(r['Expected Amount'] || r['expectedAmount'] || 0),
    energyMWh: parseFloat(r['Energy (MWh)'] || r['energyMWh'] || 0),
    capacityMW: parseFloat(r['Capacity (MW)'] || r['capacityMW'] || 0),
    tariffRate: parseFloat(r['Tariff Rate'] || r['tariffRate'] || 0)
  }));
  saveJSON(EXPECTED_BILLS_FILE, bills);
  return bills;
}

// --- HTTP Server & Web UI ---

const HTML = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NBET - GenCo Invoice Processing</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', Tahoma, sans-serif; background: #f0f2f5; color: #333; }
  .header { background: #1a5632; color: white; padding: 16px 32px; display: flex; align-items: center; gap: 16px; }
  .header h1 { font-size: 20px; font-weight: 600; }
  .header .subtitle { font-size: 13px; opacity: 0.8; }
  .nav { background: #fff; border-bottom: 1px solid #ddd; padding: 0 32px; display: flex; gap: 0; }
  .nav button { background: none; border: none; padding: 12px 20px; cursor: pointer; font-size: 14px;
    color: #666; border-bottom: 3px solid transparent; transition: all 0.2s; }
  .nav button.active { color: #1a5632; border-bottom-color: #1a5632; font-weight: 600; }
  .nav button:hover { color: #1a5632; background: #f8f9fa; }
  .container { max-width: 1200px; margin: 24px auto; padding: 0 24px; }
  .card { background: #fff; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); padding: 24px; margin-bottom: 20px; }
  .card h2 { font-size: 18px; margin-bottom: 16px; color: #1a5632; }
  .form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  .form-group { display: flex; flex-direction: column; gap: 4px; }
  .form-group.full { grid-column: 1 / -1; }
  .form-group label { font-size: 13px; font-weight: 600; color: #555; }
  .form-group input, .form-group select, .form-group textarea {
    padding: 8px 12px; border: 1px solid #ccc; border-radius: 4px; font-size: 14px; }
  .form-group textarea { resize: vertical; min-height: 60px; }
  .btn { padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; font-weight: 600; }
  .btn-primary { background: #1a5632; color: white; }
  .btn-primary:hover { background: #14472a; }
  .btn-secondary { background: #e9ecef; color: #333; }
  .btn-warning { background: #f0ad4e; color: white; }
  .btn-danger { background: #d9534f; color: white; }
  .btn-sm { padding: 6px 12px; font-size: 12px; }
  .actions { display: flex; gap: 8px; margin-top: 16px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 10px 12px; text-align: left; border-bottom: 1px solid #eee; }
  th { background: #f8f9fa; font-weight: 600; color: #555; }
  .status { padding: 3px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; }
  .status-received { background: #d4edda; color: #155724; }
  .status-reviewed { background: #cce5ff; color: #004085; }
  .status-rejected { background: #f8d7da; color: #721c24; }
  .status-compared-ok { background: #d1ecf1; color: #0c5460; }
  .status-compared-variance { background: #fff3cd; color: #856404; }
  .status-posted { background: #c3e6cb; color: #155724; }
  .comparison-box { background: #f8f9fa; border: 1px solid #dee2e6; border-radius: 6px; padding: 16px; margin: 12px 0; }
  .comparison-row { display: flex; justify-content: space-between; padding: 6px 0; }
  .comparison-row .label { font-weight: 600; color: #555; }
  .variance-ok { color: #28a745; }
  .variance-bad { color: #dc3545; }
  .journal-lines { margin: 12px 0; }
  .journal-lines table { font-size: 12px; }
  .total-row { font-weight: 700; background: #f0f2f5; }
  .hidden { display: none; }
  .alert { padding: 12px 16px; border-radius: 6px; margin-bottom: 16px; font-size: 14px; }
  .alert-success { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
  .alert-error { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
  .pipeline { display: flex; gap: 0; margin-bottom: 24px; }
  .pipeline-step { flex: 1; text-align: center; padding: 12px; background: #e9ecef; position: relative;
    font-size: 13px; font-weight: 600; color: #666; }
  .pipeline-step.active { background: #1a5632; color: white; }
  .pipeline-step.done { background: #28a745; color: white; }
  .pipeline-step:first-child { border-radius: 6px 0 0 6px; }
  .pipeline-step:last-child { border-radius: 0 6px 6px 0; }
  .money { font-family: 'Courier New', monospace; }
  .detail-modal { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5);
    display: flex; align-items: center; justify-content: center; z-index: 100; }
  .detail-content { background: white; border-radius: 8px; padding: 32px; max-width: 700px; width: 90%;
    max-height: 80vh; overflow-y: auto; }
  .detail-content h2 { margin-bottom: 20px; }
  .close-btn { float: right; background: none; border: none; font-size: 24px; cursor: pointer; color: #999; }
</style>
</head>
<body>

<div class="header">
  <div>
    <h1>NBET - GenCo Invoice Processing</h1>
    <div class="subtitle">Nigerian Bulk Electricity Trading Plc</div>
  </div>
</div>

<div class="nav">
  <button class="active" data-tab="receive">1. Receive Invoice</button>
  <button data-tab="review">2. Review</button>
  <button data-tab="compare">3. Compare with Expected</button>
  <button data-tab="journal">4. Post to Journal</button>
  <button data-tab="all">All Invoices</button>
  <button data-tab="expected">Expected Bills</button>
</div>

<div class="container">
  <div id="alert-area"></div>

  <!-- Tab 1: Receive Invoice -->
  <div id="tab-receive">
    <div class="pipeline">
      <div class="pipeline-step active">Receive</div>
      <div class="pipeline-step">Review</div>
      <div class="pipeline-step">Compare</div>
      <div class="pipeline-step">Post</div>
    </div>
    <div class="card">
      <h2>Receive GenCo Invoice</h2>
      <form id="receiveForm" onsubmit="return submitInvoice(event)">
        <div class="form-grid">
          <div class="form-group">
            <label>GenCo Name *</label>
            <select name="gencoName" required>
              <option value="">-- Select GenCo --</option>
              ${GENCOS.map(g => '<option value="' + g + '">' + g + '</option>').join('')}
            </select>
          </div>
          <div class="form-group">
            <label>Invoice Number *</label>
            <input type="text" name="invoiceNumber" required placeholder="e.g. EGP-2024-04-001">
          </div>
          <div class="form-group">
            <label>Invoice Date *</label>
            <input type="date" name="invoiceDate" required>
          </div>
          <div class="form-group">
            <label>Billing Period *</label>
            <input type="month" name="billingPeriod" required>
          </div>
          <div class="form-group">
            <label>Delivery Method *</label>
            <select name="deliveryMethod" required>
              <option value="">-- Select --</option>
              <option value="email">Email</option>
              <option value="physical">Physical Delivery</option>
            </select>
          </div>
          <div class="form-group">
            <label>Delivery Details</label>
            <input type="text" name="deliveryDetails" placeholder="e.g. sender email or courier name">
          </div>
          <div class="form-group">
            <label>Energy Delivered (MWh)</label>
            <input type="number" step="0.01" name="energyMWh" placeholder="0.00">
          </div>
          <div class="form-group">
            <label>Available Capacity (MW)</label>
            <input type="number" step="0.01" name="capacityMW" placeholder="0.00">
          </div>
          <div class="form-group">
            <label>Energy Charge (NGN)</label>
            <input type="number" step="0.01" name="energyCharge" placeholder="0.00">
          </div>
          <div class="form-group">
            <label>Capacity Charge (NGN)</label>
            <input type="number" step="0.01" name="capacityCharge" placeholder="0.00">
          </div>
          <div class="form-group">
            <label>Startup Cost (NGN)</label>
            <input type="number" step="0.01" name="startupCost" value="0" placeholder="0.00">
          </div>
          <div class="form-group">
            <label>Other Charges (NGN)</label>
            <input type="number" step="0.01" name="otherCharges" value="0" placeholder="0.00">
          </div>
          <div class="form-group">
            <label>Total Invoice Amount (NGN) *</label>
            <input type="number" step="0.01" name="totalAmount" required placeholder="0.00">
          </div>
          <div class="form-group">
            <label>Currency</label>
            <select name="currency">
              <option value="NGN">NGN (Naira)</option>
              <option value="USD">USD</option>
            </select>
          </div>
          <div class="form-group full">
            <label>Attachment Path (optional)</label>
            <input type="text" name="attachmentPath" placeholder="Path to scanned copy or email file">
          </div>
        </div>
        <div class="actions">
          <button type="submit" class="btn btn-primary">Receive Invoice</button>
          <button type="reset" class="btn btn-secondary">Clear</button>
        </div>
      </form>
    </div>
  </div>

  <!-- Tab 2: Review -->
  <div id="tab-review" class="hidden">
    <div class="pipeline">
      <div class="pipeline-step done">Receive</div>
      <div class="pipeline-step active">Review</div>
      <div class="pipeline-step">Compare</div>
      <div class="pipeline-step">Post</div>
    </div>
    <div class="card">
      <h2>Review Pending Invoices</h2>
      <div id="review-list"></div>
    </div>
  </div>

  <!-- Tab 3: Compare -->
  <div id="tab-compare" class="hidden">
    <div class="pipeline">
      <div class="pipeline-step done">Receive</div>
      <div class="pipeline-step done">Review</div>
      <div class="pipeline-step active">Compare</div>
      <div class="pipeline-step">Post</div>
    </div>
    <div class="card">
      <h2>Compare with Expected GenCo Bills</h2>
      <div id="compare-list"></div>
    </div>
  </div>

  <!-- Tab 4: Journal -->
  <div id="tab-journal" class="hidden">
    <div class="pipeline">
      <div class="pipeline-step done">Receive</div>
      <div class="pipeline-step done">Review</div>
      <div class="pipeline-step done">Compare</div>
      <div class="pipeline-step active">Post</div>
    </div>
    <div class="card">
      <h2>Post to Journal</h2>
      <div id="journal-list"></div>
    </div>
  </div>

  <!-- All Invoices -->
  <div id="tab-all" class="hidden">
    <div class="card">
      <h2>All GenCo Invoices</h2>
      <div id="all-list"></div>
    </div>
  </div>

  <!-- Expected Bills -->
  <div id="tab-expected" class="hidden">
    <div class="card">
      <h2>Expected GenCo Bills</h2>
      <p style="margin-bottom:12px;font-size:13px;color:#666;">
        Upload an Excel file with columns: GenCo Name, Billing Period, Expected Amount, Energy (MWh), Capacity (MW), Tariff Rate
      </p>
      <div class="form-group" style="max-width:400px;margin-bottom:16px;">
        <label>Import Expected Bills (Excel)</label>
        <input type="text" id="expectedFilePath" placeholder="Full path to .xlsx file">
        <button class="btn btn-primary btn-sm" style="margin-top:8px;" onclick="importExpected()">Import</button>
      </div>
      <div id="expected-list"></div>
    </div>
  </div>
</div>

<!-- Detail Modal -->
<div id="modal" class="detail-modal hidden" onclick="if(event.target===this)closeModal()">
  <div class="detail-content" id="modal-content"></div>
</div>

<script>
const API = '';

function showTab(tab, el) {
  document.querySelectorAll('.nav button').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.container > div[id^="tab-"]').forEach(d => d.classList.add('hidden'));
  document.getElementById('tab-' + tab).classList.remove('hidden');
  if (el) el.classList.add('active');
  if (tab === 'review') loadReview();
  if (tab === 'compare') loadCompare();
  if (tab === 'journal') loadJournal();
  if (tab === 'all') loadAll();
  if (tab === 'expected') loadExpected();
}

function showAlert(msg, type) {
  const area = document.getElementById('alert-area');
  area.innerHTML = '<div class="alert alert-' + type + '">' + msg + '</div>';
  setTimeout(() => area.innerHTML = '', 5000);
}

function fmt(n) { return Number(n).toLocaleString('en-NG', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }

async function api(endpoint, body) {
  const res = await fetch(API + endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  return res.json();
}

async function submitInvoice(e) {
  e.preventDefault();
  const fd = new FormData(e.target);
  const data = Object.fromEntries(fd.entries());
  const res = await api('/api/receive', data);
  if (res.error) { showAlert(res.error, 'error'); return false; }
  showAlert('Invoice ' + res.invoiceId + ' received at ' + new Date(res.receiptDate).toLocaleString() +
    ' via ' + res.deliveryMethod, 'success');
  e.target.reset();
  return false;
}

async function loadReview() {
  const res = await fetch('/api/invoices');
  const invoices = await res.json();
  const pending = invoices.filter(i => i.status === 'received');
  const div = document.getElementById('review-list');
  if (!pending.length) { div.innerHTML = '<p style="color:#666">No invoices pending review.</p>'; return; }
  div.innerHTML = '<table><thead><tr><th>Invoice ID</th><th>GenCo</th><th>Period</th><th>Amount</th>' +
    '<th>Received</th><th>Method</th><th>Actions</th></tr></thead><tbody>' +
    pending.map(i => '<tr><td>' + i.invoiceId + '</td><td>' + i.gencoName + '</td><td>' + i.billingPeriod +
    '</td><td class="money">₦' + fmt(i.totalAmount) + '</td><td>' + new Date(i.receiptDate).toLocaleString() +
    '</td><td>' + i.deliveryMethod + '</td><td>' +
    '<button class="btn btn-primary btn-sm" onclick="reviewAction(\\'' + i.invoiceId + '\\',true)">Approve</button> ' +
    '<button class="btn btn-danger btn-sm" onclick="reviewAction(\\'' + i.invoiceId + '\\',false)">Reject</button> ' +
    '<button class="btn btn-secondary btn-sm" onclick="showDetail(\\'' + i.invoiceId + '\\')">View</button>' +
    '</td></tr>').join('') + '</tbody></table>';
}

async function reviewAction(id, approved) {
  const notes = approved ? '' : prompt('Reason for rejection:');
  if (!approved && notes === null) return;
  const reviewer = prompt('Reviewer name:');
  if (reviewer === null) return;
  await api('/api/review', { invoiceId: id, approved, notes, reviewedBy: reviewer });
  showAlert('Invoice ' + id + (approved ? ' approved' : ' rejected'), approved ? 'success' : 'error');
  loadReview();
}

async function loadCompare() {
  const res = await fetch('/api/invoices');
  const invoices = await res.json();
  const reviewed = invoices.filter(i => i.status === 'reviewed');
  const div = document.getElementById('compare-list');
  if (!reviewed.length) { div.innerHTML = '<p style="color:#666">No reviewed invoices pending comparison.</p>'; return; }
  div.innerHTML = '<table><thead><tr><th>Invoice ID</th><th>GenCo</th><th>Period</th><th>Invoiced Amount</th>' +
    '<th>Reviewer</th><th>Actions</th></tr></thead><tbody>' +
    reviewed.map(i => '<tr><td>' + i.invoiceId + '</td><td>' + i.gencoName + '</td><td>' + i.billingPeriod +
    '</td><td class="money">₦' + fmt(i.totalAmount) + '</td><td>' + i.reviewedBy +
    '</td><td><button class="btn btn-warning btn-sm" onclick="compareAction(\\'' + i.invoiceId + '\\')">Compare</button></td></tr>'
    ).join('') + '</tbody></table>';
}

async function compareAction(id) {
  const res = await api('/api/compare', { invoiceId: id });
  if (res.error) { showAlert(res.error, 'error'); return; }
  const c = res.comparison;
  let html = '<h3>Comparison Result for ' + id + '</h3><div class="comparison-box">' +
    '<div class="comparison-row"><span class="label">Invoiced Amount:</span><span class="money">₦' + fmt(c.invoicedAmount) + '</span></div>';
  if (c.expectedAmount !== null) {
    html += '<div class="comparison-row"><span class="label">Expected Amount:</span><span class="money">₦' + fmt(c.expectedAmount) + '</span></div>' +
      '<div class="comparison-row"><span class="label">Variance:</span><span class="money ' +
      (c.matched ? 'variance-ok' : 'variance-bad') + '">₦' + fmt(c.variance) + ' (' + c.variancePercent + '%)</span></div>' +
      '<div class="comparison-row"><span class="label">Status:</span><span class="' +
      (c.matched ? 'variance-ok' : 'variance-bad') + '">' + c.reason + '</span></div>';
  } else {
    html += '<div class="comparison-row"><span class="variance-bad">' + c.reason + '</span></div>';
  }
  html += '</div>';
  document.getElementById('modal-content').innerHTML = '<button class="close-btn" onclick="closeModal()">&times;</button>' + html;
  document.getElementById('modal').classList.remove('hidden');
  loadCompare();
}

async function loadJournal() {
  const res = await fetch('/api/invoices');
  const invoices = await res.json();
  const ready = invoices.filter(i => i.status === 'compared-ok' || i.status === 'compared-variance');
  const div = document.getElementById('journal-list');
  if (!ready.length) { div.innerHTML = '<p style="color:#666">No invoices ready for journal posting.</p>'; return; }
  div.innerHTML = '<table><thead><tr><th>Invoice ID</th><th>GenCo</th><th>Period</th><th>Amount</th>' +
    '<th>Comparison</th><th>Actions</th></tr></thead><tbody>' +
    ready.map(i => '<tr><td>' + i.invoiceId + '</td><td>' + i.gencoName + '</td><td>' + i.billingPeriod +
    '</td><td class="money">₦' + fmt(i.totalAmount) + '</td><td><span class="status status-' + i.status + '">' +
    i.status + '</span></td><td>' +
    '<button class="btn btn-primary btn-sm" onclick="postAction(\\'' + i.invoiceId + '\\')">Post to Journal</button></td></tr>'
    ).join('') + '</tbody></table>';
}

async function postAction(id) {
  const postedBy = prompt('Posted by (your name):');
  if (postedBy === null) return;
  const narration = prompt('Narration (optional):');
  const res = await api('/api/post', { invoiceId: id, postedBy, narration: narration || '' });
  if (res.error) { showAlert(res.error, 'error'); return; }
  let html = '<h3>Journal Entry: ' + res.entryId + '</h3>' +
    '<p><strong>GenCo:</strong> ' + res.gencoName + ' | <strong>Period:</strong> ' + res.billingPeriod + '</p>' +
    '<p><strong>Posted by:</strong> ' + res.postedBy + ' at ' + new Date(res.postingDate).toLocaleString() + '</p>' +
    '<p><strong>Narration:</strong> ' + res.narration + '</p>' +
    '<div class="journal-lines"><table><thead><tr><th>Account</th><th>Code</th><th>Debit (₦)</th><th>Credit (₦)</th><th>Description</th></tr></thead><tbody>' +
    res.lines.map(l => '<tr><td>' + l.account + '</td><td>' + l.accountCode + '</td><td class="money">' +
    (l.debit > 0 ? fmt(l.debit) : '-') + '</td><td class="money">' + (l.credit > 0 ? fmt(l.credit) : '-') +
    '</td><td>' + l.description + '</td></tr>').join('') +
    '<tr class="total-row"><td colspan="2">TOTAL</td><td class="money">' + fmt(res.totalDebit) +
    '</td><td class="money">' + fmt(res.totalCredit) + '</td><td>' +
    (res.balanced ? '<span class="variance-ok">Balanced</span>' : '<span class="variance-bad">UNBALANCED</span>') +
    '</td></tr></tbody></table></div>';
  document.getElementById('modal-content').innerHTML = '<button class="close-btn" onclick="closeModal()">&times;</button>' + html;
  document.getElementById('modal').classList.remove('hidden');
  loadJournal();
}

async function loadAll() {
  const res = await fetch('/api/invoices');
  const invoices = await res.json();
  const div = document.getElementById('all-list');
  if (!invoices.length) { div.innerHTML = '<p style="color:#666">No invoices yet.</p>'; return; }
  div.innerHTML = '<table><thead><tr><th>Invoice ID</th><th>GenCo</th><th>Inv #</th><th>Period</th>' +
    '<th>Amount</th><th>Method</th><th>Received</th><th>Status</th><th></th></tr></thead><tbody>' +
    invoices.map(i => '<tr><td>' + i.invoiceId + '</td><td>' + i.gencoName + '</td><td>' + i.invoiceNumber +
    '</td><td>' + i.billingPeriod + '</td><td class="money">₦' + fmt(i.totalAmount) +
    '</td><td>' + i.deliveryMethod + '</td><td>' + new Date(i.receiptDate).toLocaleString() +
    '</td><td><span class="status status-' + i.status + '">' + i.status + '</span></td>' +
    '<td><button class="btn btn-secondary btn-sm" onclick="showDetail(\\'' + i.invoiceId + '\\')">View</button></td></tr>'
    ).join('') + '</tbody></table>';
}

async function loadExpected() {
  const res = await fetch('/api/expected');
  const bills = await res.json();
  const div = document.getElementById('expected-list');
  if (!bills.length) { div.innerHTML = '<p style="color:#666">No expected bills loaded. Import an Excel file above.</p>'; return; }
  div.innerHTML = '<table><thead><tr><th>GenCo</th><th>Period</th><th>Expected Amount</th>' +
    '<th>Energy (MWh)</th><th>Capacity (MW)</th><th>Tariff</th></tr></thead><tbody>' +
    bills.map(b => '<tr><td>' + b.gencoName + '</td><td>' + b.billingPeriod +
    '</td><td class="money">₦' + fmt(b.expectedAmount) + '</td><td>' + fmt(b.energyMWh) +
    '</td><td>' + fmt(b.capacityMW) + '</td><td>' + fmt(b.tariffRate) + '</td></tr>'
    ).join('') + '</tbody></table>';
}

async function showDetail(id) {
  const res = await fetch('/api/invoices');
  const invoices = await res.json();
  const i = invoices.find(inv => inv.invoiceId === id);
  if (!i) return;
  let html = '<button class="close-btn" onclick="closeModal()">&times;</button>' +
    '<h2>' + i.invoiceId + '</h2>' +
    '<div class="form-grid" style="font-size:14px;">' +
    '<div><strong>GenCo:</strong> ' + i.gencoName + '</div>' +
    '<div><strong>Invoice #:</strong> ' + i.invoiceNumber + '</div>' +
    '<div><strong>Invoice Date:</strong> ' + i.invoiceDate + '</div>' +
    '<div><strong>Billing Period:</strong> ' + i.billingPeriod + '</div>' +
    '<div><strong>Receipt Date:</strong> ' + new Date(i.receiptDate).toLocaleString() + '</div>' +
    '<div><strong>Receipt Time:</strong> ' + i.receiptTime + '</div>' +
    '<div><strong>Delivery Method:</strong> ' + i.deliveryMethod + '</div>' +
    '<div><strong>Delivery Details:</strong> ' + (i.deliveryDetails || '-') + '</div>' +
    '<div><strong>Energy:</strong> ' + fmt(i.energyMWh) + ' MWh</div>' +
    '<div><strong>Capacity:</strong> ' + fmt(i.capacityMW) + ' MW</div>' +
    '<div><strong>Energy Charge:</strong> ₦' + fmt(i.energyCharge) + '</div>' +
    '<div><strong>Capacity Charge:</strong> ₦' + fmt(i.capacityCharge) + '</div>' +
    '<div><strong>Startup Cost:</strong> ₦' + fmt(i.startupCost) + '</div>' +
    '<div><strong>Other Charges:</strong> ₦' + fmt(i.otherCharges) + '</div>' +
    '<div><strong>Total Amount:</strong> ₦' + fmt(i.totalAmount) + '</div>' +
    '<div><strong>Status:</strong> <span class="status status-' + i.status + '">' + i.status + '</span></div>' +
    '</div>';
  if (i.reviewedBy) {
    html += '<hr style="margin:16px 0"><div><strong>Reviewed by:</strong> ' + i.reviewedBy +
      ' at ' + new Date(i.reviewedAt).toLocaleString() + '</div>' +
      '<div><strong>Review Notes:</strong> ' + (i.reviewNotes || '-') + '</div>';
  }
  if (i.comparisonResult) {
    const c = i.comparisonResult;
    html += '<hr style="margin:16px 0"><h3>Comparison</h3><div class="comparison-box">' +
      '<div class="comparison-row"><span class="label">Expected:</span><span>₦' + (c.expectedAmount !== null ? fmt(c.expectedAmount) : 'N/A') + '</span></div>' +
      '<div class="comparison-row"><span class="label">Variance:</span><span class="' + (c.matched ? 'variance-ok' : 'variance-bad') + '">' +
      (c.variance !== null ? '₦' + fmt(c.variance) + ' (' + c.variancePercent + '%)' : c.reason) + '</span></div></div>';
  }
  if (i.journalEntryId) {
    html += '<hr style="margin:16px 0"><div><strong>Journal Entry:</strong> ' + i.journalEntryId + '</div>';
  }
  document.getElementById('modal-content').innerHTML = html;
  document.getElementById('modal').classList.remove('hidden');
}

function closeModal() { document.getElementById('modal').classList.add('hidden'); }

async function importExpected() {
  const fp = document.getElementById('expectedFilePath').value;
  if (!fp) { showAlert('Enter file path', 'error'); return; }
  const res = await api('/api/import-expected', { filePath: fp });
  if (res.error) { showAlert(res.error, 'error'); return; }
  showAlert('Imported ' + res.count + ' expected bill records', 'success');
  loadExpected();
}

document.querySelector('.nav').addEventListener('click', function(e) {
  const btn = e.target.closest('button[data-tab]');
  if (!btn) return;
  showTab(btn.dataset.tab, btn);
});
</script>
</body>
</html>`;

function parseBody(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', chunk => body += chunk);
    req.on('end', () => {
      try { resolve(JSON.parse(body)); } catch { resolve({}); }
    });
  });
}

const server = http.createServer(async (req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') { res.writeHead(200); res.end(); return; }

  try {
    if (req.url === '/' && req.method === 'GET') {
      res.writeHead(200, { 'Content-Type': 'text/html' });
      res.end(HTML);
      return;
    }

    if (req.url === '/api/invoices' && req.method === 'GET') {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(loadJSON(INVOICES_FILE)));
      return;
    }

    if (req.url === '/api/expected' && req.method === 'GET') {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(loadJSON(EXPECTED_BILLS_FILE)));
      return;
    }

    if (req.url === '/api/journal' && req.method === 'GET') {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(loadJSON(JOURNAL_FILE)));
      return;
    }

    if (req.url === '/api/receive' && req.method === 'POST') {
      const data = await parseBody(req);
      const invoice = receiveInvoice(data);
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(invoice));
      return;
    }

    if (req.url === '/api/review' && req.method === 'POST') {
      const data = await parseBody(req);
      const invoice = reviewInvoice(data.invoiceId, data);
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(invoice));
      return;
    }

    if (req.url === '/api/compare' && req.method === 'POST') {
      const data = await parseBody(req);
      const result = compareWithExpected(data.invoiceId);
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(result));
      return;
    }

    if (req.url === '/api/post' && req.method === 'POST') {
      const data = await parseBody(req);
      const entry = postToJournal(data.invoiceId, data);
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(entry));
      return;
    }

    if (req.url === '/api/import-expected' && req.method === 'POST') {
      const data = await parseBody(req);
      const bills = importExpectedBills(data.filePath);
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ count: bills.length, bills }));
      return;
    }

    res.writeHead(404);
    res.end('Not found');
  } catch (err) {
    res.writeHead(500, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: err.message }));
  }
});

const PORT = 3500;
server.listen(PORT, () => {
  console.log(`NBET GenCo Invoice Processing running at http://localhost:${PORT}`);
});
