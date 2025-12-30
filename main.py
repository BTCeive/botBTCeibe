"""
Motor principal de botCeibe.
Script de Python puro que ejecuta el bot de trading en un bucle infinito.
Lee la configuración desde config/strategy.json.
"""
import asyncio
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

# Agregar el directorio raíz al path para importar módulos existentes
# main.py está en botCeibe/, así que el ROOT_DIR es el directorio actual (botCeibe)
ROOT_DIR = Path(__file__).parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Importar usando ruta relativa (más simple y funciona desde cualquier ubicación)
from engine.trading_logic import TradingEngine
from logging.handlers import RotatingFileHandler

# Configurar logging con rotación automática (5 archivos de 10MB máximo)
log_handler = RotatingFileHandler(
    'botceibe.log',
    maxBytes=10*1024*1024,  # 10MB por archivo
    backupCount=5,  # Mantener máximo 5 archivos
    encoding='utf-8'
)
log_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        log_handler
    ]
)
logger = logging.getLogger(__name__)


async def run_bot_cycle(engine: TradingEngine, update_shared_state: bool = True):
    """
    Ejecuta un ciclo completo del bot:
    1. Obtener precios
    2. Calcular indicadores (RSI, etc.)
    3. Actualizar shared/state.json (opcional)
    """
    try:
        logger.debug("Ejecutando scan_opportunities...")
        try:
            await engine.scan_opportunities()
        except Exception as scan_error:
            logger.debug(f"Error en scan_opportunities (continuando): {scan_error}")
            # Continuar aunque falle scan_opportunities para poder guardar el estado
        
        if update_shared_state:
            logger.debug("Guardando shared/state.json...")
            try:
                await engine._save_shared_state()
            except Exception as state_error:
                logger.error(f"Error al guardar estado compartido: {state_error}", exc_info=True)
                return False
        
        logger.debug("Ciclo completado exitosamente")
        return True
    except Exception as e:
        logger.error(f"Error en ciclo del bot: {e}", exc_info=True)
        # Intentar guardar estado incluso si hay error
        if update_shared_state:
            try:
                await engine._save_shared_state()
            except:
                pass
        return False


