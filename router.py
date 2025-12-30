"""
Router optimizado para encontrar rutas de trading entre monedas.
Prioriza pares directos y minimiza comisiones.
"""
import logging
from typing import Optional, List, Tuple, Dict, Any

logger = logging.getLogger(__name__)

# Cache de pares disponibles (se actualiza dinámicamente)
_pair_cache = {}
_exchange_instance = None


def init_router(exchange):
    """Inicializa el router con una instancia de exchange."""
    global _exchange_instance
    _exchange_instance = exchange
    _update_pair_cache()


def _update_pair_cache():
    """Actualiza el cache de pares disponibles."""
    global _pair_cache
    if not _exchange_instance:
        return
    
    try:
        markets = _exchange_instance.load_markets()
        _pair_cache = {}
        for symbol in markets:
            if markets[symbol]['active']:
                _pair_cache[symbol] = markets[symbol]
    except Exception as e:
        logger.debug(f"Error actualizando cache de pares: {e}")


def get_pair_info(pair: str) -> Optional[Dict[str, Any]]:
    """
    Obtiene información de un par de trading.
    
    Args:
        pair: Par de trading (ej: "BTC/EUR")
    
    Returns:
        Dict con información del par o None si no existe
    """
    # Si hay exchange_instance, usarlo
    if _exchange_instance:
        try:
            # Intentar obtener del cache primero
            if pair in _pair_cache:
                market = _pair_cache[pair]
                ticker = _exchange_instance.fetch_ticker(pair)
                
                # Capturar price_change_percent de Binance (puede venir como 'percentage' o 'change')
                price_change_pct = ticker.get('percentage') or ticker.get('change')
                
                # Fallback: calcular desde lastPrice y previousClosePrice/open
                if price_change_pct is None:
                    last_price = ticker.get('last')
                    open_price = ticker.get('open') or ticker.get('previousClose')
                    if last_price and open_price and open_price > 0:
                        price_change_pct = ((last_price - open_price) / open_price) * 100
                    else:
                        price_change_pct = 0.0
                
                return {
                    'symbol': pair,
                    'active': market.get('active', True),
                    'last_price': ticker.get('last'),
                    'bid': ticker.get('bid'),
                    'ask': ticker.get('ask'),
                    'volume': ticker.get('quoteVolume', 0),
                    'baseVolume': ticker.get('baseVolume', 0),
                    'previousVolume': ticker.get('previousClose', 0),  # Placeholder para volumen previo
                    'price_change_percent': price_change_pct,
                    'maker': market.get('maker', 0.001),
                    'taker': market.get('taker', 0.001)
                }
        except Exception as e:
            logger.debug(f"Error obteniendo info del par {pair} con exchange: {e}")
    
    # Si no hay exchange_instance, crear uno temporal (solo lectura)
    try:
        import ccxt
        from bot_config import BINANCE_API_KEY, BINANCE_SECRET_KEY, BINANCE_TESTNET
        
        exchange_config = {
            'apiKey': BINANCE_API_KEY if BINANCE_API_KEY else '',
            'secret': BINANCE_SECRET_KEY if BINANCE_SECRET_KEY else '',
            'enableRateLimit': True,
            'options': {'defaultType': 'spot'}
        }
        
        if BINANCE_TESTNET:
            exchange_config['urls'] = {
                'api': {
                    'public': 'https://testnet.binance.vision/api',
                    'private': 'https://testnet.binance.vision/api',
                }
            }
        
        temp_exchange = ccxt.binance(exchange_config)
        ticker = temp_exchange.fetch_ticker(pair)
        
        return {
            'symbol': pair,
            'active': True,
            'last_price': ticker.get('last'),
            'bid': ticker.get('bid'),
            'ask': ticker.get('ask'),
            'volume': ticker.get('quoteVolume', 0),
            'maker': 0.001,
            'taker': 0.001
        }
    except Exception as e:
        logger.debug(f"Error obteniendo info del par {pair} sin exchange: {e}")
        return None


def get_available_pairs(base: str) -> List[str]:
    """
    Obtiene todos los pares disponibles para una moneda base.
    
    Args:
        base: Moneda base (ej: "EUR", "BTC")
    
    Returns:
        Lista de pares disponibles
    """
    if not _exchange_instance:
        return []
    
    try:
        _update_pair_cache()
        pairs = []
        for symbol in _pair_cache:
            if symbol.startswith(f"{base}/") or symbol.endswith(f"/{base}"):
                pairs.append(symbol)
        return pairs
    except Exception as e:
        logger.debug(f"Error obteniendo pares para {base}: {e}")
        return []


