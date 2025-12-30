# Whitelist de Monedas y Pares Disponibles

## Monedas en la Whitelist

El bot opera con las siguientes monedas de la whitelist:

1. **BTC** - Bitcoin
2. **ETH** - Ethereum
3. **SOL** - Solana
4. **BNB** - Binance Coin
5. **XRP** - Ripple
6. **ADA** - Cardano
7. **AVAX** - Avalanche
8. **DOT** - Polkadot
9. **LINK** - Chainlink
10. **MATIC** - Polygon
11. **NEAR** - NEAR Protocol
12. **FET** - Fetch.ai
13. **RNDR** - Render Token
14. **LTC** - Litecoin
15. **USDC** - USD Coin (Fiat estable)
16. **EUR** - Euro (Fiat)

## Fiat Assets (Monedas Base)

El bot usa estas monedas fiat como base para las operaciones:
- **EUR** (Euro)
- **USDC** (USD Coin)

## Pares Disponibles

El bot puede operar con cualquier par que combine:
- Una moneda fiat (EUR o USDC) como base
- Una moneda de la whitelist como quote

### Ejemplos de Pares que el Bot Puede Operar:

#### Con EUR como Base:
- BTC/EUR
- ETH/EUR
- SOL/EUR
- BNB/EUR
- XRP/EUR
- ADA/EUR
- AVAX/EUR
- DOT/EUR
- LINK/EUR
- MATIC/EUR
- NEAR/EUR
- FET/EUR
- RNDR/EUR
- LTC/EUR
- USDC/EUR

#### Con USDC como Base:
- BTC/USDC
- ETH/USDC
- SOL/USDC
- BNB/USDC
- XRP/USDC
- ADA/USDC
- AVAX/USDC
- DOT/USDC
- LINK/USDC
- MATIC/USDC
- NEAR/USDC
- FET/USDC
- RNDR/USDC
- LTC/USDC

## Pares Entre Monedas (Swaps)

El bot también puede hacer swaps entre monedas de la whitelist cuando:
- Existe un par directo (ej: BTC/ETH, ETH/SOL)
- O existe una ruta indirecta a través de otra moneda de la whitelist

### Ejemplos de Swaps Posibles:
- BTC ↔ ETH
- ETH ↔ SOL
- SOL ↔ BNB
- BNB ↔ XRP
- XRP ↔ ADA
- ADA ↔ AVAX
- AVAX ↔ DOT
- DOT ↔ LINK
- LINK ↔ MATIC
- MATIC ↔ NEAR
- NEAR ↔ FET
- FET ↔ RNDR
- RNDR ↔ LTC

## Notas Importantes

1. **Disponibilidad Real**: Los pares reales disponibles dependen de lo que Binance ofrezca. El bot verifica la disponibilidad usando `get_available_pairs()`.

2. **Prioridad**: El bot siempre intenta operar desde fiat (EUR/USDC) hacia las monedas de la whitelist.

3. **Gas Management**: BNB tiene prioridad especial cuando el gas está bajo (< 2.5%).

4. **Whitelist Dinámica**: La whitelist se puede modificar en `strategy.json`, pero requiere reiniciar el bot para que los cambios surtan efecto.

## Configuración Actual

```json
{
  "whitelist": [
    "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "AVAX",
    "DOT", "LINK", "MATIC", "NEAR", "FET", "RNDR", "LTC",
    "USDC", "EUR"
  ],
  "fiat_assets": ["EUR", "USDC"]
}
```

