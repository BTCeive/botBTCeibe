// Configuración
const STATE_URL = '/shared/state.json';
const BITACORA_URL = '/bitacora.txt';

// Variables de control de actualización
let lastSummaryUpdate = 0;
let lastSlotsUpdate = 0;
let lastOtherUpdate = 0;

const SUMMARY_INTERVAL = 60000; // 60 segundos
const SLOTS_INTERVAL = 5000;    // 5 segundos
const OTHER_INTERVAL = 30000;   // 30 segundos

// Cache local de radar para actualizaciones parciales
let radarCache = {};
function mergeRadarEntries(entries) {
    try {
        for (const e of entries) {
            const key = e.pair || (e.origin && e.destination ? `${e.origin}/${e.destination}` : JSON.stringify(e));
            radarCache[key] = Object.assign({}, radarCache[key] || {}, e);
        }
    } catch (err) {
        console.error('Error merging radar entries:', err);
    }
}
function getRadarList() {
    return Object.values(radarCache).sort((a,b) => (b.heat_score || 0) - (a.heat_score || 0));
}

// Funciones de utilidad
function formatCurrency(value) {
    return new Intl.NumberFormat('es-ES', {
        style: 'currency',
        currency: 'EUR',
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    }).format(value);
}

function formatNumber(value, decimals = 2) {
    if (value === null || value === undefined || isNaN(value)) return 'N/A';
    return new Intl.NumberFormat('es-ES', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals
    }).format(value);
}

function getStatusIcon(status) {
    const icons = {
        'safe': { icon: '🟢', color: '#00FF88' },
        'caution': { icon: '🟠', color: '#FF8844' },
        'unknown': { icon: '⚪', color: '#FFFFFF' }
    };
    return icons[status] || icons.unknown;
}

// Cargar estado desde el servidor
async function loadState() {
    try {
        let response = await fetch(STATE_URL + '?t=' + Date.now());
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        let text = await response.text();
        // Si el motor está escribiendo el JSON, puede estar momentáneamente incompleto.
        // Intentar parsear con reintentos cortos.
        let data = null;
        const maxRetries = 3;
        for (let attempt = 0; attempt < maxRetries; attempt++) {
            try {
                data = JSON.parse(text);
                break;
            } catch (err) {
                if (attempt === maxRetries - 1) throw err;
                // Esperar un poco y volver a obtener el archivo (re-intentar)
                await new Promise(r => setTimeout(r, 100 * (attempt + 1)));
                response = await fetch(STATE_URL + '?t=' + Date.now());
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                text = await response.text();
            }
        }
        return data;
    } catch (error) {
        console.error('Error cargando estado:', error);
        showError('No se pudo cargar el estado. Verifica que el motor esté ejecutándose.');
        return null;
    }
} 

// Cargar bitácora
async function loadBitacora() {
    try {
        const response = await fetch(BITACORA_URL + '?t=' + Date.now());
        if (!response.ok) return [];
        const text = await response.text();
        return text.split('\n').filter(line => line.trim()).slice(-50);
    } catch (error) {
        console.error('Error cargando bitácora:', error);
        return [];
    }
}

function showError(message) {
    const errorDiv = document.getElementById('error');
    errorDiv.textContent = message;
    errorDiv.style.display = 'block';
    document.getElementById('dashboard').style.display = 'none';
    document.getElementById('loading').style.display = 'none';
}

