/* VisionAiry2 price loader — vanilla JS, no framework */

function formatVolume(n) {
  if (!n && n !== 0) return '—';
  if (n >= 1e9) return (n / 1e9).toFixed(1) + 'B';
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(0) + 'K';
  return n.toFixed(0);
}

function formatMarketCap(n) {
  if (!n && n !== 0) return '—';
  if (n >= 1e12) return '$' + (n / 1e12).toFixed(2) + 'T';
  if (n >= 1e9) return '$' + (n / 1e9).toFixed(1) + 'B';
  if (n >= 1e6) return '$' + (n / 1e6).toFixed(1) + 'M';
  return '$' + n.toLocaleString();
}

function formatChange(value, pct) {
  if (value == null || pct == null) return '—';
  const sign = pct >= 0 ? '+' : '';
  return sign + value.toFixed(2) + ' (' + sign + pct.toFixed(2) + '%)';
}

window.formatMarketCap = formatMarketCap;
window.formatVolume = formatVolume;
window.formatChange = formatChange;

async function loadPrice(ticker, prefix) {
  try {
    const resp = await fetch('/api/price/' + encodeURIComponent(ticker));
    if (!resp.ok) return;
    const data = await resp.json();
    _applySnapshot(ticker, prefix, data);
  } catch (e) {
    // silent — live price is optional
  }
}

async function loadPriceBulk(tickers) {
  if (!tickers || !tickers.length) return {};
  try {
    const resp = await fetch('/api/prices', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({tickers: tickers})
    });
    if (!resp.ok) return {};
    return await resp.json();
  } catch (e) {
    return {};
  }
}

function _applySnapshot(ticker, prefix, data) {
  if (!data) return;
  const $ = (id) => document.getElementById(id);

  const priceEl = $(prefix + '-price-' + ticker);
  const changeEl = $(prefix + '-change-' + ticker);
  const volEl = $(prefix + '-vol-' + ticker);
  const avgVolEl = $(prefix + '-avgvol-' + ticker);
  const mcapEl = $(prefix + '-mcap-' + ticker);
  const markerEl = $(prefix + '-52w-marker-' + ticker);

  if (priceEl && data.current_price != null) {
    priceEl.textContent = '$' + data.current_price.toFixed(2);
  }
  if (changeEl && data.day_change != null) {
    const chg = formatChange(data.day_change, data.day_change_pct);
    changeEl.textContent = chg;
    const pct = data.day_change_pct || 0;
    changeEl.className = changeEl.className.replace(/text-\w+[-\d]*/, '')
      + (pct >= 0 ? ' text-emerald-600' : ' text-rose-600');
  }
  if (volEl && data.day_volume != null) {
    volEl.textContent = formatVolume(data.day_volume);
  }
  if (avgVolEl && data.average_volume != null) {
    avgVolEl.textContent = formatVolume(data.average_volume);
  }
  if (mcapEl && data.market_cap != null) {
    mcapEl.textContent = formatMarketCap(data.market_cap);
    const sub = mcapEl.nextElementSibling;
    if (sub) sub.textContent = 'Live';
  }
  if (markerEl && data.current_price != null && data.fifty_two_week_high && data.fifty_two_week_low) {
    const range = data.fifty_two_week_high - data.fifty_two_week_low;
    if (range > 0) {
      const pct = Math.min(100, Math.max(0, (data.current_price - data.fifty_two_week_low) / range * 100));
      markerEl.style.left = pct.toFixed(1) + '%';
    }
  }
}
