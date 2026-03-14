
#!/usr/bin/env python3
"""
RF Link Budget Calculator with Approximate Atmospheric Losses

Features
- FSPL
- Approximate gaseous attenuation (oxygen + water vapor) via log-log interpolation of anchor points
  (reference: "typical mid-latitude, sea-level, ~50% RH" style ballparks; good <~10 GHz)
- Simple rain attenuation model (rough ITU-like scaling): gamma_rain ≈ C * f_GHz^1.2 * R^1.0 (dB/km), C≈1e-4
- Optional user-provided cable/connector losses and polarization mismatch
- Noise floor and SNR for a given noise bandwidth and NF
- Outputs detailed breakdown per stage

DISCLAIMER
This script uses *engineering approximations* for atmospheric losses to enable quick-look analyses.
For certification-grade work, use official ITU-R models:
 - Gaseous loss: ITU-R P.676 with P.835 atmosphere profiles
 - Rain: ITU-R P.838/P.618 (Earth-space) or P.452 (terrestrial)
 - Terrain/ducting/troposcatter: ITU-R P.452 (terrestrial), P.618 (Earth-space)

Author: ChatGPT
"""

from dataclasses import dataclass
from typing import Optional

import math
import json

@dataclass
class LinkInputs:
    freq_MHz: float                 # Frequency in MHz
    dist_km: float                  # Path length in km
    tx_power_W: float               # Transmit power in Watts
    tx_gain_dBi: float              # Tx antenna gain (dBi)
    rx_gain_dBi: float              # Rx antenna gain (dBi)
    bw_Hz: float                    # Noise bandwidth (Hz)
    noise_figure_dB: float          # Receiver noise figure (dB)
    atm_gas_override_dB: Optional[float] = None  # If provided, overrides gas loss calc
    rain_rate_mm_per_h: float = 0.0 # Point rain rate (mm/h)
    eff_rain_len_km: float = 0.0    # Effective km of heavy rain along the path
    cable_loss_tx_dB: float = 0.0   # Tx side cable/connector loss (dB)
    cable_loss_rx_dB: float = 0.0   # Rx side cable/connector loss (dB)
    pol_mismatch_dB: float = 0.0    # Polarization mismatch loss (dB)
    extra_losses_dB: float = 0.0    # Any other lumped losses (dB)

@dataclass
class LinkOutputs:
    fspl_dB: float
    gas_loss_dB: float
    rain_loss_dB: float
    total_path_loss_dB: float
    tx_power_dBm: float
    eirp_dBm: float
    received_power_dBm: float
    noise_floor_dBm: float
    snr_dB: float

def fspl_dB(dist_km: float, freq_MHz: float) -> float:
    """Free-space path loss in dB."""
    return 32.44 + 20*math.log10(max(dist_km, 1e-9)) + 20*math.log10(max(freq_MHz, 1e-9))

def gaseous_specific_atten_dB_per_km_approx(freq_GHz: float) -> float:
    """
    Approximate clear-air gaseous attenuation (dB/km) using anchor points and log-log interpolation.
    Assumes sea-level, ~15°C, ~50% RH. Conservative enough for <~10 GHz quick looks.
    Anchor table (freq_GHz -> gamma_gas dB/km):
        0.03:  0.0001   (30 MHz)
        0.10:  0.0002   (100 MHz)
        0.147: 0.00025  (147 MHz)
        0.3:   0.0010   (300 MHz)
        1.0:   0.0020   (1 GHz)
        3.0:   0.0050   (3 GHz)
        10.0:  0.0300   (10 GHz)
        20.0:  0.1000   (20 GHz)  # Beware 22 GHz water vapor line (can be higher)
    """
    anchors = [
        (0.03, 0.0001),
        (0.10, 0.0002),
        (0.147, 0.00025),
        (0.3, 0.0010),
        (1.0, 0.0020),
        (3.0, 0.0050),
        (10.0, 0.0300),
        (20.0, 0.1000),
    ]
    f = max(freq_GHz, 0.03)
    # If below or above anchors, clamp to edge values
    if f <= anchors[0][0]:
        return anchors[0][1]
    if f >= anchors[-1][0]:
        return anchors[-1][1]
    # Find surrounding anchors
    for i in range(len(anchors)-1):
        f1, a1 = anchors[i]
        f2, a2 = anchors[i+1]
        if f1 <= f <= f2:
            # log-log interpolate
            lf1, la1 = math.log10(f1), math.log10(a1)
            lf2, la2 = math.log10(f2), math.log10(a2)
            lf  = math.log10(f)
            la  = la1 + (la2 - la1) * ( (lf - lf1) / (lf2 - lf1) )
            return 10**la
    return anchors[-1][1]

