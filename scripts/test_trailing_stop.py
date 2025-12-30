import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def approx_pct(value):
    """Return percentage difference from entry (value=price / entry -1) *100 if entry=1"""
    return (value - 1.0) * 100


def calculate_stop_local(entry_price: float, highest_price: float) -> float:
    """Implementación local de la regla: Stop = entry * (1 + ((PNL_max - 0.5)/100))"""
    max_pnl_percent = ((highest_price - entry_price) / entry_price) * 100
    trailing_drop = 0.5
    stop_percent_from_entry = max_pnl_percent - trailing_drop
    stop_price = entry_price * (1 + stop_percent_from_entry / 100.0)
    return stop_price


def test_trailing_stop_examples():
    entry = 1.0

    # Ejemplo 1: Apertura (0.00% PNL) -> Stop = -0.50%
    stop1 = calculate_stop_local(entry_price=entry, highest_price=1.0)
    stop1_pct = approx_pct(stop1)
    print(f"Ejemplo1 stop_pct={stop1_pct:.4f}% (esperado -0.50%)")
    assert abs(stop1_pct - (-0.5)) < 0.02

    # Ejemplo 2: PNL máximo +0.23% -> Stop = -0.27%
    highest_2 = 1.0023
    stop2 = calculate_stop_local(entry_price=entry, highest_price=highest_2)
    stop2_pct = approx_pct(stop2)
    print(f"Ejemplo2 stop_pct={stop2_pct:.4f}% (esperado approx -0.27%)")
    assert abs(stop2_pct - (-0.27)) < 0.05

    # Ejemplo 3: PNL máximo +1.00% -> Stop = +0.50%
    highest_3 = 1.01
    stop3 = calculate_stop_local(entry_price=entry, highest_price=highest_3)
    stop3_pct = approx_pct(stop3)
    print(f"Ejemplo3 stop_pct={stop3_pct:.4f}% (esperado +0.50%)")
    assert abs(stop3_pct - 0.5) < 0.02


if __name__ == '__main__':
    test_trailing_stop_examples()
    print('All trailing stop checks passed')