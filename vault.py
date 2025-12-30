"""
Módulo Vault para gestionar balances y conversiones de monedas.
"""
import logging
from typing import Dict, Any, Optional
from router import get_pair_info

logger = logging.getLogger(__name__)


class Vault:
    """Clase para gestionar balances y conversiones de monedas."""
    
    def __init__(self, db):
        """
        Inicializa el Vault.
        
        Args:
            db: Instancia de Database
        """
        self.db = db
        self.exchange = None  # Se inicializará desde TradingEngine
    
    def set_exchange(self, exchange):
        """Establece la instancia de exchange."""
        self.exchange = exchange
    
    def get_asset_value(self, asset: str, amount: float, target_currency: str = 'EUR') -> float:
        """
        Convierte una cantidad de un activo a su valor en la moneda objetivo.
        Busca rutas alternativas si el par directo no existe.
        
        Args:
            asset: Activo a convertir (ej: 'BTC', 'ETH', 'XRP')
            amount: Cantidad del activo
            target_currency: Moneda objetivo (default: 'EUR')
        
        Returns:
            Valor en la moneda objetivo
        """
        if amount <= 0:
            return 0.0
        
        if asset == target_currency:
            return amount
        
        # Conversión directa 1:1 para stablecoins a EUR
        if target_currency == 'EUR' and asset in ['USDC', 'USDT']:
            return amount
        
        try:
            # 1. Intentar par directo
            pair = f"{asset}/{target_currency}"
            pair_info = get_pair_info(pair)
            
            if pair_info and pair_info.get('last_price'):
                return amount * pair_info['last_price']
            
            # 2. Intentar par inverso
            pair_inv = f"{target_currency}/{asset}"
            pair_info_inv = get_pair_info(pair_inv)
            
            if pair_info_inv and pair_info_inv.get('last_price'):
                return amount / pair_info_inv['last_price']
            
            # 3. Si target_currency es EUR, intentar ruta a través de USDT
            if target_currency == 'EUR':
                # XRP/USDT → USDT/EUR
                pair_usdt = f"{asset}/USDT"
                pair_info_usdt = get_pair_info(pair_usdt)
                
                if pair_info_usdt and pair_info_usdt.get('last_price'):
                    usdt_amount = amount * pair_info_usdt['last_price']
                    # Convertir USDT a EUR
                    usdt_eur_info = get_pair_info("USDT/EUR")
                    if usdt_eur_info and usdt_eur_info.get('last_price'):
                        return usdt_amount * usdt_eur_info['last_price']
                    else:
                        # Si USDT/EUR no existe, asumir paridad 1:1
                        return usdt_amount
            
            # 4. Si target_currency es EUR, intentar ruta a través de USDC (alternativa a USDT)
            if target_currency == 'EUR':
                pair_usdc = f"{asset}/USDC"
                pair_info_usdc = get_pair_info(pair_usdc)
                
                if pair_info_usdc and pair_info_usdc.get('last_price'):
                    usdc_amount = amount * pair_info_usdc['last_price']
                    # Convertir USDC a EUR
                    usdc_eur_info = get_pair_info("USDC/EUR")
                    if usdc_eur_info and usdc_eur_info.get('last_price'):
                        return usdc_amount * usdc_eur_info['last_price']
                    else:
                        # Si USDC/EUR no existe, asumir paridad 1:1
                        return usdc_amount
            
            # 5. Si target_currency es EUR, intentar ruta a través de BTC
            if target_currency == 'EUR' and asset not in ['BTC', 'EUR']:
                pair_btc = f"{asset}/BTC"
                pair_info_btc = get_pair_info(pair_btc)
                
                if pair_info_btc and pair_info_btc.get('last_price'):
                    btc_amount = amount * pair_info_btc['last_price']
                    # Convertir BTC a EUR
                    btc_eur_info = get_pair_info("BTC/EUR")
                    if btc_eur_info and btc_eur_info.get('last_price'):
                        return btc_amount * btc_eur_info['last_price']
            
            logger.debug(f"No se pudo obtener precio para {asset}/{target_currency} (sin rutas alternativas disponibles)")
            return 0.0
        except Exception as e:
            logger.debug(f"Error convirtiendo {amount} {asset} a {target_currency}: {e}")
            return 0.0
    
    def calculate_total_portfolio_value(self) -> float:
        """
        Calcula el valor total del portfolio en EUR.
        
        Returns:
            Valor total en EUR
        """
        if not self.exchange:
            return 0.0
        
        try:
            balances = self.exchange.fetch_balance()
            total_value = 0.0
            
            for asset, balance_data in balances.get('total', {}).items():
                if balance_data > 0.00000001:  # Filtro muy bajo para incluir BTC, BNB
                    asset_value = self.get_asset_value(asset, balance_data, 'EUR')
                    total_value += asset_value
                    # Audit log para verificación
                    if asset_value > 0.01:  # Solo loguear activos con valor > 1 céntimo
                        logger.debug(f"💰 Portfolio: {asset} {balance_data:.8f} = {asset_value:.2f}€")
            
            return total_value
        except Exception as e:
            logger.error(f"Error calculando valor total del portfolio: {e}")
            return 0.0
    
    def apply_savings(self, profit_eur: float) -> Dict[str, Any]:
        """
        Aplica el sistema de ahorro (Tesoro Guardado) sobre las ganancias.
        
        Args:
            profit_eur: Ganancia en EUR
        
        Returns:
            Dict con información del ahorro aplicado
        """
        if profit_eur <= 0:
            return {'applied': False, 'savings_amount_eur': 0.0}
        
        try:
            # Obtener porcentaje de ahorro desde la base de datos o configuración
            # Por ahora, usar un valor por defecto del 5%
            savings_percent = 5.0
            savings_amount_eur = profit_eur * (savings_percent / 100.0)
            
            if savings_amount_eur > 0.01:  # Mínimo 1 céntimo
                # Guardar en treasury
                self.db.add_to_treasury(
                    amount_eur=savings_amount_eur,
                    amount_btc=0.0,
                    description="Tesoro Guardado (Savings Mode)"
                )
                
                return {
                    'applied': True,
                    'savings_amount_eur': savings_amount_eur
                }
            
            return {'applied': False, 'savings_amount_eur': 0.0}
        except Exception as e:
            logger.error(f"Error aplicando savings: {e}")
            return {'applied': False, 'savings_amount_eur': 0.0}
    
    def check_and_refill_bnb(self) -> Dict[str, Any]:
        """
        Verifica y recarga BNB si es necesario para comisiones.
        
        Returns:
            Dict con estado del BNB
        """
        if not self.exchange:
            return {'needs_refill': False, 'status': 'ok'}
        
        try:
            total_portfolio = self.calculate_total_portfolio_value()
            if total_portfolio <= 0:
                return {'needs_refill': False, 'status': 'ok'}
            
            balances = self.exchange.fetch_balance()
            bnb_balance = balances.get('BNB', {}).get('total', 0.0)
            bnb_value_eur = self.get_asset_value('BNB', bnb_balance, 'EUR')
            bnb_percent = (bnb_value_eur / total_portfolio * 100) if total_portfolio > 0 else 0
            
            # Verificar si necesita recarga (menos del 3%)
            if bnb_percent < 3.0:
                return {
                    'needs_refill': True,
                    'status': 'needs_refill',
                    'bnb_percent': bnb_percent,
                    'target_percent': 3.0
                }
            
            return {
                'needs_refill': False,
                'status': 'ok',
                'bnb_percent': bnb_percent
            }
        except Exception as e:
            logger.error(f"Error verificando BNB: {e}")
            return {'needs_refill': False, 'status': 'error'}