def find_swap_route(
    from_asset: str,
    to_asset: str,
    whitelist: List[str],
    fiat_assets: List[str] = None,
    prefer_low_fees: bool = True
) -> Optional[Tuple[str, Optional[str]]]:
    """
    Encuentra la mejor ruta para hacer un swap entre dos monedas.
    
    Prioridad:
    1. Par directo (ej: SOL/BTC, ETH/BTC)
    2. Par a través de whitelist (evitando fiat si es posible)
    3. Par a través de fiat como último recurso
    
    Args:
        from_asset: Moneda de origen
        to_asset: Moneda de destino
        whitelist: Lista de monedas permitidas
        fiat_assets: Lista de monedas fiat (EUR, USDC)
        prefer_low_fees: Si True, prioriza pares con menos comisiones
    
    Returns:
        Tuple (swap_pair, intermediate) o None si no se encuentra ruta
        - swap_pair: Par directo o primer par del swap
        - intermediate: Moneda intermedia (None si es par directo)
    """
    if fiat_assets is None:
        fiat_assets = ['EUR', 'USDC']
    
    # PRIORIDAD 1: Buscar par directo
    direct_pairs = [
        f"{from_asset}/{to_asset}",
        f"{to_asset}/{from_asset}"
    ]
    
    for pair in direct_pairs:
        pair_info = get_pair_info(pair)
        if pair_info and pair_info.get('active'):
            logger.debug(f"✅ Ruta directa encontrada: {pair}")
            return (pair, None)
    
    # PRIORIDAD 2: Buscar a través de whitelist (evitando fiat)
    # Ordenar whitelist: primero monedas no-fiat, luego fiat
    crypto_whitelist = [c for c in whitelist if c not in fiat_assets and c not in [from_asset, to_asset]]
    fiat_whitelist = [c for c in whitelist if c in fiat_assets and c not in [from_asset, to_asset]]
    
    # Buscar primero en crypto
    for intermediate in crypto_whitelist:
        pair1_candidates = [
            f"{from_asset}/{intermediate}",
            f"{intermediate}/{from_asset}"
        ]
        pair2_candidates = [
            f"{intermediate}/{to_asset}",
            f"{to_asset}/{intermediate}"
        ]
        
        for pair1 in pair1_candidates:
            pair1_info = get_pair_info(pair1)
            if not pair1_info or not pair1_info.get('active'):
                continue
            
            for pair2 in pair2_candidates:
                pair2_info = get_pair_info(pair2)
                if pair2_info and pair2_info.get('active'):
                    # Si prefer_low_fees, calcular comisiones totales
                    if prefer_low_fees:
                        total_fee = (pair1_info.get('taker', 0.001) + 
                                   pair2_info.get('taker', 0.001))
                        logger.debug(
                            f"✅ Ruta encontrada vía {intermediate}: {pair1} -> {pair2} "
                            f"(comisión total: {total_fee*100:.3f}%)"
                        )
                    else:
                        logger.debug(f"✅ Ruta encontrada vía {intermediate}: {pair1} -> {pair2}")
                    
                    return (pair1, intermediate)
    
    # PRIORIDAD 3: Buscar a través de fiat como último recurso
    for intermediate in fiat_whitelist:
        pair1_candidates = [
            f"{from_asset}/{intermediate}",
            f"{intermediate}/{from_asset}"
        ]
        pair2_candidates = [
            f"{intermediate}/{to_asset}",
            f"{to_asset}/{intermediate}"
        ]
        
        for pair1 in pair1_candidates:
            pair1_info = get_pair_info(pair1)
            if not pair1_info or not pair1_info.get('active'):
                continue
            
            for pair2 in pair2_candidates:
                pair2_info = get_pair_info(pair2)
                if pair2_info and pair2_info.get('active'):
                    logger.debug(f"✅ Ruta encontrada vía fiat {intermediate}: {pair1} -> {pair2}")
                    return (pair1, intermediate)
    
    logger.warning(f"❌ No se encontró ruta desde {from_asset} hacia {to_asset}")
    return None


def get_best_swap_pair(
    from_asset: str,
    to_asset: str,
    whitelist: List[str],
    fiat_assets: List[str] = None,
    gas_percentage: float = 0.0
) -> Optional[str]:
    """
    Obtiene el mejor par para hacer un swap, considerando comisiones y gas.
    
    Args:
        from_asset: Moneda de origen
        to_asset: Moneda de destino
        whitelist: Lista de monedas permitidas
        fiat_assets: Lista de monedas fiat
        gas_percentage: Porcentaje de gas disponible (si > 2.5%, prioriza menos comisiones)
    
    Returns:
        Par de trading óptimo o None
    """
    prefer_low_fees = gas_percentage >= 2.5  # Si hay suficiente gas, priorizar menos comisiones
    
    route = find_swap_route(
        from_asset,
        to_asset,
        whitelist,
        fiat_assets,
        prefer_low_fees
    )
    
    if route:
        return route[0]  # Retornar el primer par del swap
    
    return None