// Renderizar resumen general (actualiza cada 60 seg)
function renderSummary(state) {
    const now = Date.now();
    if (now - lastSummaryUpdate < SUMMARY_INTERVAL && lastSummaryUpdate > 0) {
        return; // No actualizar si pasaron menos de 60 segundos
    }
    lastSummaryUpdate = now;

    try {
        const balances = state.balances?.total || {};
        const treasury = state.treasury || {};
        const prices = state.prices || {};
        const marketStatus = state.market_status || {};
        
        // Obtener precios
        const btcPrice = prices.btc_price || 0;
        let bnbPrice = prices.bnb_price || 0;
        
        // Obtener gas BNB
        const gasBnb = state.gas_bnb || {};
        const bnbBalance = gasBnb.amount || balances.BNB || 0;
        let gasBnbEur = gasBnb.value_eur || 0;
        
        // Si bnb_price no está disponible en prices, calcularlo desde gas_bnb
        if (!bnbPrice || bnbPrice <= 0) {
            if (bnbBalance > 0 && gasBnbEur > 0) {
                bnbPrice = gasBnbEur / bnbBalance;
            }
        }
        
        // Si aún no tenemos gasBnbEur pero tenemos precio y balance, calcularlo
        if (gasBnbEur <= 0 && bnbPrice > 0 && bnbBalance > 0) {
            gasBnbEur = bnbBalance * bnbPrice;
        }
        
        // Asegurar que usamos el valor de gasBnb si está disponible
        if (gasBnb.value_eur && gasBnb.value_eur > 0) {
            gasBnbEur = gasBnb.value_eur;
        }
        
        // Fondos sin invertir (free_cash_eur ya excluye treasury)
        const freeCashEur = state.free_cash_eur || 0;
        
        // Calcular inversión: suma de initial_fiat_value de todos los trades activos
        let inversionEur = 0.0;
        const openTrades = state.open_trades || [];
        for (const trade of openTrades) {
            if (trade.initial_fiat_value) {
                inversionEur += trade.initial_fiat_value;
            }
        }
        
        // Fondos totales: sin invertir + invertidos + gas BNB
        const fondosTotales = freeCashEur + inversionEur + gasBnbEur;
        
        // Depósito (Hucha): Treasury EUR + BTC
        const treasuryEur = treasury.total_eur || 0;
        const treasuryBtc = treasury.total_btc || 0;
        const depositoEur = treasuryEur;
        const depositoBtcValue = treasuryBtc * btcPrice;
        const depositoTotalEur = depositoEur + depositoBtcValue;
        
        // Estado: solo icono + % de cambio BTC
        const status = getStatusIcon(marketStatus.status || 'unknown');
        const btcChange = marketStatus.btc_change;
        const btcChangeStr = btcChange !== null && btcChange !== undefined 
            ? `${btcChange >= 0 ? '+' : ''}${btcChange.toFixed(2)}%`
            : 'N/A';
        
        // Forzar casts numéricos y sincronización total de capital (EUR + USDC + USDT + Criptos + BNB)
        const safeFondos = Number(fondosTotales) || 0;
        const safeDeposito = Number(depositoTotalEur) || 0;

        const html = `
            <div class="metric-box">
                <h4>Fondos</h4>
                <div class="value">${formatCurrency(safeFondos)}</div>
            </div>
            <div class="metric-box">
                <h4>Inversión</h4>
                <div class="value">${formatCurrency(inversionEur)}</div>
            </div>
            <div class="metric-box">
                <h4>Depósito</h4>
                <div class="value">${formatCurrency(depositoTotalEur)}</div>
                <div class="subvalue">${formatNumber(treasuryBtc, 8)} BTC</div>
                <div class="subvalue">${btcPrice > 0 ? formatNumber(btcPrice, 2) + '€' : 'N/A'} BTC/EUR</div>
            </div>
            <div class="metric-box">
                <h4>Gas</h4>
                <div class="value">${formatCurrency(gasBnbEur)}</div>
                <div class="subvalue">${formatNumber(bnbBalance, 4)} BNB</div>
                <div class="subvalue">${bnbPrice > 0 ? formatNumber(bnbPrice, 2) + '€' : 'N/A'} BNB/EUR</div>
            </div>
            <div class="metric-box">
                <div class="status-indicator" style="color: ${status.color}; font-size: 2em; text-align: center;">${status.icon}</div>
                <div class="subvalue" style="margin-top: 5px; text-align: center;">${btcChangeStr}</div>
            </div>
        `;

        document.getElementById('summary-metrics').innerHTML = html;

        // Actualizar footer con leyenda dinámica (Heat + GAS thresholds)
        try {
            const gasThresholds = state.strategy?.gas_thresholds || { passive:5, strategic:2, emergency:1 };
            const heatWeights = state.strategy?.heat_weights || { rsi:40, ema:30, vol:20, bonus:10 };
            const footerEl = document.getElementById('dashboard-footer');
            if (footerEl) {
                footerEl.innerHTML = `<strong>Info Heat:</strong> RSI (${heatWeights.rsi}%) | EMA (${heatWeights.ema}%) | VOL (${heatWeights.vol}%) | Bonus (${heatWeights.bonus}%) &nbsp;&nbsp; <strong>GAS:</strong> Pasivo (&lt;${gasThresholds.passive}%) | Estratégico (&lt;${gasThresholds.strategic}%) | Emergencia (&lt;${gasThresholds.emergency}%)`;
            }
        } catch (err) {
            console.debug('No se pudo actualizar footer dinámico:', err);
        }
    } catch (error) {
        console.error('Error renderizando resumen:', error);
    }
}