def main():
    """Función principal con bucle infinito."""
    try:
        logger.info("=" * 60)
        logger.info("Iniciando botCeibe")
        logger.info("=" * 60)
        
        # Inicializar motor (carga strategy.json automáticamente)
        logger.info("Inicializando motor de trading...")
        engine = TradingEngine()
        
        # Crear estado inicial antes de conectar
        logger.info("Creando estado inicial...")
        engine._create_initial_shared_state()
        
        # Recuperar trades activos desde persistencia
        logger.info("Recuperando trades activos desde persistencia...")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(engine._recover_active_trades())
        
        # Detectar posiciones existentes
        logger.info("Detectando posiciones existentes en la wallet...")
        loop.run_until_complete(engine._detect_existing_positions())
        
        # NOTA: El radar dinámico se inicializará en el primer tick del loop principal
        # para evitar bloquear el arranque del motor
        logger.info("Radar dinámico se inicializará en el primer tick...")
        # Pequeña pausa de 2s antes de iniciar comprobaciones de tesorería
        time.sleep(2)
        
        # Verificar y gestionar BNB para comisiones
        logger.info("⛽ Verificando balance de BNB para comisiones...")
        bnb_status = engine.vault.check_and_refill_bnb()
        if bnb_status.get('status') == 'needs_refill':
            logger.info(f"📋 BNB marcado para recarga: {bnb_status.get('bnb_percent', 0):.2f}% (objetivo: 3-5%)")
        elif bnb_status.get('status') == 'emergency_refilled':
            logger.info(f"✅ BNB recargado en emergencia: {bnb_status.get('amount_bought', 0):.8f} BNB")

        # Pausa adicional de 2s antes de iniciar API/Dashboard para repartir carga de inicio
        time.sleep(2)
        
        # Obtener intervalo de escaneo desde strategy.json
        scan_interval = engine.strategy.get("scan_interval", 5)
        shared_state_update_interval = engine.strategy.get("shared_state_update_interval", 12)
        
        logger.info(f"Intervalo de escaneo: {scan_interval}s")
        logger.info(f"Actualización de estado compartido: cada {shared_state_update_interval} ticks")
        logger.info("Motor de trading iniciado. Presiona Ctrl+C para detener.")
        
        # Bucle infinito principal
        tick_count = 0
        engine.running = True
        radar_initialized = False  # Flag para inicializar radar en primer tick
        
        # Contador para snapshots del portfolio
        snapshot_interval = engine.strategy.get("portfolio_snapshot_interval", 1800)
        last_snapshot_time = time.time()
        
        # Contador para escaneo completo de oportunidades (cada 10 ticks de vigilancia)
        scan_opportunities_interval = 10
        last_full_scan_tick = 0
        
        # Contador para escaneo completo de whitelist (cada 10 ticks = 50 segundos)
        whitelist_scan_interval = 10
        last_whitelist_scan_tick = 0
        
        # Usar el loop ya creado
        
        while engine.running:
            try:
                tick_count += 1
                start_time = time.time()
                
                # 🔄 INICIALIZAR RADAR EN PRIMER TICK (para no bloquear el startup)
                if not radar_initialized:
                    logger.info("Inicializando radar dinámico en primer tick...")
                    try:
                        loop.run_until_complete(engine.start_radar_dynamic_updates())
                        radar_initialized = True
                        logger.info("✅ Radar dinámico inicializado")
                    except Exception as radar_error:
                        logger.error(f"Error inicializando radar: {radar_error}", exc_info=True)
                        radar_initialized = True  # Marcar como inicializado para no reintentar
                
                # 🔄 PRIORIDAD DE VIGILANCIA: Verificar trades activos primero
                max_slots = engine.strategy.get("trading", {}).get("max_slots", 4)
                has_active_trades = False
                try:
                    for slot_id in range(max_slots):
                        if engine.db.get_active_trade(slot_id):
                            has_active_trades = True
                            break
                except:
                    pass
                
                # ⚡ FAST TRACK: Si hay trades activos, solo vigilancia (rápido, cada 5s)
                # Escaneo completo solo cada N ticks para no bloquear
                monitor_only = has_active_trades and (tick_count - last_full_scan_tick) < scan_opportunities_interval
                
                # Si hay trades activos, actualizar shared_state cada tick (cada 5s)
                # Si no hay trades, actualizar cada N ticks para ahorrar recursos
                if has_active_trades:
                    update_shared_state = True  # Actualizar cada 5 segundos cuando hay trades activos
                else:
                    # Sin trades activos, actualizar cada N ticks para ahorrar recursos
                    update_shared_state = (tick_count == 1) or (tick_count % shared_state_update_interval == 0)
                
                # Determinar si hacer escaneo completo
                do_full_scan = not monitor_only
                if do_full_scan:
                    last_full_scan_tick = tick_count
                
                if update_shared_state:
                    scan_type = "Vigilancia + Escaneo" if do_full_scan else "Vigilancia rápida"
                    logger.info(f"--- Tick #{tick_count} iniciado ({scan_type}, actualización estado: SÍ) ---")
                else:
                    logger.debug(f"--- Tick #{tick_count} iniciado (sin actualización estado) ---")
                
                # Ejecutar ciclo del bot (vigilancia rápida o completo)
                if do_full_scan:
                    # Escaneo completo: monitoreo + búsqueda de oportunidades
                    loop.run_until_complete(engine.run_bot_cycle(monitor_only=False))
                else:
                    # Solo vigilancia rápida
                    loop.run_until_complete(engine.run_bot_cycle(monitor_only=True))
                
                # Guardar estado compartido si es necesario
                if update_shared_state:
                    try:
                        loop.run_until_complete(engine._save_shared_state())
                    except Exception as state_error:
                        logger.error(f"Error al guardar estado compartido: {state_error}", exc_info=True)
                
                # SISTEMA DE ESCANEO EN CASCADA (3 niveles de prioridad)
                # Nivel 1 (HOT - Top 10): cada tick (cada 5s)
                # Nivel 2 (WARM - Pos 11-20): cada 3 ticks (~15s)
                # Nivel 3 (COLD - Resto): cada 10 ticks (~50s)
                try:
                    # Clasificar whitelist en 3 niveles según heat_score actual
                    levels = loop.run_until_complete(engine._classify_whitelist_by_heat())
                    
                    hot_assets = levels.get('hot', [])
                    warm_assets = levels.get('warm', [])
                    cold_assets = levels.get('cold', [])
                    
                    # Nivel 1: HOT - escanear SIEMPRE (incluye Riesgo BTC)
                    if hot_assets:
                        try:
                            logger.debug(f"🔥 Escaneando Nivel 1 (HOT): {len(hot_assets)} activos")
                            loop.run_until_complete(
                                asyncio.wait_for(
                                    engine._scan_whitelist_multi_bases(['USDT','BTC','ETH'], hot_assets),
                                    timeout=15.0
                                )
                            )
                        except asyncio.TimeoutError:
                            logger.debug("⚠️ Timeout en escaneo HOT (>15s)")
                        except Exception as e:
                            logger.debug(f"⚠️ Error en escaneo HOT: {e}")
                    
                    # Nivel 2: WARM - escanear cada 3 ticks
                    if warm_assets and (tick_count % 3 == 0):
                        try:
                            logger.debug(f"🌡️  Escaneando Nivel 2 (WARM): {len(warm_assets)} activos")
                            loop.run_until_complete(
                                asyncio.wait_for(
                                    engine._scan_whitelist_multi_bases(['USDT','BTC','ETH'], warm_assets),
                                    timeout=12.0
                                )
                            )
                        except asyncio.TimeoutError:
                            logger.debug("⚠️ Timeout en escaneo WARM (>12s)")
                        except Exception as e:
                            logger.debug(f"⚠️ Error en escaneo WARM: {e}")
                    
                    # Nivel 3: COLD - escanear cada 10 ticks
                    if cold_assets and (tick_count % 10 == 0):
                        try:
                            logger.debug(f"❄️  Escaneando Nivel 3 (COLD): {len(cold_assets)} activos")
                            loop.run_until_complete(
                                asyncio.wait_for(
                                    engine._scan_whitelist_multi_bases(['USDT','BTC','ETH'], cold_assets),
                                    timeout=20.0
                                )
                            )
                        except asyncio.TimeoutError:
                            logger.debug("⚠️ Timeout en escaneo COLD (>20s)")
                        except Exception as e:
                            logger.debug(f"⚠️ Error en escaneo COLD: {e}")
                    
                    logger.debug(f"✅ Escaneo cascada completado (Tick #{tick_count})")
                    
                except Exception as cascade_error:
                    logger.warning(f"⚠️ Error en escaneo cascada: {cascade_error}")
                
                elapsed_time = time.time() - start_time
                
                if update_shared_state:
                    scan_type = "Vigilancia + Escaneo" if do_full_scan else "Vigilancia rápida"
                    logger.info(f"✅ Tick #{tick_count} completado ({scan_type}, tiempo: {elapsed_time:.2f}s)")
                else:
                    logger.debug(f"Tick #{tick_count} completado (tiempo: {elapsed_time:.2f}s)")
                
                # Guardar snapshot del portfolio cada N segundos (configurable)
                current_time = time.time()
                if current_time - last_snapshot_time >= snapshot_interval:
                    try:
                        total_value = engine.vault.calculate_total_portfolio_value()
                        
                        # Calcular efectivo libre (EUR + USDC) EXCLUYENDO el treasury
                        balances = engine.exchange.fetch_balance()
                        free_cash_eur = 0.0
                        for fiat in ['EUR', 'USDC']:
                            free_balance = balances.get(fiat, {}).get('free', 0)
                            if fiat == 'EUR':
                                free_cash_eur += free_balance
                            else:
                                free_cash_eur += engine.vault.get_asset_value('USDC', free_balance, 'EUR')
                        
                        # Excluir el treasury del free_cash disponible
                        treasury_total = engine.db.get_total_treasury()
                        treasury_eur = treasury_total.get('total_eur', 0.0)
                        free_cash_eur = max(0.0, free_cash_eur - treasury_eur)
                        
                        # Guardar snapshot
                        engine.db.save_portfolio_snapshot(total_value, free_cash_eur)
                        logger.info(
                            f"Snapshot del portfolio guardado: "
                            f"Total: {total_value:.2f} EUR, "
                            f"Efectivo libre: {free_cash_eur:.2f} EUR"
                        )
                        last_snapshot_time = current_time
                    except Exception as e:
                        logger.error(f"Error al guardar snapshot del portfolio: {e}")
                
                # Log de acción al final de cada ciclo
                print(f"Tick completado: {datetime.now()}")
                
                # Calcular tiempo de espera restante para mantener intervalo
                remaining_time = max(0, scan_interval - elapsed_time)
                if remaining_time > 0:
                    time.sleep(remaining_time)
                
            except KeyboardInterrupt:
                logger.info("\nDeteniendo bot...")
                engine.running = False
                break
            except Exception as e:
                logger.error(f"Error en bucle principal: {e}", exc_info=True)
                # Continuar el bucle incluso si hay errores
                print(f"Tick completado (con error): {datetime.now()}")
                time.sleep(scan_interval)
        
        # Detener radar dinámico si no se detuvo antes
        try:
            if engine.running:
                engine.running = False
                loop.run_until_complete(engine.stop_radar_dynamic_updates())
        except:
            pass
        
        # Cerrar loop
        loop.close()
        logger.info("Bot detenido correctamente.")
        
    except KeyboardInterrupt:
        logger.info("\nDeteniendo bot...")
        if 'engine' in locals():
            engine.running = False
            # Detener radar dinámico
            try:
                loop = asyncio.get_event_loop()
                loop.run_until_complete(engine.stop_radar_dynamic_updates())
            except:
                pass
        logger.info("Bot detenido correctamente.")
    except Exception as e:
        logger.error(f"Error fatal en el bot: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