def rain_specific_atten_dB_per_km_approx(freq_GHz: float, R_mm_per_h: float) -> float:
    """
    Simplified rain specific attenuation gamma_R (dB/km).
    ITU-R P.838 uses gamma_R = k * R^alpha, with (k, alpha) frequency/polarization-dependent.
    Here we use a rough scaling often good for <~10 GHz quick looks:
        gamma_R ≈ C * f_GHz^1.2 * R^1.0, where C ≈ 1e-4
    This intentionally underestimates at high frequencies and heavy rain; adjust C if needed.
    """
    if R_mm_per_h <= 0:
        return 0.0
    C = 1e-4
    return C * (freq_GHz**1.2) * (R_mm_per_h**1.0)

def noise_floor_dBm(bw_Hz: float, NF_dB: float) -> float:
    return -174.0 + 10.0*math.log10(max(bw_Hz,1.0)) + NF_dB

def compute_link(inputs: LinkInputs) -> LinkOutputs:
    f_MHz = inputs.freq_MHz
    f_GHz = inputs.freq_MHz / 1000.0
    d_km  = inputs.dist_km

    # Core losses
    L_fspl = fspl_dB(d_km, f_MHz)

    if inputs.atm_gas_override_dB is not None:
        L_gas = inputs.atm_gas_override_dB
    else:
        gamma_gas = gaseous_specific_atten_dB_per_km_approx(f_GHz)
        L_gas = gamma_gas * d_km

    gamma_rain = rain_specific_atten_dB_per_km_approx(f_GHz, inputs.rain_rate_mm_per_h)
    L_rain = gamma_rain * inputs.eff_rain_len_km

    # Sum path loss
    L_path = L_fspl + L_gas + L_rain

    # Power terms
    Ptx_dBm = 10.0*math.log10(max(inputs.tx_power_W * 1000.0, 1e-12))
    EIRP_dBm = Ptx_dBm + inputs.tx_gain_dBi - inputs.cable_loss_tx_dB

    # Received power
    Prx_dBm = (
        Ptx_dBm
        + inputs.tx_gain_dBi
        + inputs.rx_gain_dBi
        - inputs.cable_loss_tx_dB
        - inputs.cable_loss_rx_dB
        - inputs.pol_mismatch_dB
        - L_path
        - inputs.extra_losses_dB
    )

    # Noise / SNR
    N_dBm = noise_floor_dBm(inputs.bw_Hz, inputs.noise_figure_dB)
    SNR_dB = Prx_dBm - N_dBm

    return LinkOutputs(
        fspl_dB = L_fspl,
        gas_loss_dB = L_gas,
        rain_loss_dB = L_rain,
        total_path_loss_dB = L_path,
        tx_power_dBm = Ptx_dBm,
        eirp_dBm = EIRP_dBm,
        received_power_dBm = Prx_dBm,
        noise_floor_dBm = N_dBm,
        snr_dB = SNR_dB
    )

def pretty_print(inputs: LinkInputs, outputs: LinkOutputs) -> str:
    d = {
        "inputs": inputs.__dict__,
        "outputs": outputs.__dict__
    }
    return json.dumps(d, indent=2)

if __name__ == "__main__":
    # Example usage: modify these or call compute_link() from another script.
    # Example 1: 147 MHz, 250 mi, 25 kHz FM, 25 W, Gtx=-8 dBi, Grx=-20 dBi
    ex1 = LinkInputs(
        freq_MHz=147.0,
        dist_km=402.3,
        tx_power_W=25.0,
        tx_gain_dBi=-8.0,
        rx_gain_dBi=-20.0,
        bw_Hz=25000.0,
        noise_figure_dB=6.0,
        rain_rate_mm_per_h=25.0,
        eff_rain_len_km=10.0,
        cable_loss_tx_dB=0.0,
        cable_loss_rx_dB=0.0,
        pol_mismatch_dB=0.0,
        extra_losses_dB=0.0
    )
    out1 = compute_link(ex1)
    print("Example 1: 147 MHz, 25 W, 402.3 km")
    print(pretty_print(ex1, out1))

    # Example 2: 910 MHz, 250 mi, 25 kHz FM, 24 W, same gains
    ex2 = LinkInputs(
        freq_MHz=910.0,
        dist_km=402.3,
        tx_power_W=24.0,
        tx_gain_dBi=-8.0,
        rx_gain_dBi=-20.0,
        bw_Hz=25000.0,
        noise_figure_dB=6.0,
        rain_rate_mm_per_h=25.0,
        eff_rain_len_km=10.0,
        cable_loss_tx_dB=0.0,
        cable_loss_rx_dB=0.0,
        pol_mismatch_dB=0.0,
        extra_losses_dB=0.0
    )
    out2 = compute_link(ex2)
    print("\nExample 2: 910 MHz, 24 W, 402.3 km")
    print(pretty_print(ex2, out2))