// Renderizar slots (actualiza cada 5 seg)
function renderSlots(state) {
    const now = Date.now();
    if (now - lastSlotsUpdate < SLOTS_INTERVAL && lastSlotsUpdate > 0) {
        return; // No actualizar si pasaron menos de 5 segundos
    }
    lastSlotsUpdate = now;

    try {
        const openTrades = state.open_trades || [];
        const prices = state.prices || {};
        
        let html = '';
        for (let i = 0; i < 4; i++) {
            const trade = openTrades.find(t => t.slot_id === i);
            if (trade) {
                const entryPrice = trade.entry_price || 0;
                const amount = trade.amount || 0;
                
                // Formatear fecha/hora
                let fecha = 'N/A';
                if (trade.created_at) {
                    try {
                        // Manejar formato con y sin milisegundos
                        let dateStr = trade.created_at;
                        if (!dateStr.includes('T') && !dateStr.includes('Z')) {
                            // Formato: "2025-12-23 13:51:55"
                            dateStr = dateStr.replace(' ', 'T');
                        }
                        const date = new Date(dateStr);
                        fecha = date.toLocaleString('es-ES', {
                            day: '2-digit',
                            month: '2-digit',
                            hour: '2-digit',
                            minute: '2-digit'
                        });
                    } catch (e) {
                        console.error('Error parseando fecha:', e);
                    }
                }
                
                const initialValueEur = trade.initial_fiat_value || 0;
                
                // Obtener valor actual (calculado en el backend)
                const currentValueEur = trade.current_value_eur !== undefined && trade.current_value_eur !== null
                    ? trade.current_value_eur
                    : initialValueEur; // Fallback al valor inicial si no está disponible
                
                // Calcular P/L porcentual basado en valores en EUR
                const pnlPercent = initialValueEur > 0
                    ? ((currentValueEur - initialValueEur) / initialValueEur) * 100
                    : 0;
                const pnlClass = pnlPercent > 0 ? 'positive' : pnlPercent < 0 ? 'negative' : 'neutral';
                
                // Clase para valor actual (verde si ganancia, rojo si pérdida)
                const currentValueClass = currentValueEur >= initialValueEur ? 'positive' : 'negative';
                
                // Determinar decimales según el activo
                const decimals = trade.target_asset === 'BTC' ? 8 : 
                               (trade.target_asset === 'BNB' || trade.target_asset === 'ETH') ? 4 : 2;
                
                html += `
                    <div class="slot-box active">
                        <h3>Slot ${i + 1} - ${fecha}</h3>
                        <p><strong>${trade.target_asset}</strong> - ${trade.base_asset}</p>
                        <p>Valor inicial: ${formatCurrency(initialValueEur)}</p>
                        <p class="${currentValueClass}">Valor actual: ${formatCurrency(currentValueEur)}</p>
                        <p>Cantidad: ${formatNumber(amount, decimals)}</p>
                        <p class="${pnlClass}" style="font-size: 1.2em; font-weight: bold; margin-top: 10px;">
                            ${pnlPercent >= 0 ? '+' : ''}${formatNumber(pnlPercent, 2)}%
                        </p>
                    </div>
                `;
            } else {
                html += `
                    <div class="slot-box inactive">
                        <h3>Slot ${i + 1}</h3>
                        <p>Vacío</p>
                    </div>
                `;
            }
        }
        
        document.getElementById('slots-container').innerHTML = html;
    } catch (error) {
        console.error('Error renderizando slots:', error);
    }
}

