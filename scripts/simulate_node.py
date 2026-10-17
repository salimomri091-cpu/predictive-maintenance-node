#!/usr/bin/env python3
"""Simulateur du nœud de maintenance prédictive.

Génère des fenêtres de vibration synthétiques (1024 points à 1600 Hz), calcule les
caractéristiques prévues dans specs.md (RMS, kurtosis, fréquence dominante, énergie par
bandes) et les publie en MQTT sur nodes/<id>/telemetry.
"""
import argparse
import json
import time

import numpy as np

FS = 1600  # Hz, ODR de l'ADXL345
N = 1024  # taille de la fenêtre FFT
F0 = 20.0  # Hz, fréquence de rotation simulée (1200 tr/min)
STATES = ["normal", "balourd", "desserrage", "frottement"]
BANDS = [(0, 50), (50, 200), (200, 400), (400, 800)]
AXIS_AMP = {"x": 0.05, "y": 0.05, "z": 0.03}  # amplitude à F0, en g


def band_noise(rng, f_lo, f_hi, rms):
    """Bruit limité à la bande [f_lo, f_hi] Hz, de valeur efficace rms."""
    freqs = np.fft.rfftfreq(N, 1 / FS)
    mask = (freqs >= f_lo) & (freqs <= f_hi)
    spec = np.zeros(N // 2 + 1, dtype=complex)
    spec[mask] = rng.normal(size=mask.sum()) + 1j * rng.normal(size=mask.sum())
    noise = np.fft.irfft(spec, N)
    return noise * rms / noise.std()


def synth_axis(state, axis, rng):
    t = np.arange(N) / FS
    amp = AXIS_AMP[axis]
    if state == "balourd":
        amp *= 4
    sig = amp * np.sin(2 * np.pi * F0 * t + rng.uniform(0, 2 * np.pi))
    sig += rng.normal(0, 0.01, N)
    if state == "desserrage":
        sig += 0.5 * amp * np.sin(2 * np.pi * 2 * F0 * t + rng.uniform(0, 2 * np.pi))
        sig += 0.3 * amp * np.sin(2 * np.pi * 3 * F0 * t + rng.uniform(0, 2 * np.pi))
        idx = rng.choice(N, 8, replace=False)
        sig[idx] += rng.choice([-1.0, 1.0], 8) * 0.3
    elif state == "frottement":
        sig += band_noise(rng, 300, 600, 0.04)
    return sig - sig.mean()  # on retire la composante continue (gravité)


def rms(x):
    return float(np.sqrt(np.mean(x**2)))


def kurtosis(x):
    """Kurtosis en excès (0 pour une loi gaussienne)."""
    m = x - x.mean()
    return float(np.mean(m**4) / (np.mean(m**2) ** 2) - 3)


def features(sx, sy, sz):
    w = np.hanning(N)
    spec = np.abs(np.fft.rfft(sx * w)) * 2 / w.sum()
    freqs = np.fft.rfftfreq(N, 1 / FS)
    out = {
        "rms_x": rms(sx),
        "rms_y": rms(sy),
        "rms_z": rms(sz),
        "kurt_z": kurtosis(sz),
        "f_dom_x": float(freqs[np.argmax(spec[1:]) + 1]),
    }
    for lo, hi in BANDS:
        mask = (freqs >= lo) & (freqs < hi)
        out[f"e_{lo}_{hi}"] = float(np.sum(spec[mask] ** 2))
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default="localhost", help="adresse du broker MQTT")
    p.add_argument("--port", type=int, default=1883)
    p.add_argument("--node", default="node01", help="identifiant du nœud")
    p.add_argument("--state", default="auto", choices=["auto"] + STATES)
    p.add_argument("--period", type=float, default=1.0, help="secondes entre deux messages")
    p.add_argument("--cycle", type=float, default=30.0, help="durée de chaque état en mode auto")
    p.add_argument("--dry-run", action="store_true", help="affiche les messages sans publier")
    p.add_argument("--seed", type=int, default=None)
    args = p.parse_args()

    rng = np.random.default_rng(args.seed)
    client = None
    if not args.dry_run:
        import paho.mqtt.client as mqtt

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=args.node)
        client.connect(args.host, args.port, keepalive=30)
        client.loop_start()

    topic = f"nodes/{args.node}/telemetry"
    start = time.time()
    try:
        while True:
            if args.state == "auto":
                state = STATES[int((time.time() - start) // args.cycle) % len(STATES)]
            else:
                state = args.state
            f = features(*(synth_axis(state, a, rng) for a in "xyz"))
            msg = {k: round(v, 4) for k, v in f.items()}
            msg["state"] = state
            msg["score"] = round(float(rng.uniform(0.90, 0.99)), 3)
            payload = json.dumps(msg)
            if client:
                client.publish(topic, payload, qos=0)
            print(f"{topic} {payload}", flush=True)
            time.sleep(args.period)
    except KeyboardInterrupt:
        print("Arrêt du simulateur.")
    finally:
        if client:
            client.loop_stop()
            client.disconnect()


if __name__ == "__main__":
    main()
