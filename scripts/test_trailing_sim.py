#!/usr/bin/env python3
"""
Simulación rápida del trailing stop Gemini.
Escenario: entrada 100 → máximo 105 → caída a 104.47.
Se espera disparo de venta al cruzar 104.475 (-0.50% desde el máximo).
"""

from dataclasses import dataclass

@dataclass
class TrailingParams:
    trailing_stop_pct: float = 0.50
    activation_pct: float = 3.0
    base_stop_loss_pct: float = -1.5


def simulate_trailing(entry_price: float = 100.0, highest_price: float = 105.0, current_price: float = 104.47,
                      params: TrailingParams = TrailingParams()) -> None:
    initial_value = entry_price  # suponemos 1 unidad
    current_value = current_price

    pnl_percent = ((current_value - initial_value) / initial_value) * 100
    print(f"PNL actual: {pnl_percent:.2f}%")

    if pnl_percent <= params.base_stop_loss_pct:
        stop_loss = entry_price * (1 + params.base_stop_loss_pct / 100)
        print(f"Stop base (-1.5%) => vender en {stop_loss:.3f}")
        return

    if pnl_percent > params.activation_pct:
        stop_loss = highest_price * (1 - params.trailing_stop_pct / 100)
        print(f"Trailing activo: stop @ {stop_loss:.3f}")
        if current_price <= stop_loss:
            print("Venta gatillada: precio <= stop (coincide con la lógica del bot)")
        else:
            print("Precio aún por encima del stop; no vende")
    else:
        stop_loss = entry_price * (1 + params.base_stop_loss_pct / 100)
        print(f"Sin trailing: stop base @ {stop_loss:.3f}")


if __name__ == "__main__":
    print("Escenario 1: Bajada progresiva a 104.47")
    simulate_trailing(current_price=104.47)
    print("\nEscenario 2: Gap directo a 104.00 (-0.95% del máximo)")
    simulate_trailing(current_price=104.00)