// Renderizar slots a partir de un evento (sin necesidad de state completo)
function renderSlotsFromEvent(payload) {
    try {
        const openTrades = payload.open_trades || [];
        let html = '';
        for (let i = 0; i < 4; i++) {
            const trade = openTrades.find(t => t.slot_id === i);
            if (trade) {
                const entryPrice = trade.entry_price || 0;
                const amount = trade.amount || 0;
                // Formatear fecha/hora
                let fecha = 'N/A';
                if (trade.created_at) {
                    try {
                        let dateStr = trade.created_at;
                        if (!dateStr.includes('T') && !dateStr.includes('Z')) dateStr = dateStr.replace(' ', 'T');
                        const date = new Date(dateStr);
                        fecha = date.toLocaleString('es-ES', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
                    } catch (e) { /* ignore */ }
                }
                const initialValueEur = trade.initial_fiat_value || 0;
                const currentValueEur = trade.current_value_eur !== undefined && trade.current_value_eur !== null ? trade.current_value_eur : initialValueEur;
                const pnlPercent = initialValueEur > 0 ? ((currentValueEur - initialValueEur) / initialValueEur) * 100 : 0;
                const pnlClass = pnlPercent > 0 ? 'positive' : pnlPercent < 0 ? 'negative' : 'neutral';
                const currentValueClass = currentValueEur >= initialValueEur ? 'positive' : 'negative';
                const decimals = trade.target_asset === 'BTC' ? 8 : (trade.target_asset === 'BNB' || trade.target_asset === 'ETH') ? 4 : 2;
                html += `
                    <div class="slot-box active">
                        <h3>Slot ${i + 1} - ${fecha}</h3>
                        <p><strong>${trade.target_asset}</strong> - ${trade.base_asset}</p>
                        <p>Valor inicial: ${formatCurrency(initialValueEur)}</p>
                        <p class="${currentValueClass}">Valor actual: ${formatCurrency(currentValueEur)}</p>
                        <p>Cantidad: ${formatNumber(amount, decimals)}</p>
                        <p class="${pnlClass}" style="font-size: 1.2em; font-weight: bold; margin-top: 10px;">${pnlPercent >= 0 ? '+' : ''}${formatNumber(pnlPercent, 2)}%</p>
                    </div>
                `;
            } else {
                html += `
                    <div class="slot-box inactive">
                        <h3>Slot ${i + 1}</h3>
                        <p>Vacío</p>
                    </div>
                `;
            }
        }
        document.getElementById('slots-container').innerHTML = html;
    } catch (error) {
        console.error('Error renderizando slots desde evento:', error);
    }
}

// Renderizar historial
async function renderHistorial() {
    try {
        const bitacora = await loadBitacora();
        const container = document.getElementById('historial-container');
        
        if (bitacora.length === 0) {
            container.innerHTML = '<div class="loading-small">No hay eventos en el historial</div>';
            return;
        }
        
        let html = '<div style="font-family: monospace; font-size: 0.9em;">';
        for (const line of bitacora) {
            html += `<div style="margin: 2px 0; padding: 2px 0;">${line}</div>`;
        }
        html += '</div>';
        
        container.innerHTML = html;
    } catch (error) {
        console.error('Error renderizando historial:', error);
    }
}

// Renderizar radar
function renderRadar(state) {
    try {
        // `state` puede ser el objeto completo (con radar_data) o un arreglo directo de items
        const radarData = Array.isArray(state) ? state : (state && state.radar_data ? state.radar_data : getRadarList());
        let html = '';
        
        if (!radarData || radarData.length === 0) {
            html = '<div class="radar-line">No hay datos del radar disponibles</div>';
        } else {
            // `radarData` ya debería venir ordenado, pero garantizar orden por heat_score
            const sorted = [...radarData].sort((a, b) => (b.heat_score || 0) - (a.heat_score || 0));

            // Respetar toggle 'ver todos'
            const showAll = window._RADAR_SHOW_ALL === true;
            // Mostrar top 30 por defecto
            const list = showAll ? sorted : sorted.slice(0, 30);

            // Professional table HTML
            html = '<div style="background: #0E1117; border-radius: 8px; overflow: hidden; max-height: 500px; overflow-y: auto;">';
            html += '<table style="width: 100%; border-collapse: collapse; color: white;">';
            html += '<thead><tr style="background: rgba(255,255,255,0.05); border-bottom: 1px solid rgba(255,255,255,0.1);">';
            html += '<th style="padding: 12px; text-align: left; font-weight: 600; color: #888; font-size: 0.85em; text-transform: uppercase;">ACTIVO</th>';
            html += '<th style="padding: 12px; text-align: center; font-weight: 600; color: #888; font-size: 0.85em; text-transform: uppercase;">RSI</th>';
            html += '<th style="padding: 12px; text-align: center; font-weight: 600; color: #888; font-size: 0.85em; text-transform: uppercase;">DIST EMA</th>';
            html += '<th style="padding: 12px; text-align: center; font-weight: 600; color: #888; font-size: 0.85em; text-transform: uppercase;">VOLUMEN</th>';
            html += '<th style="padding: 12px; text-align: center; font-weight: 600; color: #888; font-size: 0.85em; text-transform: uppercase;">HEAT</th>';
            html += '</tr></thead><tbody>';

            for (const coin of list) {
                const heatScore = Number(coin.heat_score) || 0;
                const destination = coin.destination || coin.currency || coin.pair || 'N/A';
                
                const rsiVal = (coin.rsi !== undefined && coin.rsi !== null) ? Number(coin.rsi) : NaN;
                const emaVal = (coin.ema200_distance !== undefined && coin.ema200_distance !== null) ? Number(coin.ema200_distance) :
                               (coin.ema_distance !== undefined ? Number(coin.ema_distance) : NaN);
                const volVal = (coin.vol !== undefined && coin.vol !== null) ? Number(coin.vol) : NaN;

                const rsiStr = !isNaN(rsiVal) ? rsiVal.toFixed(1) : 'N/A';
                const emaStr = !isNaN(emaVal) && isFinite(emaVal) ? emaVal.toFixed(2) + '%' : 'N/A';
                const volStr = !isNaN(volVal) ? volVal.toFixed(2) : 'N/A';

                // LED color logic
                let ledColor = '#FFFFFF';
                if (heatScore >= 86) {
                    ledColor = '#00ffcc';  // Verde Brillante
                } else if (heatScore >= 71) {
                    ledColor = '#00FF88';  // Verde Claro
                } else if (heatScore >= 41) {
                    ledColor = '#FF8844';  // Naranja
                } else {
                    ledColor = '#FF4444';  // Rojo
                }
                
                // White LED if missing technical data
                if (rsiStr === 'N/A' || emaStr === 'N/A' || volStr === 'N/A') {
                    ledColor = '#FFFFFF';
                }

                html += `<tr style="border-bottom: 1px solid rgba(255,255,255,0.05);">`;
                html += `<td style="padding: 12px; color: white; font-weight: 600;">${destination}</td>`;
                html += `<td style="padding: 12px; text-align: center; color: white;">${rsiStr}</td>`;
                html += `<td style="padding: 12px; text-align: center; color: white;">${emaStr}</td>`;
                html += `<td style="padding: 12px; text-align: center; color: white;">${volStr}</td>`;
                html += `<td style="padding: 12px; text-align: center;"><span style="display: inline-block; width: 12px; height: 12px; border-radius: 50%; background: ${ledColor}; box-shadow: 0 0 8px ${ledColor}; margin-right: 8px;"></span><span style="color: white; font-weight: 700;">${heatScore}</span></td>`;
                html += `</tr>`;
            }

            html += '</tbody></table></div>';
        }
        
        if (html === '') {
            html = '<div style="padding: 20px; text-align: center; color: #888;">No hay datos del radar disponibles</div>';
        }
        document.getElementById('radar-container').innerHTML = html;
    } catch (error) {
        console.error('Error renderizando radar:', error);
    }
}

// Toggle para ver todos los items del radar
document.addEventListener('DOMContentLoaded', function() {
    window._RADAR_SHOW_ALL = false;
    const btn = document.getElementById('toggle-radar-all');
    if (btn) {
        btn.addEventListener('click', function() {
            window._RADAR_SHOW_ALL = !window._RADAR_SHOW_ALL;
            btn.textContent = window._RADAR_SHOW_ALL ? 'Ver top' : 'Ver todos';
            // Forzar re-render con contenido cacheado
            renderRadar(getRadarList());
        });
    }

    // Cargar estado inicial una vez
    loadState().then(state => {
        if (state) {
            // Inicializar cache con radar completo si viene
            if (state.radar_data && Array.isArray(state.radar_data)) mergeRadarEntries(state.radar_data);
            renderSummary(state);
            renderSlots(state);
            renderRadar(getRadarList());
            renderDistribution(state);
        }
    });

    // Inicializar EventSource (SSE) para recibir actualizaciones parciales
    if (window.EventSource) {
        const es = new EventSource('/stream');
        es.addEventListener('summary', e => {
            // Cuando llegue summary pedimos el estado completo para consistencia
            loadState().then(state => { if (state) renderSummary(state); });
        });
        es.addEventListener('slots', e => {
            try {
                const data = JSON.parse(e.data);
                renderSlotsFromEvent(data);
            } catch (err) { console.error('Error processing slots event', err); }
        });
        es.addEventListener('radar', e => {
            try {
                const data = JSON.parse(e.data);
                mergeRadarEntries(data.entries || []);
                renderRadar(getRadarList());
            } catch (err) { console.error('Error processing radar event', err); }
        });
        es.onerror = () => {
            console.warn('EventSource error, activando fallback de polling (cada 30s)');
            if (!window._RADAR_FALLBACK_INTERVAL) {
                window._RADAR_FALLBACK_INTERVAL = setInterval(() => {
                    loadState().then(state => {
                        if (state) { renderSummary(state); renderSlots(state); mergeRadarEntries(state.radar_data || []); renderRadar(getRadarList()); }
                    });
                }, 30000);
            }
        };
    } else {
        // Fallback para navegadores sin SSE
        console.warn('EventSource no soportado - usando polling cada 30s');
        setInterval(() => loadState().then(state => {
            if (state) { renderSummary(state); renderSlots(state); mergeRadarEntries(state.radar_data || []); renderRadar(getRadarList()); }
        }), 30000);
    }
});

// Variable global para el gráfico de distribución
let distributionChart = null;

// Renderizar distribución completa con gráfico de queso y tabla
function renderDistribution(state) {
    const now = Date.now();
    if (now - lastOtherUpdate < OTHER_INTERVAL && lastOtherUpdate > 0) {
        return; // No actualizar si pasaron menos de 30 segundos
    }
    lastOtherUpdate = now;

    try {
        const balances = state.balances?.total || {};
        const treasury = state.treasury || {};
        const prices = state.prices || {};
        const gasBnb = state.gas_bnb || {};
        
        // Obtener precios
        const btcPrice = prices.btc_price || 0;
        let bnbPrice = prices.bnb_price || 0;
        const ethPrice = prices.eth_price || 0;
        
        // Si bnb_price no está disponible, calcularlo desde gas_bnb
        if (!bnbPrice || bnbPrice <= 0) {
            const bnbBalance = gasBnb.amount || balances.BNB || 0;
            const gasBnbEur = gasBnb.value_eur || 0;
            if (bnbBalance > 0 && gasBnbEur > 0) {
                bnbPrice = gasBnbEur / bnbBalance;
            }
        }
        
        // Array para almacenar todos los activos con su información
        const distributionData = [];
        let totalValueEur = 0;
        
        // Función helper para obtener precio de un activo
        function getAssetPrice(asset) {
            if (asset === 'EUR' || asset === 'USDC') return 1.0;
            if (asset === 'BTC') return btcPrice;
            if (asset === 'BNB') return bnbPrice;
            if (asset === 'ETH') return ethPrice;
            // Para otros activos, intentar obtener precio desde open_trades
            const openTrades = state.open_trades || [];
            for (const trade of openTrades) {
                if (trade.target_asset === asset && trade.entry_price > 0) {
                    return trade.entry_price;
                }
            }
            // Si no encontramos precio, retornar 0 (se ignorará el activo)
            return 0;
        }
        
        // 1. Balances de wallet (excluyendo fiat y activos ya contabilizados)
        for (const [asset, amount] of Object.entries(balances)) {
            if (amount <= 0.0001) continue; // Ignorar balances muy pequeños
            
            // EUR y USDC se manejan juntos
            if (asset === 'EUR' || asset === 'USDC') {
                continue; // Se manejará después
            }
            
            const price = getAssetPrice(asset);
            if (price <= 0) continue; // Ignorar si no tenemos precio
            
            const valueEur = amount * price;
            if (valueEur < 0.01) continue; // Ignorar valores muy pequeños
            
            // Para BNB, si está en gas_bnb, no lo añadimos aquí (se añadirá como "BNB")
            if (asset === 'BNB' && gasBnb.amount && gasBnb.amount > 0) {
                // Solo añadir la diferencia si hay BNB adicional fuera del gas
                const bnbInGas = gasBnb.amount;
                if (amount <= bnbInGas) continue; // Todo el BNB está en gas
                // Hay BNB adicional fuera del gas
                const extraBnb = amount - bnbInGas;
                const extraBnbEur = extraBnb * price;
                if (extraBnbEur >= 0.01) {
                    distributionData.push({
                        name: asset,
                        amount: extraBnb,
                        valueEur: extraBnbEur,
                        price: price
                    });
                    totalValueEur += extraBnbEur;
                }
            } else {
                distributionData.push({
                    name: asset,
                    amount: amount,
                    valueEur: valueEur,
                    price: price
                });
                totalValueEur += valueEur;
            }
        }
        
        // 2. EUR/USDC (juntar ambos)
        const eurAmount = (balances.EUR || 0) + (balances.USDC || 0);
        if (eurAmount > 0.01) {
            distributionData.push({
                name: 'EUR',
                amount: eurAmount,
                valueEur: eurAmount,
                price: 1.0
            });
            totalValueEur += eurAmount;
        }
        
        // 3. Treasury (Depósito/Hucha) - EUR
        const treasuryEur = treasury.total_eur || 0;
        if (treasuryEur > 0.01) {
            distributionData.push({
                name: 'Depósito EUR',
                amount: treasuryEur,
                valueEur: treasuryEur,
                price: 1.0
            });
            totalValueEur += treasuryEur;
        }
        
        // 4. Treasury (Depósito/Hucha) - BTC
        const treasuryBtc = treasury.total_btc || 0;
        if (treasuryBtc > 0.00000001 && btcPrice > 0) {
            const treasuryBtcEur = treasuryBtc * btcPrice;
            if (treasuryBtcEur > 0.01) {
                distributionData.push({
                    name: 'Depósito BTC',
                    amount: treasuryBtc,
                    valueEur: treasuryBtcEur,
                    price: btcPrice
                });
                totalValueEur += treasuryBtcEur;
            }
        }
        
        // 5. Gas BNB (mostrar como BNB en la distribución)
        const gasBnbEur = gasBnb.value_eur || 0;
        const gasBnbAmount = gasBnb.amount || 0;
        if (gasBnbEur > 0.01 && gasBnbAmount > 0) {
            // Si no tenemos precio, calcularlo
            let gasBnbPrice = bnbPrice;
            if (!gasBnbPrice || gasBnbPrice <= 0) {
                gasBnbPrice = gasBnbEur / gasBnbAmount;
            }
            distributionData.push({
                name: 'BNB',
                amount: gasBnbAmount,
                valueEur: gasBnbEur,
                price: gasBnbPrice
            });
            totalValueEur += gasBnbEur;
        }
        
        // Si no hay datos, mostrar mensaje
        if (distributionData.length === 0 || totalValueEur <= 0) {
            document.getElementById('distribution-container').innerHTML = 
                '<div class="loading-small">No hay datos de distribución disponibles</div>';
            if (distributionChart) {
                distributionChart.destroy();
                distributionChart = null;
            }
            return;
        }
        
        // Calcular porcentajes y ordenar por %
        distributionData.forEach(item => {
            item.percentage = (item.valueEur / totalValueEur) * 100;
        });
        
        distributionData.sort((a, b) => b.percentage - a.percentage);
        
        // Crear gráfico de queso
        const chartCanvas = document.getElementById('distribution-chart');
        
        if (chartCanvas && typeof Chart !== 'undefined') {
            // Destruir gráfico anterior si existe
            if (distributionChart) {
                distributionChart.destroy();
            }
            
            // Colores para el gráfico (asignar un color a cada item)
            const colors = [
                '#00FF88', '#FF8844', '#4444FF', '#FF44FF', '#44FFFF',
                '#FFFF44', '#FF4444', '#8888FF', '#FF8888', '#88FF88',
                '#00AAFF', '#AA00FF', '#FFAA00', '#AAFF00', '#FF00AA'
            ];
            
            // Asignar colores a cada item de distribución
            distributionData.forEach((item, index) => {
                item.color = colors[index % colors.length];
            });
            
            const chartData = {
                labels: distributionData.map(item => item.name),
                datasets: [{
                    data: distributionData.map(item => item.valueEur),
                    backgroundColor: distributionData.map(item => item.color),
                    borderColor: '#0E1117',
                    borderWidth: 2
                }]
            };
            
            distributionChart = new Chart(chartCanvas, {
                type: 'pie',
                data: chartData,
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    aspectRatio: 1,
                    plugins: {
                        legend: {
                            display: false // Ocultar leyenda (la tabla la reemplaza)
                        },
                        tooltip: {
                            callbacks: {
                                label: function(context) {
                                    const label = context.label || '';
                                    const value = context.parsed || 0;
                                    const percentage = ((value / totalValueEur) * 100).toFixed(2);
                                    return `${label}: ${formatCurrency(value)} (${percentage}%)`;
                                }
                            }
                        }
                    }
                }
            });
        }
        
        // Crear tabla ordenada por % con colores de leyenda
        let tableHtml = '<table class="distribution-table">';
        tableHtml += '<thead><tr><th></th><th>%</th><th>Nombre</th><th>Valor (€)</th><th>Cantidad</th><th>Precio</th></tr></thead>';
        tableHtml += '<tbody>';
        
        for (const item of distributionData) {
            const decimals = item.name.includes('BTC') ? 8 : 
                           item.name.includes('BNB') ? 4 : 2;
            
            const colorStyle = item.color ? `background-color: ${item.color};` : '';
            
            tableHtml += `<tr>
                <td class="legend-color-cell"><span class="color-indicator" style="${colorStyle}"></span></td>
                <td class="percentage-cell">${formatNumber(item.percentage, 2)}%</td>
                <td class="name-cell">${item.name}</td>
                <td class="value-cell">${formatCurrency(item.valueEur)}</td>
                <td class="amount-cell">${formatNumber(item.amount, decimals)}</td>
                <td class="price-cell">${formatCurrency(item.price)}</td>
            </tr>`;
        }
        
        tableHtml += '</tbody></table>';
        
        // Actualizar contenedor de tabla
        document.getElementById('distribution-table-container').innerHTML = tableHtml;
        
    } catch (error) {
        console.error('Error renderizando distribución:', error);
        document.getElementById('distribution-container').innerHTML = 
            `<div class="error">Error cargando distribución: ${error.message}</div>`;
        if (distributionChart) {
            distributionChart.destroy();
            distributionChart = null;
        }
    }
}


