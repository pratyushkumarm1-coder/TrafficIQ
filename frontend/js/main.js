const API = 'http://localhost:8000';

const RISK_META = {
    LOW:      { cls: 'ok',     color: '#34d399', pct: 10 },
    MODERATE: { cls: 'warn',   color: '#fbbf24', pct: 38 },
    HIGH:     { cls: 'orange', color: '#fb923c', pct: 66 },
    SEVERE:   { cls: 'danger', color: '#f87171', pct: 95 }
};
const STATUS_META = {
    Normal:    { cls: 'ok' },
    Heavy:     { cls: 'warn' },
    Congested: { cls: 'danger' }
};

Chart.defaults.font.family = "'Inter', sans-serif";
Chart.defaults.color = '#8b93a7';
Chart.defaults.borderColor = 'rgba(255,255,255,.06)';

document.addEventListener('DOMContentLoaded', function () {

    /* ---------- charts ---------- */
    const MAX_POINTS = 120;
    const volumeData = {
        labels: [],
        datasets: [{
            label: 'Vehicles',
            data: [],
            borderColor: '#22d3ee',
            backgroundColor: 'rgba(34, 211, 238, .12)',
            fill: true,
            tension: .35,
            pointRadius: 0,
            borderWidth: 2
        }]
    };
    const volumeChart = new Chart(document.getElementById('volumeChart'), {
        type: 'line',
        data: volumeData,
        options: {
            responsive: true,
            animation: false,
            plugins: { legend: { display: false } },
            scales: {
                x: { ticks: { display: false }, grid: { display: false } },
                y: { beginAtZero: true, suggestedMax: 20, ticks: { precision: 0 } }
            }
        }
    });

    const typesChart = new Chart(document.getElementById('vehicleTypesChart'), {
        type: 'doughnut',
        data: {
            labels: ['Cars', 'Motorcycles', 'Buses', 'Trucks'],
            datasets: [{
                data: [0, 0, 0, 0],
                backgroundColor: ['#22d3ee', '#fbbf24', '#34d399', '#f87171'],
                borderColor: '#111827',
                borderWidth: 3
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '62%',
            plugins: { legend: { position: 'bottom', labels: { usePointStyle: true, boxWidth: 8 } } }
        }
    });

    /* ---------- map ---------- */
    const map = L.map('osmMap').setView([20.5005, 85.868], 13);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; OpenStreetMap contributors'
    }).addTo(map);

    const nodeMarkers = {};

    async function fetchMapNodes() {
        try {
            const res = await fetch(`${API}/map/nodes`);
            if (!res.ok) return;
            const data = await res.json();

            data.nodes.forEach(node => {
                const popup = `
                    <strong>${node.name}</strong><br>
                    ${node.live
                        ? '<span style="color:#22d3ee;font-weight:700">● LIVE</span>'
                        : '<span style="color:#8b93a7">○ simulated</span>'}
                    <span style="color:${node.color};font-weight:700">&nbsp;${node.risk_level}</span><br>
                    Vehicles: ${node.vehicle_count} &nbsp;|&nbsp; Speed: ${node.average_speed} km/h<br>
                    Status: ${node.traffic_status}<br>
                    <span style="color:#8b93a7">${node.advisory || ''}</span>`;

                if (nodeMarkers[node.id]) {
                    const m = nodeMarkers[node.id];
                    m.setStyle({ fillColor: node.color, color: node.color });
                    m.setPopupContent(popup);
                } else {
                    nodeMarkers[node.id] = L.circleMarker([node.lat, node.lng], {
                        radius: 11,
                        color: node.color,
                        weight: 2,
                        fillColor: node.color,
                        fillOpacity: .8
                    }).addTo(map).bindPopup(popup).bindTooltip(node.name);
                }
            });

            document.getElementById('mapUpdated').textContent =
                'updated ' + new Date().toLocaleTimeString();
        } catch (e) {
            setConnection(false);
        }
    }

    /* ---------- stats polling ---------- */
    let volumeTick = 0;

    function setConnection(ok) {
        const pill = document.getElementById('connPill');
        pill.className = 'conn-pill ' + (ok ? 'online' : 'offline');
        pill.innerHTML = `<span class="dot"></span>${ok ? 'Connected' : 'Disconnected'}`;
    }

    async function fetchStats() {
        try {
            const res = await fetch(`${API}/stats`);
            if (!res.ok) throw new Error('bad status');
            const d = await res.json();
            setConnection(true);

            document.getElementById('kpiVehicles').textContent = d.vehicle_count;
            document.getElementById('kpiSpeed').textContent = d.average_speed;

            const sMeta = STATUS_META[d.traffic_status] || STATUS_META.Normal;
            const statusEl = document.getElementById('kpiStatus');
            statusEl.textContent = d.traffic_status.toUpperCase();
            statusEl.className = 'status-badge ' + sMeta.cls;

            const rMeta = RISK_META[d.traffic_risk.level] || RISK_META.LOW;
            const riskEl = document.getElementById('kpiRisk');
            riskEl.textContent = d.traffic_risk.level;
            riskEl.className = 'status-badge ' + rMeta.cls;

            const big = document.getElementById('riskLevelBig');
            big.textContent = d.traffic_risk.level;
            big.style.color = rMeta.color;

            const fill = document.getElementById('riskMeterFill');
            fill.style.width = rMeta.pct + '%';
            fill.style.background = rMeta.color;

            document.getElementById('riskAdvisory').textContent = d.traffic_risk.advisory;
            document.getElementById('riskBreakdown').innerHTML =
                `risk score <b style="color:${rMeta.color}">${d.traffic_risk.score}</b>` +
                ` · traffic ${d.traffic_risk.traffic_points}` +
                ` · weather ${d.traffic_risk.weather_points}` +
                ` (${d.traffic_risk.weather_label})`;

            const banner = document.getElementById('riskBanner');
            if (['HIGH', 'SEVERE'].includes(d.traffic_risk.level)) {
                banner.classList.remove('d-none');
                document.getElementById('riskBannerText').textContent =
                    `${d.traffic_risk.level} RISK — ${d.traffic_risk.advisory}`;
            } else {
                banner.classList.add('d-none');
            }

            const w = d.weather;
            const iconEl = document.getElementById('weatherIcon');
            if (w && w.available) {
                document.getElementById('kpiCity').textContent = w.city;
                document.getElementById('kpiTemp').textContent = w.temperature_c;
                document.getElementById('kpiWeatherDesc').textContent = w.description;
                iconEl.src = `https://openweathermap.org/img/wn/${w.icon}@2x.png`;
                iconEl.style.display = 'inline-block';
                document.getElementById('wdHumidity').textContent = w.humidity_pct + ' %';
                document.getElementById('wdWind').textContent = w.wind_kmh + ' km/h';
                document.getElementById('wdFeels').textContent = w.feels_like_c + ' °C';
            } else {
                document.getElementById('kpiWeatherDesc').textContent = 'unavailable';
                document.getElementById('wdHumidity').textContent = '--';
                document.getElementById('wdWind').textContent = '--';
                document.getElementById('wdFeels').textContent = '--';
            }

            typesChart.data.datasets[0].data = [
                d.vehicle_types.Car,
                d.vehicle_types.Motorcycle,
                d.vehicle_types.Bus,
                d.vehicle_types.Truck
            ];
            typesChart.update('none');

            volumeTick++;
            if (volumeTick % 2 === 0) {
                const now = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
                volumeData.labels.push(now);
                volumeData.datasets[0].data.push(d.vehicle_count);
                if (volumeData.labels.length > MAX_POINTS) {
                    volumeData.labels.shift();
                    volumeData.datasets[0].data.shift();
                }
                volumeChart.update('none');
            }
        } catch (e) {
            setConnection(false);
        }
    }

    /* ---------- clock ---------- */
    function tickClock() {
        document.getElementById('clock').textContent =
            new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    }

    tickClock();
    setInterval(tickClock, 1000);
    fetchStats();
    setInterval(fetchStats, 1000);
    fetchMapNodes();
    setInterval(fetchMapNodes, 3000);
});
