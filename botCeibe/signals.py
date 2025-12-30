"""
Módulo de señales técnicas para el bot.
Proporciona indicadores técnicos como RSI, EMA200, volumen, etc.
"""
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


def get_technical_indicators(pair: str, exchange) -> Dict[str, Any]:
    """
    Obtiene indicadores técnicos para un par de trading.
    
    Args:
        pair: Par de trading (ej: "BTC/EUR")
        exchange: Instancia de exchange (ccxt)
    
    Returns:
        Dict con indicadores: rsi, ema200_distance, volume_status, profit_potential
    """
    try:
        # Obtener datos OHLCV
        ohlcv = exchange.fetch_ohlcv(pair, '1h', limit=200)
        
        if len(ohlcv) < 200:
            return {}
        
        # Calcular RSI (simplificado)
        closes = [c[4] for c in ohlcv]
        rsi = _calculate_rsi(closes, period=14)
        
        # Calcular EMA200
        ema200 = _calculate_ema(closes, period=200)
        current_price = closes[-1]
        ema200_distance = ((current_price - ema200) / ema200 * 100) if ema200 > 0 else 0
        
        # Calcular volumen promedio
        volumes = [c[5] for c in ohlcv]
        avg_volume = sum(volumes[-20:]) / 20
        current_volume = volumes[-1]
        # RELAJADO MÁXIMO: volume_status es 'high' si volumen actual > 0 (cualquier volumen es válido)
        # Antes: 1.5x = 150%, después: 0.7x = 70%, ahora: > 0
        # Esto permite que TODO activo con datos OHLCV aparezca en el radar
        volume_status = 'high' if current_volume > 0 else 'normal'
        
        # Potencial de ganancia (simplificado)
        profit_potential = abs(ema200_distance) if ema200_distance < 0 else 0
        
        return {
            'rsi': rsi,
            'ema200_distance': ema200_distance,
            'volume_status': volume_status,
            'profit_potential': profit_potential
        }
    except Exception as e:
        logger.debug(f"Error obteniendo indicadores para {pair}: {e}")
        return {}


def _calculate_rsi(prices: list, period: int = 14) -> Optional[float]:
    """Calcula el RSI (Relative Strength Index)."""
    if len(prices) < period + 1:
        return None
    
    try:
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [d if d > 0 else 0 for d in deltas]
        losses = [-d if d < 0 else 0 for d in deltas]
        
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    except Exception as e:
        logger.debug(f"Error calculando RSI: {e}")
        return None


def _calculate_ema(prices: list, period: int = 200) -> Optional[float]:
    """Calcula la EMA (Exponential Moving Average)."""
    if len(prices) < period:
        return None
    
    try:
        multiplier = 2 / (period + 1)
        ema = sum(prices[:period]) / period
        
        for price in prices[period:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))
        
        return ema
    except Exception as e:
        logger.debug(f"Error calculando EMA: {e}")
        return None