// Función principal de actualización
async function updateDashboard() {
    try {
        const state = await loadState();
        if (!state) {
            const loadingEl = document.getElementById('loading');
            if (loadingEl) {
                loadingEl.textContent = 'Esperando datos del bot...';
                loadingEl.style.display = 'block';
            }
            return;
        }

        // Siempre mostrar el dashboard, incluso si está inicializando
        const loadingEl = document.getElementById('loading');
        const dashboardEl = document.getElementById('dashboard');
        const errorEl = document.getElementById('error');

        if (!loadingEl || !dashboardEl || !errorEl) {
            console.error('Elementos del DOM no encontrados');
            return;
        }

        // Verificar si el bot está inicializando
        const marketStatus = state.market_status || {};
        const balances = state.balances?.total || {};
        const isInitializing = marketStatus.message && marketStatus.message.includes('Inicializando');

        // Mostrar mensaje de inicialización pero también mostrar el dashboard
        if (isInitializing && Object.keys(balances).length === 0) {
            loadingEl.textContent = '⏳ El bot está inicializando. Espera unos segundos...';
            loadingEl.style.display = 'block';
            loadingEl.style.color = '#00FF88';
            loadingEl.style.fontSize = '1.2em';
            errorEl.style.display = 'none';
            // No ocultar el dashboard, mostrar con datos vacíos
        } else {
            loadingEl.style.display = 'none';
        }

        dashboardEl.style.display = 'block';
        errorEl.style.display = 'none';

        // Actualizar secciones según su intervalo (incluso si están vacías)
        renderSummary(state);
        renderSlots(state);
        renderRadar(state);
        renderDistribution(state);
    } catch (error) {
        console.error('Error en updateDashboard:', error);
        showError('Error cargando el dashboard: ' + error.message);
    }
}

// Inicializar
document.addEventListener('DOMContentLoaded', function() {
    console.log('Dashboard inicializado');
    try {
        // Cargar inmediatamente
        updateDashboard();
        renderHistorial();
        
        // Actualizar dashboard cada 5 segundos (para slots)
        setInterval(updateDashboard, SLOTS_INTERVAL);
        
        // Actualizar historial cada 30 segundos
        setInterval(renderHistorial, OTHER_INTERVAL);
    } catch (error) {
        console.error('Error inicializando dashboard:', error);
        showError('Error inicializando el dashboard: ' + error.message);
    }
});
